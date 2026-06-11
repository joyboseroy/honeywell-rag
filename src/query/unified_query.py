"""
query/unified_query.py
The main query engine — search metadata index, route to correct lane, fetch content.
All four stages:
  1. Metadata index search (1-14ms)
  2. Query routing (<1ms)
  3. Targeted content fetch (3ms–1s depending on source)
  4. LLM answer generation (600ms–3s)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import re
import pickle
import time
import numpy as np
from pathlib import Path
from sklearn.metrics.pairwise import cosine_similarity

from config import UNIFIED_STORE, PDF_INDEX, TOP_K_RESULTS
from query.router import route, explain_route
from query import fetch_pdf, fetch_excel, fetch_sensors
from llm import answer as llm_answer


# ── LOAD INDEX ────────────────────────────────────────────────────────────────

def load_store() -> dict:
    """Load the unified metadata store. Falls back to PDF-only index."""
    if UNIFIED_STORE.exists():
        with open(UNIFIED_STORE,"rb") as f:
            store = pickle.load(f)
        return store
    if PDF_INDEX.exists():
        with open(PDF_INDEX,"rb") as f:
            idx = pickle.load(f)
        print("Note: using PDF-only index. Run build_excel_index.py for full store.")
        return idx
    return {}


def warm(store: dict) -> None:
    """Warm the page cache — call once at startup."""
    records = store.get("records",[])
    fetch_pdf.warm_cache(records)


# ── METADATA SEARCH ────────────────────────────────────────────────────────────

def search_metadata(store: dict, query: str, lane: str = None) -> list:
    """
    Stage 2: search the metadata index.
    Returns top_k records with relevance scores.
    No files are opened at this stage.
    """
    if not store:
        return []

    records = store.get("records",[])
    vec     = store.get("vec")
    mat     = store.get("mat")

    if vec is None or mat is None:
        return []

    # Filter to lane if specified
    lane_type_map = {
        "pdf":    "pdf",
        "excel":  "xlsx",
        "sensor": "db",
    }
    file_type = lane_type_map.get(lane)

    if file_type:
        mask = [i for i, r in enumerate(records) if r.get("file_type") == file_type]
    else:
        mask = list(range(len(records)))

    if not mask:
        return []

    q_vec  = vec.transform([query])
    scores = cosine_similarity(q_vec, mat).flatten()

    # Keyword boost: records whose keywords match query terms score higher
    q_lower = query.lower()
    boosted = []
    for i in mask:
        rec    = records[i]
        kw_hit = sum(
            1 for kw in rec.get("keywords",[])
            if kw.lower() in q_lower and len(kw) > 3
        )
        boosted.append((scores[i] + kw_hit * 0.05, i))

    top = sorted(boosted, reverse=True)[:TOP_K_RESULTS]

    results = []
    for score, i in top:
        if score > 0.02:
            rec = records[i].copy()
            rec["relevance_score"] = round(float(score), 3)
            results.append(rec)

    return results


# ── LANGUAGE FILTER ────────────────────────────────────────────────────────────

def _prefer_english(results: list) -> list:
    """
    For PDF results: prefer English docs over French/Italian variants.
    Falls back to non-English if no English version found.
    """
    LANG_SUFFIXES = ["-fra","-ita","-deu","-esp"]
    en_results = [
        r for r in results
        if r.get("file_type") == "pdf" and
        not any(suf in r.get("filename","").lower() for suf in LANG_SUFFIXES)
    ]
    other_results = [r for r in results if r not in en_results]

    if en_results:
        return en_results + other_results
    return results


# ── VERSION CHECK ──────────────────────────────────────────────────────────────

def _check_version(results: list, query: str) -> list:
    """
    Warn if user asked about a specific version that differs from current.
    Attaches a warning string to affected records.
    """
    ver_match = re.search(
        r'v(?:ersion\s*)?(\d+[\.\d]*)|issue\s*(\d+)|rev\s*([a-z\d]+)',
        query, re.I
    )
    if not ver_match:
        return results

    req_ver = ver_match.group(0).lower()
    for rec in results:
        cur = rec.get("product_version","").lower()
        doc = rec.get("doc_version","").lower()
        if req_ver not in cur and req_ver not in doc:
            rec["version_warning"] = (
                f"You asked about '{ver_match.group(0)}' but current "
                f"{rec.get('product','')} version is {rec.get('product_version','')} "
                f"({rec.get('doc_version','')} dated {rec.get('doc_date','')})"
            )
    return results


# ── MAIN QUERY FUNCTION ────────────────────────────────────────────────────────

def run_query(question: str, store: dict, verbose: bool = True) -> dict:
    """
    Full four-stage pipeline.
    Returns dict with answer, sources, latency breakdown, warnings.
    """
    if not store:
        return {
            "question": question,
            "answer":   "No index loaded. Run the ingestion scripts first.",
            "sources":  [],
            "latency":  {},
        }

    t0 = time.time()

    # Stage 1: routing
    lanes = route(question)
    if verbose:
        print(f"\nQ: {question}")
        print(f"   Routing: {lanes}")
        print(f"   ({explain_route(question)})")

    # Stage 2: metadata index search — one search per lane, top results across all
    all_matched = []
    for lane in lanes:
        matched = search_metadata(store, question, lane=lane)
        all_matched.extend(matched)

    # Deduplicate, sort by score
    seen = set()
    deduped = []
    for r in sorted(all_matched, key=lambda x: x.get("relevance_score",0), reverse=True):
        doc_id = r.get("doc_id","")
        if doc_id not in seen:
            seen.add(doc_id)
            deduped.append(r)

    # Apply language preference and version check
    deduped = _prefer_english(deduped)
    deduped = _check_version(deduped, question)

    t1 = time.time()

    if verbose:
        print(f"   Index search: {(t1-t0)*1000:.0f}ms → {len(deduped)} records")
        for r in deduped[:4]:
            vw = " ⚠ "+r.get("version_warning","")[:40] if r.get("version_warning") else ""
            print(f"     [{r['relevance_score']}] {r.get('title','')[:50]} "
                  f"({r.get('product_version','')}) {r.get('file_type','')}{vw}")

    # Stage 3: targeted content fetch
    chunks = []
    pdf_done = excel_done = sensor_done = False

    for rec in deduped[:5]:
        ft = rec.get("file_type","")

        if ft == "pdf":
            chunk = fetch_pdf.fetch(rec, question)
            chunks.append(chunk)

        elif ft == "xlsx" and not excel_done:
            chunk = fetch_excel.fetch(rec, question)
            chunks.append(chunk)
            excel_done = True

        elif ft == "db" and not sensor_done:
            chunk = fetch_sensors.fetch(question)
            chunks.append(chunk)
            sensor_done = True



    # Sensor lane always queries DB directly
    if "sensor" in lanes and not sensor_done:
        chunk = fetch_sensors.fetch(question)
        chunks.append(chunk)

    t2 = time.time()

    if verbose:
        print(f"   Content fetch: {(t2-t1)*1000:.0f}ms | {len(chunks)} sources")

    # Stage 4: LLM answer
    answer_text = llm_answer(question, chunks, verbose=verbose)
    t3 = time.time()

    # Collect warnings
    warnings = [r["version_warning"] for r in deduped if r.get("version_warning")]

    result = {
        "question": question,
        "answer":   answer_text,
        "sources":  [c.get("source","") for c in chunks],
        "warnings": warnings,
        "latency": {
            "index_ms": int((t1-t0)*1000),
            "fetch_ms": int((t2-t1)*1000),
            "llm_ms":   int((t3-t2)*1000),
            "total_ms": int((t3-t0)*1000),
        },
    }

    if verbose:
        print(f"\nA: {answer_text[:600]}")
        if warnings:
            for w in warnings:
                print(f"   ⚠  {w}")
        lat = result["latency"]
        print(f"\n   Latency: index={lat['index_ms']}ms "
              f"fetch={lat['fetch_ms']}ms "
              f"llm={lat['llm_ms']}ms "
              f"TOTAL={lat['total_ms']}ms")
        print(f"   Sources: {' | '.join(result['sources'])}")
        print("-"*70)

    return result
