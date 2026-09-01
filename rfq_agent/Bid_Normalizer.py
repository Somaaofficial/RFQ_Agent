# Bid_Normalizer.py
# ─────────────────────────────────────────────────────────────────────────────
# Gap 1 fill: normalizes all vendor quotes to a common basis BEFORE scoring.
# Handles: currency → INR, freight inclusion/exclusion, unit consistency.
# Called as a single node after the parallel extract fan-in.
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI

load_dotenv()
api_key = os.getenv("MISTRAL_API_KEY")
client  = ChatMistralAI(model="mistral-small-latest", api_key=api_key)

# ── Static exchange rates to INR ──────────────────────────────────────────────
# Update these periodically or replace with a live API call.
RATES_TO_INR = {
    "INR": 1.0,
    "USD": 94.5,
    "EUR": 108.16,
    "GBP": 124.7,
    "JPY": 0.59,
    "AED": 25.69,
    "SGD": 73.09,
}

# Incoterms where freight is INCLUDED in the quoted price
FREIGHT_INCLUDED_INCOTERMS = {"cif", "ddp", "dap", "for", "delivered", "c&f"}


def _recalculate_landed_cost(fields: dict) -> float:
    """
    Landed cost = (unit_price_inr + freight_per_unit_inr) × (1 + gst_rate / 100)
    Uses the already-normalized price fields in the dict.
    """
    unit_price = float(fields.get("unit_price") or 0)
    freight    = float(fields.get("freight_per_unit") or 0)
    gst_rate   = float(fields.get("gst_rate") or 18)

    incoterm = str(fields.get("incoterm") or "").lower()
    if any(t in incoterm for t in FREIGHT_INCLUDED_INCOTERMS):
        freight = 0.0

    base   = unit_price + freight
    landed = base * (1 + gst_rate / 100)
    return round(landed, 2)


