# Should_Cost_Estimator.py
# ─────────────────────────────────────────────────────────────────────────────
# Estimates the fair market / benchmark price for the RFQ item using Mistral.
# Compares every vendor's normalized landed cost against the benchmark.
# Runs after normalization so all prices are in INR before comparison.
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


def estimate_should_cost(
    rfq_item:             str,
    rfq_quantity:         float,
    rfq_unit:             str,
    delivery_location:    str,
    normalized_quotes:    dict,
) -> dict:
    """
    Estimates the fair market benchmark price for the RFQ item.

    Uses Mistral to reason about what the item should cost based on:
    - The item description and specs
    - The quantity and unit
    - The cluster of vendor prices received (as calibration data)

    Returns:
    {
      "benchmark_price":               float  — INR per unit (AI estimate),
      "benchmark_basis":               str    — how the estimate was derived,
      "benchmark_confidence":          str    — High / Medium / Low,
      "market_assessment":             str    — one-sentence overall view,
      "all_above_benchmark":           bool,
      "per_vendor": {
          vendor_name: {
              "landed_cost":           float,
              "deviation_pct":         float  — positive = above benchmark,
              "deviation_inr_total":   float  — (deviation_pct/100) × qty × unit_cost,
              "status":                str    — Fair / Above market / Below market / Suspiciously low,
          }
      }
    }
    """
    print(f"\n{'='*60}")
    print(f"SHOULD-COST ESTIMATOR has been started")
    print(f"Item: {rfq_item}  |  Qty: {rfq_quantity:,.0f} {rfq_unit}")
    print(f"{'='*60}")

    # ── Build price snapshot from normalized quotes ──────────────────────────
    landed_costs = {
        v: float(f.get("landed_cost") or 0)
        for v, f in normalized_quotes.items()
        if f.get("landed_cost")
    }

    valid_costs = [c for c in landed_costs.values() if c > 0]
    if not valid_costs:
        return _fallback(rfq_item, rfq_unit)

    median_cost = statistics.median(valid_costs)
    min_cost    = min(valid_costs)
    max_cost    = max(valid_costs)

    price_summary = {
        v: round(c, 2) for v, c in landed_costs.items()
    }

    # ── Ask Mistral for benchmark estimate ───────────────────────────────────
    prompt = f"""
You are a senior procurement analyst with deep knowledge of Indian industrial markets.
and you have good knowledge about the RFQ's which are used in indian market

RFQ DETAILS:
- Item: {rfq_item}
- Quantity required: {rfq_quantity:,.0f} {rfq_unit}
- Delivery location: {delivery_location}

VENDOR QUOTES RECEIVED (INR landed cost per {rfq_unit}):
{json.dumps(price_summary, indent=2)}

Price statistics:
- Lowest quote  : INR {min_cost:.2f}
- Median quote  : INR {median_cost:.2f}
- Highest quote : INR {max_cost:.2f}

Based on your knowledge of this type of item, Indian procurement markets, typical
manufacturing costs, freight, GST, and trader margins:

1. Estimate a fair SHOULD-COST benchmark price (INR per {rfq_unit}).
2. Explain briefly what drives this estimate (material cost, margin, logistics).
3. Rate your confidence: High (well-known commodity), Medium (some uncertainty),
   or Low (specialist item, limited data).
4. Give a one-sentence overall market assessment.

Reply ONLY with valid JSON — no markdown:
{{
  "benchmark_price":       <float — your fair market estimate in INR per {rfq_unit}>,
  "benchmark_basis":       "<2-3 sentences explaining what drives this price>",
  "benchmark_confidence":  "High" | "Medium" | "Low",
  "market_assessment":     "<one sentence overall view of the quotes vs fair market>"
}}
"""

    benchmark_price    = median_cost * 0.92   # fallback: 8% below median
    benchmark_basis    = "Estimated from median of vendor quotes received."
    benchmark_conf     = "Low"
    market_assessment  = f"Benchmark estimated from {len(valid_costs)} vendor quotes."

    try:
        resp = _client.invoke(prompt)
        raw  = resp.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())

        benchmark_price   = float(data.get("benchmark_price",   benchmark_price))
        benchmark_basis   = data.get("benchmark_basis",   benchmark_basis)
        benchmark_conf    = data.get("benchmark_confidence", benchmark_conf)
        market_assessment = data.get("market_assessment",  market_assessment)

        print(f"  AI Benchmark price is    : ₹{benchmark_price:.2f} / {rfq_unit}")
        print(f"  AI  Confidence  ABOUT bench mark is     : {benchmark_conf}")
        print(f"   AI  Market view   value is   : {market_assessment}")
    except Exception as e:
        print(f"  ⚠️  Mistral call failed ({e}) — using statistical fallback")

    # ── Per-vendor deviation analysis ────────────────────────────────────────
    per_vendor = {}
    all_above  = True

    for vendor, lc in landed_costs.items():
        if benchmark_price > 0:
            dev_pct   = round((lc - benchmark_price) / benchmark_price * 100, 1)
        else:
            dev_pct   = 0.0

        dev_inr_total = round((lc - benchmark_price) * rfq_quantity, 0)

        if dev_pct < -25:
            status = "Suspiciously low"
        elif dev_pct < -5:
            status = "Below market"
        elif dev_pct <= 10:
            status = "Fair"
        elif dev_pct <= 25:
            status = "Above market"
        else:
            status = "Significantly overpriced"

        if dev_pct <= 10:
            all_above = False

        per_vendor[vendor] = {
            "landed_cost":          round(lc, 2),
            "deviation_pct":        dev_pct,
            "deviation_inr_total":  dev_inr_total,
            "status":               status,
        }

        icon = ("🟢" if "Fair" in status or "Below" in status
                else "🔴" if "Suspicious" in status or "Significantly" in status
                else "🟡")
        print(f"  {icon} [{vendor}]  ₹{lc:.2f}  →  {dev_pct:+.1f}%  ({status})")

    if all_above:
        print(f"\n  ⚠️  ALL vendors are above the benchmark — consider re-floating with tighter specs")

    return {
        "benchmark_price":      round(benchmark_price, 2),
        "benchmark_basis":      benchmark_basis,
        "benchmark_confidence": benchmark_conf,
        "market_assessment":    market_assessment,
        "all_above_benchmark":  all_above,
        "per_vendor":           per_vendor,
    }


def _fallback(rfq_item: str, rfq_unit: str) -> dict:
    return {
        "benchmark_price":      0.0,
        "benchmark_basis":      "Could not estimate — no valid vendor prices available.",
        "benchmark_confidence": "Low",
        "market_assessment":    f"Benchmark unavailable for {rfq_item}.",
        "all_above_benchmark":  False,
        "per_vendor":           {},
    }