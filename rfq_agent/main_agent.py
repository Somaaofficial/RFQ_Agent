# main_agent.py — RFQ Intelligence Agent (updated with Gap fills)
# ─────────────────────────────────────────────────────────────────────────────
# Changes from original:
#   NEW nodes   : normalize_quotes_node, technical_compliance_node,
#                 supplier_history_node
#   MODIFIED    : RFQState (4 new fields), score_all_vendors_node (tech blend),
#                 rank_and_summarise_node (AI recommendation reason),
#                 generate_report_node (passes extra dicts to Excel exporter),
#                 build_rfq_graph (3 new edges), initial_state (4 new keys)
#   UNCHANGED   : trigger_node, extract_vendor_node, flag_all_vendors_node,
#                 email_hitl_node, process_decision_node, generate_po_node,
#                 should_generate_po, run_rfq_agent
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys
import json
from typing import Annotated, TypedDict, Optional
from dotenv  import load_dotenv

from langgraph.graph            import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types            import Send, Command, interrupt

# ── Original modules ──────────────────────────────────────────────────────────
from read_pdf_text import (
    readpdfnode,
    ExtractFields,
    calculate_landed_cost,
)
from RAG_Scorer   import uploadToChroma, policy_context, score_vendor
from Risk_Flagger import run_full_risk_analysis
from Excel_Exporter import build_excel_report
from Email_HITL   import (
    build_email_body,
    build_po_email_html,
    create_outlook_draft,
    send_draft_by_entry_id,
    discard_draft_by_entry_id,
    generate_po_draft,
    process_hitl_decision,
)

# ── NEW Gap-fill modules ──────────────────────────────────────────────────────
from Bid_Normalizer       import normalize_quotes
from Tech_Compliance      import run_technical_compliance_all
from supplier_history     import get_all_supplier_history
from should_cost_estimator import estimate_should_cost
from anomaly_detector     import detect_bid_anomalies

load_dotenv()

# ── Mistral client (shared by recommendation node) ───────────────────────────
from langchain_mistralai import ChatMistralAI
_mistral = ChatMistralAI(
    model  = "mistral-small-latest",
    api_key = os.getenv("MISTRAL_API_KEY"),
)


# ══════════════════════════════════════════════════════════════════════════════
# STATE DEFINITION  (updated)
# ══════════════════════════════════════════════════════════════════════════════

def merge_dicts(a: dict, b: dict) -> dict:
    return {**a, **b}


class RFQState(TypedDict):
    # ── RFQ inputs ────────────────────────────────────────────────────────────
    rfq_item:             str
    rfq_quantity:         float
    rfq_unit:             str
    delivery_location:    str
    vendor_quotes_folder: str
    vendor_files:         list
    vendor_name_map:      dict   # {filename → sender display name} from inbox scanner

    # ── per-vendor data written by parallel extract nodes ─────────────────────
    extracted_fields: Annotated[dict, merge_dicts]   # raw, from PDFs
    landed_costs:     Annotated[dict, merge_dicts]   # quick lookup

    # ── NEW: normalized + technical + history layers ──────────────────────────
    normalized_quotes: dict   # output of normalize_quotes_node (Gap 1)
    should_cost_data:  dict   # output of should_cost_node — benchmark + per-vendor deviation
    anomaly_flags:     dict   # output of anomaly_detection_node — bid anomalies
    tech_scores:       dict   # output of technical_compliance_node (Gap 2)
    supplier_history:  dict   # output of supplier_history_node (Gap 5)

    # ── scoring, risk, ranking ────────────────────────────────────────────────
    vendor_scores:    dict
    risk_flags:       dict
    ranked_vendors:   list
    qualified_vendors: list
    top_recommendation: str

    # ── NEW: AI recommendation reason (Gap 6) ─────────────────────────────────
    recommendation_reason:  str   # 2-3 sentence summary for email + report
    recommendation_details: dict  # structured JSON from Mistral

    # ── outputs ───────────────────────────────────────────────────────────────
    report_path:         str
    human_decision:      str
    selected_vendor:     str
    po_draft_path:       str
    po_draft_entry_id:   str
    po_draft_store_id:   str
    draft_entry_id:      str
    draft_store_id:      str
    thread_id:           str


class VendorState(TypedDict):
    vendor_name: str
    pdf_path:    str
    rfq_item:    str


# ══════════════════════════════════════════════════════════════════════════════
# SHARED RESOURCES — loaded once at startup
# ══════════════════════════════════════════════════════════════════════════════

print("Loading shared resources...")
vectorstore    = uploadToChroma()
policy_context_text = policy_context(
    vectorstore,
    """
    Procurement policy for vendor evaluation and RFQ scoring:
    price and landed cost scoring,
    delivery lead time scoring,
    payment terms and advance payment scoring,
    quality certifications scoring,
    penalty clause scoring,
    mandatory red disqualification flags,
    amber caution flags,
    landed cost calculation formula,
    vendor evaluation criteria and weightage.
    """,
    k=8,
)
print(f"ChromaDB has been  loaded | {len(policy_context_text)} chars policy context")


