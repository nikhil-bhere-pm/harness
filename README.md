# Athena (The Harness)

A clean, minimalist, high-end multi-model AI workspace built with Streamlit. Athena unifies leading AI models with real-time web search, document RAG, and read-only Gmail access, backed by silent background Google Sheets logging.

---

## ⚡ Core Capabilities

- **Multi-Model Intelligence**: Seamlessly switch between:
  - Anthropic **Claude 3.5 Sonnet** (`claude-sonnet-4-6` / `claude-3-5-sonnet-latest`)
  - OpenAI **GPT-4o** (`gpt-4o`)
  - Google **Gemini 3.8 Flash** (`gemini-3.8-flash`)
  - xAI **Grok 2** (`grok-2-latest`)
- **🌐 Web Search**: Grounded real-time answers via Tavily Search API with dynamic tool-calling and fallback context injection.
- **📄 Document RAG**: Instant keyword relevance retrieval from uploaded `.txt` and `.pdf` documents with 800-char / 100-overlap in-memory chunking (zero external vector database required).
- **✉️ Gmail IMAP (Read-Only)**: Secure, read-only extraction with sequence ID ranges, 10MB buffer protection, and copy-paste sanitized credentials.
- **📊 Google Sheets Logger**: Optional, non-blocking background thread logging each conversation turn to a target spreadsheet.
- **Sources Used Footer**: Transparent citations under every response showing exactly what sources fired and how many results/chunks were used.
- **Zero Raw Stack Traces**: All external calls log full diagnostic data to `harness.log` and console while presenting clean, resilient messages in the UI.

---

## 🛠️ Environment Variables

Configure these either via your hosting platform's environment settings, in a local `.env` file, or dynamically within the app's **⚙️ Settings** modal:

| Variable | Required | Description |
| :--- | :---: | :--- |
| `ANTHROPIC_API_KEY` | Optional* | API key for Anthropic Claude models (`sk-ant-...`) |
| `OPENAI_API_KEY` | Optional* | API key for OpenAI GPT-4o (`sk-...`) |
| `GEMINI_API_KEY` | Optional* | API key for Google Gemini (`AIzaSy...`) |
| `XAI_API_KEY` | Optional* | API key for xAI Grok (`xai-...`) |
| `TAVILY_API_KEY` | Optional | API key for Tavily live web search (`tvly-...`) |
| `GMAIL_USER` | Optional | Gmail email address for IMAP read-only access |
| `GMAIL_APP_PASSWORD` | Optional | 16-character Google App Password (spaces/non-breaking spaces auto-sanitized) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Optional | Raw JSON string or file path for Google Service Account credentials |
| `TARGET_SHEET_ID` | Optional | Google Spreadsheet ID string for background conversation logging |
| `HARNESS_TITLE` | Optional | Custom display title (defaults to `Athena`) |

*\*At least one LLM provider key is required for chatting.*

---

## 🚀 Deployment (Render)

This application is configured for deployment on [Render](https://render.com) as a **Web Service**.

### 1. Build & Start Commands
- **Environment**: `Python 3`
- **Build Command**:
  ```bash
  pip install -r requirements.txt
  ```
- **Start Command**:
  ```bash
  streamlit run app.py --server.port $PORT --server.address 0.0.0.0
  ```

### 2. Configure Environment Variables
In your Render Dashboard, navigate to **Environment** and add any of the API keys listed above.

---

## 💻 Local Development

1. **Clone the repository**:
   ```bash
   git clone https://github.com/<your-username>/harness.git
   cd harness
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the app**:
   ```bash
   streamlit run app.py
   ```
   Open `http://localhost:8501` in your browser.
