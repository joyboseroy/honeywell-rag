"""
config.py — central configuration for all paths and LLM settings.
Change BASE to your local folder. Everything else derives from it.

LLM priority:
  1. Groq  (if GROQ_API_KEY is set)          → llama-3.1-8b-instant, ~1s
  2. Ollama (if running on localhost:11434)   → qwen2.5:7b, ~10s on CPU
  3. Retrieval-only fallback                 → shows context, no LLM prose
"""

import os
from pathlib import Path

# ── ROOT ──────────────────────────────────────────────────────────────────────
# Change this one line to move the whole project
BASE = Path("/mnt/c/Users/ebosjoy/Downloads/honeywell-rag")

# ── DATA DIRECTORIES ──────────────────────────────────────────────────────────
DATA_DIR    = BASE / "data"
PDF_DIR     = DATA_DIR / "pdfs"       # drop your .pdf files here
EXCEL_DIR   = DATA_DIR / "excel"      # drop your .xlsx files here
SENSOR_DIR  = DATA_DIR / "sensors"    # honeywell_sensors.db lives here

# ── INDEX DIRECTORY (generated, not committed to git) ─────────────────────────
INDEX_DIR   = BASE / "index"
PDF_INDEX   = INDEX_DIR / "metadata_index.pkl"
UNIFIED_STORE = INDEX_DIR / "unified_metadata_store.pkl"

# ── SENSOR DATABASE ───────────────────────────────────────────────────────────
DB_PATH = SENSOR_DIR / "honeywell_sensors.db"

# ── LLM CONFIGURATION ─────────────────────────────────────────────────────────
# Groq — free tier, fast, requires API key from console.groq.com
GROQ_MODEL          = "llama-3.1-8b-instant"   # fastest, good quality
GROQ_MODEL_HQ       = "llama-3.3-70b-versatile" # higher quality, still free
GROQ_TEMPERATURE    = 0.1
GROQ_MAX_TOKENS     = 600

# Ollama — fully local, no API key, works offline
# Falls back to this automatically if GROQ_API_KEY is not set
OLLAMA_URL          = "http://localhost:11434/api/generate"
OLLAMA_MODEL        = "qwen2.5:7b"     # best quality of locally available models
OLLAMA_MODEL_FAST   = "tinyllama"      # use if qwen2.5 is too slow on your machine
OLLAMA_TEMPERATURE  = 0.1
OLLAMA_MAX_TOKENS   = 600
OLLAMA_TIMEOUT      = 90              # seconds — CPU inference is slow

# ── RETRIEVAL SETTINGS ────────────────────────────────────────────────────────
TOP_K_RESULTS   = 4    # how many metadata records to retrieve
MAX_PDF_PAGES   = 4    # how many pages to fetch per matched PDF
MAX_EXCEL_ROWS  = 20   # how many rows to fetch per matched sheet
PDF_CHUNK_CHARS = 2000 # max characters per page sent to LLM

# ── ENSURE DIRECTORIES EXIST ──────────────────────────────────────────────────
def ensure_dirs():
    for d in [DATA_DIR, PDF_DIR, EXCEL_DIR, SENSOR_DIR, INDEX_DIR]:
        d.mkdir(parents=True, exist_ok=True)
