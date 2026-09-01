# chunk6_email_hitl.py
import os
import json
from email import encoders
from datetime import datetime, timedelta
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI

load_dotenv()

client = ChatMistralAI(
    model="mistral-small-latest",
    mistral_api_key=os.getenv("MISTRAL_API_KEY")
)


# ── Step 1: build HTML email body ─────────────────────────────────────────────
def build_email_body(
        ranked_vendors:        list,
        extracted:             dict,
        scores:                dict,
        risks:                 dict,
        rfq_item:              str  = "HR Steel Sheets 3mm",
        rfq_qty:               str  = "10,000 Kg",
        top_vendor:            str  = "",
        recommendation_reason: str  = "",
        should_cost_data:      dict = None,
        anomaly_flags:         dict = None,
        rfq_quantity:          float = 0,
        rfq_unit:              str  = "",
) -> str:
    """
    Builds a professional HTML email with:
    - Executive summary (recommended vendor, savings, risk, anomaly alerts)
    - Top 3 vendor comparison table
    - Risk alerts
    - Approval instructions
    """
    should_cost_data = should_cost_data or {}
    anomaly_flags    = anomaly_flags    or {}

    # Build copy-paste SELECT lines for all qualified vendors
    all_qualified = [
        v for v in ranked_vendors
        if not risks.get(v, {}).get("disqualify_recommended", False)
    ]
    select_lines = "".join(
        f"""<tr style="background:white">
          <td colspan="2" style="padding:2px 10px 2px 40px;
                                 font-size:11px;color:#1E3A5F;
                                 font-family:Courier New,monospace">
            SELECT: {v}
          </td>
        </tr>"""
        for v in all_qualified
    )

    disqualified = [
        v for v in ranked_vendors
        if risks.get(v, {}).get("disqualify_recommended", False)
    ]

    today    = datetime.today().strftime("%d %b %Y")
    deadline = (datetime.today() + timedelta(days=2)).strftime("%d %b %Y")

    # ── Executive summary metrics ─────────────────────────────────────────────
    top = top_vendor or (all_qualified[0] if all_qualified else "N/A")
    top_fields    = extracted.get(top, {})
    top_lc        = float(top_fields.get("landed_cost") or 0)
    top_score     = scores.get(top, {}).get("total_score", 0)
    top_risk      = risks.get(top, {}).get("overall_risk_level", "LOW")
    top_red       = risks.get(top, {}).get("red_count", 0)
    top_amber     = risks.get(top, {}).get("amber_count", 0)

    # Savings vs highest competing quote
    other_costs   = [
        float(extracted.get(v, {}).get("landed_cost") or 0)
        for v in ranked_vendors if v != top
    ]
    highest_other = max(other_costs) if other_costs else 0
    savings_per_unit = max(0, highest_other - top_lc)
    savings_total    = savings_per_unit * rfq_quantity if rfq_quantity else 0

    # Should-cost benchmark deviation for top vendor
    sc_dev = should_cost_data.get("per_vendor", {}).get(top, {})
    sc_dev_pct  = sc_dev.get("deviation_pct", 0)
    sc_benchmark = should_cost_data.get("benchmark_price", 0)

    # Anomaly warning HTML
    has_anomalies    = anomaly_flags.get("has_anomalies", False)
    anomaly_summary  = anomaly_flags.get("anomaly_summary", "")
    anomaly_red      = anomaly_flags.get("red_count", 0)
    anomaly_block    = ""
    if has_anomalies:
        alert_bg  = "#FCEBEB" if anomaly_red > 0 else "#FFF3CD"
        alert_bdr = "#E24B4A" if anomaly_red > 0 else "#F0AD00"
        alert_col = "#8B1A1A" if anomaly_red > 0 else "#7B5000"
        icon      = "🔴" if anomaly_red > 0 else "⚠️"
        anomaly_block = f"""
        <tr><td colspan="3">
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px">
          <tr><td style="background:{alert_bg};border:1px solid {alert_bdr};
                         border-radius:6px;padding:12px 16px">
            <p style="color:{alert_col};font-size:13px;font-weight:bold;margin:0">
              {icon} Bid Anomalies Detected</p>
            <p style="color:{alert_col};font-size:12px;margin:5px 0 0;line-height:1.5">
              {anomaly_summary} — see Risk Flags tab in the attached report.</p>
          </td></tr>
        </table>
        </td></tr>"""

    # Risk colour
    risk_bg  = ("#D6F0E4" if top_risk == "LOW"    else
                "#FFF3CD" if top_risk == "MEDIUM"  else "#FCEBEB")
    risk_col = ("#085041" if top_risk == "LOW"    else
                "#7B5000" if top_risk == "MEDIUM"  else "#8B1A1A")

    # Should-cost deviation badge
    sc_badge = ""
    if sc_benchmark > 0:
        sc_col   = "#085041" if sc_dev_pct <= 10 else ("#7B5000" if sc_dev_pct <= 25 else "#8B1A1A")
        sc_bg    = "#D6F0E4" if sc_dev_pct <= 10 else ("#FFF3CD" if sc_dev_pct <= 25 else "#FCEBEB")
        sc_sign  = "+" if sc_dev_pct >= 0 else ""
        sc_badge = f"""<tr><td colspan="3">
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 14px">
          <tr>
            <td style="background:{sc_bg};border:1px solid #D0D0D0;
                       border-radius:6px;padding:10px 16px">
              <span style="font-size:12px;font-weight:bold;color:{sc_col}">
                AI Benchmark Price: ₹{sc_benchmark:,.2f}/{rfq_unit}
              </span>
              <span style="font-size:12px;color:{sc_col};margin-left:16px">
                {top} is {sc_sign}{sc_dev_pct:.1f}% vs benchmark
                ({should_cost_data.get('benchmark_confidence','')}-confidence estimate)
              </span>
            </td>
          </tr>
        </table>
        </td></tr>"""

    exec_summary = f"""
    <!-- ═══ EXECUTIVE SUMMARY ═══ -->
    <table width="100%" cellpadding="0" cellspacing="0"
           style="margin-bottom:22px;border-radius:8px;overflow:hidden;
                  border:1px solid #0F6E56">
      <!-- Header -->
      <tr>
        <td colspan="3" style="background:#0F6E56;padding:16px 20px">
          <p style="color:#ffffff;font-size:17px;font-weight:bold;margin:0 0 6px">
            Recommended Vendor: {top}</p>
          <p style="color:#9FE1CB;font-size:13px;margin:0;line-height:1.5">
            {recommendation_reason or f"Ranked #1 with a blended score of {top_score:.1f}/100."}</p>
        </td>
      </tr>
      <!-- Metric tiles -->
      <tr>
        <td width="33%" style="background:#E1F5EE;padding:14px 16px;
                               border:1px solid #9FE1CB;vertical-align:top">
          <p style="color:#0F6E56;font-size:10px;font-weight:bold;
                    letter-spacing:.05em;margin:0 0 5px">LANDED COST</p>
          <p style="color:#085041;font-size:20px;font-weight:bold;margin:0">
            ₹{top_lc:,.2f}</p>
          <p style="color:#0F6E56;font-size:11px;margin:4px 0 0">
            per {rfq_unit}</p>
        </td>
        <td width="33%" style="background:#E1F5EE;padding:14px 16px;
                               border:1px solid #9FE1CB;vertical-align:top">
          <p style="color:#0F6E56;font-size:10px;font-weight:bold;
                    letter-spacing:.05em;margin:0 0 5px">SAVINGS VS HIGHEST QUOTE</p>
          <p style="color:#085041;font-size:20px;font-weight:bold;margin:0">
            {'₹{:,.0f}'.format(savings_total) if savings_total > 0 else 'N/A'}</p>
          <p style="color:#0F6E56;font-size:11px;margin:4px 0 0">
            {'₹{:,.2f}/unit × {:,.0f} {}'.format(savings_per_unit, rfq_quantity, rfq_unit)
             if savings_total > 0 else 'only 1 qualified vendor'}</p>
        </td>
        <td width="33%" style="background:{risk_bg};padding:14px 16px;
                               border:1px solid #D0D0D0;vertical-align:top">
          <p style="color:{risk_col};font-size:10px;font-weight:bold;
                    letter-spacing:.05em;margin:0 0 5px">RISK LEVEL</p>
          <p style="color:{risk_col};font-size:20px;font-weight:bold;margin:0">
            {top_risk}</p>
          <p style="color:{risk_col};font-size:11px;margin:4px 0 0">
            {top_red} red · {top_amber} amber flag(s)</p>
        </td>
      </tr>
      {anomaly_block}
      {sc_badge}
    </table>
    <!-- ═══════════════════════════ -->
    """

    # top 3 table rows
    vendor_rows = ""
    medals      = ["🥇", "🥈", "🥉"]
    row_colors  = ["#D6F0E4", "#E6F1FB", "#EEEDFE"]
    qualified = all_qualified[:3]  # Top 3 qualified vendors

    for i, vname in enumerate(qualified):
        f    = extracted.get(vname, {})
        s    = scores.get(vname, {})
        r    = risks.get(vname, {})
        lc   = f.get("landed_cost", 0) or 0
        dd   = f.get("delivery_days", "N/A")
        pay  = f.get("payment_terms", "N/A")
        adv  = f.get("advance_percentage", 0) or 0
        tot  = s.get("total_score", 0)
        rl   = r.get("overall_risk_level", "LOW")
        rl_c = ("#1A5C38" if rl == "LOW"    else
                "#7B5000" if rl == "MEDIUM" else
                "#8B1A1A")

        vendor_rows += f"""
        <tr style="background:{row_colors[i]}">
          <td style="padding:8px 12px;font-weight:bold;
                     font-size:15px">{medals[i]}</td>
          <td style="padding:8px 12px;font-weight:bold;
                     color:#1E3A5F">{vname}</td>
          <td style="padding:8px 12px;text-align:right;
                     font-weight:bold">&#8377;{lc:.2f}/Kg</td>
          <td style="padding:8px 12px;text-align:center">
            {dd} days</td>
          <td style="padding:8px 12px">{pay}</td>
          <td style="padding:8px 12px;text-align:center">
            {"None" if adv == 0 else f"{adv}%"}</td>
          <td style="padding:8px 12px;text-align:center;
                     font-weight:bold;font-size:14px;
                     color:#1E3A5F">{tot:.1f}</td>
          <td style="padding:8px 12px;text-align:center;
                     font-weight:bold;color:{rl_c}">{rl}</td>
        </tr>"""

    # disqualified rows
    disq_rows = ""
    for vname in disqualified:
        r    = risks.get(vname, {})
        rc   = r.get("red_count", 0)
        summ = r.get("risk_summary", "")[:120]
        disq_rows += f"""
        <tr style="background:#FCEBEB">
          <td style="padding:6px 12px;
                     text-align:center">&#9940;</td>
          <td style="padding:6px 12px;font-weight:bold;
                     color:#8B1A1A">{vname}</td>
          <td colspan="6"
              style="padding:6px 12px;color:#8B1A1A;
                     font-size:12px">
            {rc} RED flag(s) — DISQUALIFIED. {summ}
          </td>
        </tr>"""

    # top recommendation
    top_vendor  = qualified[0] if qualified else "N/A"
    top_score   = scores.get(top_vendor, {}).get(
        "total_score", 0)
    top_summary = scores.get(top_vendor, {}).get(
        "one_line_summary", "")
    top_lc      = extracted.get(top_vendor, {}).get(
        "landed_cost", 0) or 0

    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{
      font-family: Calibri, Arial, sans-serif;
      color: #333;
      margin: 0;
      padding: 0;
    }}
    .container {{
      max-width: 820px;
      margin: auto;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
    }}
    th {{
      background: #1E3A5F;
      color: white;
      padding: 8px 12px;
      text-align: left;
      font-size: 13px;
    }}
    .section-title {{
      background: #2E6DA4;
      color: white;
      padding: 8px 14px;
      font-size: 13px;
      font-weight: bold;
      margin-top: 16px;
    }}
    .footer {{
      background: #F5F5F5;
      padding: 12px 16px;
      font-size: 11px;
      color: #777;
      border-top: 2px solid #1E3A5F;
    }}
    .approve-box {{
      background: #D6F0E4;
      border: 2px solid #1A5C38;
      padding: 14px 18px;
      margin: 16px 0;
      border-radius: 4px;
    }}
    .action-box {{
      background: #FFF3CD;
      border: 2px solid #7B5000;
      padding: 12px 18px;
      margin: 8px 0;
      border-radius: 4px;
    }}
    .draft-banner {{
      background: #8B1A1A;
      color: white;
      padding: 8px 14px;
      font-size: 12px;
      font-weight: bold;
      text-align: center;
    }}
  </style>
