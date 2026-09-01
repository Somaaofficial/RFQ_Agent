# Anomaly_Detector.py
# ─────────────────────────────────────────────────────────────────────────────
# Detects bid anomalies across all vendor quotes BEFORE scoring.
# Step 1 — Statistical checks (pure math, no LLM): identical prices, outliers.
# Step 2 — AI pattern analysis (Mistral): cartel hints, financial distress,
#           above-benchmark clusters.
# Runs after normalization + should-cost so all prices are comparable.
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
import statistics
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI

load_dotenv()
_client = ChatMistralAI(
    model   = "mistral-small-latest",
    api_key = os.getenv("MISTRAL_API_KEY"),
)

# Thresholds
IDENTICAL_THRESHOLD_PCT  = 2.0    # ±2% — treat as "same price" (cartel hint)
OUTLIER_LOW_THRESHOLD    = 0.70   # below 70% of median → suspiciously low
OUTLIER_HIGH_THRESHOLD   = 1.30   # above 130% of median → suspiciously high
ABOVE_BENCHMARK_WARN_PCT = 20.0   # all vendors >20% above benchmark → market issue


# ── Step 1: statistical anomaly checks ───────────────────────────────────────

def _stat_checks(normalized_quotes: dict, should_cost_data: dict) -> list:
    """Pure math checks  here— no LLM call. Returns list of anomaly dicts."""
    anomalies = []

    landed = {
        v: float(f.get("landed_cost") or 0)
        for v, f in normalized_quotes.items()
        if f.get("landed_cost")
    }
    valid = [(v, c) for v, c in landed.items() if c > 0]
    if len(valid) < 2:
        return anomalies

    costs  = [c for _, c in valid]
    median = statistics.median(costs)

    # ── Check 1: near-identical prices (cartel hint) ─────────────────────────
    vendors_list = list(valid)
    for i in range(len(vendors_list)):
        for j in range(i + 1, len(vendors_list)):
            v1, c1 = vendors_list[i]
            v2, c2 = vendors_list[j]
            if c1 > 0:
                diff_pct = abs(c1 - c2) / c1 * 100
                if diff_pct <= IDENTICAL_THRESHOLD_PCT:
                    anomalies.append({
                        "type":             "cartel_hint",
                        "severity":         "RED",
                        "vendors_involved": [v1, v2],
                        "detail": (
                            f"{v1} (₹{c1:.2f}) and {v2} (₹{c2:.2f}) "
                            f"quoted within {diff_pct:.1f}% of each other — "
                            f"coordinated pricing cannot be ruled out."
                        ),
                        "recommendation": (
                            "Investigate independently. Request revised quotes "
                            "after a cooling-off period. Consider adding new vendors."
                        ),
                    })

    # ── Check 2: outlier-low bid ──────────────────────────────────────────────
    for v, c in valid:
        if c < median * OUTLIER_LOW_THRESHOLD:
            pct_below = round((1 - c / median) * 100, 1)
            anomalies.append({
                "type":             "outlier_low",
                "severity":         "AMBER",
                "vendors_involved": [v],
                "detail": (
                    f"{v} quoted ₹{c:.2f} which is {pct_below}% below the median "
                    f"(₹{median:.2f}). This may indicate bait pricing, wrong specs "
                    f"understood, or a data entry error."
                ),
                "recommendation": (
                    "Verify scope — confirm vendor has included all cost components "
                    "(freight, GST, packaging). Request written confirmation of quote validity."
                ),
            })

    # ── Check 3: outlier-high bid ─────────────────────────────────────────────
    for v, c in valid:
        if c > median * OUTLIER_HIGH_THRESHOLD:
            pct_above = round((c / median - 1) * 100, 1)
            anomalies.append({
                "type":             "outlier_high",
                "severity":         "AMBER",
                "vendors_involved": [v],
                "detail": (
                    f"{v} quoted ₹{c:.2f} which is {pct_above}% above the median "
                    f"(₹{median:.2f}). May indicate premium brand, different spec, "
                    f"or limited interest in the RFQ."
                ),
                "recommendation": (
                    "Confirm vendor has quoted against correct specification. "
                    "Include in comparison but flag to management."
                ),
            })

    # ── Check 4: all vendors above should-cost benchmark ─────────────────────
    benchmark = should_cost_data.get("benchmark_price", 0)
    if benchmark > 0 and should_cost_data.get("all_above_benchmark"):
        pct_above_bench = round((median / benchmark - 1) * 100, 1)
        if pct_above_bench > ABOVE_BENCHMARK_WARN_PCT:
            anomalies.append({
                "type":             "all_above_benchmark",
                "severity":         "AMBER",
                "vendors_involved": list(landed.keys()),
                "detail": (
                    f"All {len(valid)} vendors are quoting above the AI benchmark of "
                    f"₹{benchmark:.2f}. Median quote is {pct_above_bench:.1f}% above "
                    f"fair market. This may indicate specification issues, supply "
                    f"constraints, or insufficient vendor competition."
                ),
                "recommendation": (
                    "Consider re-floating RFQ with wider vendor list, "
                    "relaxed specifications, or different delivery window."
                ),
            })

    return anomalies


# ── Step 2: AI pattern analysis ───────────────────────────────────────────────

