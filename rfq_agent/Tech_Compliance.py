# Tech_Compliance.py
# ─────────────────────────────────────────────────────────────────────────────
# Gap 2 fill: checks whether each vendor's quote meets the TECHNICAL
# specifications of the RFQ before commercial scoring begins.
# Prevents a cheapest-but-spec-mismatched vendor from winning on price alone.
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI

load_dotenv()
api_key = os.getenv("MISTRAL_API_KEY")
client  = ChatMistralAI(model="mistral-small-latest", api_key=api_key)


# ── Scoring weights for the 5 technical sub-criteria ─────────────────────────
TECH_WEIGHTS = {
    "certification":  40,   # Does vendor have relevant certifications?
    "moq_feasibility": 20,  # Can vendor fulfill the required quantity?
    "quote_validity":  15,  # Is the quote valid long enough?
    "price_firmness":  15,  # Is the price firm (not subject to revision)?
    "warranty":        10,  # Is warranty provided?
}

# ── Hard disqualification triggers ───────────────────────────────────────────
DISQUALIFY_TRIGGERS = [
    "moq_exceeds_rfq",       # vendor can't supply the quantity needed
    "validity_below_7_days", # quote expires before procurement can complete
    "zero_certs_safety_item", # no certifications on a BIS-mandated product
]


