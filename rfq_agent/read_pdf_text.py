import os
import json
import fitz  # PyMuPDF
import pandas as pd
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI
load_dotenv()
api_key=os.getenv("MISTRAL_API_KEY")
client=ChatMistralAI(model="mistral-small-latest",api_key=api_key)

print("reading pdf raw  text has been started")

def readpdfnode(filepath :str) ->str:
    "it will read all pdf's and get the text from those RFQ's"
    filetext = fitz.open(filepath)
    full_text = ""
    for page in filetext:
        full_text += page.get_text()
    filetext.close()
    return full_text.strip()

print("extracting fields from the raw text has been started")
def ExtractFields(vendor_name : str , full_text : str) ->dict:
    """this function will extract all 15 fields from the raw text
    irrespective of any layout or format and return in dictionary format"""
    prompt =f"""
You are a procurement analyst reading a vendor quotation document.
Extract the following 15 fields from the quote text below.

RULES:
- Return ONLY a valid JSON object — no markdown, no backticks, no explanation
- If a field is not mentioned, use null
- For numeric fields (prices, days, percentages), return numbers only — no currency symbols or units
- For boolean fields, return true or false
- For text fields, return clean short strings

FIELDS TO EXTRACT:
1. unit_price          → Base price per unit (number, no currency symbol). E.g. 452.0
2. freight_per_unit    → Freight/transport cost per unit (number). 0 if CIF/included. E.g. 8.0
3. incoterm            → Delivery terms. E.g. "Ex-Works", "CIF", "DDP", "FOR"
4. gst_rate            → GST percentage as number. E.g. 18.0
5. delivery_days       → Lead time in working days (number). E.g. 12
6. payment_terms       → Credit days offered. E.g. "60 days credit", "30 days from delivery", "Advance"
7. advance_percentage  → Advance payment % required (number). 0 if no advance. E.g. 25.0
8. quote_validity_days → Number of days quote is valid from quote date (number). E.g. 30
9. quote_date          → Date of quotation as string. E.g. "10-Jun-2026"
10. minimum_order_qty  → Minimum order quantity in kg or units (number). E.g. 2000.0
11. certifications     → List of certifications mentioned. E.g. ["ISO 9001", "BIS", "NABL"]
12. warranty_months    → Warranty period in months (number). E.g. 12
13. penalty_clause     → Short description of LD/penalty clause. null if none. E.g. "0.5% per week, max 5%"
14. price_firm         → Is price firm (not subject to revision)? true or false
15. special_conditions → Any notable special conditions or risks as a short string. null if none.

QUOTE TEXT:
{full_text}

Return ONLY the JSON object now:
"""
    response = client.invoke(prompt)
    value = response.content.strip()
    try:
        # remove markdown fences if present
        clean = value
        if "```" in clean:
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        result = json.loads(clean.strip())
    except json.JSONDecodeError:
        print(f"     JSON parse failed for {vendor_name} — using fallback")
        result = {
            "unit_price": None, "freight_per_unit": None,
            "incoterm": None, "gst_rate": 18.0,
            "delivery_days": None, "payment_terms": None,
            "advance_percentage": 0, "quote_validity_days": None,
            "quote_date": None, "minimum_order_qty": None,
            "certifications": [], "warranty_months": None,
            "penalty_clause": None, "price_firm": None,
            "special_conditions":value[:200]
        }
    result["vendor_name"] = vendor_name
    return result

def calculate_landed_cost(fields : dict) ->float:
    """
     Landed Cost = (unit_price + freight_per_unit) x (1 + gst_rate/100)

    Handles incoterm logic:
    - Ex-Works / EXW → freight is EXTRA (use freight_per_unit)
    - CIF / DDP / FOR → freight already included in unit_price
    """
    unit_price = float(fields.get("unit_price") or 0)
    freight = float(fields.get("freight_per_unit") or 0)
    gst_rate = float(fields.get("gst_rate") or 15)
    incoterm = str(fields.get("incoterm") or "NA")
    if any( t in incoterm for t in ["cif", "ddp", "for ", "delivered"]):
        base_price = unit_price
    base_price = unit_price +freight
    landed = base_price * (1 + gst_rate / 100)
    return round(landed, 2)