</head>
<body>
<div class="container">

  <div class="draft-banner">
    &#128221; DRAFT — Saved to Outlook Drafts folder.
    This email has NOT been sent. Review before sending.
  </div>

  <!-- Header -->
  <table>
    <tr>
      <td style="background:#1E3A5F;padding:16px 20px;">
        <div style="color:white;font-size:18px;
                    font-weight:bold">
          &#128203; RFQ Evaluation Complete —
          Action Required
        </div>
        <div style="color:#B5D4F4;font-size:12px;
                    margin-top:4px">
          Please review and approve to proceed
          with Purchase Order
        </div>
      </td>
      <td style="background:#1E3A5F;padding:16px 20px;
                 text-align:right;vertical-align:top">
        <div style="color:#B5D4F4;font-size:11px">
          Date: {today}
        </div>
        <div style="color:#B5D4F4;font-size:11px">
          Decision By:
          <b style="color:white">{deadline}</b>
        </div>
      </td>
    </tr>
  </table>

  {exec_summary}

  <!-- RFQ Details -->
  <div class="section-title">RFQ DETAILS</div>
  <table>
    <tr style="background:#F5F5F5">
      <td style="padding:8px 14px;font-weight:bold;
                 width:200px;color:#1E3A5F">
        Item Description
      </td>
      <td style="padding:8px 14px">{rfq_item}</td>
    </tr>
    <tr style="background:white">
      <td style="padding:8px 14px;font-weight:bold;
                 color:#1E3A5F">Quantity Required</td>
      <td style="padding:8px 14px">{rfq_qty}</td>
    </tr>
    <tr style="background:#F5F5F5">
      <td style="padding:8px 14px;font-weight:bold;
                 color:#1E3A5F">Vendors Evaluated</td>
      <td style="padding:8px 14px">
        {len(extracted)} quotations received
      </td>
    </tr>
    <tr style="background:white">
      <td style="padding:8px 14px;font-weight:bold;
                 color:#1E3A5F">Disqualified</td>
      <td style="padding:8px 14px;color:#8B1A1A">
        {len(disqualified)} vendor(s) —
        see risk flags tab in attached Excel
      </td>
    </tr>
  </table>

  <!-- AI Recommendation -->
  <div class="approve-box">
    <div style="font-size:15px;font-weight:bold;
                color:#1A5C38">
      &#127942; AI RECOMMENDATION: {top_vendor}
    </div>
    <div style="font-size:13px;color:#333;
                margin-top:6px">
      Score: <b>{top_score:.1f}/100</b>
      &nbsp;|&nbsp;
      Landed Cost: <b>&#8377;{top_lc:.2f}/Kg</b>
    </div>
    <div style="font-size:12px;color:#555;
                margin-top:4px">
      {top_summary}
    </div>
  </div>

  <!-- Vendor Table -->
  <div class="section-title">
    VENDOR COMPARISON — QUALIFIED VENDORS
  </div>
  <table>
    <tr>
      <th style="width:30px">#</th>
      <th>Vendor Name</th>
      <th style="text-align:right">Landed Cost</th>
      <th style="text-align:center">Delivery</th>
      <th>Payment Terms</th>
      <th style="text-align:center">Advance</th>
      <th style="text-align:center">Score</th>
      <th style="text-align:center">Risk</th>
    </tr>
    {vendor_rows}
  </table>

  <!-- Disqualified -->
  {"<div class='section-title' style='background:#8B1A1A'>DISQUALIFIED VENDORS — DO NOT SELECT</div>" if disqualified else ""}
  {"<table><tr><th style='width:30px'></th><th>Vendor</th><th colspan='6'>Reason</th></tr>" + disq_rows + "</table>" if disqualified else ""}

  <!-- Action Required -->
  <div class="section-title">YOUR ACTION REQUIRED</div>
  <div class="action-box">
    <div style="font-size:13px;font-weight:bold;
                color:#7B5000">
      &#9888;&#65039; Please review the attached Excel
      report and reply to this email with one of
      the following:
    </div>
    <table style="margin-top:10px;width:100%">
      <tr style="background:#FFF8E1">
        <td style="padding:6px 10px;font-weight:bold;
                   color:#1E3A5F;width:220px">
          Reply: APPROVE
        </td>
        <td style="padding:6px 10px;font-size:12px">
          Approve AI recommendation —
          proceed with {top_vendor}
        </td>
      </tr>
      <tr style="background:white">
        <td style="padding:6px 10px;font-weight:bold;
                   color:#1E3A5F">
          Reply: SELECT: [Vendor Name]
        </td>
        <td style="padding:6px 10px;font-size:12px">
          Select a different vendor — copy exact name below:
        </td>
      </tr>
      {select_lines}
      <tr style="background:#FFF8E1">
        <td style="padding:6px 10px;font-weight:bold;
                   color:#1E3A5F">
          Reply: HOLD: [reason]
        </td>
        <td style="padding:6px 10px;font-size:12px">
          Pause the process and seek
          further clarification
        </td>
      </tr>
      <tr style="background:white">
        <td style="padding:6px 10px;font-weight:bold;
                   color:#1E3A5F">
          Reply: REJECT: [reason]
        </td>
        <td style="padding:6px 10px;font-size:12px">
          Reject all vendors —
          re-float RFQ to new vendors
        </td>
      </tr>
    </table>
    <div style="font-size:12px;font-weight:bold;
                color:#8B1A1A;margin-top:10px">
      &#9200; Decision required by {deadline}
      to meet delivery timeline.
    </div>
  </div>

  <!-- Footer -->
  <div class="footer">
    <b>RFQ Intelligence Agent</b> —
    Powered by LangGraph + Mistral AI &nbsp;|&nbsp;
    Evaluated against Procurement Policy Rev 4.1
    &nbsp;|&nbsp;
    Prices are indicative and subject to formal PO.
    &nbsp;|&nbsp;
    Queries: purchase@abcmfg.com
  </div>

