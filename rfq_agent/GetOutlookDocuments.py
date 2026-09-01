# Outlook_Inbox_Scanner.py
# ─────────────────────────────────────────────────────────────────────────────
# Scans the last N emails in the Outlook desktop inbox.
# Uses Mistral to identify which emails are vendor quote responses for the RFQ.
# Downloads PDF/DOCX/XLSX attachments to vendor_quotes/ folder.
# Names each file as "{seq}_{SenderName}.ext" so trigger_node correctly
# derives the vendor name from the filename.
# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import json
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI

load_dotenv()
_client = ChatMistralAI(
    model   = "mistral-small-latest",
    api_key = os.getenv("MISTRAL_API_KEY"),
)

# Attachment extensions the agent can process
ALLOWED_EXTS = {".pdf", ".docx", ".xlsx"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _sanitize(name: str) -> str:
    """Convert a sender display name into a safe filename stem."""
    name = re.sub(r'[\\/*?:"<>|@]', '', name)
    name = re.sub(r'\s+', '_', name.strip())
    return name[:55] or "Vendor"


def _get_inbox():
    """Connect to the Outlook desktop app and return the Inbox folder."""
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        mapi    = outlook.GetNamespace("MAPI")
        return mapi.GetDefaultFolder(6)          # 6 = Inbox
    except ImportError:
        raise ImportError(
            "pywin32 is not installed. Run:  pip install pywin32 --break-system-packages"
        )
    except Exception as e:
        raise ConnectionError(f"Could not connect to Outlook desktop app: {e}")


def _ai_classify(candidates: list, rfq_item: str) -> list:
    """
    Sends all candidate email subjects + senders to Mistral in one batch.
    Returns a list of list-indices that are likely vendor quote responses.
    Falls back to keyword matching if the LLM call fails.
    """
    batch = [
        {"id": i, "subject": c["subject"], "sender": c["sender"]}
        for i, c in enumerate(candidates)
    ]

    prompt = f"""
You are a procurement assistant. The company is running an RFQ for: {rfq_item}

Review these {len(batch)} emails from the Outlook inbox.
Identify which ones are vendor quote / price offer responses for this specific RFQ.

Include:  quote, quotation, rate offer, price offer, bid, proposal, revised offer
Exclude:  invoices, delivery notifications, newsletters, spam, unrelated items

EMAILS:
{json.dumps(batch, indent=2)}

Reply ONLY with valid JSON — no markdown:
{{"quote_ids": [list of id numbers]}}
"""

    try:
        resp = _client.invoke(prompt)
        raw  = resp.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip()).get("quote_ids", [])
    except Exception as e:
        print(f"  ⚠️  AI classification failed ({e}) — using keyword fallback")
        kw = {"quote","quotation","offer","price","bid","proposal","rfq","rate","tender"}
        return [
            i for i, c in enumerate(candidates)
            if any(k in c["subject"].lower() for k in kw)
        ]


# ── main public function ──────────────────────────────────────────────────────

