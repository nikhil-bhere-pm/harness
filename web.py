import json
import traceback
from typing import Dict, Any, List
from tavily import TavilyClient
from config import get_config
from logger import log_event

TAVILY_TOOL_ANTHROPIC = {
    "name": "web_search",
    "description": "Search the live web using Tavily for current information, news, facts, and real-time data. Returns up to 5 relevant snippets.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query string"
            }
        },
        "required": ["query"]
    }
}

TAVILY_TOOL_OPENAI = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the live web using Tavily for current information, news, facts, and real-time data. Returns up to 5 relevant snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string"
                }
            },
            "required": ["query"]
        }
    }
}

def search_web(query: str, max_results: int = 5) -> Dict[str, Any]:
    """Execute Tavily web search capped at max_results (default 5). Logs full request and result."""
    api_key = get_config("TAVILY_API_KEY")
    if not api_key:
        err_msg = "TAVILY_API_KEY not configured. Web search unavailable."
        log_event("WEB_SEARCH_WARN", err_msg, level="warning")
        return {"error": err_msg, "results": []}

    log_event("WEB_SEARCH_START", f"Searching web for: '{query}' [max_results={max_results}]")

    try:
        client = TavilyClient(api_key=api_key)
        # basic search depth for speed
        response = client.search(query=query, max_results=max_results, search_depth="basic")
        
        raw_results = response.get("results", [])
        formatted_results: List[Dict[str, str]] = []
        for r in raw_results[:max_results]:
            formatted_results.append({
                "title": r.get("title", "Untitled"),
                "url": r.get("url", ""),
                "content": r.get("content", "")
            })

        log_event(
            "WEB_SEARCH_SUCCESS",
            f"Query: '{query}' -> Found {len(formatted_results)} results. Full data: {json.dumps(formatted_results)}"
        )
        return {"results": formatted_results, "error": None}

    except Exception as exc:
        full_err = f"Exception: {type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
        log_event("WEB_SEARCH_FAILURE", f"Tavily error for query '{query}': {full_err}", level="error")
        return {"error": str(exc), "results": []}

def format_search_results_for_llm(results: List[Dict[str, str]]) -> str:
    """Format structured search results into a clean string for LLMs."""
    if not results:
        return "No web results found."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r.get('title', 'Untitled')}\nURL: {r.get('url', '')}\nSnippet: {r.get('content', '')}\n")
    return "\n".join(lines)