</div>
</body>
</html>"""

    return html


# ── Step 2: Outlook draft creation + send-by-id ──────────────────────────────
# These two functions are the only place that touch win32com.
# The graph node (Chunk 7) is responsible for the interrupt()/resume —
# it calls create_outlook_draft() before the interrupt, and
# send_draft_by_entry_id() only after a human approval is received
# on resume. Nothing in this module sends mail on its own.

def create_outlook_draft(
        to_email:        str,
        subject:         str,
        html_body:       str,
        attachment_path: str | None = None
) -> dict:
    """
    Creates a draft email in Outlook (Drafts folder).
    Does NOT send it. Returns identifying info so the
    draft can be retrieved and sent later, after human
    approval, without re-building it from scratch.

    Returns:
        {
          "success":   bool,
          "entry_id":  str | None,   # Outlook MailItem.EntryID
          "store_id":  str | None,   # Outlook MailItem.Parent.StoreID
          "error":     str | None
        }
    """
    try:
        import win32com.client  # type: ignore[import]  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

        print(f"   📬 Connecting to Outlook desktop app...")
        outlook = win32com.client.Dispatch("Outlook.Application")

        mail          = outlook.CreateItem(0)  # olMailItem
        mail.To       = to_email
        mail.Subject  = subject
        mail.HTMLBody = html_body

        if attachment_path and os.path.exists(attachment_path):
            abs_path = os.path.abspath(attachment_path)
            mail.Attachments.Add(abs_path)
            print(f"   📎 Attached: {attachment_path}")
        elif attachment_path:
            print(f"   ⚠️  Attachment not found: {attachment_path}")

        # Save() writes the item to Drafts instead of sending it
        mail.Save()

        entry_id = mail.EntryID
        store_id = mail.Parent.StoreID

        print(f"   📝 Draft saved to Outlook Drafts folder")
        print(f"   🆔 EntryID: {entry_id}")

        return {
            "success":  True,
            "entry_id": entry_id,
            "store_id": store_id,
            "error":    None
        }

    except ImportError:
        msg = "pywin32 not installed — run: pip install pywin32"
        print(f"   ❌ {msg}")
        return {"success": False, "entry_id": None,
                "store_id": None, "error": msg}

    except Exception as e:
        print(f"   ❌ Draft creation failed: {e}")
        return {"success": False, "entry_id": None,
                "store_id": None, "error": str(e)}


def send_draft_by_entry_id(entry_id: str, store_id: str) -> bool:
    """
    Retrieves a previously-saved draft by its EntryID and
    sends it. Call this ONLY after human approval — e.g. from
    the LangGraph node right after interrupt() resumes with
    an approve decision.

    If the human edited the draft in Outlook before approving,
    those edits are preserved, since we re-open the same item
    rather than rebuilding it.
    """
    try:
        import win32com.client  # type: ignore[import]  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

        outlook   = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        mail      = namespace.GetItemFromID(entry_id, store_id)

        mail.Send()
        print(f"   ✅ Draft sent (EntryID: {entry_id})")
        return True

    except ImportError:
        print("   ❌ pywin32 not installed — run: pip install pywin32")
        return False

    except Exception as e:
        print(f"   ❌ Failed to send draft: {e}")
        return False


def discard_draft_by_entry_id(entry_id: str, store_id: str) -> bool:
    """
    Deletes a previously-saved draft instead of sending it —
    use this on HOLD/REJECT decisions so a stale draft doesn't
    linger in the mailbox.
    """
    try:
        import win32com.client  # type: ignore[import]  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

        outlook   = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        mail      = namespace.GetItemFromID(entry_id, store_id)

        mail.Delete()
        print(f"   🗑️  Draft discarded (EntryID: {entry_id})")
        return True

    except ImportError:
        print("   ❌ pywin32 not installed — run: pip install pywin32")
        return False

    except Exception as e:
        print(f"   ❌ Failed to discard draft: {e}")
        return False


# ── Step 3: generate PO draft via Mistral ────────────────────────────────────
def generate_po_draft(
        selected_vendor: str,
        fields:          dict,
        rfq_item:        str = "HR Steel Sheets 3mm",
        rfq_qty:         int = 10000,
        rfq_unit:        str = "Kg"
) -> str:
    """
    Uses Mistral to write a formal Purchase Order letter
    based on the selected vendor's quoted terms.
    """
    print(f"\n   📝 Generating PO draft for "
          f"{selected_vendor}...")

    today     = datetime.today().strftime("%d %B %Y")
    po_number = (f"PO/2026/"
                 f"{datetime.today().strftime('%m%d')}/001")

    gst_rate  = (fields.get("gst_rate", 18) or 18) / 100
    lc        = fields.get("landed_cost", 0) or 0
    base_val  = round(lc / (1 + gst_rate) * rfq_qty, 2)

    prompt = f"""
