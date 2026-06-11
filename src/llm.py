"""
llm.py — all LLM calls go through here.

Priority:
  1. Groq  (GROQ_API_KEY set)   → llama-3.1-8b-instant, cloud, ~1s
  2. Ollama (localhost:11434)   → qwen2.5:7b, local, ~10s on CPU
  3. Retrieval-only fallback    → returns raw context, no LLM prose

Switch models by changing GROQ_MODEL or OLLAMA_MODEL in config.py.
To force Ollama even if Groq key is set: USE_OLLAMA=1 python3 demo.py
"""

import os
import json
import time
import urllib.request
from typing import Optional

from config import (
    GROQ_MODEL, GROQ_TEMPERATURE, GROQ_MAX_TOKENS,
    OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TEMPERATURE,
    OLLAMA_MAX_TOKENS, OLLAMA_TIMEOUT,
)

SYSTEM_PROMPT = (
    "You are a Honeywell Building Automation technical assistant. "
    "Answer questions using ONLY the provided context. "
    "Always cite the document name, version, and page number. "
    "If the answer is not in the context, say so clearly. "
    "Be precise and technical. Do not calculate numbers — they are pre-computed."
)


# ── LLM SELECTION ─────────────────────────────────────────────────────────────

def get_llm_backend() -> str:
    """
    Determine which LLM backend to use.
    Returns: 'groq' | 'ollama' | 'none'
    """
    # Force Ollama override
    if os.environ.get("USE_OLLAMA", "").strip() == "1":
        if _ollama_available():
            return "ollama"
        print("[LLM] USE_OLLAMA=1 set but Ollama not reachable at localhost:11434")
        return "none"

    # Try Groq first
    if os.environ.get("GROQ_API_KEY", "").strip():
        return "groq"

    # Fall back to Ollama
    if _ollama_available():
        return "ollama"

    return "none"


def _ollama_available() -> bool:
    """Check if Ollama is running and has the required model."""
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read())
            models = [m["name"] for m in data.get("models", [])]
            # Accept qwen2.5:7b or any qwen2.5 variant
            has_model = any(
                OLLAMA_MODEL.split(":")[0] in m for m in models
            )
            if not has_model:
                print(f"[LLM] Ollama running but '{OLLAMA_MODEL}' not found. "
                      f"Available: {models}. "
                      f"Run: ollama pull {OLLAMA_MODEL}")
            return has_model
    except Exception:
        return False


# ── MAIN ANSWER FUNCTION ──────────────────────────────────────────────────────

def answer(question: str, chunks: list, verbose: bool = True) -> str:
    """
    Generate an answer from retrieved chunks.
    Tries Groq → Ollama → retrieval-only in that order.

    chunks: list of dicts with keys: lane, source, version, page, text/content, score
    """
    backend = get_llm_backend()

    if verbose:
        print(f"   LLM backend: {backend}")

    if backend == "groq":
        return _groq_answer(question, chunks)
    elif backend == "ollama":
        return _ollama_answer(question, chunks)
    else:
        print("   [LLM] No backend available — returning retrieved context only")
        return _synthesise(question, chunks)


# ── GROQ ──────────────────────────────────────────────────────────────────────

def _groq_answer(question: str, chunks: list) -> str:
    try:
        from groq import Groq
        context = _build_context(chunks)
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}"},
            ],
            max_tokens=GROQ_MAX_TOKENS,
            temperature=GROQ_TEMPERATURE,
        )
        return resp.choices[0].message.content.strip()
    except ImportError:
        print("   [Groq] groq package not installed: pip install groq --break-system-packages")
        return _try_ollama_fallback(question, chunks)
    except Exception as e:
        print(f"   [Groq] Error: {e} — falling back to Ollama")
        return _try_ollama_fallback(question, chunks)


def _try_ollama_fallback(question: str, chunks: list) -> str:
    """Called when Groq fails mid-session."""
    if _ollama_available():
        print("   [Fallback] Switching to Ollama")
        return _ollama_answer(question, chunks)
    print("   [Fallback] Ollama not available — returning retrieved context")
    return _synthesise(question, chunks)


# ── OLLAMA ────────────────────────────────────────────────────────────────────

def _ollama_answer(question: str, chunks: list) -> str:
    context = _build_context(chunks)
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {question}\n\n"
        f"ANSWER:"
    )
    payload = json.dumps({
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": OLLAMA_TEMPERATURE,
            "num_predict": OLLAMA_MAX_TOKENS,
        },
    }).encode()
    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as r:
            data = json.loads(r.read())
            return data.get("response", "").strip()
    except Exception as e:
        print(f"   [Ollama] Error: {e}")
        return _synthesise(question, chunks)


# ── RETRIEVAL-ONLY FALLBACK ───────────────────────────────────────────────────

def _synthesise(question: str, chunks: list) -> str:
    """
    No LLM available — return the raw retrieved content clearly formatted.
    Still useful: shows exactly what was retrieved and from where.
    """
    if not chunks:
        return "No relevant information found."
    lines = [
        "No LLM available — showing retrieved context directly:\n",
        f"Sources: {', '.join(c.get('source', '') for c in chunks[:3])}\n",
    ]
    for c in chunks[:3]:
        lines.append(
            f"[{c.get('lane', '')} | {c.get('source', '')} "
            f"| score {c.get('score', '')}]"
        )
        content = c.get("text", c.get("content", ""))
        lines.append(str(content)[:600])
        lines.append("")
    return "\n".join(lines)


# ── SHARED CONTEXT BUILDER ────────────────────────────────────────────────────

def _build_context(chunks: list) -> str:
    parts = []
    for c in chunks[:4]:
        source  = c.get("source", "Unknown")
        version = c.get("version", "")
        page    = c.get("page", "")
        content = c.get("text", c.get("content", ""))
        header  = f"[{source}"
        if version: header += f" | version {version}"
        if page:    header += f" | page {page}"
        header += "]"
        parts.append(f"{header}\n{str(content)[:1200]}")
    return "\n\n---\n\n".join(parts)


# ── STATUS REPORT ─────────────────────────────────────────────────────────────

def llm_status() -> dict:
    """Print and return which backends are available."""
    groq_key   = bool(os.environ.get("GROQ_API_KEY", "").strip())
    ollama_ok  = _ollama_available()
    backend    = get_llm_backend()

    status = {
        "groq_key_set":    groq_key,
        "ollama_available": ollama_ok,
        "active_backend":  backend,
        "groq_model":      GROQ_MODEL,
        "ollama_model":    OLLAMA_MODEL,
    }

    print(f"  Groq API key:    {'✓ set' if groq_key else '✗ not set'}")
    print(f"  Ollama running:  {'✓ available' if ollama_ok else '✗ not reachable'}")
    print(f"  Active backend:  {backend}")
    if backend == "groq":
        print(f"  Model:           {GROQ_MODEL} (~1–3s responses)")
    elif backend == "ollama":
        print(f"  Model:           {OLLAMA_MODEL} (~5–15s on CPU)")
    else:
        print(f"  Model:           none — retrieval-only mode")
    return status
