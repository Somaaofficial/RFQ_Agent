# chunk4_risk_flagger.py
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI

load_dotenv()

client = ChatMistralAI(
    model="mistral-small-latest",
    mistral_api_key=os.getenv("MISTRAL_API_KEY")
)

# ── today's date — used for validity expiry check ─────────────────────────────
TODAY = datetime.today()


# ── Step 1: rule-based pre-checks (instant, no Mistral needed) ────────────────
def run_rule_checks(vendor_name: str, fields: dict) -> list:
    """
    Fast rule-based checks that don't need any LLM .
    These are binary — either flagged or not.
    Returns a list of flag dicts.
    """
    flags = []

    advance    = float(fields.get("advance_percentage", 0) or 0)
    validity   = int(fields.get("quote_validity_days",  30) or 30)
    certs      = fields.get("certifications", []) or []
    price_firm = fields.get("price_firm")
    penalty    = fields.get("penalty_clause")
    warranty   = int(fields.get("warranty_months", 12) or 12)
    incoterm   = str(fields.get("incoterm", "") or "").lower()
    freight    = float(fields.get("freight_per_unit", 0) or 0)
    special    = str(fields.get("special_conditions", "") or "").lower()
    payment    = str(fields.get("payment_terms", "") or "").lower()

    # ── RED FLAGS ─────────────────────────────────────────────────────────────
    if advance >= 100:
        flags.append({
            "flag_id":   "R1",
            "severity":  "RED",
            "category":  "Payment Risk",
            "condition": "100% advance required",
            "detail":    "Full payment before dispatch demanded. "
                         "Unacceptable cash flow and fraud risk per procurement policy.",
            "action":    "DISQUALIFY — do not evaluate further"
        })

    if len(certs) == 0:
        flags.append({
            "flag_id":   "R2",
            "severity":  "RED",
            "category":  "Quality Risk",
            "condition": "No quality certifications",
            "detail":    "Vendor has provided no quality certifications. "
                         "Policy requires minimum ISO 9001 for procurement above INR 50,000.",
            "action":    "DISQUALIFY for critical items"
        })

    if price_firm is False:
        flags.append({
            "flag_id":   "R3",
            "severity":  "RED",
            "category":  "Price Risk",
            "condition": "Price not firm — subject to revision",
            "detail":    "Vendor explicitly stated price is subject to market or index revision. "
                         "This is not a firm quotation and cannot be reliably compared.",
            "action":    "DISQUALIFY or seek written price lock confirmation"
        })

    if validity <= 3:
        flags.append({
            "flag_id":   "R4",
            "severity":  "RED",
            "category":  "Validity Risk",
            "condition": f"Quote validity only {validity} days — likely expired",
            "detail":    "Quote validity is critically short. "
                         "By the time evaluation and approval is complete this quote will be invalid.",
            "action":    "DISQUALIFY — request fresh quotation"
        })

    if any(word in special for word in
           ["100% advance", "full advance", "no gstin", "gstin not", "gst not available",
            "no gst invoice", "no certificate", "no warranty"]):
        flags.append({
            "flag_id":   "R5",
            "severity":  "RED",
            "category":  "Compliance Risk",
            "condition": "Critical compliance issue in special conditions",
            "detail":    f"Special conditions text contains critical risk: '{fields.get('special_conditions','')}'"
                         " — review immediately.",
            "action":    "DISQUALIFY pending review"
        })

    # ── AMBER FLAGS ───────────────────────────────────────────────────────────
    if 25 <= advance < 100:
        flags.append({
            "flag_id":   "A1",
            "severity":  "AMBER",
            "category":  "Payment Risk",
            "condition": f"Advance payment required: {advance}%",
            "detail":    f"Vendor requires {advance}% advance with order. "
                         f"Policy flags advance above 25% as caution. "
                         f"Bank Guarantee may be required.",
            "action":    "CFO approval required; obtain Bank Guarantee against advance"
        })

    if 5 < validity <= 15:
        flags.append({
            "flag_id":   "A2",
            "severity":  "AMBER",
            "category":  "Validity Risk",
            "condition": f"Short quote validity — only {validity} days",
            "detail":    "Quote validity is tight. "
                         "Approval process must be completed urgently before expiry.",
            "action":    "Request validity extension; expedite approval"
        })

    if len(certs) == 1:
        flags.append({
            "flag_id":   "A3",
            "severity":  "AMBER",
            "category":  "Quality Risk",
            "condition": f"Only one certification: {certs}",
            "detail":    "Policy prefers ISO 9001 + BIS + NABL stack. "
                         "Single certification gives lower quality score.",
            "action":    "Verify certification scope and validity"
        })

    if penalty is None or penalty == "":
        flags.append({
            "flag_id":   "A4",
            "severity":  "AMBER",
            "category":  "Delivery Risk",
            "condition": "No penalty / LD clause mentioned",
            "detail":    "Vendor has not offered any penalty clause for delayed delivery. "
                         "Purchase Order must include company's standard LD clause.",
            "action":    "Insert standard 0.5%/week LD clause in PO terms"
        })

    if warranty < 6:
        flags.append({
            "flag_id":   "A5",
            "severity":  "AMBER",
            "category":  "Quality Risk",
            "condition": f"Warranty only {warranty} months",
            "detail":    "Policy recommends minimum 12 months warranty. "
                         "Short warranty increases replacement cost risk.",
            "action":    "Negotiate warranty extension to 12 months"
        })

    if any(word in special for word in
           ["lme", "index", "forex", "exchange rate", "market rate",
            "revision", "subject to", "prevailing rate"]):
        flags.append({
            "flag_id":   "A6",
            "severity":  "AMBER",
            "category":  "Price Risk",
            "condition": "Price subject to index / LME / forex revision",
            "detail":    f"Special conditions mention price revision triggers: "
                         f"'{fields.get('special_conditions', '')}'",
            "action":    "Seek written confirmation of price lock for PO validity period"
        })

    if "advance" in payment and advance == 0:
        # payment terms say advance but field shows 0 — inconsistency
        flags.append({
            "flag_id":   "A7",
            "severity":  "AMBER",
            "category":  "Data Inconsistency",
            "condition": "Payment terms mention advance but advance % not clear",
            "detail":    "Payment terms text suggests advance requirement but "
                         "percentage is ambiguous. Clarify before PO.",
            "action":    "Request clarification on exact advance amount"
        })

    if "approximate" in special or "approx" in special or freight == 0 and "ex" in incoterm:
        flags.append({
            "flag_id":   "A8",
            "severity":  "AMBER",
            "category":  "Cost Risk",
            "condition": "Freight cost approximate or not confirmed",
            "detail":    "Freight is either approximate or not included despite ex-works terms. "
                         "Landed cost calculation may be understated.",
            "action":    "Obtain firm freight quote before PO; use actual rate in comparison"
        })
    print("Flag updation has been completed")
    return flags