You are a procurement officer drafting a formal Purchase Order.
Write a complete, professional Purchase Order letter in plain text.
Do NOT use markdown. Use standard business letter format.

PURCHASE ORDER DETAILS:
- PO Number         : {po_number}
- Date              : {today}
- Buyer             : ABC Manufacturing Private Limited, Mumbai
- Vendor            : {selected_vendor}
- Item Description  : {rfq_item}
- Quantity          : {rfq_qty:,} {rfq_unit}
- Unit Price        : INR {fields.get('unit_price', 0):.2f}/{rfq_unit}
- Freight           : INR {fields.get('freight_per_unit', 0):.2f}/{rfq_unit}
- Incoterm          : {fields.get('incoterm', 'Ex-Works')}
- GST Rate          : {fields.get('gst_rate', 18)}%
- PO Value (ex GST) : INR {base_val:,.2f}
- Delivery Lead Time: {fields.get('delivery_days', 14)} working days
- Delivery Location : ABC Manufacturing Plant, Mumbai
- Payment Terms     : {fields.get('payment_terms', '45 days from invoice')}
- Warranty          : {fields.get('warranty_months', 12)} months

MANDATORY CLAUSES TO INCLUDE:
1. Delivery date commitment required from vendor within 2 days of PO
2. Material must conform to IS:2062 Grade A specifications
3. Mill Test Certificate to accompany every consignment
4. Liquidated Damages: 0.5% of PO value per week of delay,
   maximum 5% of total PO value
