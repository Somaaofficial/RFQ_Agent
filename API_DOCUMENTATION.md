# RFQ Agent API - Documentation

## 🚀 Quick Start

**Base URL:** `http://localhost:5000`

**Status:** API must be running
```powershell
cd C:\Users\HP\RFQ_Agent\rfq_agent
python api.py
```

---

## 📋 API Endpoints

### 1. **Upload & Process Files**

**Endpoint:** `POST /api/rfq/upload`

**Purpose:** Upload ZIP file with vendor quote PDFs

**Input:** 
- ZIP file containing PDF/DOCX/XLSX files
- Max size: 500MB
- Supported formats: .zip, .rar

**Example (PowerShell):**
```powershell
$file = Get-Item "C:\path\to\quotes.zip"
$form = @{ files = $file }
Invoke-WebRequest -Uri "http://localhost:5000/api/rfq/upload" `
    -Method Post `
    -Form $form
```

**Response:**
```json
{
  "uploadId": "upload_9da1ddaf827d064e",
  "files": 1,
  "message": "Successfully uploaded 1 file(s)",
  "result": {...}
}
```

---

### 2. **Process via JSON Parameters** ⭐ RECOMMENDED

**Endpoint:** `POST /api/rfq/process`

**Purpose:** Process RFQ with direct JSON input (no file upload needed)

**Parameters:**
```json
{
  "rfq_item": "Aluminum Plates 5083",      // Required: Item name
  "rfq_quantity": 5000,                     // Required: Quantity
  "rfq_unit": "kg",                         // Required: Unit (kg, tons, etc)
  "delivery_location": "Chennai Plant"      // Required: Delivery location
}
```

**Example (PowerShell):**
```powershell
$body = @{
    rfq_item = "Steel Sheets"
    rfq_quantity = 1000
    rfq_unit = "kg"
    delivery_location = "Mumbai"
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:5000/api/rfq/process" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

**Example (cURL):**
```bash
curl -X POST http://localhost:5000/api/rfq/process \
  -H "Content-Type: application/json" \
  -d '{
    "rfq_item": "Steel Plates",
    "rfq_quantity": 1000,
    "rfq_unit": "kg",
    "delivery_location": "Mumbai"
  }'
```

**Response:**
```json
{
  "message": "RFQ processing complete",
  "thread_id": "api_xyz123",
  "result": {
    "top_recommendation": "Shree Metals Pvt Ltd",
    "vendor_scores": {...},
    "risk_flags": {...},
    "anomaly_flags": {...}
  }
}
```

---

### 3. **Get Review Data**

**Endpoint:** `GET /api/rfq/review/:uploadId`

**Purpose:** Get extracted vendor quotes for review

**Example:**
```
GET http://localhost:5000/api/rfq/review/upload_9da1ddaf827d064e
```

**Response:**
```json
{
  "total": 7,
  "auto_approved": [...],
  "needs_review": [...]
}
```

---

### 4. **Get Dashboard Statistics**

**Endpoint:** `GET /api/rfq/stats`

**Purpose:** Get RFQ processing metrics

**Parameters:**
- `range`: "7d", "30d", "90d" (default: 30d)

**Example:**
```
GET http://localhost:5000/api/rfq/stats?range=30d
```

**Response:**
```json
{
  "total_pos": 1000,
  "auto_approved": 600,
  "manual_reviewed": 300,
  "rejected": 50,
  "pending": 50,
  "avg_processing_time": "15 min",
  "total_value": 50000000
}
```

---

## 🔄 System Architecture

```
Manager / External System
        ↓
    API Endpoint
        ↓
   Python Agent
        ↓
PDF Processing → Vendor Extraction → Risk Assessment
        ↓
Outlook Draft Email ← Recommendation ← Vendor Comparison
        ↓
Excel Report + JSON Results
```

---

## 📊 Output Files Generated

When processing completes, these files are created:

| File | Purpose |
|------|---------|
| `RFQ_Comparison_Report.xlsx` | Vendor comparison with scores |
| `extracted_quotes.json` | Extracted vendor quote data |
| `vendor_scores.json` | Scoring results |
| `risk_flags.json` | Risk assessment details |
| `supplier_history.json` | Historical supplier data |

---

## 🛠️ Prerequisites

1. **Python 3.8+** installed
2. **API running:** `python api.py` in `C:\Users\HP\RFQ_Agent\rfq_agent\`
3. **Vendor quotes folder:** `C:\Users\HP\RFQ_Agent\vendor_quotes\` (with PDFs)
4. **Network:** localhost:5000 accessible

---

## 📝 Example Workflow

### **Scenario: Evaluate Steel Suppliers**

**Step 1:** Have vendor PDFs ready in vendor_quotes folder

**Step 2:** Call API with JSON:
```powershell
$body = @{
    rfq_item = "HR Steel Sheets 3mm"
    rfq_quantity = 10000
    rfq_unit = "kg"
    delivery_location = "Mumbai Warehouse"
} | ConvertTo-Json

Invoke-WebRequest -Uri "http://localhost:5000/api/rfq/process" `
    -Method Post `
    -ContentType "application/json" `
    -Body $body
```

**Step 3:** Agent returns:
- Top vendor recommendation
- Vendor comparison scores
- Risk flags & anomalies
- Outlook draft for approval

**Step 4:** Review draft in Outlook & send

**Step 5:** Excel report ready for records

---

## ⚠️ Error Handling

**No files found:**
```json
{
  "error": "No files found to process. Please upload files first."
}
```

**Invalid parameters:**
```json
{
  "error": "Invalid parameter: rfq_quantity must be a number"
}
```

**API not running:**
```
Connection refused on localhost:5000
```

**Solution:** Start API with `python api.py`

---

## 🔐 Security Notes

- API runs on localhost only (secure by default)
- CORS enabled for cross-origin requests if needed
- No authentication required for localhost
- For production: Add API key authentication

---

## 📞 Support

- **API Status:** Check terminal for errors
- **Files Location:** `C:\Users\HP\RFQ_Agent\`
- **Upload Folder:** `C:\Users\HP\RFQ_Agent\rfq_agent\..\uploads\`
- **Vendor Quotes:** `C:\Users\HP\RFQ_Agent\vendor_quotes\`

---

## ✅ Quick Reference

| Task | Command |
|------|---------|
| **Start API** | `python api.py` in rfq_agent folder |
| **Upload file** | POST to `/api/rfq/upload` |
| **Process RFQ** | POST JSON to `/api/rfq/process` |
| **Get stats** | GET `/api/rfq/stats` |
| **Stop API** | Press `Ctrl + C` |

---

**Generated:** August 31, 2026  
**Version:** 1.0.0  
**Status:** Production Ready ✅
