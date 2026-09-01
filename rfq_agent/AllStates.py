# state.py
from typing import TypedDict, Optional

class RFQState(TypedDict):
    # ── RFQ details ───────────────────────────────────────
    rfq_item: str               # "HR Steel 3mm"
    rfq_quantity: float         # 10000.0 kg
    rfq_unit: str               # "kg"
    delivery_location: str      # "Mumbai Warehouse"
    vendor_quotes_folder: str   # "vendor_quotes/"

    # ── per vendor data written by parallel nodes ─────────
    extracted_fields: dict      # {vendor_name: {15 fields}}
    landed_costs: dict          # {vendor_name: 462.5}
    vendor_scores: dict         # {vendor_name: {score, breakdown}}
    risk_flags: dict            # {vendor_name: {flags, severity}}

    # ── after all vendors processed ───────────────────────
    ranked_vendors: list        # sorted by score descending
    top_recommendation: str     # "Tata Steel Ltd"
    recommendation_reason: str  # Mistral's explanation

    # ── outputs ───────────────────────────────────────────
    report_path: str            # "RFQ_Comparison_Report.xlsx"
    human_decision: str         # "approve" / "select_other"
    selected_vendor: str        # final selected vendor name
    po_draft: str               # PO text for winning vendor

    # ── notification payload (shown in the UI) ────────────
    # Built regardless of whether Outlook is available, so the
    # frontend can render the recommendation instead of relying
    # on a desktop mail client.
    email_subject: str          # "[ACTION REQUIRED] RFQ Evaluation Ready — ..."
    email_html: str             # full HTML comparison body
    email_recipient: str        # who it would have gone to
    outlook_draft_created: bool # False on Linux / when disabled

    # ── LangGraph internals ───────────────────────────────
    thread_id: str

    normalized_quotes: dict  #modified code