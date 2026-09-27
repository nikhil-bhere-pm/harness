import os
import json
import threading
import datetime
import traceback
from typing import Optional, List, Dict, Any
from google.oauth2 import service_account
from googleapiclient.discovery import build
from config import get_config
from logger import log_event

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def _append_row_worker(
    sheet_id: str,
    sa_json_str_or_path: str,
    row_data: List[str]
) -> None:
    """Worker function executed in background thread to append row to Google Sheet."""
    log_event("SHEETS_START", f"Appending conversation row to sheet '{sheet_id}'")
    try:
        # Resolve service account credentials from JSON string or file path
        sa_str = sa_json_str_or_path.strip()
        if sa_str.startswith("{"):
            info = json.loads(sa_str)
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        elif os.path.isfile(sa_str):
            creds = service_account.Credentials.from_service_account_file(sa_str, scopes=SCOPES)
        else:
            info = json.loads(sa_str)
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        body = {
            "values": [row_data]
        }

        result = service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="A:F",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()

        updated_cells = result.get("updates", {}).get("updatedCells", 0)
        log_event("SHEETS_SUCCESS", f"Row successfully appended to sheet '{sheet_id}' ({updated_cells} cells updated)")

    except Exception as exc:
        full_err = f"Exception: {type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
        log_event("SHEETS_FAILURE", f"Failed appending row to sheet '{sheet_id}': {full_err}", level="error")

def log_conversation_turn(
    model: str,
    prompt: str,
    reply: str,
    sources_allowed: str,
    sources_fired: str
) -> None:
    """
    Non-blocking background logger to Google Sheets.
    If GOOGLE_SERVICE_ACCOUNT_JSON or TARGET_SHEET_ID is missing, skips silently.
    Sheets must never block a reply.
    """
    sheet_id = get_config("TARGET_SHEET_ID")
    sa_json = get_config("GOOGLE_SERVICE_ACCOUNT_JSON")

    if not sheet_id or not sa_json:
        log_event("SHEETS_SKIP", "Google Sheets logging skipped: credentials or TARGET_SHEET_ID not configured")
        return

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    row = [
        now_iso,
        model,
        prompt,
        reply[:2000],  # Truncate reply to fit standard spreadsheet cell limits
        sources_allowed,
        sources_fired
    ]

    # Spawn background daemon thread so logging never blocks the chat UI or user reply
    thread = threading.Thread(
        target=_append_row_worker,
        args=(sheet_id, sa_json, row),
        daemon=True,
        name="SheetsLoggerThread"
    )
    thread.start()