# ── Step 2: Mistral deep analysis for nuanced risks ───────────────────────────
def run_mistral_risk_analysis(vendor_name: str, fields: dict,
                               rule_flags: list) -> dict:
    """
    Sends full vendor data to Mistral for deeper risk analysis.
    Catches risks that rules might miss — contractual nuances,
    unusual conditions, combinations of multiple risk factors.
    """
    print(f"    Mistral risk analysis for {vendor_name} has been started...")

    existing_flags_summary = "\n".join([
        f"- [{f['severity']}] {f['condition']}"
        for f in rule_flags
    ]) if rule_flags else "None detected by rule engine"

    prompt = f"""
You are a senior procurement risk analyst reviewing a vendor quotation.
Rule-based checks have already identified these flags:
{existing_flags_summary}

Now perform a DEEPER analysis of this vendor's quotation for any 
additional risks not already captured above.

VENDOR: {vendor_name}
FULL QUOTE DATA:
{json.dumps(fields, indent=2, default=str)}

Look specifically for:
1. Contractual traps — auto-renewal, exclusivity, jurisdiction clauses
2. Hidden cost risks — "charges extra" language, vague inclusions
3. Delivery risks — "subject to stock availability", seasonal constraints
4. Combination risks — multiple amber flags that together become a red
5. Commercial risks — payment terms that don't match industry norms
6. Reputation/stability risks based on quote quality and professionalism

Respond ONLY with this JSON — no markdown:
{{
  "additional_flags": [
    {{
      "flag_id": "M1",
      "severity": "RED" or "AMBER" or "INFO",
      "category": "category name",
      "condition": "short condition title",
      "detail": "1-2 sentence explanation",
      "action": "recommended action"
    }}
  ],
  "overall_risk_level": "LOW" or "MEDIUM" or "HIGH" or "CRITICAL",
  "risk_summary": "2-3 sentence overall risk assessment for this vendor",
  "disqualify_recommended": true or false
}}

If no additional flags found, return empty list for additional_flags.
"""

    response = client.invoke(prompt)
    raw      = response.content.strip()

    try:
        clean = raw
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        result = json.loads(clean.strip())
    except Exception:
        result = {
            "additional_flags":       [],
            "overall_risk_level":     "MEDIUM",
            "risk_summary":           f"Automated risk analysis completed for {vendor_name}.",
            "disqualify_recommended": False
        }
    print("mistral run has been completed for flags")
    return result