# ══════════════════════════════════════════════════════════════════════════════
# NODE 1 — TRIGGER NODE  (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def trigger_node(state: RFQState) -> dict:
    folder = state.get("vendor_quotes_folder", "vendor_quotes")

    # Look for PDFs recursively (including subdirectories)
    pdf_files = []
    if os.path.exists(folder):
        for root, dirs, files in os.walk(folder):
            for f in sorted(files):
                if f.endswith((".pdf", ".docx", ".xlsx", ".png", ".jpg")) and "policy" not in f.lower():
                    pdf_files.append(os.path.join(root, f))

    print(f"\n{'='*60}")
    print(f"NODE 1 — TRIGGER has been started")
    print(f"Found {len(pdf_files)} vendor RFQ files")
    print(f"{'='*60}")

    vendor_list = []
    for filepath in sorted(pdf_files):
        filename = os.path.basename(filepath)

        # Derive vendor name from the filename
        vendor_name = filename
        for ext in (".pdf", ".docx", ".xlsx", ".png", ".jpg"):
            vendor_name = vendor_name.replace(ext, "")
        vendor_name = vendor_name.replace("_", " ").strip()

        # Strip any leading sequence number e.g. "1 ", "01 ", "1. ", "1- "
        import re
        vendor_name = re.sub(r'^\d+[\s.\-]+', '', vendor_name).strip()

        vendor_list.append({
            "name": vendor_name,
            "path": filepath,
        })
        print(f"  ✓ Found: {filename} → {vendor_name}")

    return {"vendor_files": vendor_list}


def route_to_vendors(state: RFQState):
    vendor_files = state.get("vendor_files", [])
    rfq_item     = state.get("rfq_item", "")
    print(f"\n Firing {len(vendor_files)} parallel vendor extractions...")
    return [
        Send("extract_vendor_node", {
            "vendor_name": v["name"],
            "pdf_path":    v["path"],
            "rfq_item":    rfq_item,
        })
        for v in vendor_files
    ]


# ══════════════════════════════════════════════════════════════════════════════
# NODE 2 — EXTRACT VENDOR NODE  (unchanged — parallel per vendor)
# ══════════════════════════════════════════════════════════════════════════════

