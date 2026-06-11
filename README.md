# Enterprise RAG System

A metadata-first retrieval system for building automation that answers natural language questions across three incompatible data sources: PDF technical documentation, operational Excel files with cryptic column names, and live IoT sensor readings.

Built as a demo to show that enterprise RAG does not require a single vector store. Each data source needs a different retrieval mechanism. This system unifies them behind a single query interface.

**Core principle:** the index answers "which document?" The document answers "what does it say?" These are two different problems, with two different mechanisms.

---

## What it does

Ask a natural language question. The system routes it to the right data source, fetches only the relevant content, and generates a cited answer.

```
Ask: What is the maximum number of devices per SLC loop on AFP-3030?
A:   318 devices per SLC loop.
     Source: AFP-3030 Intelligent Fire Alarm Control Panel | Rev G | page 1
     Latency: index=5ms fetch=193ms llm=1219ms TOTAL=1438ms

Ask: Are there any CO2 alerts in Bangalore?
A:   Yes. S0044 | Honeywell Bangalore Campus Floor 3 | avg=594ppm max=1180ppm | 3 alerts
     Source: honeywell_sensors.db (live)
     Latency: index=2ms fetch=83ms llm=1453ms TOTAL=1539ms

Ask: Show me buildings where availability is below 98 percent?
A:   ATL-HQ has average availability of 97.43%, below the 98% threshold.
     Source: Rpt_FA_v3_FINAL_USE_THIS.xlsx :: Bld_Smry_Agg
     Latency: index=2ms fetch=376ms llm=935ms TOTAL=1314ms
```

---

## Why metadata-first

Standard chunk RAG embeds raw document content. At scale this produces:
- Version confusion: v4.0 chunk sits next to v4.2 chunk, no version awareness
- Excel failure beyond 50 columns: standard parsers cannot handle merged headers and cryptic column names
- 10-15 second latency: cold loading of full files on every query
- Sensor data is invisible: you cannot embed a temperature reading

This system instead:
- Embeds only a plain-English summary per document (the metadata record)
- Keeps raw content in the original source, fetched on demand
- Maintains a version registry that pre-filters retrieval before semantic search runs
- Routes sensor queries to SQL, never to the vector index
- Uses a page cache so PDF fetch after startup is 3-15ms

Index size: 54 records, 28 KB. Compare to naive chunk RAG: hundreds of chunks, several MB of raw text.

---

## Architecture

```
DATA SOURCES
  PDFs (55 Honeywell BA manuals)
  Excel files (57-72 cols, cryptic names, messy structure)
  IoT sensor DB (120 sensors, 80,760 readings)
         |
INGESTION (offline, once per document)
  PDF pipeline:    PyMuPDF extraction -> metadata record -> embed summary only
  Excel pipeline:  Read 12 rows -> infer column semantics -> classify domain -> embed summary
  Sensor pipeline: Register sensor group metadata -> SQL at runtime
         |
UNIFIED METADATA STORE (54 records, 28 KB TF-IDF matrix)
  Version registry: pre-filters before semantic search
  Page cache: all PDF pages in memory after startup, 3-15ms fetch
         |
QUERY TIME
  Natural language query
  -> Query router (<1ms regex intent classification)
  -> Metadata index search (1-14ms cosine similarity)
  -> Targeted fetch: PDF pages | Excel rows | Sensor SQL
  -> Groq llama-3.1-8b-instant (600ms-3s)
  -> Answer with source citation
```

---

## Folder structure

```
honeywell-rag/
├── demo.py                      single entry point for all queries
├── demo_interactive.py          interactive mode, loads once, stays warm
├── requirements.txt
├── .env.example
│
├── data/
│   ├── pdfs/                    copy your Honeywell PDF files here
│   ├── excel/                   Excel files (generated + your own)
│   └── sensors/                 honeywell_sensors.db (generated)
│
├── index/                       generated at runtime, not committed
│   ├── metadata_index.pkl
│   └── unified_metadata_store.pkl
│
└── src/
    ├── config.py                all paths and LLM settings
    ├── llm.py                   Groq -> Ollama fallback chain
    │
    ├── ingestion/
    │   ├── simulate_data.py     generates sensor DB and clean Excel files
    │   ├── make_messy_excels.py generates 3 realistic messy Excel files (57-72 cols)
    │   ├── build_pdf_index.py   builds metadata_index.pkl from PDFs
    │   └── build_excel_index.py builds unified_metadata_store.pkl
    │
    └── query/
        ├── router.py            intent classification (<1ms)
        ├── fetch_pdf.py         page cache and targeted PDF fetch
        ├── fetch_excel.py       semantic row fetch from Excel
        ├── fetch_sensors.py     SQL queries against sensor DB
        └── unified_query.py     four-stage pipeline: search, route, fetch, LLM
```

---

## Setup

