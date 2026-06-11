#!/usr/bin/env python3
"""
demo.py — single entry point for all demo queries.

Usage:
  python3 demo.py                              # run all 5 demo queries
  python3 demo.py "your question here"         # single query
  python3 demo.py --setup                      # run full setup first
  python3 demo.py --status                     # check LLM backend status
  python3 demo.py --rebuild                    # rebuild index from scratch

Environment:
  export GROQ_API_KEY=your_key    → uses Groq (fast, cloud)
  export USE_OLLAMA=1             → forces Ollama (slow, local, offline)
  (neither set)                   → tries Ollama, then retrieval-only

Demo queries:
  1. PDF:    AFP-3030 max devices per SLC loop
  2. PDF:    Advanced Controller operating temperature
  3. Sensor: CO2 levels across all buildings
  4. Excel:  Equipment with most fault events
  5. PDF:    AFP-3030 BMS communication protocols
"""

import sys
import os

# Add src/ to path so imports work from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from config import ensure_dirs, BASE, PDF_DIR, EXCEL_DIR, SENSOR_DIR, INDEX_DIR
from llm import llm_status

DEMO_QUERIES = [
    "What is the maximum number of devices per SLC loop on AFP-3030?",
    "What is the operating temperature range of the Advanced Controller?",
    "What is the current CO2 level across all buildings?",
    "Which equipment has the most fault events this year?",
    "What communication protocols does AFP-3030 support for BMS integration?",
]


def run_setup():
    """Run the full ingestion pipeline."""
    ensure_dirs()
    print("="*60)
    print("SETUP: Running ingestion pipeline")
    print("="*60)

    # Step 1: simulate sensor + clean Excel data
    print("\n[1/3] Generating simulated sensor and Excel data...")
    from ingestion.simulate_data import (
        make_sensor_db, make_asset_register,
        make_maintenance_log, make_energy_report
    )
    make_sensor_db()
    make_asset_register()
    make_maintenance_log()
    make_energy_report()

    # Step 2: make messy Excel files
    print("\n[2/3] Generating messy Excel files...")
    from ingestion.make_messy_excels import make_file1, make_file2, make_file3
    make_file1()
    make_file2()
    make_file3()

    # Step 3: build PDF index
    print("\n[3a/3] Building PDF metadata index...")
    pdf_count = len(list(PDF_DIR.glob("*.pdf")))
    if pdf_count == 0:
        print(f"  No PDFs found in {PDF_DIR}")
        print(f"  Copy your Honeywell PDF files to: {PDF_DIR}")
        print(f"  Then run: python3 demo.py --rebuild")
    else:
        from ingestion.build_pdf_index import build as build_pdf
        build_pdf(rebuild=True)

    # Step 4: build unified store
    print("\n[3b/3] Building unified metadata store (PDF + Excel)...")
    from ingestion.build_excel_index import build as build_excel
    build_excel(rebuild=True)

    print("\nSetup complete.")


def run_demo(questions: list, verbose: bool = True):
    """Load index, warm cache, run queries."""
    from query.unified_query import load_store, warm, run_query

    print("="*70)
    print("HONEYWELL BA — ENTERPRISE RAG DEMO")
    print("="*70)

    print("\nLLM backend:")
    status = llm_status()

    print("\nLoading metadata store...")
    store = load_store()
    if not store:
        print("\nNo index found. Run first:")
        print("  python3 demo.py --setup")
        return

    records = store.get("records",[])
    pdf_count  = sum(1 for r in records if r.get("file_type")=="pdf")
    xl_count   = sum(1 for r in records if r.get("file_type")=="xlsx")
    db_count   = sum(1 for r in records if r.get("file_type")=="db")
    print(f"  {len(records)} records: {pdf_count} PDF + {xl_count} Excel + {db_count} sensor groups")

    print("\nWarming page cache (all PDFs into memory)...")
    warm(store)

    print("\n" + "="*70)
    for q in questions:
        run_query(q, store, verbose=verbose)


def check_status():
    print("="*60)
    print("SYSTEM STATUS")
    print("="*60)

    print("\nDirectories:")
    for label, path in [
        ("PDFs",  PDF_DIR), ("Excel", EXCEL_DIR),
        ("Sensors", SENSOR_DIR), ("Index", INDEX_DIR),
    ]:
        exists = path.exists()
        count  = ""
        if exists:
            if label == "PDFs":
                count = f"({len(list(path.glob('*.pdf')))} PDFs)"
            elif label == "Excel":
                count = f"({len(list(path.glob('*.xlsx')))} xlsx files)"
            elif label == "Sensors":
                db = SENSOR_DIR / "honeywell_sensors.db"
                count = f"({'DB exists' if db.exists() else 'no DB'})"
            elif label == "Index":
                from config import PDF_INDEX, UNIFIED_STORE
                pkls = sum(1 for p in [PDF_INDEX, UNIFIED_STORE] if p.exists())
                count = f"({pkls} index files)"
        status = "✓" if exists else "✗ missing"
        print(f"  {label:10} {status} {path}  {count}")

    print("\nLLM backends:")
    llm_status()


if __name__ == "__main__":
    ensure_dirs()

    if "--status" in sys.argv:
        check_status()

    elif "--setup" in sys.argv:
        run_setup()

    elif "--rebuild" in sys.argv:
        from ingestion.build_pdf_index import build as build_pdf
        from ingestion.build_excel_index import build as build_excel
        build_pdf(rebuild=True)
        build_excel(rebuild=True)

    elif len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        question = " ".join(sys.argv[1:])
        run_demo([question])

    else:
        run_demo(DEMO_QUERIES)
