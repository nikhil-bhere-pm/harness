import streamlit as st
import json
import traceback
from config import get_config, set_session_config, is_configured
from logger import logger, log_event
from llm import ask
from rag import extract_text, chunk_text
from sheets import log_conversation_turn

# Configure Streamlit page
st.set_page_config(
    page_title="Athena",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom minimalist styling
st.markdown("""
<style>
    /* Clean layout & typography */
    .stApp {
        background-color: #FFFFFF;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Subtle slate borders */
    .stChatFloatingInputContainer {
        background-color: #FFFFFF;
        border-top: 1px solid #E2E8F0;
    }
    
    /* Composer tool row styling */
    .composer-toolbar {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 6px 12px;
        margin-bottom: 8px;
    }
    
    /* Status indicators */
    .status-set {
        color: #10B981;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .status-empty {
        color: #94A3B8;
        font-weight: 500;
        font-size: 0.85rem;
    }
    
    /* Header layout */
    .header-container {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #E2E8F0;
        padding-bottom: 12px;
        margin-bottom: 16px;
    }
    
    /* Sidebar header */
    .sidebar-title {
        font-size: 1.6rem;
        font-weight: 700;
        color: #0F172A;
        margin-bottom: 8px;
    }
    .sidebar-blurb {
        font-size: 0.9rem;
        line-height: 1.5;
        color: #475569;
    }
</style>
""", unsafe_allow_html=True)

# Log session initialization once
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.messages = []
    log_event("APP_START", "Athena session initialized")

# -------------------------------------------------------------
# RIGHT ZONE: Settings Dialog Modal
# -------------------------------------------------------------
@st.dialog("⚙️ Settings", width="large")
def show_settings_modal():
    st.markdown("Configure runtime credentials and app title for this session. Values override environment variables and are never written to disk.")
    
    current_title = get_config("HARNESS_TITLE", "Athena")
    new_title = st.text_input("Application Title", value=current_title, help="Sets the prominent title in the left sidebar.")
    
    st.markdown("---")
    st.subheader("Models · Web")
    
    col1, col2 = st.columns(2)
    with col1:
        anthropic_set = is_configured("ANTHROPIC_API_KEY")
        st.markdown(f"**Anthropic API Key** — <span class='{'status-set' if anthropic_set else 'status-empty'}'>{'● set' if anthropic_set else '○ empty'}</span>", unsafe_allow_html=True)
        anthropic_key = st.text_input("Anthropic Key", type="password", placeholder="•••••••• (configured)" if anthropic_set else "sk-ant-...", label_visibility="collapsed")
        
        openai_set = is_configured("OPENAI_API_KEY")
        st.markdown(f"**OpenAI API Key** — <span class='{'status-set' if openai_set else 'status-empty'}'>{'● set' if openai_set else '○ empty'}</span>", unsafe_allow_html=True)
        openai_key = st.text_input("OpenAI Key", type="password", placeholder="•••••••• (configured)" if openai_set else "sk-...", label_visibility="collapsed")

    with col2:
        xai_set = is_configured("XAI_API_KEY")
        st.markdown(f"**xAI (Grok) API Key** — <span class='{'status-set' if xai_set else 'status-empty'}'>{'● set' if xai_set else '○ empty'}</span>", unsafe_allow_html=True)
        xai_key = st.text_input("xAI Key", type="password", placeholder="•••••••• (configured)" if xai_set else "xai-...", label_visibility="collapsed")
        
        tavily_set = is_configured("TAVILY_API_KEY")
        st.markdown(f"**Tavily Search API Key** — <span class='{'status-set' if tavily_set else 'status-empty'}'>{'● set' if tavily_set else '○ empty'}</span>", unsafe_allow_html=True)
        tavily_key = st.text_input("Tavily Key", type="password", placeholder="•••••••• (configured)" if tavily_set else "tvly-...", label_visibility="collapsed")

    st.markdown("---")
    st.subheader("Email (Gmail IMAP)")
    col_em1, col_em2 = st.columns(2)
    with col_em1:
        gmail_user_set = is_configured("GMAIL_USER")
        st.markdown(f"**Gmail User / Address** — <span class='{'status-set' if gmail_user_set else 'status-empty'}'>{'● set' if gmail_user_set else '○ empty'}</span>", unsafe_allow_html=True)
        current_gmail_user = get_config("GMAIL_USER")
        gmail_user = st.text_input("Gmail User", value=current_gmail_user, placeholder="you@gmail.com", label_visibility="collapsed")
    with col_em2:
        gmail_pass_set = is_configured("GMAIL_APP_PASSWORD")
        st.markdown(f"**Gmail App Password** — <span class='{'status-set' if gmail_pass_set else 'status-empty'}'>{'● set' if gmail_pass_set else '○ empty'}</span>", unsafe_allow_html=True)
        gmail_pass = st.text_input("Gmail App Password", type="password", placeholder="•••••••• (16 alphanumerics)" if gmail_pass_set else "xxxx xxxx xxxx xxxx", label_visibility="collapsed")

    st.markdown("---")
    st.subheader("Google Sheets (Background Logging)")
    col_sh1, col_sh2 = st.columns(2)
    with col_sh1:
        sheet_id_set = is_configured("TARGET_SHEET_ID")
        st.markdown(f"**Target Sheet ID** — <span class='{'status-set' if sheet_id_set else 'status-empty'}'>{'● set' if sheet_id_set else '○ empty'}</span>", unsafe_allow_html=True)
        current_sheet_id = get_config("TARGET_SHEET_ID")
        sheet_id = st.text_input("Sheet ID", value=current_sheet_id, placeholder="Spreadsheet ID string", label_visibility="collapsed")
    with col_sh2:
        sa_set = is_configured("GOOGLE_SERVICE_ACCOUNT_JSON")
        st.markdown(f"**Service Account JSON** — <span class='{'status-set' if sa_set else 'status-empty'}'>{'● set' if sa_set else '○ empty'}</span>", unsafe_allow_html=True)
        sa_file = st.file_uploader("Upload Service Account JSON", type=["json"], label_visibility="collapsed")
        sa_text = st.text_area("Or Paste Service Account JSON", placeholder="{ ... }" if not sa_set else "{ (configured) }", height=100)

    st.markdown("")
    if st.button("💾 Save for this session", type="primary", use_container_width=True):
        saved_keys = []
        if new_title.strip():
            set_session_config("HARNESS_TITLE", new_title.strip())
            saved_keys.append("HARNESS_TITLE")
        if anthropic_key.strip():
            set_session_config("ANTHROPIC_API_KEY", anthropic_key.strip())
            saved_keys.append("ANTHROPIC_API_KEY")
        if openai_key.strip():
            set_session_config("OPENAI_API_KEY", openai_key.strip())
            saved_keys.append("OPENAI_API_KEY")
        if xai_key.strip():
            set_session_config("XAI_API_KEY", xai_key.strip())
            saved_keys.append("XAI_API_KEY")
        if tavily_key.strip():
            set_session_config("TAVILY_API_KEY", tavily_key.strip())
            saved_keys.append("TAVILY_API_KEY")
        if gmail_user.strip():
            set_session_config("GMAIL_USER", gmail_user.strip())
            saved_keys.append("GMAIL_USER")
        if gmail_pass.strip():
            set_session_config("GMAIL_APP_PASSWORD", gmail_pass.strip())
            saved_keys.append("GMAIL_APP_PASSWORD")
        if sheet_id.strip():
            set_session_config("TARGET_SHEET_ID", sheet_id.strip())
            saved_keys.append("TARGET_SHEET_ID")
            
        # Handle service account JSON from file or text
        if sa_file is not None:
            try:
                content = sa_file.read().decode("utf-8")
                json.loads(content) # validate JSON format
                set_session_config("GOOGLE_SERVICE_ACCOUNT_JSON", content)
                saved_keys.append("GOOGLE_SERVICE_ACCOUNT_JSON")
            except Exception as e:
                st.error(f"Invalid Service Account JSON file: {e}")
        elif sa_text.strip():
            try:
                json.loads(sa_text.strip())
                set_session_config("GOOGLE_SERVICE_ACCOUNT_JSON", sa_text.strip())
                saved_keys.append("GOOGLE_SERVICE_ACCOUNT_JSON")
            except Exception as e:
                st.error(f"Invalid Service Account JSON: {e}")

        log_event("SETTINGS_SAVED", f"Updated session credentials: {saved_keys}")
        st.success("Settings saved for this session!")
        st.rerun()

# -------------------------------------------------------------
# LEFT ZONE: Native Sidebar
# -------------------------------------------------------------
with st.sidebar:
    app_title = get_config("HARNESS_TITLE", "Athena")
    st.markdown(f"<div class='sidebar-title'>{app_title}</div>", unsafe_allow_html=True)
    st.markdown("""
    <div class='sidebar-blurb'>
    Pick a model, toggle Web, Docs, or Email sources, and ask. 
    Athena grounds responses in real-time sources according to your intent.
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    
    # Active sources status overview in sidebar
    st.markdown("**Active Capabilities**")
    tav_ok = is_configured("TAVILY_API_KEY")
    gmail_ok = is_configured("GMAIL_USER") and is_configured("GMAIL_APP_PASSWORD")
    sheets_ok = is_configured("GOOGLE_SERVICE_ACCOUNT_JSON") and is_configured("TARGET_SHEET_ID")
    
    st.markdown(f"- Web Search: {'🟢 Available' if tav_ok else '⚪ Missing Key'}")
    doc_status = "⚪ No document loaded"
    if st.session_state.get("doc_filename"):
        if st.session_state.get("doc_error"):
            doc_status = f"⚠️ {st.session_state['doc_filename']} (no text)"
        else:
            doc_status = f"🟢 Ready: {st.session_state['doc_filename']} ({len(st.session_state.get('doc_chunks', []))} chunks)"
    st.markdown(f"- Document RAG: {doc_status}")
    st.markdown(f"- Gmail (Read-only): {'🟢 Available' if gmail_ok else '⚪ Needs Config'}")
    st.markdown(f"- Sheets Log: {'🟢 Enabled' if sheets_ok else '⚪ Inactive'}")

# -------------------------------------------------------------
# CENTER ZONE: Main Area & Chat Console
# -------------------------------------------------------------
# Top row with settings button
col_head, col_btn = st.columns([10, 2])
with col_head:
    st.markdown(f"### {app_title} Console")
with col_btn:
    if st.button("⚙️ Settings", use_container_width=True):
        show_settings_modal()

# Message Feed
chat_container = st.container()
with chat_container:
    if not st.session_state.messages:
        st.info("👋 Welcome to Athena. Choose your model and sources below, then enter your question.")
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# Claude-style Tool Row directly above chat input
st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
tool_col1, tool_col2, tool_col3, tool_col4, tool_col5 = st.columns([3, 2, 2, 2, 2])

with tool_col1:
    selected_model = st.selectbox(
        "Model",
        options=["claude-sonnet-4-6", "gpt-4o", "grok-2-latest"],
        format_func=lambda m: {
            "claude-sonnet-4-6": "Claude 3.5 Sonnet",
            "gpt-4o": "OpenAI GPT-4o",
            "grok-2-latest": "Grok 2"
        }.get(m, m),
        label_visibility="collapsed"
    )

with tool_col2:
    web_toggle = st.toggle("🌐 Web", value=False, help="Search the live web via Tavily")

with tool_col3:
    gmail_toggle = st.toggle("✉️ Gmail", value=False, help="Access recent emails via IMAP (read-only)")

with tool_col4:
    docs_toggle = st.toggle("📄 Docs", value=False, help="Ground response with uploaded document")

with tool_col5:
    with st.popover("📎 Upload Doc", use_container_width=True):
        uploaded_doc = st.file_uploader("Upload .txt or .pdf", type=["txt", "pdf"], key="rag_uploader")
        if uploaded_doc is not None:
            if st.session_state.get("last_uploaded_doc_name") != uploaded_doc.name:
                file_bytes = uploaded_doc.read()
                text, err = extract_text(file_bytes, uploaded_doc.name)
                if err:
                    st.session_state["doc_error"] = err
                    st.session_state["doc_chunks"] = []
                    st.session_state["doc_filename"] = uploaded_doc.name
                else:
                    chunks = chunk_text(text, chunk_size=800, overlap=100)
                    st.session_state["doc_chunks"] = chunks
                    st.session_state["doc_filename"] = uploaded_doc.name
                    st.session_state["doc_error"] = None
                st.session_state["last_uploaded_doc_name"] = uploaded_doc.name

        if st.session_state.get("doc_filename"):
            if st.session_state.get("doc_error"):
                st.warning(st.session_state["doc_error"])
            else:
                chunks_count = len(st.session_state.get("doc_chunks", []))
                st.success(f"Loaded '{st.session_state['doc_filename']}' ({chunks_count} chunks)")

# Bottom Prompt Input
prompt = st.chat_input("Ask a question across Web, Docs, and Gmail...")
if prompt:
    # Append and display user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    log_event("USER_PROMPT", f"Received message: '{prompt}' (Model: {selected_model}, Web: {web_toggle}, Gmail: {gmail_toggle}, Docs: {docs_toggle})")
    
    with chat_container:
        with st.chat_message("user"):
            st.markdown(prompt)
            
        with st.chat_message("assistant"):
            try:
                response_stream = ask(
                    provider=selected_model,
                    messages=st.session_state.messages,
                    web_enabled=web_toggle,
                    docs_enabled=docs_toggle,
                    doc_chunks=st.session_state.get("doc_chunks", []),
                    email_enabled=gmail_toggle,
                    doc_filename=st.session_state.get("doc_filename")
                )
                full_reply = st.write_stream(response_stream)
            except Exception as stream_err:
                full_err = f"{type(stream_err).__name__}: {str(stream_err)}\n{traceback.format_exc()}"
                log_event("STREAM_FAILURE", full_err, level="error")
                full_reply = f"⚠️ An unexpected error occurred: {str(stream_err)}"
                st.error(full_reply)
            
    st.session_state.messages.append({"role": "assistant", "content": full_reply})
    log_event("ASSISTANT_REPLY", f"Completed assistant reply for prompt: '{prompt}'")
    
    # Background Sheets logging (optional & non-blocking)
    allowed_list = []
    if web_toggle: allowed_list.append("Web")
    if docs_toggle: allowed_list.append("Docs")
    if gmail_toggle: allowed_list.append("Gmail")
    sources_allowed_str = ", ".join(allowed_list) if allowed_list else "None"

    sources_fired_str = "None"
    if "**Sources used:**" in full_reply:
        sources_fired_str = full_reply.split("**Sources used:**")[-1].strip()

    log_conversation_turn(
        model=selected_model,
        prompt=prompt,
        reply=full_reply,
        sources_allowed=sources_allowed_str,
        sources_fired=sources_fired_str
    )
