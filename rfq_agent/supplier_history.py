# Supplier_History.py
# ─────────────────────────────────────────────────────────────────────────────
# Gap 5 fill: retrieves past supplier performance data before risk flagging.
# Reads from supplier_history.json (file-based DB — replace with ERP/DB call
# when available). Auto-seeds a sample file on first run.
# ─────────────────────────────────────────────────────────────────────────────

import os
import json
from datetime import datetime

HISTORY_FILE = "supplier_history.json"

# ── Fallback record for vendors not in the history DB ────────────────────────
_DEFAULT_RECORD = {
    "past_delivery_score":    70,
    "on_time_delivery_rate":  70,
    "quality_issues_count":    0,
    "po_delays_count":         0,
    "average_delay_days":      0,
    "last_award_date":         None,
    "total_pos_awarded":       0,
    "total_pos_completed":     0,
    "historical_rating":       "New Vendor",
    "notes":                   "No prior transaction history on record",
}


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════════════════════

def get_supplier_history(vendor_name: str) -> dict:
    """
    Returns performance history for a single vendor.

    Lookup order:
      1. Exact key match in supplier_history.json
      2. Case-insensitive match
      3. Falls back to _DEFAULT_RECORD (new vendor)

    The returned dict includes a computed `history_score` (0–100) that
    the main agent feeds into risk flagging and the recommendation engine.

    history_score formula:
      base = delivery_score × 0.40 + on_time_rate × 0.40
      penalty = min(quality_issues × 10, 30) + min(po_delays × 5, 20)
      history_score = max(0, base − penalty)
      New vendors with 0 POs get a neutral 65.
    """
    db = _load_db()

    record = db.get(vendor_name)
    if not record:
        lower = vendor_name.lower()
        for key, val in db.items():
            if key.lower() == lower:
                record = val
                break

    if record:
        merged      = {**_DEFAULT_RECORD, **record}
        data_source = "history_file"
    else:
        merged      = dict(_DEFAULT_RECORD)
        data_source = "default"

    # ── Compute composite history_score ──────────────────────────────────────
    total_pos      = int(merged.get("total_pos_awarded") or 0)
    delivery_score = float(merged.get("past_delivery_score") or 70)
    on_time_rate   = float(merged.get("on_time_delivery_rate") or 70)
    quality_issues = int(merged.get("quality_issues_count") or 0)
    po_delays      = int(merged.get("po_delays_count") or 0)

    if total_pos == 0:
        history_score = 65.0   # neutral — benefit of the doubt for new vendors
    else:
        base    = delivery_score * 0.40 + on_time_rate * 0.40
        penalty = min(quality_issues * 10, 30) + min(po_delays * 5, 20)
        history_score = round(max(0.0, base - penalty), 1)

    merged["vendor"]        = vendor_name
    merged["history_score"] = history_score
    merged["data_source"]   = data_source

    return merged


def get_all_supplier_history(vendor_names: list) -> dict:
    """
    Fetches history for every vendor in vendor_names.
    Returns {vendor_name: history_dict}.
    Called by supplier_history_node in main_agent.py.
    """
    print(f"\n{'='*60}")
    print(f"SUPPLIER HISTORY — looking up {len(vendor_names)} vendors has been started")
    print(f"{'='*60}")

    all_history = {}
    for vendor in vendor_names:
        history = get_supplier_history(vendor)
        all_history[vendor] = history

        rating = history.get("historical_rating", "Unknown")
        score  = history.get("history_score", 0)
        source = history.get("data_source", "default")
        total  = history.get("total_pos_awarded", 0)
        icon   = "📂" if source == "history_file" else "🆕"

        print(f"  {icon} [{vendor}]")
        print(f"      Rating: {rating:<12} | History Score: {score:.1f}/100 "
              f"| POs Awarded: {total}")

        warnings = []
        if history.get("quality_issues_count", 0) >= 2:
            warnings.append(f"{history['quality_issues_count']} quality issues on record")
        if history.get("po_delays_count", 0) >= 3:
            warnings.append(f"{history['po_delays_count']} PO delays on record")
        if history.get("historical_rating") == "Poor":
            warnings.append("Vendor is flagged as Poor performer — procurement review recommended")

        for w in warnings:
            print(f"      ⚠️  {w}")

    return all_history


def save_supplier_history(vendor_name: str, update: dict):
    """
    Persists a new or updated history record for a vendor.
    Call this after a PO is completed to keep the DB current.

    Example:
        save_supplier_history("Tata Steel Ltd", {
            "past_delivery_score": 95,
            "on_time_delivery_rate": 93,
            "po_delays_count": 0,
            "last_award_date": "17-Jun-2026",
            "total_pos_awarded": 9,
            "total_pos_completed": 9,
            "historical_rating": "Excellent",
        })
    """
    db = _load_db()
    existing = db.get(vendor_name, {})
    db[vendor_name] = {**existing, **update}
    _save_db(db)
    print(f"  💾 History updated for: {vendor_name}")