def _ai_analysis(normalized_quotes: dict, should_cost_data: dict,
                 rfq_item: str, stat_anomalies: list) -> list:
    """Calls Mistral to look for patterns the statistical checks can't catch."""

    price_table = {
        v: {
            "landed_cost":  round(float(f.get("landed_cost") or 0), 2),
            "advance_pct":  f.get("advance_percentage", 0),
            "delivery_days": f.get("delivery_days"),
            "certifications": f.get("certifications", []),
        }
        for v, f in normalized_quotes.items()
    }

    prompt = f"""
You are a procurement fraud and risk analyst.

RFQ item: {rfq_item}
AI benchmark price: INR {should_cost_data.get('benchmark_price', 'N/A')} per unit

VENDOR BID DATA (normalized, all in INR):
{json.dumps(price_table, indent=2)}

STATISTICAL ANOMALIES ALREADY DETECTED:
{json.dumps([a["type"] for a in stat_anomalies], indent=2)}

Look for these additional patterns that statistics alone cannot catch:
1. FINANCIAL DISTRESS SIGNAL: A normally-priced vendor suddenly quoting 
   far below their typical range (combined with 100% advance demand or 
   very short validity) — may indicate cash-flow problems.
2. ANCHOR PRICING: One vendor quoted very high to make others look cheap by comparison.
3. SPEC GAMING: A vendor seems to be quoting a different/lower spec than asked.
4. COLLUSION BEYOND PRICE: Similar payment terms AND delivery days AND prices 
   across multiple vendors (coordinated beyond just pricing).

Only flag genuine concerns — do not invent anomalies. If you see nothing beyond 
what's already detected, return an empty array.

Reply ONLY with valid JSON — no markdown:
{{
  "additional_anomalies": [
    {{
      "type":             "<financial_distress | anchor_pricing | spec_gaming | coord_terms>",
      "severity":         "RED" | "AMBER",
      "vendors_involved": ["vendor name(s)"],
      "detail":           "<specific observation with numbers>",
      "recommendation":   "<what buyer should do>"
    }}
  ]
}}
"""

    try:
        resp = _client.invoke(prompt)
        raw  = resp.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        return data.get("additional_anomalies", [])
    except Exception as e:
        print(f"  ⚠️  AI anomaly analysis failed ({e}) — using statistical results only")
        return []


# ── Main public function ──────────────────────────────────────────────────────

def detect_bid_anomalies(
    normalized_quotes: dict,
    should_cost_data:  dict,
    rfq_item:          str,
) -> dict:
    """
    Detects anomalies across all vendor bids before scoring begins.

    Returns:
    {
      "has_anomalies":    bool,
      "red_count":        int,
      "amber_count":      int,
      "anomaly_summary":  str   — one sentence for email/report,
      "anomalies":        [list of anomaly dicts],
      "per_vendor_flags": {vendor_name: ["flag description", ...]},
    }
    """
    print(f"\n{'='*60}")
    print(f"ANOMALY DETECTOR")
    print(f"Analysing number of  {len(normalized_quotes)} vendor bids...")
    print(f"{'='*60}")

    # Step 1 — statistical
    stat_anomalies = _stat_checks(normalized_quotes, should_cost_data)

    # Step 2 — AI pattern analysis
    ai_anomalies   = _ai_analysis(normalized_quotes, should_cost_data,
                                   rfq_item, stat_anomalies)

    all_anomalies  = stat_anomalies + ai_anomalies

    red_count   = sum(1 for a in all_anomalies if a.get("severity") == "RED")
    amber_count = sum(1 for a in all_anomalies if a.get("severity") == "AMBER")

    # Build per-vendor flag map
    per_vendor_flags: dict = {}
    for anomaly in all_anomalies:
        for vendor in anomaly.get("vendors_involved", []):
            per_vendor_flags.setdefault(vendor, [])
            per_vendor_flags[vendor].append(
                f"[{anomaly['severity']}] {anomaly['type'].replace('_', ' ').title()}: "
                f"{anomaly['detail'][:80]}..."
            )

    # Summary sentence
    if not all_anomalies:
        summary = "No bid anomalies detected — all quotes appear independent and within normal range."
    elif red_count > 0:
        types = list({a["type"] for a in all_anomalies if a["severity"] == "RED"})
        summary = (f"{red_count} RED anomaly detected: "
                   f"{', '.join(t.replace('_', ' ') for t in types)}. Immediate review recommended.")
    else:
        summary = (f"{amber_count} amber-level anomaly detected. "
                   f"Review before finalising award.")

    print(f"\n  Anomalies found: {len(all_anomalies)} "
          f"(RED: {red_count}, AMBER: {amber_count})")
    for a in all_anomalies:
        icon = "🔴" if a["severity"] == "RED" else "🟡"
        print(f"  {icon} {a['type'].replace('_', ' ').title()}: "
              f"{', '.join(a['vendors_involved'][:2])}")
    if not all_anomalies:
        print(f"  ✅ No anomalies detected")

    return {
        "has_anomalies":    len(all_anomalies) > 0,
        "red_count":        red_count,
        "amber_count":      amber_count,
        "anomaly_summary":  summary,
        "anomalies":        all_anomalies,
        "per_vendor_flags": per_vendor_flags,
    }