def check_technical_compliance(
    vendor_name: str,
    fields: dict,
    rfq_specs: dict,
) -> dict:
    """
    Evaluates one vendor's quote against the RFQ technical/commercial
    requirements.

    Hard, deterministic checks are performed locally first.
    LLM is used only for specification/certification interpretation
    and scoring of the remaining requirements.

    Args:
        vendor_name: display name of the vendor

        fields:
            Normalized extracted fields for this vendor.

        rfq_specs:
            {
                "item": str,
                "quantity": float,
                "unit": str,
                "delivery_location": str
            }

    Returns:
        {
            "supplier": str,
            "technical_score": int,
            "certification_score": int,
            "moq_score": int,
            "validity_score": int,
            "price_firm_score": int,
            "warranty_score": int,
            "compliance_flags": list,
            "disqualify_on_tech": bool,
            "disqualify_reasons": list,
            "spec_match_summary": str
        }
    """

    # =========================================================
    # 1. RFQ DETAILS
    # =========================================================

    rfq_item = rfq_specs.get(
        "item",
        "Unknown"
    )

    rfq_quantity = float(
        rfq_specs.get("quantity") or 0
    )

    rfq_unit = rfq_specs.get(
        "unit",
        "Kg"
    )

    rfq_delivery_location = rfq_specs.get(
        "delivery_location",
        "Bengaluru"
    )

    # =========================================================
    # 2. LOCAL HARD-RULE CHECKS
    # =========================================================
    #
    # These checks don't require an LLM because they are
    # deterministic comparisons.
    # =========================================================

    disqualify_reasons = []
    compliance_flags = []

    # ---------------------------------------------------------
    # MOQ CHECK
    # ---------------------------------------------------------

    moq = float(
        fields.get("minimum_order_qty") or 0
    )

    if (
        moq > 0
        and rfq_quantity > 0
        and moq > rfq_quantity
    ):

        disqualify_reasons.append(
            "moq_exceeds_rfq"
        )

        compliance_flags.append(
            f"MOQ ({moq:,.0f} {rfq_unit}) exceeds "
            f"RFQ quantity ({rfq_quantity:,.0f} {rfq_unit})"
        )

    # ---------------------------------------------------------
    # QUOTE VALIDITY CHECK
    # ---------------------------------------------------------

    validity = float(
        fields.get("quote_validity_days") or 0
    )

    if (
        validity > 0
        and validity < 7
    ):

        disqualify_reasons.append(
            "validity_below_7_days"
        )

        compliance_flags.append(
            f"Quote validity only {validity:.0f} days "
            f"— too short for procurement cycle"
        )

    # ---------------------------------------------------------
    # CERTIFICATION CHECK
    # ---------------------------------------------------------
    #
    # IMPORTANT:
    #
    # We do NOT assume:
    #
    #     steel = BIS
    #
    # here.
    #
    # Certification requirements depend on the actual
    # RFQ requirements / applicable product requirements.
    #
    # The LLM will evaluate certification relevance below.
    # ---------------------------------------------------------

    certs = fields.get(
        "certifications"
    ) or []

    # =========================================================
    # 3. IF HARD DISQUALIFICATION ALREADY EXISTS
    # =========================================================
    #
    # No reason to spend an LLM call if a deterministic
    # mandatory rule has already failed.
    # =========================================================

    if disqualify_reasons:

        # Certification is not automatically zero unless
        # certification itself caused the disqualification.
        cert_score = 40

        if "zero_certs_required" in disqualify_reasons:
            cert_score = 0

        # MOQ
        moq_score = (
            0
            if "moq_exceeds_rfq" in disqualify_reasons
            else 20
        )

        # Validity
        valid_score = (
            0
            if "validity_below_7_days" in disqualify_reasons
            else 15
        )

        # We don't evaluate these because the vendor has
        # already failed a mandatory condition.
        price_firm_score = 0
        warranty_score = 0

        total = (
            cert_score
            + moq_score
            + valid_score
            + price_firm_score
            + warranty_score
        )

        return {
            "supplier": vendor_name,

            "technical_score": total,

            "certification_score": cert_score,

            "moq_score": moq_score,

            "validity_score": valid_score,

            "price_firm_score": price_firm_score,

            "warranty_score": warranty_score,

            "compliance_flags": compliance_flags,

            "disqualify_on_tech": True,

            "disqualify_reasons": disqualify_reasons,

            "spec_match_summary": (
                f"{vendor_name} disqualified on "
                f"technical/commercial compliance grounds: "
                + "; ".join(compliance_flags)
            ),
        }

    # =========================================================
    # 4. LLM EVALUATION
    # =========================================================
    #
    # Vendors that pass hard rules reach here.
    #
    # The LLM evaluates:
    #
    # - Specification match
    # - Certification relevance
    # - MOQ feasibility
    # - Quote validity
    # - Price firmness
    # - Warranty
    #
    # =========================================================

    prompt = f"""
You are a technical procurement evaluator.

Evaluate the vendor quotation against the RFQ requirements.

IMPORTANT:
- Do not invent vendor information.
- Do not assume a certification is required unless the RFQ
  specification or the information provided establishes that
  requirement.
- Do not assume that every product category has the same
  certification requirements.
- If the RFQ does not specify a certification requirement,
  assess whether the vendor certifications are relevant to
  the product category and clearly state the basis.
- Do not automatically classify a product as steel, chemical,
  electrical, IT, etc. unless the RFQ description supports it.
- If information is unavailable, use the "not mentioned"
  scoring rule.
- Return ONLY valid JSON.

=========================================================
RFQ REQUIREMENTS
=========================================================

Item:
{rfq_item}

Quantity:
{rfq_quantity:,.0f} {rfq_unit}

Delivery Location:
{rfq_delivery_location}

=========================================================
VENDOR
=========================================================

Vendor:
{vendor_name}

Unit Price:
{fields.get("unit_price", "N/A")} INR/{rfq_unit}

Incoterm:
{fields.get(
    "incoterm_normalized",
    fields.get("incoterm", "N/A")
)}

Delivery Lead Time:
{fields.get("delivery_days", "N/A")} working days

Minimum Order Quantity:
{fields.get("minimum_order_qty", "N/A")} {rfq_unit}

Certifications:
{json.dumps(certs)}

Warranty:
{fields.get("warranty_months", "N/A")} months

Price Firm:
{fields.get("price_firm", "Unknown")}

Quote Validity:
{fields.get("quote_validity_days", "N/A")} days

Special Conditions:
{str(fields.get("special_conditions") or "None")[:200]}

=========================================================
SCORING RUBRIC
=========================================================

1. CERTIFICATION MATCH — MAX 40

Evaluate how well the vendor's certifications match the
actual RFQ/product requirements.

If the RFQ explicitly requires specific certifications,
check for those certifications.

If no certification requirement is explicitly given:
evaluate relevance and completeness based only on the
information available.

Do NOT assume every product requires BIS.

Return a score from 0 to 40.

---------------------------------------------------------

2. MOQ FEASIBILITY — MAX 20

- MOQ <= RFQ quantity = 20
- MOQ > RFQ quantity AND <= 1.5 × RFQ quantity = 10
- MOQ > 1.5 × RFQ quantity = 0
- MOQ not mentioned = 15

---------------------------------------------------------

3. QUOTE VALIDITY — MAX 15

- >= 45 days = 15
- 30–44 days = 12
- 15–29 days = 8
- 8–14 days = 4
- < 8 days = 0
- Not mentioned = 10

---------------------------------------------------------

4. PRICE FIRMNESS — MAX 15

- Price firm / true = 15
- Price not firm / false = 0
- Unknown = 8

---------------------------------------------------------

5. WARRANTY — MAX 10

- >= 12 months = 10
- 6–11 months = 6
- 1–5 months = 3
- None / 0 = 0
- Not mentioned = 5

=========================================================
DISQUALIFICATION
=========================================================

Only set disqualify_on_tech=true if a mandatory requirement
is clearly violated.

Do NOT disqualify merely because:
- a certification is not mentioned,
- the product appears to be a particular category,
- or the vendor has fewer certifications than another vendor.

=========================================================
RETURN FORMAT
=========================================================

{{
    "supplier": "{vendor_name}",

    "technical_score": <sum of all five scores, max 100>,

    "certification_score": <0-40>,

    "moq_score": <0-20>,

    "validity_score": <0-15>,

    "price_firm_score": <0-15>,

    "warranty_score": <0-10>,

    "compliance_flags": [],

    "disqualify_on_tech": false,

    "disqualify_reasons": [],

    "spec_match_summary":
        "one concise sentence explaining the overall result"
}}
"""

    # =========================================================
    # 5. CALL MISTRAL
    # =========================================================

    try:

        response = client.invoke(
            prompt
        )

        raw = response.content.strip()

        # -----------------------------------------------------
        # Remove markdown fences if model adds them
        # -----------------------------------------------------

        if "```" in raw:

            raw = raw.split("```")[1]

            if raw.strip().startswith("json"):

                raw = raw.strip()[4:]

        result = json.loads(
            raw.strip()
        )

        # =====================================================
        # 6. VALIDATE / NORMALIZE LLM OUTPUT
        # =====================================================

        result.setdefault(
            "supplier",
            vendor_name
        )

        result.setdefault(
            "certification_score",
            0
        )

        result.setdefault(
            "moq_score",
            0
        )

        result.setdefault(
            "validity_score",
            0
        )

        result.setdefault(
            "price_firm_score",
            0
        )

        result.setdefault(
            "warranty_score",
            0
        )

        result.setdefault(
            "compliance_flags",
            []
        )

        result.setdefault(
            "disqualify_on_tech",
            False
        )

        result.setdefault(
            "disqualify_reasons",
            []
        )

        result.setdefault(
            "spec_match_summary",
            ""
        )

        # -----------------------------------------------------
        # Make sure numeric values are actually numbers
        # -----------------------------------------------------

        certification_score = int(
            result.get("certification_score") or 0
        )

        moq_score = int(
            result.get("moq_score") or 0
        )

        validity_score = int(
            result.get("validity_score") or 0
        )

        price_firm_score = int(
            result.get("price_firm_score") or 0
        )

        warranty_score = int(
            result.get("warranty_score") or 0
        )

        # -----------------------------------------------------
        # Clamp scores to allowed ranges
        # -----------------------------------------------------

        certification_score = max(
            0,
            min(certification_score, 40)
        )

        moq_score = max(
            0,
            min(moq_score, 20)
        )

        validity_score = max(
            0,
            min(validity_score, 15)
        )

        price_firm_score = max(
            0,
            min(price_firm_score, 15)
        )

        warranty_score = max(
            0,
            min(warranty_score, 10)
        )

        # -----------------------------------------------------
        # Calculate total ourselves
        #
        # Don't trust the LLM's total.
        # -----------------------------------------------------

        technical_score = (
            certification_score
            + moq_score
            + validity_score
            + price_firm_score
            + warranty_score
        )

        # -----------------------------------------------------
        # Merge local flags
        # -----------------------------------------------------

        llm_flags = result.get(
            "compliance_flags"
        ) or []

        compliance_flags = (
            compliance_flags
            + llm_flags
        )

        # Remove duplicate flags
        compliance_flags = list(
            dict.fromkeys(
                compliance_flags
            )
        )

        # -----------------------------------------------------
        # Merge disqualification reasons
        # -----------------------------------------------------

        llm_disqualify_reasons = (
            result.get("disqualify_reasons")
            or []
        )

        disqualify_reasons = (
            disqualify_reasons
            + llm_disqualify_reasons
        )

        disqualify_reasons = list(
            dict.fromkeys(
                disqualify_reasons
            )
        )

        # -----------------------------------------------------
        # Final result
        # -----------------------------------------------------

        return {
            "supplier": vendor_name,

            "technical_score": technical_score,

            "certification_score":
                certification_score,

            "moq_score":
                moq_score,

            "validity_score":
                validity_score,

            "price_firm_score":
                price_firm_score,

            "warranty_score":
                warranty_score,

            "compliance_flags":
                compliance_flags,

            "disqualify_on_tech":
                bool(
                    result.get(
                        "disqualify_on_tech",
                        False
                    )
                ),

            "disqualify_reasons":
                disqualify_reasons,

            "spec_match_summary":
                result.get(
                    "spec_match_summary",
                    ""
                ),
        }

    # =========================================================
    # 7. LLM FAILURE
    # =========================================================

    except Exception as e:

        print(
            f"     ⚠️ LLM technical compliance failed "
            f"for {vendor_name}: {e}"
        )

        return {
            "supplier": vendor_name,

            # Do NOT pretend this is a genuine score.
            "technical_score": 0,

            "certification_score": 0,

            "moq_score": 0,

            "validity_score": 0,

            "price_firm_score": 0,

            "warranty_score": 0,

            "compliance_flags": (
                compliance_flags
                + [
                    "Automated technical evaluation failed "
                    "— manual review required"
                ]
            ),

            "disqualify_on_tech": True,

            "disqualify_reasons": (
                disqualify_reasons
                + [
                    "technical_evaluation_failed"
                ]
            ),

            "spec_match_summary": (
                f"Technical evaluation could not be completed "
                f"for {vendor_name}; manual review required."
            ),
        }