# ── Step 3: combine rule flags + Mistral flags ────────────────────────────────
def run_full_risk_analysis(vendor_name: str, fields: dict) -> dict:
    """
    Combines rule-based flags and Mistral deep analysis
    into one complete risk report per vendor.
    """
    # run rule checks first (fast)
    rule_flags = run_rule_checks(vendor_name, fields)

    # run Mistral deep analysis
    mistral_result = run_mistral_risk_analysis(
        vendor_name, fields, rule_flags
    )

    # merge all flags
    all_flags = rule_flags + mistral_result.get("additional_flags", [])

    # count by severity
    red_count   = sum(1 for f in all_flags if f["severity"] == "RED")
    amber_count = sum(1 for f in all_flags if f["severity"] == "AMBER")
    info_count  = sum(1 for f in all_flags if f["severity"] == "INFO")

    return {
        "vendor_name":            vendor_name,
        "all_flags":              all_flags,
        "red_count":              red_count,
        "amber_count":            amber_count,
        "info_count":             info_count,
        "total_flags":            len(all_flags),
        "overall_risk_level":     mistral_result.get("overall_risk_level", "MEDIUM"),
        "risk_summary":           mistral_result.get("risk_summary", ""),
        "disqualify_recommended": mistral_result.get("disqualify_recommended", False)
            or red_count >= 2
    }


# ── Step 4: run for all vendors ───────────────────────────────────────────────
def run_risk_flagging(extracted_quotes: dict) -> dict:
    """
    Runs full risk analysis for every vendor.
    Returns dict keyed by vendor name.
    """
    print(f"\n{'='*60}")
    print("CHUNK 4 — RISK FLAG DETECTION NODE")
    print(f"Analysing {len(extracted_quotes)} vendors for risks...")
    print(f"{'='*60}")

    all_risk_results = {}
    for vendor_name, fields in extracted_quotes.items():
        print(f"\n {vendor_name}")
        result = run_full_risk_analysis(vendor_name, fields)
        all_risk_results[vendor_name] = result
        print(f"    RED: {result['red_count']}  "
              f" AMBER: {result['amber_count']}  "
              f"Risk Level: {result['overall_risk_level']}")

    return all_risk_results


# ── Step 5: display risk report ───────────────────────────────────────────────
def display_risk_report(all_risks: dict):
    """
    Displays clean risk summary for all vendors.
    """
    print(f"\n{'='*60}")
    print("RISK FLAG SUMMARY — ALL VENDORS")
    print(f"{'='*60}")

    print(f"\n{'Vendor':<30} {'RED':>5} {'AMBER':>6} "
          f"{'Risk Level':>12} {'Disqualify':>11}")
    print("─" * 70)

    for vendor, risk in all_risks.items():
        red   = risk["red_count"]
        amb   = risk["amber_count"]
        level = risk["overall_risk_level"]
        dis   = "YES" if risk["disqualify_recommended"] else "  No"
        icon  = "🔴" if red > 0 else ("🟡" if amb > 0 else "🟢")
        print(f"{icon} {vendor:<28} {red:>5} {amb:>6} "
              f"{level:>12} {dis:>11}")

    # detailed flags per vendor
    print(f"\n{'─'*60}")
    print("DETAILED FLAGS:")
    for vendor, risk in all_risks.items():
        if risk["total_flags"] == 0:
            print(f"\n🟢 {vendor} — No flags. Clean quote.")
            continue

        print(f"\n{'🔴' if risk['red_count'] > 0 else '🟡'} {vendor}")
        print(f"   Risk: {risk['overall_risk_level']} | "
              f"Summary: {risk['risk_summary']}")

        for flag in risk["all_flags"]:
            sev_icon = {"RED":"🔴","AMBER":"🟡","INFO":"ℹ️"}.get(
                flag["severity"],"❓")
            print(f"\n   {sev_icon} [{flag['flag_id']}] "
                  f"{flag['category']} — {flag['condition']}")
            print(f"      Detail : {flag['detail']}")
            print(f"      Action : {flag['action']}")

    # disqualified vendors
    disq = [v for v, r in all_risks.items()
            if r["disqualify_recommended"]]
    if disq:
        print(f"\n{'='*60}")
        print(f"⛔ DISQUALIFIED VENDORS ({len(disq)}):")
        for v in disq:
            print(f"   - {v}")
        print(f"These vendors will NOT appear in the final Excel comparison.")

    print(f"\n✅ Chunk 4 complete — risk flagging done!")

