import json
import traceback
from typing import Generator, List, Dict, Optional, Any
import anthropic
import openai
from config import get_config
from logger import log_event
from web import (
    search_web,
    format_search_results_for_llm,
    TAVILY_TOOL_ANTHROPIC,
    TAVILY_TOOL_OPENAI
)
from rag import retrieve_relevant_chunks

def _prepare_anthropic_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Format messages for Anthropic: valid roles (user/assistant) with alternating order."""
    formatted = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if not content:
            continue
        if role in ("user", "assistant"):
            if formatted and formatted[-1]["role"] == role and isinstance(content, str) and isinstance(formatted[-1]["content"], str):
                formatted[-1]["content"] += f"\n\n{content}"
            else:
                formatted.append({"role": role, "content": content})
                
    while formatted and formatted[0]["role"] != "user":
        formatted.pop(0)
        
    return formatted

def _prepare_openai_messages(
    messages: List[Dict[str, Any]],
    system_prompt: str
) -> List[Dict[str, Any]]:
    """Format messages for OpenAI / Grok: prepend system prompt and include turns."""
    formatted = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if not content:
            continue
        if role in ("user", "assistant", "system"):
            formatted.append({"role": role, "content": content})
    return formatted

def _ask_claude(
    messages: List[Dict[str, Any]],
    web_enabled: bool = False,
    system_prompt: str = "You are a helpful AI assistant in Athena.",
    sources_used: Optional[List[str]] = None,
) -> Generator[str, None, None]:
    """Stream response from Anthropic Claude with tool-calling support for web search."""
    if sources_used is None:
        sources_used = []

    api_key = get_config("ANTHROPIC_API_KEY")
    if not api_key:
        msg = "⚠️ Anthropic API key not configured. Add ANTHROPIC_API_KEY in Settings (⚙️) or environment."
        log_event("LLM_WARN", "Claude call skipped: ANTHROPIC_API_KEY is empty", level="warning")
        yield msg
        return

    formatted_messages = _prepare_anthropic_messages(messages)
    if not formatted_messages:
        yield "⚠️ No user message found to send to Claude."
        return

    model = "claude-sonnet-4-6"
    log_event("LLM_START", f"Starting Claude call [model={model}, turns={len(formatted_messages)}, web={web_enabled}]")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        tools = [TAVILY_TOOL_ANTHROPIC] if web_enabled else None

        def _call_claude_tool_step(current_model: str, msgs: list, tools_to_use: Optional[list]):
            return client.messages.create(
                model=current_model,
                max_tokens=4096,
                system=system_prompt,
                messages=msgs,
                tools=tools_to_use if tools_to_use else anthropic.NOT_GIVEN
            )

        active_model = model
        if tools:
            try:
                response = _call_claude_tool_step(active_model, formatted_messages, tools)
            except anthropic.NotFoundError:
                active_model = "claude-3-5-sonnet-latest"
                log_event("LLM_WARN", f"Model '{model}' not found; falling back to '{active_model}'", level="warning")
                response = _call_claude_tool_step(active_model, formatted_messages, tools)

            # Check if Claude called web_search
            if response.stop_reason == "tool_use":
                yield "🌐 Searching the web…\n\n"

                tool_use_block = next((b for b in response.content if b.type == "tool_use" and b.name == "web_search"), None)
                if tool_use_block:
                    query = tool_use_block.input.get("query", "")
                    search_res = search_web(query)
                    if search_res.get("error"):
                        tool_content = f"Web search error: {search_res['error']}"
                        sources_used.append("Web — search error")
                    else:
                        num_res = len(search_res.get("results", []))
                        tool_content = format_search_results_for_llm(search_res.get("results", []))
                        sources_used.append(f"Web — {num_res} result{'s' if num_res != 1 else ''}")

                    followup_messages = list(formatted_messages)
                    followup_messages.append({"role": "assistant", "content": response.content})
                    followup_messages.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_block.id,
                                "content": tool_content
                            }
                        ]
                    })

                    with client.messages.stream(
                        model=active_model,
                        max_tokens=4096,
                        system=system_prompt,
                        messages=followup_messages,
                    ) as stream:
                        for text_chunk in stream.text_stream:
                            yield text_chunk

                    log_event("LLM_SUCCESS", f"Claude call with web search completed [model={active_model}]")
                    return
            else:
                for block in response.content:
                    if hasattr(block, "text"):
                        yield block.text
                log_event("LLM_SUCCESS", f"Claude call without tools completed [model={active_model}]")
                return

        # Pure streaming when web is not enabled
        try:
            with client.messages.stream(
                model=active_model,
                max_tokens=4096,
                system=system_prompt,
                messages=formatted_messages,
            ) as stream:
                for text_chunk in stream.text_stream:
                    yield text_chunk
            log_event("LLM_SUCCESS", f"Claude pure streaming completed [model={active_model}]")
        except anthropic.NotFoundError:
            active_model = "claude-3-5-sonnet-latest"
            log_event("LLM_WARN", f"Model '{model}' not found; falling back to '{active_model}'", level="warning")
            with client.messages.stream(
                model=active_model,
                max_tokens=4096,
                system=system_prompt,
                messages=formatted_messages,
            ) as stream:
                for text_chunk in stream.text_stream:
                    yield text_chunk
            log_event("LLM_SUCCESS", f"Claude pure streaming completed with fallback [model={active_model}]")

    except anthropic.APIError as err:
        full_err = f"Status: {getattr(err, 'status_code', 'N/A')} | Message: {str(err)} | Body: {getattr(err, 'body', 'N/A')}"
        log_event("LLM_FAILURE", f"Claude API Error: {full_err}", level="error")
        yield f"⚠️ Claude API Error ({getattr(err, 'status_code', 'error')}): {err.message if hasattr(err, 'message') else str(err)}"
    except Exception as exc:
        full_err = f"Exception: {type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
        log_event("LLM_FAILURE", f"Claude Unexpected Error: {full_err}", level="error")
        yield f"⚠️ Error communicating with Claude: {str(exc)}"

def _ask_openai_compatible(
    provider_name: str,
    model: str,
    api_key_name: str,
    base_url: Optional[str],
    messages: List[Dict[str, Any]],
    web_enabled: bool = False,
    system_prompt: str = "You are a helpful AI assistant in Athena.",
    sources_used: Optional[List[str]] = None,
) -> Generator[str, None, None]:
    """Stream response from OpenAI-compatible endpoint with tool-calling support."""
    if sources_used is None:
        sources_used = []

    api_key = get_config(api_key_name)
    if not api_key:
        msg = f"⚠️ {provider_name} API key not configured. Add {api_key_name} in Settings (⚙️) or environment."
        log_event("LLM_WARN", f"{provider_name} call skipped: {api_key_name} is empty", level="warning")
        yield msg
        return

    formatted_messages = _prepare_openai_messages(messages, system_prompt)
    if len(formatted_messages) <= 1:
        yield f"⚠️ No user message found to send to {provider_name}."
        return

    log_event("LLM_START", f"Starting {provider_name} call [model={model}, turns={len(formatted_messages)}, web={web_enabled}]")

    try:
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = openai.OpenAI(**kwargs)
        tools = [TAVILY_TOOL_OPENAI] if web_enabled else None

        if tools:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=formatted_messages,
                    tools=tools,
                    tool_choice="auto",
                )
                choice = response.choices[0]
                if choice.message and choice.message.tool_calls:
                    yield "🌐 Searching the web…\n\n"

                    tool_call = choice.message.tool_calls[0]
                    args = {}
                    if tool_call.function and tool_call.function.arguments:
                        try:
                            args = json.loads(tool_call.function.arguments)
                        except Exception:
                            args = {"query": tool_call.function.arguments}
                    query = args.get("query", "")
                    
                    search_res = search_web(query)
                    if search_res.get("error"):
                        tool_content = f"Web search error: {search_res['error']}"
                        sources_used.append("Web — search error")
                    else:
                        num_res = len(search_res.get("results", []))
                        tool_content = format_search_results_for_llm(search_res.get("results", []))
                        sources_used.append(f"Web — {num_res} result{'s' if num_res != 1 else ''}")

                    followup_messages = list(formatted_messages)
                    followup_messages.append(choice.message)
                    followup_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_content
                    })

                    stream = client.chat.completions.create(
                        model=model,
                        messages=followup_messages,
                        stream=True
                    )
                    for chunk in stream:
                        if chunk.choices and len(chunk.choices) > 0:
                            delta = chunk.choices[0].delta
                            if delta and delta.content:
                                yield delta.content

                    log_event("LLM_SUCCESS", f"{provider_name} call with web search completed [model={model}]")
                    return
                else:
                    if choice.message and choice.message.content:
                        yield choice.message.content
                    log_event("LLM_SUCCESS", f"{provider_name} call without tools completed [model={model}]")
                    return

            except Exception as tool_exc:
                if provider_name in ("Grok", "Gemini"):
                    log_event("LLM_WARN", f"{provider_name} tool-calling failed ({tool_exc}), falling back to direct context injection", level="warning")
                    yield "🌐 Searching the web…\n\n"
                    user_q = ""
                    for m in reversed(messages):
                        if m.get("role") == "user":
                            user_q = m.get("content", "")
                            break
                    search_res = search_web(user_q)
                    num_res = len(search_res.get("results", []))
                    tool_content = format_search_results_for_llm(search_res.get("results", []))
                    sources_used.append(f"Web — {num_res} result{'s' if num_res != 1 else ''}")

                    fallback_system = f"{system_prompt}\n\nWeb Search Results:\n{tool_content}"
                    fallback_messages = _prepare_openai_messages(messages, fallback_system)

                    stream = client.chat.completions.create(
                        model=model,
                        messages=fallback_messages,
                        stream=True
                    )
                    for chunk in stream:
                        if chunk.choices and len(chunk.choices) > 0:
                            delta = chunk.choices[0].delta
                            if delta and delta.content:
                                yield delta.content

                    log_event("LLM_SUCCESS", f"{provider_name} completed with web fallback context [model={model}]")
                    return
                else:
                    raise tool_exc

        # Pure streaming when web is not enabled
        stream = client.chat.completions.create(
            model=model,
            messages=formatted_messages,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        log_event("LLM_SUCCESS", f"{provider_name} pure streaming completed [model={model}]")

    except openai.APIError as err:
        full_err = f"Status: {getattr(err, 'status_code', 'N/A')} | Message: {str(err)} | Body: {getattr(err, 'body', 'N/A')}"
        log_event("LLM_FAILURE", f"{provider_name} API Error: {full_err}", level="error")
        yield f"⚠️ {provider_name} API Error ({getattr(err, 'status_code', 'error')}): {err.message if hasattr(err, 'message') else str(err)}"
    except Exception as exc:
        full_err = f"Exception: {type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
        log_event("LLM_FAILURE", f"{provider_name} Unexpected Error: {full_err}", level="error")
        yield f"⚠️ Error communicating with {provider_name}: {str(exc)}"

def ask(
    provider: str,
    messages: List[Dict[str, Any]],
    web_enabled: bool = False,
    docs_enabled: bool = False,
    doc_chunks: Optional[List[str]] = None,
    email_enabled: bool = False,
    doc_filename: Optional[str] = None,
) -> Generator[str, None, None]:
    """Unified generator interface for all providers, handling web search, document RAG, and Gmail."""
    sources_used: List[str] = []
    system_prompt = "You are a helpful AI assistant in Athena, a clean multi-model workspace."

    # 1. Document RAG handling
    if docs_enabled:
        if not doc_chunks:
            yield "⚠️ Docs toggle is ON, but no document is loaded. Please upload a .txt or .pdf file using the 📎 Upload Doc control.\n\n"
        else:
            last_user_query = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    c = m.get("content", "")
                    if isinstance(c, str):
                        last_user_query = c
                    break

            relevant_chunks = retrieve_relevant_chunks(last_user_query, doc_chunks, top_k=4)
            if relevant_chunks:
                yield "📄 Reading your document…\n\n"
                num_chunks = len(relevant_chunks)
                doc_label = f"Document — {num_chunks} chunk{'s' if num_chunks != 1 else ''}" + (f" ({doc_filename})" if doc_filename else "")
                sources_used.append(doc_label)
                doc_context = "\n---\n".join(relevant_chunks)
                system_prompt += f"\n\n[CONTEXT FROM UPLOADED DOCUMENT]:\n{doc_context}\nUse this document context to answer the user's questions where applicable."

    # 2. Gmail IMAP handling
    if email_enabled:
        import importlib
        import gmail
        importlib.reload(gmail)

        yield "✉️ Checking email…\n\n"
        emails, gmail_err = gmail.fetch_recent_emails(max_count=10)
        if gmail_err:
            yield f"{gmail_err}\n\n"
            diag_clean = gmail_err.replace("⚠️ Gmail Diagnostic: ", "").strip()
            sources_used.append(f"Email — diagnostic: {diag_clean[:35]}")
        elif emails:
            num_emails = len(emails)
            sources_used.append(f"Email — {num_emails} message{'s' if num_emails != 1 else ''}")
            email_context = gmail.format_emails_for_llm(emails)
            system_prompt += f"\n\n[CONTEXT FROM RECENT EMAILS]:\n{email_context}\nUse the above email context to answer the user's questions about recent emails, messages, or senders."
        else:
            sources_used.append("Email — no recent messages")

    # 3. Provider routing
    if provider == "claude-sonnet-4-6":
        yield from _ask_claude(
            messages=messages,
            web_enabled=web_enabled,
            system_prompt=system_prompt,
            sources_used=sources_used
        )
    elif provider == "gpt-4o":
        yield from _ask_openai_compatible(
            provider_name="OpenAI",
            model="gpt-4o",
            api_key_name="OPENAI_API_KEY",
            base_url=None,
            messages=messages,
            web_enabled=web_enabled,
            system_prompt=system_prompt,
            sources_used=sources_used
        )
    elif provider == "grok-2-latest":
        yield from _ask_openai_compatible(
            provider_name="Grok",
            model="grok-2-latest",
            api_key_name="XAI_API_KEY",
            base_url="https://api.x.ai/v1",
            messages=messages,
            web_enabled=web_enabled,
            system_prompt=system_prompt,
            sources_used=sources_used
        )
    elif provider in ("gemini-3.8-flash", "gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"):
        actual_model = "gemini-3.8-flash" if provider in ("gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash") else provider
        yield from _ask_openai_compatible(
            provider_name="Gemini",
            model=actual_model,
            api_key_name="GEMINI_API_KEY",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            messages=messages,
            web_enabled=web_enabled,
            system_prompt=system_prompt,
            sources_used=sources_used
        )
    else:
        yield f"⚠️ Unknown provider: '{provider}'."

    # 4. Sources used footer
    if sources_used:
        yield f"\n\n---\n**Sources used:** {', '.join(sources_used)}"
    else:
        yield "\n\n---\n**Sources used:** None (model knowledge)"