def extract_vendor_node(state: VendorState) -> dict:
    vendor_name = state["vendor_name"]
    pdf_path    = state["pdf_path"]

    print(f"   for  [{vendor_name}] Reading Document...")
    raw_text = readpdfnode(pdf_path)

    print(f"   for [{vendor_name}] Extracting fields has been started...")
    fields = ExtractFields(vendor_name, raw_text)
    fields["landed_cost"] = calculate_landed_cost(fields)

    print(f"   for the  [{vendor_name}] Landed cost is : ₹{fields['landed_cost']:.2f}")

    return {
        "extracted_fields": {vendor_name: fields},
        "landed_costs":     {vendor_name: fields["landed_cost"]},
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 2.5 — NORMALIZE QUOTES NODE  (NEW — Gap 1)
# Runs once after all parallel extractions fan in.
# Corrects currency, freight treatment, recalculates landed costs.
# ══════════════════════════════════════════════════════════════════════════════

def normalize_quotes_node(state: RFQState) -> dict:
    extracted = state.get("extracted_fields", {})
    rfq_unit  = state.get("rfq_unit", "Kg")

    print(f"\n{'='*60}")
    print(f"NODE 2 — BID NORMALIZATION has been started ")
    print(f"{'='*60}")

    normalized = normalize_quotes(extracted, rfq_unit)
    return {"normalized_quotes": normalized}


#after normalize node moving ahead for should cost node, anomaly detection, technical compliance, scoring, history, risk flagging, ranking, report generation, email HITL, and decision processing.

def should_cost_node(state: RFQState) -> dict:
    quotes = state.get("normalized_quotes") or state.get("extracted_fields", {})

    print(f"\n{'='*60}")
    print(f"NODE 3 — should cost estimator and AI Bench marker has been started")
    print(f"{'='*60}")

    should_cost = estimate_should_cost(
        rfq_item          = state.get("rfq_item", ""),
        rfq_quantity      = state.get("rfq_quantity", 0),
        rfq_unit          = state.get("rfq_unit", "Kg"),
        delivery_location = state.get("delivery_location", ""),
        normalized_quotes = quotes,
    )
    return {"should_cost_data": should_cost}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 2.7 — ANOMALY DETECTION NODE  (NEW)
# Detects cartel hints, outliers, above-benchmark clusters before scoring.
# Runs after should-cost so deviation data is available.
# ══════════════════════════════════════════════════════════════════════════════

def anomaly_detection_node(state: RFQState) -> dict:
    quotes      = state.get("normalized_quotes") or state.get("extracted_fields", {})
    should_cost = state.get("should_cost_data", {})

    print(f"\n{'='*60}")
    print(f"NODE 4 — ANOMALY DETECTOR has been started")
    print(f"{'='*60}")

    anomalies = detect_bid_anomalies(
        normalized_quotes = quotes,
        should_cost_data  = should_cost,
        rfq_item          = state.get("rfq_item", ""),
    )
    return {"anomaly_flags": anomalies}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 2.8 — TECHNICAL COMPLIANCE NODE  (NEW — Gap 2)
# Checks spec match: certifications, MOQ, validity, price firmness, warranty.
# Vendors that fail hard rules are flagged disqualify_on_tech=True.
# ══════════════════════════════════════════════════════════════════════════════

def technical_compliance_node(state: RFQState) -> dict:
    # Use normalized quotes; fall back to raw extraction if normalizer failed
    quotes = state.get("normalized_quotes") or state.get("extracted_fields", {})

    print(f"\n{'='*60}")
    print(f"NODE 5 — TECHNICAL COMPLIANCE has been strated")
    print(f"{'='*60}")

    tech_scores = run_technical_compliance_all(
        normalized_quotes      = quotes,
        rfq_item               = state.get("rfq_item", ""),
        rfq_quantity           = state.get("rfq_quantity", 0),
        rfq_unit               = state.get("rfq_unit", "Kg"),
        rfq_delivery_location  = state.get("delivery_location", ""),
    )
    return {"tech_scores": tech_scores}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 3 — SCORE ALL VENDORS NODE  (modified)
# Now reads from normalized_quotes + blends tech_score (15%) into total.
# ══════════════════════════════════════════════════════════════════════════════

def score_all_vendors_node(state: RFQState) -> dict:
    # Always prefer normalized quotes for scoring
    quotes      = state.get("normalized_quotes") or state.get("extracted_fields", {})
    tech_scores = state.get("tech_scores", {})
    history     = state.get("supplier_history", {})   # now available — runs after history node
    all_landed  = {v: f.get("landed_cost", 0) for v, f in quotes.items()}

    print(f"\n{'='*60}")
    print(f"NODE 6 — RAG SCORING + TECH + HISTORY BLEND has been started")
    print(f"Scoring {len(quotes)} vendors...")
    print(f"{'='*60}")

    all_scores = {}
    for vendor_name, fields in quotes.items():
        print(f"  Scoring {vendor_name}...")
        raw_score = score_vendor(
            vendor_name     = vendor_name,
            fields          = fields,
            context         = policy_context,
            all_landed_cost = all_landed,
        )

      
        commercial_total = float(raw_score.get("total_score", 0))
        tech_result      = tech_scores.get(vendor_name, {})
        tech_total       = float(tech_result.get("technical_score", 100))
        history_score    = float(history.get(vendor_name, {}).get("history_score", 65))
        blended_total    = round(
            commercial_total * 0.75 +
            tech_total       * 0.15 +
            history_score    * 0.10,
            1
        )

        raw_score["commercial_score"]  = commercial_total
        raw_score["tech_score"]        = tech_total
        raw_score["history_score"]     = history_score
        raw_score["total_score"]       = blended_total
        raw_score["tech_disqualified"] = tech_result.get("disqualify_on_tech", False)

        all_scores[vendor_name] = raw_score

        print(f"      Commercial: {commercial_total:.1f}  "
              f"Tech: {tech_total:.1f}  "
              f"History: {history_score:.1f}  "
              f"Blended: {blended_total:.1f}/100")

    return {"vendor_scores": all_scores}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 3.5 — SUPPLIER HISTORY NODE  (NEW — Gap 5)
# Runs after scoring, before risk flagging, so risk flags can factor history.
# ══════════════════════════════════════════════════════════════════════════════

def supplier_history_node(state: RFQState) -> dict:
    # Now runs BEFORE scoring — read from quotes, not vendor_scores
    quotes       = state.get("normalized_quotes") or state.get("extracted_fields", {})
    vendor_names = list(quotes.keys())

    print(f"\n{'='*60}")
    print(f"NODE 7 — SUPPLIER HISTORY has been strated")
    print(f"{'='*60}")

    history = get_all_supplier_history(vendor_names)
    return {"supplier_history": history}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 4 — FLAG ALL VENDORS NODE  (modified: history passed to risk analysis)
# ══════════════════════════════════════════════════════════════════════════════

def flag_all_vendors_node(state: RFQState) -> dict:
    extracted = state.get("normalized_quotes") or state.get("extracted_fields", {})
    history   = state.get("supplier_history", {})

    print(f"\n{'='*60}")
    print(f"NODE 8 — RISK FLAGGING (with history context)")
    print(f"{'='*60}")

    all_risks = {}
    for vendor_name, fields in extracted.items():
        print(f"  🔍 Analysing {vendor_name}...")

        # Enrich fields with historical data so risk flagger can use them
        enriched = dict(fields)
        vendor_hist = history.get(vendor_name, {})
        enriched["historical_rating"]    = vendor_hist.get("historical_rating", "Unknown")
        enriched["history_score"]        = vendor_hist.get("history_score", 65)
        enriched["past_po_delays"]       = vendor_hist.get("po_delays_count", 0)
        enriched["past_quality_issues"]  = vendor_hist.get("quality_issues_count", 0)

        risk = run_full_risk_analysis(vendor_name, enriched)
        all_risks[vendor_name] = risk

        rc   = risk["red_count"]
        ac   = risk["amber_count"]
        rl   = risk["overall_risk_level"]
        icon = "🔴" if rc > 0 else ("🟡" if ac > 0 else "🟢")
        print(f"      {icon} RED:{rc} AMBER:{ac} Level:{rl}")

    return {"risk_flags": all_risks}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 5 — RANK AND SUMMARISE NODE  (modified: adds AI recommendation — Gap 6)
# ══════════════════════════════════════════════════════════════════════════════

def rank_and_summarise_node(state: RFQState) -> dict:
    scores    = state.get("vendor_scores",   {})
    risks     = state.get("risk_flags",      {})
    extracted = state.get("normalized_quotes") or state.get("extracted_fields", {})
    history   = state.get("supplier_history", {})
    tech_sc   = state.get("tech_scores",     {})

    print(f"\n{'='*60}")
    print(f"NODE 5 — RANKING & AI RECOMMENDATION ")
    print(f"{'='*60}")

    # ── Rank all vendors by blended score ─────────────────────────────────────
    ranked = sorted(
        extracted.keys(),
        key=lambda v: scores.get(v, {}).get("total_score", 0),
        reverse=True,
    )

    # ── Split: disqualified by risk OR by technical compliance ────────────────
    def _is_disqualified(v):
        risk_disq = risks.get(v, {}).get("disqualify_recommended", False)
        tech_disq = tech_sc.get(v, {}).get("disqualify_on_tech", False)
        return risk_disq or tech_disq

    qualified    = [v for v in ranked if not _is_disqualified(v)]
    disqualified = [v for v in ranked if     _is_disqualified(v)]

    top = qualified[0] if qualified else "N/A"

    print(f"\n  RANKINGS are given below:")
    for i, v in enumerate(ranked, 1):
        s     = scores.get(v, {}).get("total_score", 0)
        disq  = _is_disqualified(v)
        tech  = tech_sc.get(v, {}).get("technical_score", "N/A")
        hist  = history.get(v, {}).get("historical_rating", "Unknown")
        tag   = " ⛔ DISQUALIFIED" if disq else ""
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"  #{i}")
        print(f"  {medal} {v:<35} Score:{s:.1f}  Tech:{tech}  History:{hist}{tag}")

    print(f"\n  🏆 TOP RECOMMENDATION: {top}")

    # ── Generate AI recommendation reason (Gap 6 + 7) ─────────────────────────
    recommendation_reason  = ""
    recommendation_details = {}

    if top != "N/A":
        # Build a tight summary for the top 3 vendors to keep the prompt small
        top3 = ranked[:3]

        top3_summary = {}
        for v in top3:
            top3_summary[v] = {
                "total_score":    scores.get(v, {}).get("total_score", 0),
                "commercial":     scores.get(v, {}).get("commercial_score", 0),
                "tech_score":     tech_sc.get(v, {}).get("technical_score", 0),
                "rank_category":  scores.get(v, {}).get("rank_category", ""),
                "risk_level":     risks.get(v, {}).get("overall_risk_level", ""),
                "red_flags":      risks.get(v, {}).get("red_count", 0),
                "amber_flags":    risks.get(v, {}).get("amber_count", 0),
                "history_rating": history.get(v, {}).get("historical_rating", "Unknown"),
                "history_score":  history.get(v, {}).get("history_score", 65),
                "landed_cost":    extracted.get(v, {}).get("landed_cost", 0),
                "delivery_days":  extracted.get(v, {}).get("delivery_days", "N/A"),
                "payment_terms":  extracted.get(v, {}).get("payment_terms", "N/A"),
            }

        criteria_breakdown = {}
        for v in top3:
            cs = scores.get(v, {}).get("criteria_scores", {})
            criteria_breakdown[v] = {
                criterion: {
                    "raw":      data.get("raw_score", 0),
                    "weighted": data.get("weighted_score", 0),
                }
                for criterion, data in cs.items()
            }

        rec_prompt = f"""
You are a senior procurement AI advisor generating an RFQ award recommendation.

RECOMMENDED VENDOR: {top}
RFQ ITEM: {state.get('rfq_item', 'N/A')}

TOP 3 VENDOR COMPARISON:
{json.dumps(top3_summary, indent=2)}

CRITERIA SCORE BREAKDOWN (weighted):
{json.dumps(criteria_breakdown, indent=2)}

Write a concise, professional award recommendation.

Respond ONLY with valid JSON — no markdown:
{{
  "recommended_vendor":   "{top}",
  "recommendation_summary": "2-3 sentences explaining WHY this vendor wins — \
mention price rank, delivery, history, and risk profile specifically",
  "key_reasons": [
    "reason 1 — specific fact (e.g. lowest landed cost of ₹X vs next at ₹Y)",
    "reason 2 — specific fact",
    "reason 3 — specific fact"
  ],
  "risk_note":      "one sentence on the risk profile of the recommended vendor",
  "caution_note":   "one sentence flagging anything the manager should watch \
(null if no concerns)"
}}
"""

        try:
            rec_resp = _mistral.invoke(rec_prompt)
            rec_raw  = rec_resp.content.strip()
            if "```" in rec_raw:
                rec_raw = rec_raw.split("```")[1]
                if rec_raw.startswith("json"):
                    rec_raw = rec_raw[4:]
            recommendation_details = json.loads(rec_raw.strip())
            recommendation_reason  = recommendation_details.get(
                "recommendation_summary", ""
            )
            print(f"\n   AI Recommendation is given below")
            print(f"     {recommendation_reason}")
        except Exception as e:
            print(f"\n  ⚠️  Recommendation LLM failed ({e}) — using fallback text")
            top_score = scores.get(top, {}).get("total_score", 0)
            recommendation_reason  = (
                f"{top} is recommended as the top-ranked vendor with a blended "
                f"score of {top_score:.1f}/100, combining commercial evaluation, "
                f"technical compliance, and supplier history."
            )
            recommendation_details = {
                "recommended_vendor":      top,
                "recommendation_summary":  recommendation_reason,
                "key_reasons":             [],
                "risk_note":               "",
                "caution_note":            None,
            }

    return {
        "ranked_vendors":          ranked,
        "qualified_vendors":       qualified,
        "top_recommendation":      top,
        "recommendation_reason":   recommendation_reason,
        "recommendation_details":  recommendation_details,
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 6 — GENERATE REPORT NODE  (modified: passes new dicts to Excel exporter)
# ══════════════════════════════════════════════════════════════════════════════

def generate_report_node(state: RFQState) -> dict:
    extracted   = state.get("normalized_quotes") or state.get("extracted_fields", {})
    scores      = state.get("vendor_scores",    {})
    risks       = state.get("risk_flags",       {})
    tech_scores = state.get("tech_scores",      {})
    history     = state.get("supplier_history", {})
    rec_reason  = state.get("recommendation_reason", "")
    rec_details = state.get("recommendation_details", {})

    print(f"\n{'='*60}")
    print(f"NODE 6 — EXCEL REPORT")
    print(f"{'='*60}")

    # Excel_Exporter.py's build_excel_report accepts **kwargs for extra data.
    # If you haven't updated it yet, these kwargs are safely ignored.
    # To display tech/history columns, update Excel_Exporter.py to consume them.
    report_path = build_excel_report(
        extracted,
        scores,
        risks,
        "RFQ_Comparison_Report.xlsx",
        tech_scores          = tech_scores,
        supplier_history     = history,
        recommendation_reason = rec_reason,
        recommendation_details = rec_details,
    )
    print(f"  ✅ Report saved: {report_path}")
    return {"report_path": report_path}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 7 — EMAIL HITL NODE  (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def email_hitl_node(state: RFQState) -> dict:
    extracted     = state.get("normalized_quotes") or state.get("extracted_fields", {})
    scores        = state.get("vendor_scores",    {})
    risks         = state.get("risk_flags",       {})
    ranked        = state.get("ranked_vendors",   [])
    top           = state.get("top_recommendation", "N/A")
    rec_reason    = state.get("recommendation_reason", "")
    report_path   = state.get("report_path", "")
    manager_email = os.getenv("MANAGER_EMAIL", "manager@example.com")

    print(f"\n{'='*60}")
    print(f"NODE 8 — EMAIL + HITL(Human in the loop...)")
    print(f"{'='*60}")

    html_body = build_email_body(
        ranked,
        extracted,
        scores,
        risks,
        top_vendor          = top,
        recommendation_reason = rec_reason,
        should_cost_data    = state.get("should_cost_data", {}),
        anomaly_flags       = state.get("anomaly_flags", {}),
        rfq_quantity        = state.get("rfq_quantity", 0),
        rfq_unit            = state.get("rfq_unit", ""),
    )

    # Build subject with savings figure if available
    savings_str = ""
    sc_per_vendor = state.get("should_cost_data", {}).get("per_vendor", {})
    if top != "N/A" and sc_per_vendor:
        top_lc = extracted.get(top, {}).get("landed_cost", 0)
        all_lc = [
            extracted.get(v, {}).get("landed_cost", 0)
            for v in ranked if v != top
        ]
        if all_lc and top_lc:
            max_other = max(all_lc)
            savings   = (max_other - top_lc) * state.get("rfq_quantity", 0)
            if savings > 0:
                savings_str = f" | Savings: ₹{savings:,.0f}"

    from datetime import datetime
    today   = datetime.today().strftime("%d-%b-%Y")
    subject = (f"[ACTION REQUIRED] RFQ Evaluation Ready — "
               f"Recommend: {top} | {today}{savings_str}")

    # ------------------------------------------------------------------
    # Outlook draft creation is Windows-only (win32com/COM). When the
    # agent runs on a Linux server there is no Outlook to talk to, so we
    # skip it and hand the rendered email back to the caller instead.
    # The review step is unchanged either way — only the delivery
    # mechanism differs.
    # ------------------------------------------------------------------
    outlook_enabled = (
        sys.platform == "win32"
        and os.getenv("DISABLE_OUTLOOK", "0") != "1"
    )

    draft = {"success": False, "entry_id": None, "store_id": None, "error": None}

    if outlook_enabled:
        print(f"\n  📝 Creating draft in Outlook for {manager_email}...")
        try:
            draft = create_outlook_draft(
                to_email        = manager_email,
                subject         = subject,
                html_body       = html_body,
                attachment_path = report_path or "RFQ_Comparison_Report.xlsx",
            )
        except Exception as exc:                       # noqa: BLE001
            draft["error"] = str(exc)

        if draft["success"]:
            print(f"  ✅ Draft saved to Outlook Drafts")
            print(f"  🆔 EntryID: {draft['entry_id']}")
        else:
            print(f"  ⚠️  Draft creation failed: {draft['error']}")
    else:
        draft["error"] = "Outlook unavailable on this platform"
        print(f"\n  📄 Outlook skipped (platform={sys.platform}).")
        print(f"     Recommendation returned to the caller instead.")

    print(f"\n  ⏸️  GRAPH PAUSED — interrupt() fired")
    print(f"  Waiting for manager reply...")

    decision = interrupt({
        "message":         (
            "RFQ comparison draft created in Outlook. Awaiting approval."
            if draft["success"]
            else "RFQ comparison ready for review. Awaiting approval."
        ),
        "recommendation":  top,
        "reason":          rec_reason,
        "report_path":     report_path,
        "manager_email":   manager_email,
        "email_subject":   subject,
        "email_html":      html_body,
        "draft_entry_id":  draft["entry_id"],
        "draft_store_id":  draft["store_id"],
        "reply_options":   [
            "APPROVE",
            "SELECT: [vendor name]",
            "HOLD: [reason]",
            "REJECT: [reason]",
        ],
    })

    print(f"\n  ▶️  GRAPH RESUMED — decision: '{decision}'")

    return {
        "human_decision":        str(decision),
        "draft_entry_id":        draft["entry_id"],
        "draft_store_id":        draft["store_id"],
        "email_subject":         subject,
        "email_html":            html_body,
        "email_recipient":       manager_email,
        "outlook_draft_created": bool(draft["success"]),
    }


# ══════════════════════════════════════════════════════════════════════════════
# NODE 8 — PROCESS DECISION NODE  (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def process_decision_node(state: RFQState) -> dict:
    decision  = state.get("human_decision", "APPROVE")
    qualified = state.get("qualified_vendors", [])
    scores    = state.get("vendor_scores",     {})
    entry_id  = state.get("draft_entry_id",    "")
    store_id  = state.get("draft_store_id",    "")

    result = process_hitl_decision(
        decision, qualified,
        state.get("normalized_quotes") or state.get("extracted_fields", {}),
        scores,
    )

    print(f"\n{'='*60}")
    print(f"NODE 8 — DECISION PROCESSING")
    print(f"{'='*60}")
    print(f"  Action:          {result['action']}")
    print(f"  Selected vendor: {result['selected_vendor']}")
    print(f"  Note:            {result['decision_note']}")

    if result["action"] in ("approved", "manually_selected"):
        if entry_id and store_id:
            print(f"\n  📤 Sending Outlook draft...")
            sent = send_draft_by_entry_id(entry_id, store_id)
            print(f"  {'✅ Sent' if sent else '❌ Send failed'}")
    else:
        if entry_id and store_id:
            print(f"\n  🗑️  Discarding unsent draft...")
            discard_draft_by_entry_id(entry_id, store_id)

    return {"selected_vendor": result["selected_vendor"] or ""}


# ── Conditional edge after decision ──────────────────────────────────────────

def should_generate_po(state: RFQState) -> str:
    decision = state.get("human_decision", "").upper()
    if decision.startswith("HOLD"):
        print("\n  ⏸️  Process ON HOLD — no PO generated")
        return "end_hold"
    if decision.startswith("REJECT"):
        print("\n  ❌ All vendors REJECTED — re-float RFQ")
        return "end_reject"
    if not state.get("selected_vendor"):
        print("\n  ⚠️  No vendor selected — ending")
        return "end_hold"
    return "generate_po"


# ══════════════════════════════════════════════════════════════════════════════
# NODE 9 — GENERATE PO NODE  (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def generate_po_node(state: RFQState) -> dict:
    selected      = state.get("selected_vendor", "")
    extracted     = state.get("normalized_quotes") or state.get("extracted_fields", {})
    fields        = extracted.get(selected, {})
    manager_email = os.getenv("MANAGER_EMAIL", "manager@example.com")

    print(f"\n{'='*60}")
    print(f"NODE 9 — PO GENERATION")
    print(f"{'='*60}")
    print(f"  Generating PO for: {selected}")

    po_draft = generate_po_draft(
        selected_vendor = selected,
        fields          = fields,
        rfq_item        = state.get("rfq_item", "HR Steel Sheets 3mm"),
        rfq_qty         = int(state.get("rfq_quantity", 10000)),
        rfq_unit        = state.get("rfq_unit", "Kg"),
    )

    po_path = f"PO_Draft_{selected.replace(' ', '_')}.txt"
    with open(po_path, "w") as f:
        f.write(po_draft)
    print(f"  💾 PO saved: {po_path}")

    from datetime import datetime
    today   = datetime.today().strftime("%d-%b-%Y")
    po_subj = f"PO Draft Ready — {selected} | HR Steel 3mm | {today}"
    po_html = build_po_email_html(
        sel_vendor    = selected,
        decision_note = f"Selected vendor: {selected}",
        po_draft      = po_draft,
    )

    print(f"\n  📝 Creating PO draft email in Outlook for {manager_email}...")
    po_email_draft = create_outlook_draft(
        to_email        = manager_email,
        subject         = po_subj,
        html_body       = po_html,
        attachment_path = po_path,
    )

    if po_email_draft["success"]:
        print(f"  ✅ PO email saved to Outlook Drafts")
        print(f"  🆔 EntryID: {po_email_draft['entry_id']}")
    else:
        print(f"  ⚠️  PO draft email creation failed: {po_email_draft['error']}")

    return {
        "po_draft_path":     po_path,
        "po_draft_entry_id": po_email_draft["entry_id"],
        "po_draft_store_id": po_email_draft["store_id"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# BUILD THE GRAPH  (updated with 3 new nodes + 3 new edges)
# ══════════════════════════════════════════════════════════════════════════════

def build_rfq_graph():
    graph = StateGraph(RFQState)

    # ── Register all nodes ────────────────────────────────────────────────────
    graph.add_node("trigger_node",              trigger_node)
    graph.add_node("extract_vendor_node",       extract_vendor_node)
    graph.add_node("normalize_quotes_node",     normalize_quotes_node)
    graph.add_node("should_cost_node",          should_cost_node)          # NEW
    graph.add_node("anomaly_detection_node",    anomaly_detection_node)    # NEW
    graph.add_node("technical_compliance_node", technical_compliance_node)
    graph.add_node("score_all_vendors_node",    score_all_vendors_node)
    graph.add_node("supplier_history_node",     supplier_history_node)     # NEW
    graph.add_node("flag_all_vendors_node",     flag_all_vendors_node)
    graph.add_node("rank_and_summarise_node",   rank_and_summarise_node)
    graph.add_node("generate_report_node",      generate_report_node)
    graph.add_node("email_hitl_node",           email_hitl_node)
    graph.add_node("process_decision_node",     process_decision_node)
    graph.add_node("generate_po_node",          generate_po_node)

    # ── Edges ─────────────────────────────────────────────────────────────────
    # START → trigger (returns dict, not Sends)
    graph.add_edge(START, "trigger_node")

    # trigger → routing function → parallel Sends per vendor
    graph.add_conditional_edges("trigger_node", route_to_vendors)

    # extract → normalize → should_cost → anomaly → tech → history → score
    graph.add_edge("extract_vendor_node",       "normalize_quotes_node")
    graph.add_edge("normalize_quotes_node",     "should_cost_node")
    graph.add_edge("should_cost_node",          "anomaly_detection_node")
    graph.add_edge("anomaly_detection_node",    "technical_compliance_node")
    graph.add_edge("technical_compliance_node", "supplier_history_node")
    graph.add_edge("supplier_history_node",     "score_all_vendors_node") # score uses history

    # score → risk → rank → report → email/HITL
    graph.add_edge("score_all_vendors_node",    "flag_all_vendors_node")
    graph.add_edge("flag_all_vendors_node",     "rank_and_summarise_node")
    graph.add_edge("rank_and_summarise_node",   "generate_report_node")
    graph.add_edge("generate_report_node",      "email_hitl_node")
    graph.add_edge("email_hitl_node",           "process_decision_node")

    # Conditional after decision
    graph.add_conditional_edges(
        "process_decision_node",
        should_generate_po,
        {
            "generate_po": "generate_po_node",
            "end_hold":    END,
            "end_reject":  END,
        },
    )
    graph.add_edge("generate_po_node", END)

    return graph


# ══════════════════════════════════════════════════════════════════════════════
# RUN THE AGENT  (updated initial_state with 4 new keys)
# ══════════════════════════════════════════════════════════════════════════════

# Outlook inbox scanning is Windows-only and no longer part of the flow
# (files arrive via the upload endpoint). Import defensively so the module
# still loads on Linux.
try:
    from GetOutlookDocuments import scan_inbox_for_rfq_quotes
except Exception:                                      # noqa: BLE001
    scan_inbox_for_rfq_quotes = None


def run_rfq_agent(
        rfq_item:             str   = "HR Steel Sheets 3mm",
        rfq_quantity:         float = 10000.0,
        rfq_unit:             str   = "Kg",
        delivery_location:    str   = "Mumbai Warehouse",
        vendor_quotes_folder: str   = "vendor_quotes",
        thread_id:            str   = "rfq-001",
):
    print(f"\n{'#'*60}")
    print(f"  RFQ INTELLIGENCE AGENT — STARTING")
    print(f"  Item     : {rfq_item}")
    print(f"  Quantity : {rfq_quantity:,} {rfq_unit}")
    print(f"  Location : {delivery_location}")
    print(f"  Thread   : {thread_id}")
    print(f"{'#'*60}")

    # ── Step 0: Get files from vendor_quotes folder ───────────────────────────
    # Use files from vendor_quotes folder (where extracted ZIP files go)
    print(f"\n{'─'*60}")
    print(f"STEP 0 — LOADING VENDOR QUOTE FILES")
    print(f"{'─'*60}")

    # Create scan_result for compatibility
    scan_result = {"vendor_name_map": {}, "files_downloaded": 0, "downloaded_files": []}

    # Look for files in vendor_quotes folder (both direct files and in subdirs)
    uploaded_files = []

    if os.path.exists(vendor_quotes_folder):
        # Get all PDF files recursively
        for root, dirs, files in os.walk(vendor_quotes_folder):
            for file in files:
                if file.lower().endswith(('.pdf', '.docx', '.xlsx')):
                    # Skip procurement_policy.pdf (it's for RAG, not vendor quotes)
                    if 'policy' not in file.lower():
                        filepath = os.path.join(root, file)
                        uploaded_files.append(filepath)

        if uploaded_files:
            print(f"  ✅ Found {len(uploaded_files)} vendor quote file(s)")
            for f in uploaded_files:
                print(f"     • {os.path.basename(f)}")
        else:
            print(f"\n  ⚠️  No vendor quote files found in '{vendor_quotes_folder}/'")
            print(f"      Please upload ZIP files with PDFs")
            return None   # nothing to process
    else:
        print(f"\n  ⚠️  Folder not found: '{vendor_quotes_folder}/'")
        return None

    graph  = build_rfq_graph()
    memory = MemorySaver()
    app    = graph.compile(checkpointer=memory)

    initial_state = {
        "rfq_item":             rfq_item,
        "rfq_quantity":         rfq_quantity,
        "rfq_unit":             rfq_unit,
        "delivery_location":    delivery_location,
        "vendor_quotes_folder": vendor_quotes_folder,
        "vendor_files":         [],
        # filename → sender display name (from inbox scanner, empty if manual files)
        "vendor_name_map":      scan_result.get("vendor_name_map", {}),
        "extracted_fields":     {},
        "landed_costs":         {},
        "normalized_quotes":    {},
        "should_cost_data":     {},
        "anomaly_flags":        {},
        "tech_scores":          {},
        "supplier_history":     {},
        "recommendation_reason":  "",
        "recommendation_details": {},
        "vendor_scores":        {},
        "risk_flags":           {},
        "ranked_vendors":       [],
        "qualified_vendors":    [],
        "top_recommendation":   "",
        "report_path":          "",
        "human_decision":       "",
        "selected_vendor":      "",
        "po_draft_path":        "",
        "po_draft_entry_id":    "",
        "po_draft_store_id":    "",
        "draft_entry_id":       "",
        "draft_store_id":       "",
        "email_subject":        "",
        "email_html":           "",
        "email_recipient":      "",
        "outlook_draft_created": False,
        "thread_id":            thread_id,
    }

    config = {"configurable": {"thread_id": thread_id}}

    # ── Phase 1: run until HITL interrupt ─────────────────────────────────────
    print(f"\n🚀 PHASE 1 — Running agent until HITL pause...")
    for event in app.stream(initial_state, config):
        pass

    state_snapshot = app.get_state(config)
    top_rec        = state_snapshot.values.get("top_recommendation", "N/A")
    rec_reason     = state_snapshot.values.get("recommendation_reason", "")

    # ── Save extracted quotes to JSON for RAG pipeline ──────────────────────────
    extracted_fields = state_snapshot.values.get("extracted_fields", {})
    if extracted_fields:
        with open("extracted_quotes.json", "w") as f:
            json.dump({"quotes": extracted_fields}, f, indent=2, default=str)
        print(f"✓ Saved extracted_quotes.json ({len(extracted_fields)} vendors)")

    print(f"\n{'─'*60}")
    print(f"⏸️  AGENT PAUSED — interrupt() fired at email_hitl_node")
    print(f"   Top recommendation : {top_rec}")
    if rec_reason:
        print(f"   Reason             : {rec_reason[:120]}...")
    print(f"   Excel report at    : RFQ_Comparison_Report.xlsx")
    print(f"   Check Outlook Drafts, then enter your decision below.")
    print(f"{'─'*60}")

    qualified_vendors = state_snapshot.values.get("qualified_vendors", [])

    print(f"\n📬 Reply options:")
    print(f"   1. APPROVE                  → proceed with {top_rec}")
    print(f"   2. SELECT: [vendor name]    → choose a different vendor")
    if qualified_vendors:
        print(f"      Qualified vendors (copy exact name):")
        for v in qualified_vendors:
            marker = " ← AI pick" if v == top_rec else ""
            print(f"        SELECT: {v}{marker}")
    print(f"   3. HOLD: [reason]           → pause, needs clarification")
    print(f"   4. REJECT: [reason]         → reject all, re-float RFQ")

    human_decision = input("\n   Enter your decision: ").strip()
    if not human_decision:
        human_decision = "APPROVE"

    print(f"\n   You replied: '{human_decision}'")

    # ── Phase 2: resume with decision ─────────────────────────────────────────
    print(f"\n🚀 PHASE 2 — Resuming with decision...")
    resume_input = Command(resume=human_decision)
    for event in app.stream(resume_input, config):
        pass

    final_state = app.get_state(config).values

    print(f"\n{'#'*60}")
    print(f"  RFQ INTELLIGENCE AGENT — COMPLETE")
    print(f"{'#'*60}")
    print(f"  Top Recommendation : {final_state.get('top_recommendation')}")
    print(f"  Manager Decision   : {final_state.get('human_decision')}")
    print(f"  Selected Vendor    : {final_state.get('selected_vendor')}")
    print(f"  Excel Report       : {final_state.get('report_path')}")
    print(f"  PO Draft (file)    : {final_state.get('po_draft_path')}")
    print(f"\n  📁 Output files:")
    print(f"     RFQ_Comparison_Report.xlsx")
    print(f"     extracted_quotes.json")
    print(f"     vendor_scores.json")
    print(f"     risk_flags.json")
    print(f"     supplier_history.json")
    po = final_state.get("po_draft_path", "")
    if po:
        print(f"     {po}")
    print(f"\n✅ Agent run complete!")

    return final_state


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    final = run_rfq_agent(
    rfq_item = "Aluminum Plates 5083 5mm",
    rfq_quantity = 5.0,
    rfq_unit = "Tons",
    delivery_location = "Chennai Plant",
    vendor_quotes_folder = os.environ.get(
        "VENDOR_QUOTES_FOLDER",
        os.path.join(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            "vendor_quotes",
        ),
    ),
    thread_id = "rfq-2026-002",
)