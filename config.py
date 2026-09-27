import os
import re
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

def _clean_str(val: Optional[str]) -> str:
    if val is None:
        return ""
    # Strip non-ASCII / non-breaking spaces (\xa0 / \u00a0)
    cleaned = val.replace("\xa0", " ").replace("\u00a0", " ")
    return cleaned.strip()

def sanitize_credential(key: str, val: Optional[str]) -> str:
    """Sanitize credential value according to key type."""
    if not val:
        return ""
    cleaned = _clean_str(val)
    if key == "GMAIL_APP_PASSWORD":
        # Google App Password is 16 alphanumeric characters; strip all spaces & non-alphanumerics
        return re.sub(r"[^a-zA-Z0-9]", "", cleaned)
    return cleaned

def get_config(key: str, default: str = "") -> str:
    """Unified get_config: checks st.session_state first, then os.environ."""
    val = ""
    try:
        import streamlit as st
        if hasattr(st, "session_state"):
            session_creds = st.session_state.get("session_creds", {})
            if key in session_creds and session_creds[key]:
                val = session_creds[key]
    except Exception:
        pass

    if not val:
        val = os.environ.get(key, "")

    sanitized = sanitize_credential(key, val) if key == "GMAIL_APP_PASSWORD" else _clean_str(val)
    return sanitized if sanitized else default

def set_session_config(key: str, val: str) -> str:
    """Safely updates config in os.environ and session_creds dict without touching widget keys."""
    sanitized = sanitize_credential(key, val)
    os.environ[key] = sanitized
    try:
        import streamlit as st
        if hasattr(st, "session_state"):
            if "session_creds" not in st.session_state:
                st.session_state["session_creds"] = {}
            st.session_state["session_creds"][key] = sanitized
    except Exception:
        pass
    return sanitized

def is_configured(key: str) -> bool:
    """Check if a specific config or credential has a non-empty value."""
    return bool(get_config(key))