```bash
# 1. Clone
git clone https://github.com/joyboseroy/honeywell-rag
cd honeywell-rag

# 2. Install dependencies
pip install -r requirements.txt --break-system-packages

# 3. Set your Groq API key (free at console.groq.com, no credit card)
export GROQ_API_KEY=your_key_here

# 4. Copy your Honeywell PDF files into data/pdfs/
cp /path/to/your/pdfs/*.pdf data/pdfs/

# 5. Run full setup (generates simulated data, builds index)
python3 demo.py --setup

# 6. Check everything is working
python3 demo.py --status
```

---

## Running

```bash
# Interactive mode: loads once, stays warm, ask anything
python3 demo_interactive.py

# Run the 5 prepared demo queries then go interactive
python3 demo_interactive.py --demo

# Single query (reloads each time)
python3 demo.py "What is the maximum devices per SLC loop AFP-3030?"

# Rebuild index after adding new PDFs or Excel files
python3 demo.py --rebuild
```

**Confirmed working queries**

PDF documentation:
```
What is the maximum number of devices per SLC loop on AFP-3030?
What is the operating temperature range of the Advanced Controller?
What communication protocols does AFP-3030 support for BMS integration?
How many SLC loops can the AFP-3030 support?
What Australian standards does the AFP-3030 comply with?
What is the wallbus address range for RS-WMB sensors?
```

IoT sensor DB:
```
Are there any CO2 alerts in Bangalore?
What is the HVAC power consumption across all buildings?
Are there any active fire alarms right now?
```

Operational Excel:
```
Show me buildings where availability is below 98 percent?
What is the total OPEX across all buildings?
How many assets are active versus faulty in Atlanta?
Which equipment has the most fault events this year?
How many critical assets are there in Singapore?
```

---

## LLM backends

**Groq (default)**
- Fast: 600ms-3s responses
- Free: 14,400 requests/day, no credit card needed
- Requires internet and GROQ_API_KEY from console.groq.com

**Ollama (fallback, fully offline)**
- Runs locally, no API key, no internet required
- Slow on CPU: 5-15s for qwen2.5:7b
- Start: `ollama serve`
- Models: `qwen2.5:7b` (best quality), `mistral`, `tinyllama` (fastest)
- Force Ollama: `USE_OLLAMA=1 python3 demo_interactive.py`

**Retrieval-only (last resort)**
- No LLM: returns raw retrieved content directly
- Still demonstrates routing, index search, page fetch, source citation
- Activates automatically if both Groq and Ollama are unavailable

To switch models, edit `src/config.py`:
```python
GROQ_MODEL   = "llama-3.1-8b-instant"    # or "llama-3.3-70b-versatile"
OLLAMA_MODEL = "qwen2.5:7b"              # or "mistral" or "tinyllama"
```

One line change. Rest of the architecture unchanged.

---

## Known limitations

**PDF fetch latency cold:** opening a large PDF takes 1-4 seconds on first access. Page cache fixes this after startup (3-15ms warm). Production fix: Redis with page-level keys.

**Excel row matching:** queries that do not use words appearing literally in row values fall back to sample rows. Production fix: pre-materialise row summaries at ingestion, store in PostgreSQL.

**Sensor context contention:** sensor DB data can be crowded out of the LLM context window by PDF and Excel content when multiple sources match. Production fix: dedicated context slot for sensor data on sensor-routed queries.

**key_specs hand-authored:** critical numbers (318 devices per SLC, -25 to 60C) are manually written for 13 known documents. Production fix: LLM extracts key_specs at ingestion time automatically.

**Language filtering partial:** French and Italian TC300 variants can outscore the English guide. Production fix: langdetect at ingestion + multilingual-e5-large embedding model.

**TF-IDF not multilingual:** French query will not match English metadata summary. Production fix: replace TfidfVectorizer with SentenceTransformer('intfloat/multilingual-e5-large'), one line change.

---

## Production roadmap

**Phase 1 (1-2 months)**
- Replace TF-IDF with multilingual-e5-large embedding model
- Auto-extract key_specs via LLM at ingestion
- Redis page cache
- FastAPI REST wrapper for Forge.AI integration
- langdetect for language handling

**Phase 2 (3-6 months)**
- ChromaDB or Weaviate for persistent vector storage
- PostgreSQL and TimescaleDB for sensor data
- Pre-materialised row summaries for Excel performance
- Role-based access control with Azure AD
- Full audit log to SIEM

**Phase 3 (6-12 months)**
- Kafka for real-time sensor stream ingestion
- Apache Spark for nightly Excel batch processing
- FalkorDB knowledge graph for schema catalogue
- Pinecone or Azure AI Search for million-scale vector search
- On-premise LLM option for government and fire safety contracts

Architecture is identical at all three phases. Infrastructure scales up. Query logic, version registry, access control, and answer synthesis remain unchanged.

---

## About

Built by Dr. Joy Bose
- GitHub: github.com/joyboseroy
- Email: joyboseroy@gmail.com
- LinkedIn: linkedin.com/in/joyboseroy
