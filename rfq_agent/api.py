from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os
import sys
import json
import zipfile
import shutil
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from main_agent import start_rfq_agent, resume_rfq_agent

app = Flask(__name__)

# Enable CORS for all routes
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Configuration
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

UPLOAD_FOLDER = os.environ.get(
    'UPLOAD_FOLDER',
    os.path.join(BASE_DIR, 'uploads')
)
VENDOR_QUOTES_FOLDER = os.environ.get(
    'VENDOR_QUOTES_FOLDER',
    os.path.join(BASE_DIR, 'vendor_quotes')
)
ALLOWED_EXTENSIONS = {'zip', 'rar', 'pdf', 'xlsx'}

# Create folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VENDOR_QUOTES_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/api/rfq/upload', methods=['POST'])
def upload_files():
    """Upload and process RFQ files"""
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400

        files = request.files.getlist('files')
        if not files or files[0].filename == '':
            return jsonify({'error': 'No files selected'}), 400

        upload_id = f"upload_{os.urandom(8).hex()}"
        upload_dir = os.path.join(UPLOAD_FOLDER, upload_id)
        os.makedirs(upload_dir, exist_ok=True)

        saved_files = []
        extracted_files = []

        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(upload_dir, filename)
                file.save(filepath)
                saved_files.append(filename)

                # If it's a ZIP file, extract it to vendor_quotes folder
                if filename.lower().endswith('.zip'):
                    try:
                        print(f"📦 Extracting {filename}...")
                        with zipfile.ZipFile(filepath, 'r') as zip_ref:
                            zip_ref.extractall(VENDOR_QUOTES_FOLDER)

                        # List extracted files
                        for item in zip_ref.namelist():
                            if item.lower().endswith(('.pdf', '.docx', '.xlsx')):
                                extracted_files.append(item)
                                print(f"   ✓ Extracted: {item}")
                    except Exception as e:
                        print(f"   ❌ Failed to extract {filename}: {str(e)}")

        if not saved_files:
            return jsonify({'error': 'No valid files uploaded'}), 400

        print(f"✓ Total extracted files: {len(extracted_files)}")

        # Start processing
        try:
            result = start_rfq_agent(
                rfq_item="Uploaded Files",
                rfq_quantity=1,
                rfq_unit="lot",
                delivery_location="Default",
                vendor_quotes_folder=VENDOR_QUOTES_FOLDER,
                thread_id=upload_id
            )
        except Exception as e:
            print(f"❌ Processing error: {str(e)}")
            result = None

        return jsonify({
            'uploadId': upload_id,
            'files': len(saved_files),
            'message': f'Successfully uploaded {len(saved_files)} file(s)',
            'summary': _summarise(result),
            'result': result
        }), 200

    except Exception as e:
        print(f"❌ Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/rfq/review/<upload_id>', methods=['GET'])
def get_review_data(upload_id):
    """Get review data for uploaded files"""
    try:
        # Load extracted quotes
        quotes_file = 'extracted_quotes.json'

        if not os.path.exists(quotes_file):
            return jsonify({
                'total': 0,
                'auto_approved': [],
                'needs_review': [],
                'error': 'No extracted data found'
            }), 200

        with open(quotes_file, 'r') as f:
            data = json.load(f)

        # Simulate risk assessment
        auto_approved = []
        needs_review = []

        for item in data.get('quotes', []):
            if item.get('price', 0) < 100000:  # Auto-approve < 1 lakh
                auto_approved.append(item)
            else:
                item['risk_level'] = 'medium'
                item['risk_reason'] = 'High value'
                needs_review.append(item)

        return jsonify({
            'total': len(auto_approved) + len(needs_review),
            'auto_approved': auto_approved,
            'needs_review': needs_review
        }), 200

    except Exception as e:
        print(f"❌ Review error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/rfq/approve', methods=['POST'])
def approve_pos():
    """Approve selected POs"""
    try:
        data = request.json
        po_ids = data.get('poIds', [])
        print(f"✓ Approving {len(po_ids)} POs")

        return jsonify({
            'message': f'Successfully approved {len(po_ids)} PO(s)',
            'approved_count': len(po_ids)
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/rfq/process', methods=['POST'])
def process_rfq():
    """Process RFQ with JSON input (direct agent call)"""
    try:
        data = request.json or {}

        # Get parameters from JSON
        rfq_item = data.get('rfq_item', 'Steel Plates')
        rfq_quantity = float(data.get('rfq_quantity', 1000))
        rfq_unit = data.get('rfq_unit', 'kg')
        delivery_location = data.get('delivery_location', 'Default')
        thread_id = f"api_{os.urandom(8).hex()}"

        print(f"\n📋 Processing RFQ via JSON:")
        print(f"   Item: {rfq_item}")
        print(f"   Qty: {rfq_quantity} {rfq_unit}")
        print(f"   Location: {delivery_location}")

        # Run agent with JSON parameters
        result = start_rfq_agent(
            rfq_item=rfq_item,
            rfq_quantity=rfq_quantity,
            rfq_unit=rfq_unit,
            delivery_location=delivery_location,
            vendor_quotes_folder=VENDOR_QUOTES_FOLDER,
            thread_id=thread_id
        )

        return jsonify({
            'message': 'RFQ processing complete',
            'thread_id': thread_id,
            'summary': _summarise(result),
            'result': result
        }), 200

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/rfq/stats', methods=['GET'])
def get_stats():
    """Get dashboard statistics"""
    try:
        time_range = request.args.get('range', '30d')

        return jsonify({
            'total_pos': 1000,
            'auto_approved': 600,
            'manual_reviewed': 300,
            'rejected': 50,
            'pending': 50,
            'avg_processing_time': '15 min',
            'total_value': 50000000,
            'uploads': []
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _summarise(result):
    """
    Flatten the agent's final state into what the UI needs.

    Outlook drafting is Windows-only, so on the server we hand back the
    rendered email instead of creating a draft. The frontend displays it
    and offers the Excel report for download.
    """
    if not isinstance(result, dict):
        return None

    report_path = result.get('report_path') or ''

    return {
        # ── HITL ──────────────────────────────────────────────────────
        'awaiting_decision': result.get('awaiting_decision', False),
        'thread_id':         result.get('thread_id', ''),
        'decision_options':  result.get('decision_options', []),
        'human_decision':    result.get('human_decision', ''),
        'selected_vendor':   result.get('selected_vendor', ''),

        'top_recommendation':    result.get('top_recommendation', ''),
        'recommendation_reason': result.get('recommendation_reason', ''),
        'ranked_vendors':        result.get('ranked_vendors', []),
        'qualified_vendors':     result.get('qualified_vendors', []),
        'vendor_scores':         result.get('vendor_scores', {}),
        'risk_flags':            result.get('risk_flags', {}),
        'anomaly_flags':         result.get('anomaly_flags', {}),
        'normalized_quotes':     result.get('normalized_quotes', {}),
        'notification': {
            'subject':   result.get('email_subject', ''),
            'html':      result.get('email_html', ''),
            'recipient': result.get('email_recipient', ''),
            'delivered_to_outlook': result.get('outlook_draft_created', False),
        },
        'report': {
            'filename':     os.path.basename(report_path) if report_path else '',
            'available':    bool(report_path and os.path.exists(report_path)),
            'download_url': '/api/rfq/report',
        },
    }


@app.route('/api/rfq/decision', methods=['POST'])
def submit_decision():
    """
    Human-in-the-loop step.

    The processing endpoints stop at the review pause and return a
    thread_id. Once the reviewer has seen the comparison, they send
    their decision here and the graph resumes from where it paused.

    Body:
      {
        "thread_id": "api_ab12...",          # required
        "decision":  "APPROVE"               # required
                     | "SELECT: Tata Steel Ltd"
                     | "HOLD: need revised freight"
                     | "REJECT: all quotes over budget"
      }
    """
    try:
        data      = request.json or {}
        thread_id = (data.get('thread_id') or '').strip()
        decision  = (data.get('decision') or '').strip()

        if not thread_id:
            return jsonify({'error': 'thread_id is required'}), 400
        if not decision:
            return jsonify({
                'error': 'decision is required',
                'valid_options': [
                    'APPROVE',
                    'SELECT: [vendor name]',
                    'HOLD: [reason]',
                    'REJECT: [reason]',
                ],
            }), 400

        verb = decision.split(':', 1)[0].strip().upper()
        if verb not in {'APPROVE', 'SELECT', 'HOLD', 'REJECT'}:
            return jsonify({
                'error': f"Unrecognised decision '{decision}'",
                'valid_options': [
                    'APPROVE',
                    'SELECT: [vendor name]',
                    'HOLD: [reason]',
                    'REJECT: [reason]',
                ],
            }), 400

        print(f"\n🧑 Decision received for {thread_id}: {decision}")

        try:
            result = resume_rfq_agent(thread_id, decision)
        except ValueError as ve:
            # Unknown or already-completed thread
            return jsonify({'error': str(ve)}), 409

        return jsonify({
            'message':   'Decision processed',
            'thread_id': thread_id,
            'decision':  decision,
            'summary':   _summarise(result),
            'result':    result,
        }), 200

    except Exception as e:
        print(f"❌ Decision error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/rfq/report', methods=['GET'])
def download_report():
    """Download the generated Excel comparison report."""
    candidates = [
        os.path.join(BASE_DIR, 'RFQ_Comparison_Report.xlsx'),
        os.path.join(os.path.dirname(__file__), 'RFQ_Comparison_Report.xlsx'),
        'RFQ_Comparison_Report.xlsx',
    ]

    for path in candidates:
        if os.path.exists(path):
            return send_file(
                path,
                as_attachment=True,
                download_name='RFQ_Comparison_Report.xlsx',
            )

    return jsonify({'error': 'No report generated yet. Process an RFQ first.'}), 404


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status':   'healthy',
        'platform': sys.platform,
        'outlook':  sys.platform == 'win32',
    }), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 RFQ Agent API running on http://localhost:{port}")
    print("📁 Upload folder:", UPLOAD_FOLDER)
    print("📦 Vendor quotes folder:", VENDOR_QUOTES_FOLDER)
    app.run(debug=True, port=port, host='0.0.0.0')