5. Buyer reserves right to inspect material before dispatch
6. Payment will be released per agreed terms from date of
   undisputed invoice and GRN sign-off
7. Jurisdiction: Mumbai courts, Indian law applies
8. Vendor to acknowledge PO within 2 working days

Write the complete PO letter now:
"""

    response = client.invoke(prompt)
    return response.content


def build_po_email_html(sel_vendor: str, decision_note: str, po_draft: str) -> str:
    """Builds the HTML body for the PO draft email (also goes to Drafts)."""
    today = datetime.today().strftime("%d-%b-%Y")
    return f"""
<html><body>
<div style="font-family:Calibri;
            max-width:700px;margin:auto">
  <div style="background:#8B1A1A;color:white;padding:8px 14px;
              font-size:12px;font-weight:bold;text-align:center">
    &#128221; DRAFT — Saved to Outlook Drafts folder.
    This email has NOT been sent. Review before sending.
  </div>
  <div style="background:#0F6E56;padding:14px 18px;
              color:white;font-size:16px;
              font-weight:bold">
    &#9989; Purchase Order Draft — Ready for Issue
  </div>
  <div style="padding:14px 18px;background:#D6F0E4;
              border:1px solid #0F6E56">
    <b>Selected Vendor:</b> {sel_vendor}<br>
    <b>Decision:</b> {decision_note}<br>
    <b>Next Step:</b> Review attached PO draft and
    issue to vendor within 2 working days.
  </div>
  <pre style="padding:14px 18px;background:#F9F9F9;
              font-size:11px;border:1px solid #ddd;
              white-space:pre-wrap">
{po_draft[:1200]}...
  </pre>
  <div style="padding:10px 18px;background:#F5F5F5;
              font-size:11px;color:#777">
    Generated by RFQ Intelligence Agent |
    LangGraph + Mistral AI | {today}
  </div>
