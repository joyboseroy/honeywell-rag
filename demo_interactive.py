#!/usr/bin/env python3
"""
demo_interactive.py
===================
Loads the metadata store and page cache ONCE, then accepts queries interactively.
No reloading between questions — ideal for live demo.

Usage:
  python3 demo_interactive.py          # interactive mode
  python3 demo_interactive.py --demo   # runs the 5 prepared demo queries then goes interactive

Demo queries (in order):
  1. PDF    — AFP-3030 max devices per SLC loop
  2. PDF    — Advanced Controller operating temperature
  3. Sensor — CO2 levels across all buildings
  4. Excel  — Equipment with most fault events
  5. PDF    — AFP-3030 BMS communication protocols
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from config import ensure_dirs
from llm import llm_status
from query.unified_query import load_store, warm, run_query

DEMO_QUERIES = [
    "What is the maximum number of devices per SLC loop on AFP-3030?",
    "What is the operating temperature range of the Advanced Controller?",
    "What is the current CO2 level across all buildings?",
    "Which equipment has the most fault events this year?",
    "What communication protocols does AFP-3030 support for BMS integration?",
]

BANNER = """
======================================================================
  HONEYWELL BA — ENTERPRISE RAG DEMO
  Metadata-First · Three-Lane Retrieval · Groq + Ollama Fallback
======================================================================"""

HELP = """
Commands:
  <question>   — ask anything
  demo         — run the 5 prepared demo queries
  status       — show LLM backend status
  quit / exit  — exit
"""


def main():
    ensure_dirs()

    print(BANNER)

    # ── LLM STATUS ────────────────────────────────────────────────────────────
    print("\nLLM backend:")
    status = llm_status()

    # ── LOAD INDEX ────────────────────────────────────────────────────────────
    print("\nLoading metadata store...")
    store = load_store()

    if not store:
        print("\nNo index found. Run setup first:")
        print("  python3 demo.py --setup")
        sys.exit(1)

    records     = store.get("records", [])
    pdf_count   = sum(1 for r in records if r.get("file_type") == "pdf")
    excel_count = sum(1 for r in records if r.get("file_type") == "xlsx")
    print(f"  {len(records)} records: {pdf_count} PDF + {excel_count} Excel")

    # ── WARM PAGE CACHE ───────────────────────────────────────────────────────
    print("\nWarming page cache...")
    warm(store)
    print("  Ready.\n")

    # ── RUN PREPARED QUERIES IF --demo FLAG ───────────────────────────────────
    run_demo_first = "--demo" in sys.argv
    if run_demo_first:
        print("="*70)
        print("RUNNING 5 PREPARED DEMO QUERIES")
        print("="*70)
        for q in DEMO_QUERIES:
            run_query(q, store, verbose=True)
        print("\n" + "="*70)
        print("PREPARED QUERIES DONE — now in interactive mode")
        print("="*70 + "\n")

    # ── INTERACTIVE LOOP ──────────────────────────────────────────────────────
    print(HELP)

    while True:
        try:
            user_input = input("Ask: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        elif cmd == "status":
            print("\nLLM backend:")
            llm_status()
            print()

        elif cmd == "demo":
            print("="*70)
            print("RUNNING 5 PREPARED DEMO QUERIES")
            print("="*70)
            for q in DEMO_QUERIES:
                run_query(q, store, verbose=True)

        elif cmd == "help":
            print(HELP)

        else:
            run_query(user_input, store, verbose=True)


if __name__ == "__main__":
    main()
