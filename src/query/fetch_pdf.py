"""
query/fetch_pdf.py
Handles all PDF content retrieval.

Two stages:
  1. warm_cache()  — load all PDFs into memory at startup (~5s once)
  2. fetch()       — return relevant pages for a query (3-15ms, cache warm)

The cache is a module-level dict — persists across queries in the same process.
"""

import re
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from config import PDF_CHUNK_CHARS, MAX_PDF_PAGES

# Module-level page cache: {filepath: {page_num: text}}
_PAGE_CACHE: dict = {}


def warm_cache(records: list) -> None:
    """
    Load all PDF pages into memory at startup.
    Call this once before running queries.
    After this, fetch() is 3-15ms for any PDF.
    """
    try:
        import fitz
    except ImportError:
        print("  [PDF] pymupdf not installed: pip install pymupdf --break-system-packages")
        return

    pdf_records = [r for r in records if r.get("file_type") == "pdf"]
    loaded = 0
    for rec in pdf_records:
        fp = rec.get("filepath","")
        if fp and Path(fp).exists() and fp not in _PAGE_CACHE:
            _get_pages(fp)
            loaded += 1
    print(f"  Page cache: {loaded} PDFs loaded ({len(_PAGE_CACHE)} total in cache)")


def _get_pages(filepath: str) -> dict:
    """Load and cache all pages of a PDF. Returns {page_num: text}."""
    if filepath in _PAGE_CACHE:
        return _PAGE_CACHE[filepath]
    try:
        import fitz
        doc = fitz.open(filepath)
        pages = {}
        for pn in range(len(doc)):
            text = doc[pn].get_text("text").strip()
            if text:
                pages[pn] = text
        doc.close()
        _PAGE_CACHE[filepath] = pages
    except Exception as e:
        _PAGE_CACHE[filepath] = {}
    return _PAGE_CACHE.get(filepath, {})


def fetch(record: dict, query: str) -> dict:
    """
    Fetch the most relevant pages from a PDF for a given query.
    Returns a dict with source metadata + content.
    """
    filepath    = record.get("filepath","")
    section_map = (record.get("section_map") or
                   record.get("fetch_params",{}).get("section_map",[]))

    if not filepath or not Path(filepath).exists():
        return {
            "lane":    "PDF Documentation",
            "source":  record.get("title",""),
            "version": record.get("product_version",""),
            "score":   record.get("relevance_score",0),
            "text":    f"[File not found: {filepath}]",
        }

    pages   = _get_pages(filepath)
    q_words = set(re.findall(r'\b\w{3,}\b', query.lower()))

    # Score every page by keyword hits
    page_scores = {
        pn: sum(1 for w in q_words if w in text.lower())
        for pn, text in pages.items()
    }

    # Boost pages from section_map that match query topics
    for section in section_map:
        sec_words = set(re.findall(r'\b\w{3,}\b', section.get("title","").lower()))
        if sec_words & q_words:
            for pn in range(section["pages"][0]-1, section["pages"][1]):
                page_scores[pn] = page_scores.get(pn,0) + 10

    # Always boost first 3 pages — specs often appear early in datasheets
    for pn in range(min(3, len(pages))):
        page_scores[pn] = page_scores.get(pn,0) + 2

    best_pages = sorted(page_scores, key=page_scores.get, reverse=True)[:MAX_PDF_PAGES]
    best_pages = sorted(best_pages)  # restore reading order

    parts = []

    # Prepend key_specs so critical numbers always reach the LLM
    specs = record.get("key_specs",{})
    if specs:
        parts.append(
            "KEY SPECIFICATIONS: " +
            "; ".join(f"{k}={v}" for k,v in specs.items())
        )

    for pn in best_pages:
        if pn in pages:
            parts.append(f"[Page {pn+1}]\n{pages[pn][:PDF_CHUNK_CHARS]}")

    return {
        "lane":    "PDF Documentation",
        "source":  record.get("title",""),
        "version": record.get("product_version",""),
        "page":    f"pages {[p+1 for p in best_pages]}",
        "score":   record.get("relevance_score",0),
        "text":    "\n\n".join(parts) if parts else "[No relevant content found]",
    }