</div>
</body></html>"""


# ── Step 4: parse manager's decision ──────────────────────────────────────────
def process_hitl_decision(
        decision:          str,
        qualified_vendors: list,
        extracted:         dict,
        scores:            dict
) -> dict:
    """
    Parses manager's reply (this is what comes back into the
    graph after interrupt() resumes).

    Supported replies:
      APPROVE                    → approve AI recommendation
      SELECT: [vendor name]      → pick specific vendor
      HOLD: [reason]             → pause process
      REJECT: [reason]           → reject all vendors
    """
    decision_upper = decision.strip().upper()

    if (decision_upper == "APPROVE" or
            decision_upper == ""):
        selected = (qualified_vendors[0]
                    if qualified_vendors else None)
        action   = "approved"
        note     = (f"AI recommendation approved — "
                    f"{selected}")

    elif decision_upper.startswith("SELECT:"):
        # Use length-based slice so "Select:", "SELECT:", "select:" all work.
        # Also strip [] brackets in case user copied the "[Vendor Name]" template literally.
        selected_raw       = decision[len("SELECT:"):].strip().strip("[]").strip()
        selected_raw_lower = selected_raw.lower()

        # Fuzzy match: accept partial name (e.g. "JSW" matches "JSW Steel Ltd")
        selected = None
        for vname in qualified_vendors:
            vname_lower = vname.lower()
            if selected_raw_lower in vname_lower or vname_lower in selected_raw_lower:
                selected = vname
                break

        if not selected:
            # Check whether the manager typed a DISQUALIFIED vendor
            disqualified_match = None
            for vname in (set(extracted.keys()) - set(qualified_vendors)):
                vname_lower = vname.lower()
                if selected_raw_lower in vname_lower or vname_lower in selected_raw_lower:
                    disqualified_match = vname
                    break

            if disqualified_match:
                # Explicit override of a disqualification — allow it with a strong warning
                selected = disqualified_match
                action   = "manually_selected"
                note     = (f"⚠️  Manager explicitly selected DISQUALIFIED vendor: "
                            f"{selected}. Proceeding against AI recommendation.")
            else:
                # Name not found at all — hold and ask for clarification
                qual_names = "\n      ".join(f"• SELECT: {v}" for v in qualified_vendors)
                return {
                    "action":          "on_hold",
                    "selected_vendor": None,
                    "decision_note":   (
                        f"Vendor '{selected_raw}' not found. "
                        f"Qualified vendors are:\n      {qual_names}\n"
                        f"Please retry with the exact vendor name."
                    ),
                    "timestamp": datetime.now().isoformat()
                }
        else:
            action = "manually_selected"
            note   = f"Manager overrode AI recommendation — selected: {selected}"

    elif decision_upper.startswith("HOLD:"):
        reason   = (decision
                    .replace("HOLD:", "")
                    .replace("hold:", "")
                    .strip())
        selected = None
        action   = "on_hold"
        note     = f"Process on hold — {reason}"

    elif decision_upper.startswith("REJECT:"):
        reason   = (decision
                    .replace("REJECT:", "")
                    .replace("reject:", "")
                    .strip())
        selected = None
        action   = "rejected"
        note     = f"All vendors rejected — {reason}"

    else:
        # unrecognised reply — do NOT default to approve for a
        # draft-based flow; nothing has been sent yet, so the
        # safer default is to hold and ask for clarification
        selected = None
        action   = "on_hold"
        note     = (f"Unrecognised reply ('{decision}') — "
                    f"holding for clarification")

    return {
        "action":          action,
        "selected_vendor": selected,
        "decision_note":   note,
        "timestamp":       datetime.now().isoformat()
    }


# ── Step 5: graph-facing node functions ───────────────────────────────────────
# Chunk 7 (rfq_agent.py) wires these around interrupt(). This module
# never decides on its own to send mail — every send is the direct
# result of a human approval passed in from outside.

def prepare_rfq_draft(
        extracted: dict,
        scores:    dict,
        risks:     dict
) -> dict:
    """
    Node-friendly Step A: build the RFQ comparison email and
    save it as an Outlook draft. Call this BEFORE interrupt().

    Returns everything the graph needs to keep in state across
    the interrupt: ranking info plus the draft's entry_id/store_id.
    """
    print(f"\n{'='*60}")
    print("CHUNK 6 — PREPARE RFQ DRAFT (Outlook, not sent)")
    print(f"{'='*60}")

    ranked_all = sorted(
        extracted.keys(),
        key=lambda v: scores.get(v, {}).get("total_score", 0),
        reverse=True
    )
    qualified = [
        v for v in ranked_all
        if not risks.get(v, {}).get("disqualify_recommended", False)
    ]
    top_vendor = qualified[0] if qualified else "N/A"

    print("\n   📧 Building HTML email...")
    html_body = build_email_body(ranked_all, extracted, scores, risks)

    today   = datetime.today().strftime("%d-%b-%Y")
    subject = (f"[ACTION REQUIRED] RFQ Evaluation — "
               f"Recommend: {top_vendor} | {today}")

    manager_email = os.getenv("MANAGER_EMAIL", "manager@example.com")

    print(f"\n   📝 Creating draft for {manager_email} in Outlook...")
    draft = create_outlook_draft(
        to_email        = manager_email,
        subject         = subject,
        html_body       = html_body,
        attachment_path = "RFQ_Comparison_Report.xlsx"
    )

    if not draft["success"]:
        print(f"   ⚠️  Draft creation failed: {draft['error']}")

    result = {
        "top_recommendation": top_vendor,
        "qualified_vendors":  qualified,
        "ranked_all":         ranked_all,
        "manager_email":      manager_email,
        "draft_created":      draft["success"],
        "draft_entry_id":     draft["entry_id"],
        "draft_store_id":     draft["store_id"],
        "draft_error":        draft["error"],
    }

    print(f"\n   ⏸️  Ready for interrupt() — "
          f"awaiting human approval of draft.")
    return result


def resume_after_decision(
        decision:          str,
        draft_state:       dict,
        extracted:         dict,
        scores:             dict
) -> dict:
    """
    Node-friendly Step B: call this from the graph right after
    interrupt() resumes with the human's reply.

    - APPROVE / SELECT  → sends the RFQ draft that's sitting in
                           Outlook (preserving any human edits),
                           then prepares + drafts (NOT sends) the
                           PO email for a second round of approval.
    - HOLD / REJECT      → discards the RFQ draft, sends nothing.
    """
    qualified = draft_state.get("qualified_vendors", [])
    decision_result = process_hitl_decision(
        decision, qualified, extracted, scores
    )

    entry_id = draft_state.get("draft_entry_id")
    store_id = draft_state.get("draft_store_id")

    print(f"\n   ▶️  GRAPH RESUMED")
    print(f"   Action   : {decision_result['action']}")
    print(f"   Selected : {decision_result['selected_vendor']}")
    print(f"   Note     : {decision_result['decision_note']}")

    rfq_sent = False
    po_draft = None
    po_path  = None
    po_draft_info = None

    if decision_result["action"] in ("approved", "manually_selected"):
        if entry_id and store_id:
            print(f"\n   📤 Sending approved RFQ draft...")
            rfq_sent = send_draft_by_entry_id(entry_id, store_id)
        else:
            print("   ⚠️  No draft entry_id/store_id available — "
                  "cannot send. Was prepare_rfq_draft() run first?")

        sel_vendor = decision_result["selected_vendor"]
        sel_fields = extracted.get(sel_vendor, {})

        po_draft = generate_po_draft(sel_vendor, sel_fields)

        po_path = f"PO_Draft_{sel_vendor.replace(' ', '_')}.txt"
        with open(po_path, "w") as f:
            f.write(po_draft)
        print(f"\n   💾 PO Draft saved: {po_path}")
        print(f"\n   {'─'*50}")
        print("   PO DRAFT PREVIEW:")
        print(f"   {'─'*50}")
        print(po_draft[:600] + "\n   ...")

        today = datetime.today().strftime("%d-%b-%Y")
        po_subject = (f"PO Draft Ready — {sel_vendor} | "
                      f"HR Steel 3mm | {today}")
        po_html = build_po_email_html(
            sel_vendor, decision_result["decision_note"], po_draft
        )

        print(f"\n   📝 Creating PO draft email in Outlook "
              f"(awaiting separate approval)...")
        po_draft_info = create_outlook_draft(
            to_email        = draft_state.get(
                "manager_email", os.getenv("MANAGER_EMAIL", "manager@example.com")),
            subject         = po_subject,
            html_body       = po_html,
            attachment_path = po_path
        )

    elif entry_id and store_id:
        # HOLD or REJECT — nothing should go out; clean up the
        # draft so it doesn't sit in the mailbox unsent.
        print(f"\n   🗑️  Discarding RFQ draft ({decision_result['action']})...")
        discard_draft_by_entry_id(entry_id, store_id)

    final = {
        "top_recommendation": draft_state.get("top_recommendation"),
        "qualified_vendors":  qualified,
        "human_decision":     decision,
        "action":             decision_result["action"],
        "selected_vendor":    decision_result["selected_vendor"],
        "decision_note":      decision_result["decision_note"],
        "rfq_draft_sent":     rfq_sent,
        "po_draft_path":      po_path,
        "po_draft_created":   bool(po_draft_info and po_draft_info["success"]),
        "po_draft_entry_id":  po_draft_info["entry_id"] if po_draft_info else None,
        "po_draft_store_id":  po_draft_info["store_id"] if po_draft_info else None,
        "timestamp":          decision_result["timestamp"]
    }

    print(f"\n{'='*60}")
    print("CHUNK 6 — SUMMARY")
    print(f"{'='*60}")
    print(f"  RFQ draft sent  : {'✅ Yes' if rfq_sent else '❌ No'}")
    print(f"  Recommendation  : {final['top_recommendation']}")
    print(f"  Decision        : {decision}")
    print(f"  Action          : {decision_result['action']}")
    print(f"  Final vendor    : {decision_result['selected_vendor'] or 'None'}")
    print(f"  PO draft file   : {po_path or 'Not generated'}")
    print(f"  PO email draft  : {'✅ Created (pending approval)' if final['po_draft_created'] else 'Not created'}")
    print(f"\n✅ Chunk 6 complete — Email HITL (draft-based) done!")

    return final