def _detect_currency(fields: dict, all_prices: list) -> str:
    """
    Heuristic: if this vendor's unit_price is < 20% of the median of all prices,
    it is likely in a foreign currency (e.g. USD when others are INR).
    Returns the detected currency string.
    """
    price = float(fields.get("unit_price") or 0)
    if not price or not all_prices:
        return "INR"

    valid = [p for p in all_prices if p and p > 0]
    if not valid:
        return "INR"

    median = sorted(valid)[len(valid) // 2]
    if median > 0 and price < median * 0.05:
        # Price is less than 5% of median — very likely USD or similar
        return "USD"
    if median > 0 and price < median * 0.15:
        return "USD"   # still suspicious

    return "INR"


def normalize_quotes(extracted_fields: dict, rfq_unit: str = "Kg") -> dict:
    """
    Main normalization entry point. Called by normalize_quotes_node in main_agent.py.

    Steps:
    1. Detect currency anomalies using heuristic + Mistral confirmation.
    2. Apply exchange rate conversion where needed.
    3. Ensure freight is correctly included/excluded based on incoterm.
    4. Recalculate landed_cost with normalized values.
    5. Attach normalization metadata to each vendor dict for audit trail.

    Args:
        extracted_fields: {vendor_name: {15-field dict}} from extract_vendor_node
        rfq_unit: the unit of measure for this RFQ (e.g. "Kg", "MT", "Piece")

    Returns:
        normalized: same structure, with corrected price/freight/landed_cost values
                    + added keys: currency_detected, normalization_notes,
                                  freight_treatment, landed_cost_normalized
    """
    print(f"\n{'='*60}")
    print(f"BID NORMALIZER — normalizing {len(extracted_fields)} vendors")
    print(f"Target: INR / {rfq_unit}")
    print(f"{'='*60}")

    if not extracted_fields:
        return {}

    # ── Step 1: gather all unit prices to detect outliers ────────────────────
    all_prices = [
        float(f.get("unit_price") or 0)
        for f in extracted_fields.values()
    ]

    # ── Step 2: build a compact summary for Mistral ──────────────────────────
    vendor_summary = {}
    for vendor, fields in extracted_fields.items():
        vendor_summary[vendor] = {
            "unit_price":      fields.get("unit_price"),
            "freight_per_unit": fields.get("freight_per_unit"),
            "incoterm":        fields.get("incoterm"),
            "gst_rate":        fields.get("gst_rate"),
            "special_conditions": str(fields.get("special_conditions") or "")[:120],
        }

    prompt = f"""
You are a procurement bid normalization expert.
Vendors have submitted quotes for: {rfq_unit} material.
All final scores will be in INR per {rfq_unit}.

Exchange rates to INR: {json.dumps(RATES_TO_INR)}

VENDOR QUOTE DATA:
{json.dumps(vendor_summary, indent=2)}

TASKS FOR EACH VENDOR:
1. CURRENCY: If unit_price looks like it is NOT in INR (unusually low vs others,
   or special_conditions mentions foreign currency/export), detect the currency
   and convert unit_price to INR. Otherwise keep as-is.
2. FREIGHT: If incoterm is Ex-Works/EXW, freight_per_unit is EXTRA — keep it.
   If incoterm is CIF/DDP/FOR/Delivered, freight is INCLUDED — set freight_per_unit to 0.
   If incoterm is null/unknown, use your best judgment from the price pattern.
3. FLAG any vendor whose minimum_order_qty might be in wrong units (e.g. pieces
   instead of {rfq_unit}).

Respond ONLY with valid JSON — no markdown, no explanation:
{{
  "<vendor_name>": {{
    "unit_price_inr":           <float — corrected price in INR>,
    "freight_per_unit_inr":     <float — 0 if included, otherwise the freight amount>,
    "currency_detected":        "INR" | "USD" | "EUR" etc,
    "currency_conversion_applied": true | false,
    "conversion_rate_used":     <float — 1.0 if no conversion>,
    "incoterm_normalized":      "<Ex-Works|CIF|DDP|FOR|Unknown>",
    "freight_treatment":        "included" | "extra" | "unknown",
    "normalization_notes":      "<short note or null>"
  }},
  ...
}}
"""

    normalization_map = {}
    try:
        response = client.invoke(prompt)
        raw = response.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        normalization_map = json.loads(raw.strip())
        print(f"   Mistral normalization analysis has been completed")
    except Exception as e:
        print(f"    Mistral normalization failed ({e}) — using heuristic fallback")

    # ── Step 3: apply normalization to each vendor ───────────────────────────
    normalized = {}

    for vendor, fields in extracted_fields.items():
        norm = normalization_map.get(vendor, {})
        nf   = dict(fields)   # shallow copy — we only change price/freight fields

        original_price   = float(fields.get("unit_price") or 0)
        original_freight = float(fields.get("freight_per_unit") or 0)
        original_landed  = float(fields.get("landed_cost") or 0)

        # ── Currency ─────────────────────────────────────────────────────────
        if norm.get("currency_conversion_applied"):
            corrected_price  = float(norm.get("unit_price_inr") or original_price)
            detected_currency = norm.get("currency_detected", "INR")
            rate_used         = float(norm.get("conversion_rate_used") or 1.0)
        else:
            # Heuristic fallback if Mistral call failed
            detected_currency = _detect_currency(fields, all_prices)
            if detected_currency != "INR":
                rate_used       = RATES_TO_INR.get(detected_currency, 1.0)
                corrected_price = round(original_price * rate_used, 2)
            else:
                detected_currency = "INR"
                rate_used         = 1.0
                corrected_price   = original_price

        nf["unit_price"]        = corrected_price
        nf["currency_detected"] = detected_currency

        if detected_currency != "INR":
            print(f"  💱 [{vendor}] {detected_currency} {original_price} "
                  f"→ INR {corrected_price:.2f} (rate: {rate_used})")

        # ── Freight ──────────────────────────────────────────────────────────
        corrected_freight = norm.get("freight_per_unit_inr")
        if corrected_freight is not None:
            nf["freight_per_unit"] = float(corrected_freight)
        else:
            # Heuristic: check incoterm ourselves
            incoterm_str = str(fields.get("incoterm") or "").lower()
            if any(t in incoterm_str for t in FREIGHT_INCLUDED_INCOTERMS):
                nf["freight_per_unit"] = 0.0

        freight_treatment = norm.get("freight_treatment", "unknown")
        nf["freight_treatment"]    = freight_treatment
        nf["incoterm_normalized"]  = norm.get("incoterm_normalized",
                                               fields.get("incoterm", "Unknown"))
        nf["normalization_notes"]  = norm.get("normalization_notes")

        # ── Recalculate landed cost with corrected values ────────────────────
        nf["landed_cost"] = _recalculate_landed_cost(nf)

        delta = nf["landed_cost"] - original_landed
        delta_str = (f" (Δ {delta:+.2f})" if abs(delta) > 0.01 else " (no change)")
        print(f"  ✅ [{vendor}] Landed cost: ₹{nf['landed_cost']:.2f}{delta_str}")

        normalized[vendor] = nf

    print(f"\n  Normalization complete — {len(normalized)} vendors processed")
    return normalized