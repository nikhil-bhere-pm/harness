import re
import email
import email.message
import imaplib
import traceback
from email.header import decode_header
from typing import List, Dict, Optional, Tuple, Any
from config import get_config
from logger import log_event

def _decode_mime_header(header_val: Optional[str]) -> str:
    """Safely decode MIME header values (Subject, From, Date)."""
    if not header_val:
        return ""
    try:
        decoded_parts = decode_header(header_val)
        result = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                enc = encoding or "utf-8"
                try:
                    result.append(part.decode(enc, errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    result.append(part.decode("utf-8", errors="replace"))
            else:
                result.append(str(part))
        return "".join(result).strip()
    except Exception:
        return str(header_val).strip()

def _extract_body_text(msg: email.message.Message, max_chars: int = 1000) -> str:
    """Extract plain text body from email message, truncating to ~1000 chars."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in cdisp:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        body = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        body = payload.decode("utf-8", errors="replace")
                    break
        # Fallback to text/html if no text/plain found
        if not body:
            for part in msg.walk():
                ctype = part.get_content_type()
                cdisp = str(part.get("Content-Disposition", ""))
                if ctype == "text/html" and "attachment" not in cdisp:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            html = payload.decode(charset, errors="replace")
                            # Simple regex tag strip
                            body = re.sub(r"<[^>]+>", " ", html)
                        except Exception:
                            pass
                        break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                body = payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                body = payload.decode("utf-8", errors="replace")

    # Clean whitespace and truncate to ~1000 chars
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) > max_chars:
        body = body[:max_chars] + "… [truncated]"
    return body

def fetch_recent_emails(max_count: int = 10) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """
    Fetch recent emails from Gmail via IMAP (read-only).
    Adheres strictly to buffer limits, sequence ID ranges, and app-password sanitization.
    Returns (emails_list, diagnostic_error_or_none).
    """
    # 1. Sanitize GMAIL_APP_PASSWORD with re.sub(r'[^a-zA-Z0-9]', '', val)
    user = get_config("GMAIL_USER")
    raw_password = get_config("GMAIL_APP_PASSWORD")
    password = re.sub(r"[^a-zA-Z0-9]", "", raw_password)

    if not user or not password:
        err_msg = "⚠️ Gmail Diagnostic: GMAIL_USER or GMAIL_APP_PASSWORD is not configured."
        log_event("GMAIL_WARN", "Gmail fetch aborted: Missing credentials", level="warning")
        return [], err_msg

    # 2. imaplib._MAXLINE = 10000000 (10 MB buffer) before connecting
    imaplib._MAXLINE = 10000000
    mail = None

    try:
        # 3. Connect to imaplib.IMAP4_SSL("imap.gmail.com", 993)
        log_event("GMAIL_CONNECT", "Connecting to imap.gmail.com:993")
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)

        # 4. Wrap mail.login() in try/except Exception as login_err
        try:
            log_event("GMAIL_LOGIN", f"Attempting login for user: {user}")
            mail.login(user, password)
            log_event("GMAIL_SUCCESS", f"IMAP login successful for {user}")
        except Exception as login_err:
            err_text = str(login_err)
            if hasattr(login_err, "args") and login_err.args:
                arg0 = login_err.args[0]
                if isinstance(arg0, bytes):
                    err_text = arg0.decode("utf-8", errors="replace")
                elif isinstance(arg0, str):
                    err_text = arg0
            full_err = f"{type(login_err).__name__}: {err_text}\n{traceback.format_exc()}"
            log_event("GMAIL_FAILURE", f"IMAP login failed for {user}: {full_err}", level="error")
            return [], f"⚠️ Gmail Diagnostic: {err_text}"

        # 5. Do NOT call mail.search(None, "ALL"). Get total from mail.select("INBOX", readonly=True)
        res, data = mail.select("INBOX", readonly=True)
        total = 0
        if res == "OK" and data and data[0]:
            try:
                total = int(data[0].decode("utf-8") if isinstance(data[0], bytes) else data[0])
            except (ValueError, TypeError):
                total = 0

        # Fallback to [Gmail]/All Mail if total is 0
        if total == 0:
            log_event("GMAIL_INFO", "INBOX total is 0; checking [Gmail]/All Mail")
            res_all, data_all = mail.select('"[Gmail]/All Mail"', readonly=True)
            if res_all == "OK" and data_all and data_all[0]:
                try:
                    total = int(data_all[0].decode("utf-8") if isinstance(data_all[0], bytes) else data_all[0])
                except (ValueError, TypeError):
                    total = 0

        # If total is 0, return no messages cleanly (don't error)
        if total == 0:
            log_event("GMAIL_SUCCESS", "Inbox is empty (0 messages)")
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass
            return [], None

        # 6. Compute start = max(1, total-9), end = total
        start = max(1, total - (max_count - 1))
        end = total
        log_event("GMAIL_FETCH", f"Fetching email range {start}:{end} (total={total})")

        # 7. Fetch that range with BODY.PEEK[] (never mark read), newest first
        emails: List[Dict[str, str]] = []
        for seq_id in range(end, start - 1, -1):
            try:
                res_fetch, msg_data = mail.fetch(str(seq_id), "(BODY.PEEK[])")
                if res_fetch != "OK" or not msg_data:
                    continue

                raw_bytes = None
                for part in msg_data:
                    if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], bytes):
                        raw_bytes = part[1]
                        break

                if not raw_bytes:
                    continue

                msg = email.message_from_bytes(raw_bytes)
                subject = _decode_mime_header(msg.get("Subject", "(No Subject)"))
                sender = _decode_mime_header(msg.get("From", "(Unknown Sender)"))
                date_str = _decode_mime_header(msg.get("Date", ""))
                body_snippet = _extract_body_text(msg, max_chars=1000)

                emails.append({
                    "subject": subject,
                    "from": sender,
                    "date": date_str,
                    "body": body_snippet
                })
            except Exception as fetch_err:
                log_event("GMAIL_WARN", f"Error parsing message seq_id {seq_id}: {fetch_err}", level="warning")

        try:
            mail.close()
            mail.logout()
        except Exception:
            pass

        log_event("GMAIL_SUCCESS", f"Successfully retrieved {len(emails)} emails")
        return emails, None

    except Exception as exc:
        full_err = f"{type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
        log_event("GMAIL_FAILURE", f"IMAP operation error: {full_err}", level="error")
        if mail:
            try:
                mail.logout()
            except Exception:
                pass
        return [], f"⚠️ Gmail Diagnostic: {str(exc)}"

def format_emails_for_llm(emails: List[Dict[str, str]]) -> str:
    """Format emails into a readable context string for LLMs."""
    if not emails:
        return "No recent emails found."
    lines = []
    for i, em in enumerate(emails, 1):
        lines.append(
            f"Email #{i}:\n"
            f"From: {em.get('from', '')}\n"
            f"Date: {em.get('date', '')}\n"
            f"Subject: {em.get('subject', '')}\n"
            f"Body:\n{em.get('body', '')}\n"
        )
    return "\n---\n".join(lines)