# ════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _load_db() -> dict:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_db(db: dict):
    with open(HISTORY_FILE, "w") as f:
        json.dump(db, f, indent=2, default=str)


def _create_sample_history_file():
    """
    Seeds supplier_history.json with realistic data for the 7 sample vendors
    that ship with the RFQ agent. Run once; after that, maintain the file
    manually or via save_supplier_history().
    """
    sample = {
        "Tata Steel Ltd": {
            "past_delivery_score":   92,
            "on_time_delivery_rate": 90,
            "quality_issues_count":   0,
            "po_delays_count":        1,
            "average_delay_days":     3,
            "last_award_date":       "15-Jan-2026",
            "total_pos_awarded":      8,
            "total_pos_completed":    8,
            "historical_rating":     "Excellent",
            "notes": (
                "Consistent performer across 8 POs. Minor 3-day delay in Jan 2025 "
                "due to port congestion — fully communicated in advance."
            ),
        },
        "JSW Steel Ltd": {
            "past_delivery_score":   85,
            "on_time_delivery_rate": 82,
            "quality_issues_count":   1,
            "po_delays_count":        2,
            "average_delay_days":     7,
            "last_award_date":       "20-Mar-2026",
            "total_pos_awarded":      5,
            "total_pos_completed":    5,
            "historical_rating":     "Good",
            "notes": (
                "One quality rejection in Q3 2025 due to thickness deviation (0.2 mm). "
                "Issue resolved; replacement delivered within 10 days."
            ),
        },
        "Hindustan Alloys Steel": {
            "past_delivery_score":   78,
            "on_time_delivery_rate": 74,
            "quality_issues_count":   2,
            "po_delays_count":        3,
            "average_delay_days":    12,
            "last_award_date":       "10-Nov-2025",
            "total_pos_awarded":      4,
            "total_pos_completed":    3,
            "historical_rating":     "Average",
            "notes": (
                "One incomplete PO in Aug 2025 (partial supply, balance pending). "
                "Quality issues in 2 batches — surface finish non-conformance."
            ),
        },
        "Shree Metals Pvt Ltd": {
            "past_delivery_score":   88,
            "on_time_delivery_rate": 86,
            "quality_issues_count":   0,
            "po_delays_count":        1,
            "average_delay_days":     4,
            "last_award_date":       "05-Feb-2026",
            "total_pos_awarded":      3,
            "total_pos_completed":    3,
            "historical_rating":     "Good",
            "notes": (
                "Relatively new supplier with 3 clean POs. "
                "One minor delay of 4 days flagged but within acceptable range."
            ),
        },
        "Prime Supplies LLP": {
            "past_delivery_score":   60,
            "on_time_delivery_rate": 55,
            "quality_issues_count":   3,
            "po_delays_count":        5,
            "average_delay_days":    18,
            "last_award_date":       "12-Aug-2025",
            "total_pos_awarded":      2,
            "total_pos_completed":    2,
            "historical_rating":     "Poor",
            "notes": (
                "Multiple delays averaging 18 days. 3 quality non-conformances. "
                "Currently under performance improvement plan. "
                "Procurement head approval required before next award."
            ),
        },
        "Apex Metals Trading": {
            "past_delivery_score":    0,
            "on_time_delivery_rate":  0,
            "quality_issues_count":   0,
            "po_delays_count":        0,
            "average_delay_days":     0,
            "last_award_date":        None,
            "total_pos_awarded":      0,
            "total_pos_completed":    0,
            "historical_rating":     "New Vendor",
            "notes": "First RFQ participation. No prior transaction history with this entity.",
        },
        "Global Traders Suppliers": {
            "past_delivery_score":    0,
            "on_time_delivery_rate":  0,
            "quality_issues_count":   0,
            "po_delays_count":        0,
            "average_delay_days":     0,
            "last_award_date":        None,
            "total_pos_awarded":      0,
            "total_pos_completed":    0,
            "historical_rating":     "New Vendor",
            "notes": "First RFQ participation. No prior transaction history with this entity.",
        },
    }

    _save_db(sample)
    print(f"✅ supplier_history.json created — {len(sample)} vendors seeded.")
    return sample


# ── Auto-seed on first run ────────────────────────────────────────────────────
if not os.path.exists(HISTORY_FILE):
    print(f"📝 supplier_history.json not found — seeding sample data...")
    _create_sample_history_file()