def process_vendor_pdf(pdf_path : str)->dict:
    "read all pdf's and get the full text and calculate the landed cost"
    filename    = os.path.basename(pdf_path)
    vendor_name = filename.replace(".pdf", "").replace("_", " ")
    # remove leading number prefix like "01 " "02 " etc.
    if vendor_name[:2].strip().isdigit():
        vendor_name = vendor_name[3:].strip()
    pdf_text = readpdfnode(pdf_path) 
    all_fields = ExtractFields(vendor_name,pdf_text)
    all_fields["landed_cost"]= calculate_landed_cost(all_fields)
    print(f"   💰 Landed cost calculated: INR {all_fields['landed_cost']}/unit")
    return all_fields

def run_extraction(quotes_folder : str = "vendor_quotes") -> dict:
     """
    Processes all PDFs in the vendor_quotes folder.
    Returns a dict keyed by vendor_name.
    """
     pdf_files   = sorted([
        f for f in os.listdir(quotes_folder)
        if f.endswith(".pdf")
    ])
     full_text_value = {}
     for file in pdf_files:
         pdf_path            = os.path.join(quotes_folder, file)
         text_value = process_vendor_pdf(pdf_path)
         full_text_value[text_value["vendor_name"]] = text_value
     return full_text_value

def display_results(all_results: dict):
    print(f"\n{'='*60}")
    print("EXTRACTION SUMMARY — ALL VENDORS")
    print(f"{'='*60}")

    rows = []
    for vendor, fields in all_results.items():
        rows.append({
            "Vendor":           vendor,
            "Unit Price":       f"₹{fields.get('unit_price', 'N/A')}",
            "Freight":          f"₹{fields.get('freight_per_unit', 0)}",
            "Incoterm":         fields.get("incoterm", "N/A"),
            "GST %":            f"{fields.get('gst_rate', 18)}%",
            "Landed Cost":      f"₹{fields.get('landed_cost', 'N/A')}",
            "Delivery (days)":  fields.get("delivery_days", "N/A"),
            "Payment":          str(fields.get("payment_terms", "N/A"))[:20],
            "Advance %":        f"{fields.get('advance_percentage', 0)}%",
            "Validity (days)":  fields.get("quote_validity_days", "N/A"),
            "Certs":            fields.get("certifications", []),
            "Warranty (mo)":    fields.get("warranty_months", "N/A"),
            "Price Firm":       "✅" if fields.get("price_firm") else "⚠️",
        })

    df = pd.DataFrame(rows)
    print(df.to_string(index=False))

    # highlight key observations
    print(f"\n{'─'*60}")
    print("KEY OBSERVATIONS:")
    for vendor, fields in all_results.items():
        flags = []
        lc    = fields.get("landed_cost", 0) or 0
        adv   = fields.get("advance_percentage", 0) or 0
        val   = fields.get("quote_validity_days", 30) or 30
        certs = fields.get("certifications", [])
        firm  = fields.get("price_firm")

        if adv >= 100:
            flags.append("🔴 100% ADVANCE")
        elif adv >= 50:
            flags.append("🔴 50%+ ADVANCE")
        elif adv >= 25:
            flags.append("🟡 25% ADVANCE")

        if val <= 3:
            flags.append("🔴 VALIDITY ONLY 3 DAYS")
        elif val <= 10:
            flags.append("🟡 SHORT VALIDITY")

        if not certs:
            flags.append("🔴 NO CERTIFICATIONS")
        elif len(certs) == 1:
            flags.append("🟡 ONLY 1 CERT")

        if firm is False:
            flags.append("🔴 PRICE NOT FIRM")

        if fields.get("penalty_clause") is None:
            flags.append("🟡 NO PENALTY CLAUSE")

        status = " | ".join(flags) if flags else "🟢 CLEAN"
        print(f"  {vendor:<30} Landed: ₹{lc:>7.2f}  {status}")

    print(f"\n✅ Chunk 2 complete — all vendor PDFs extracted!")
    return df