def scan_inbox_for_rfq_quotes(
    rfq_item:             str,
    vendor_quotes_folder: str  = "vendor_quotes",
    n_emails:             int  = 30,
    use_ai_filter:        bool = True,
) -> dict:
    """
    Scans the last n_emails in Outlook inbox for vendor quote attachments.

    Steps:
      1. Reads last n_emails from Outlook Inbox (sorted newest-first).
      2. Filters down to emails that have attachments.
      3. Uses Mistral (or keyword fallback) to identify which are vendor quotes
         for the given rfq_item.
      4. Downloads PDF/DOCX/XLSX attachments to vendor_quotes_folder.
         Filename: "{seq}_{SenderName}.ext" — trigger_node strips the number
         prefix and uses the rest as the vendor name.

    Args:
        rfq_item:             Description of the item being procured.
        vendor_quotes_folder: Destination folder (created if absent).
        n_emails:             How many recent emails to scan (default 30).
        use_ai_filter:        True = Mistral classification, False = keywords only.

    Returns:
        {
          "emails_checked":     int,
          "quote_emails_found": int,
          "files_downloaded":   int,
          "downloaded_files":   [{vendor_name, filename, source_email, sender, received}],
          "errors":             [str],
        }
    """
    print(f"\n{'='*60}")
    print(f"OUTLOOK INBOX SCANNER")
    print(f"Scanning last {n_emails} emails for: {rfq_item}")
    print(f"{'='*60}")

    os.makedirs(vendor_quotes_folder, exist_ok=True)

    result = {
        "emails_checked":     0,
        "quote_emails_found": 0,
        "files_downloaded":   0,
        "downloaded_files":   [],
        "errors":             [],
    }

    # ── Step 1: connect and read last n_emails ─────────────────────────────
    try:
        inbox = _get_inbox()
    except Exception as e:
        result["errors"].append(str(e))
        print(f"  ❌ {e}")
        return result

    items = inbox.Items
    items.Sort("[ReceivedTime]", True)   # newest first

    raw_emails = []
    for i, msg in enumerate(items):
        if i >= n_emails:
            break
        try:
            raw_emails.append({
                "subject":        str(msg.Subject  or ""),
                "sender":         str(msg.SenderName or "Unknown Sender"),
                "received":       str(msg.ReceivedTime),
                "n_attachments":  msg.Attachments.Count,
                "_msg":           msg,
            })
        except Exception as e:
            result["errors"].append(f"Email {i}: {e}")

    result["emails_checked"] = len(raw_emails)
    print(f"  📬 Read {len(raw_emails)} emails")

    # ── Step 2: keep only those with attachments ───────────────────────────
    with_att = [e for e in raw_emails if e["n_attachments"] > 0]
    skipped  = len(raw_emails) - len(with_att)
    print(f"  📎 {len(with_att)} have attachments ({skipped} skipped — no attachments)")

    if not with_att:
        print(f"  ℹ️  Nothing to download.")
        return result

    # ── Step 3: AI / keyword filter ────────────────────────────────────────
    if use_ai_filter and len(with_att) > 0:
        print(f"  🤖 Asking Mistral to identify quote emails...")
        quote_indices = _ai_classify(with_att, rfq_item)
    else:
        kw = {"quote","quotation","offer","price","bid","proposal","rfq","rate"}
        quote_indices = [
            i for i, e in enumerate(with_att)
            if any(k in e["subject"].lower() for k in kw)
        ]

    quote_emails = [
        with_att[i] for i in quote_indices
        if 0 <= i < len(with_att)
    ]
    result["quote_emails_found"] = len(quote_emails)
    print(f"  ✅ {len(quote_emails)} identified as vendor quote emails")

    if not quote_emails:
        print(f"\n  ℹ️  No vendor quote emails found in the last {n_emails} emails.")
        print(f"      Check that vendor replies contain keywords like: quote, offer, bid, price")
        return result

    # ── Step 4: download attachments ──────────────────────────────────────
    vendor_name_map = {}   # {filename → sender display name} returned in result

    for email_info in quote_emails:
        msg     = email_info["_msg"]
        sender  = email_info["sender"]
        subject = email_info["subject"]

        print(f"\n  📨 [{sender}]")
        print(f"     Subject : {subject[:70]}")
        print(f"     Received: {email_info['received'][:19]}")

        for att in msg.Attachments:
            try:
                att_name = str(att.FileName)
                ext      = os.path.splitext(att_name)[1].lower()

                if ext not in ALLOWED_EXTS:
                    print(f"     ⏭  Skipped {att_name!r} — not a supported type")
                    continue

                # ── keep the original filename exactly as the vendor named it ──
                filename  = att_name
                path      = os.path.join(vendor_quotes_folder, filename)

                # if a file with that name already exists, add (2), (3) … suffix
                if os.path.exists(path):
                    stem    = os.path.splitext(att_name)[0]
                    counter = 2
                    while os.path.exists(
                        os.path.join(vendor_quotes_folder, f"{stem}({counter}){ext}")
                    ):
                        counter += 1
                    filename = f"{stem}({counter}){ext}"
                    path     = os.path.join(vendor_quotes_folder, filename)

                att.SaveAsFile(path)

                # map filename → sender so trigger_node can use the real vendor name
                vendor_name_map[filename] = sender

                record = {
                    "vendor_name":  sender,
                    "filename":     filename,
                    "save_path":    path,
                    "source_email": subject,
                    "sender":       sender,
                    "received":     email_info["received"],
                }
                result["downloaded_files"].append(record)
                result["files_downloaded"] += 1

                print(f"     💾 Saved → {filename}  (vendor: {sender})")

            except Exception as e:
                msg_err = f"Download failed [{sender} / {att_name}]: {e}"
                result["errors"].append(msg_err)
                print(f"     ❌ {msg_err}")

    result["vendor_name_map"] = vendor_name_map

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n  {'─'*50}")
    print(f"  Emails checked      : {result['emails_checked']}")
    print(f"  Quote emails found  : {result['quote_emails_found']}")
    print(f"  Files downloaded    : {result['files_downloaded']}")
    print(f"  Saved to            : {os.path.abspath(vendor_quotes_folder)}/")
    if result["errors"]:
        print(f"  Errors              : {len(result['errors'])}")
        for e in result["errors"][:3]:
            print(f"    • {e}")

    return result