def run_technical_compliance_all(
    normalized_quotes: dict,
    rfq_item: str,
    rfq_quantity: float,
    rfq_unit: str,
    rfq_delivery_location: str,
) -> dict:
    """
    Runs technical compliance checks for ALL vendors.

    Args:
        normalized_quotes: output of normalize_quotes_node
        rfq_item, rfq_quantity, rfq_unit, rfq_delivery_location: from RFQState

    Returns:
        dict keyed by vendor_name, each value is a tech compliance result dict
    """
    print(f"\n{'='*60}")
    print(f"TECHNICAL COMPLIANCE CHECK has been strated")
    print(f"Checking {len(normalized_quotes)} vendors against: {rfq_item}")
    print(f"{'='*60}")

    rfq_specs = {
        "item":              rfq_item,
        "quantity":          rfq_quantity,
        "unit":              rfq_unit,
        "delivery_location": rfq_delivery_location,
    }

    all_tech_scores = {}

    for vendor_name, fields in normalized_quotes.items():
        print(f"\n  🔬 [{vendor_name}] Evaluating technical compliance...")
        result = check_technical_compliance(vendor_name, fields, rfq_specs)
        all_tech_scores[vendor_name] = result

        score = result.get("technical_score", 0)
        disq  = result.get("disqualify_on_tech", False)
        flags = result.get("compliance_flags", [])

        icon = "⛔" if disq else ("🟡" if score < 60 else "🟢")
        print(f"      {icon} Technical Score: {score}/100"
              + (" — DISQUALIFIED" if disq else ""))

        if flags:
            for flag in flags[:3]:
                print(f"         ⚠  {flag}")

    disq_count = sum(
        1 for r in all_tech_scores.values() if r.get("disqualify_on_tech")
    )
    print(f"\n  Summary: {len(all_tech_scores) - disq_count} passed, "
          f"{disq_count} disqualified on technical grounds")

    return all_tech_scores