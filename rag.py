import io
import re
import traceback
from typing import List, Tuple, Optional
import pypdf
from logger import log_event

# Stopwords to filter during keyword extraction
STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with", "by", 
    "is", "are", "was", "were", "it", "this", "that", "what", "which", "who",
    "how", "can", "could", "would", "should", "do", "does", "did", "of", "from"
}

def extract_text(file_bytes: bytes, filename: str, max_chars: int = 1_000_000) -> Tuple[str, Optional[str]]:
    """
    Extract text from .txt or .pdf files.
    Returns (extracted_text, warning_or_error_message).
    """
    log_event("RAG_START", f"Extracting text from '{filename}' ({len(file_bytes)} bytes)")
    fname_lower = filename.lower()
    
    try:
        if fname_lower.endswith(".txt"):
            try:
                text = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = file_bytes.decode("latin-1", errors="replace")
                
        elif fname_lower.endswith(".pdf"):
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages_text = []
            for idx, page in enumerate(reader.pages):
                try:
                    ptxt = page.extract_text()
                    if ptxt:
                        pages_text.append(ptxt)
                except Exception as page_err:
                    log_event("RAG_WARN", f"Page {idx} extraction failed in '{filename}': {page_err}", level="warning")
            text = "\n\n".join(pages_text).strip()
            
            if not text:
                msg = f"⚠️ The PDF '{filename}' contains no extractable text (it may be a scanned image)."
                log_event("RAG_WARN", msg, level="warning")
                return "", msg
        else:
            msg = f"⚠️ Unsupported file type for '{filename}'. Only .txt and .pdf are supported."
            log_event("RAG_WARN", msg, level="warning")
            return "", msg

        # Truncate very large files if exceeding threshold
        if len(text) > max_chars:
            log_event("RAG_WARN", f"Document '{filename}' truncated from {len(text)} to {max_chars} chars", level="warning")
            text = text[:max_chars]

        log_event("RAG_SUCCESS", f"Extracted {len(text)} characters from '{filename}'")
        return text, None

    except Exception as exc:
        full_err = f"Exception: {type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
        log_event("RAG_FAILURE", f"Failed extracting text from '{filename}': {full_err}", level="error")
        return "", f"⚠️ Error extracting text from '{filename}': {str(exc)}"

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
    """
    In-memory chunking at 800 characters with 100 character overlap.
    """
    if not text:
        return []
    
    step = max(1, chunk_size - overlap)
    chunks = []
    for start in range(0, len(text), step):
        chunk = text[start:start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
    return chunks

def retrieve_relevant_chunks(query: str, chunks: List[str], top_k: int = 4) -> List[str]:
    """
    Keyword relevance retrieval scoring in-memory chunks without external vector DB.
    """
    if not chunks:
        return []
    if not query.strip():
        return chunks[:top_k]

    # Tokenize query terms
    raw_terms = re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", query.lower())
    terms = [t for t in raw_terms if t not in STOPWORDS]
    if not terms:
        terms = raw_terms if raw_terms else [query.lower()]

    scored_chunks = []
    query_lower = query.lower()

    for idx, chunk in enumerate(chunks):
        chunk_lower = chunk.lower()
        score = 0

        # Term frequency score
        for term in terms:
            count = chunk_lower.count(term)
            score += count * 2

        # Exact phrase bonus
        if query_lower in chunk_lower:
            score += 15

        scored_chunks.append((score, idx, chunk))

    # Sort descending by score
    scored_chunks.sort(key=lambda x: x[0], reverse=True)

    # If any matched with score > 0, return top_k of those
    positive_matches = [chunk for score, _, chunk in scored_chunks if score > 0]
    if positive_matches:
        selected = positive_matches[:top_k]
        log_event("RAG_RETRIEVAL", f"Retrieved {len(selected)} relevant chunks for query: '{query}' (top score: {scored_chunks[0][0]})")
        return selected

    # Fallback to first few chunks if no specific keyword matched
    log_event("RAG_RETRIEVAL", f"No keyword match found for '{query}'; using initial document chunks")
    return chunks[:min(top_k, 2)]
