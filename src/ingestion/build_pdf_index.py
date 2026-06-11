"""
ingestion/build_pdf_index.py
Reads all PDFs from data/pdfs/ and builds the metadata index.
Saves to index/metadata_index.pkl

Run from project root:
  python3 src/ingestion/build_pdf_index.py
  python3 src/ingestion/build_pdf_index.py --rebuild   (force rebuild)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pickle, re, hashlib, time
import numpy as np
from pathlib import Path
from datetime import datetime
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from config import PDF_DIR, PDF_INDEX, INDEX_DIR, ensure_dirs

# ── DOCUMENT REGISTRY ─────────────────────────────────────────────────────────
# Known documents get rich hand-authored metadata.
# Unknown documents are auto-registered from filename + first pages.
# In production: LLM writes this record at ingestion time automatically.

KNOWN_DOCS = {
    "hon-ba-bms-en-tc201256-uk0yr0516e.pdf": {
        "title": "IQ4 Web User Guide", "product": "IQ4",
        "product_version": "3.50", "doc_version": "Issue 5", "doc_date": "2018-06-19",
        "status": "current", "supersedes": [],
        "topics": ["web interface","controller","login","alarms","time schedules","TCP/IP","BEMS"],
        "key_specs": {"firmware":"v3.50","protocols":["HTTP","HTTPS","TCP/IP"]},
        "section_map": [
            {"section":"3","title":"Overview of IQ4 Web Interface","pages":[9,14]},
            {"section":"4","title":"Using the IQ4 Web Interface","pages":[15,30]},
        ],
        "keywords": ["IQ4","controller","web browser","login","occupation times","alarm log"],
    },
    "hon-ba-bms-32344442-a.pdf": {
        "title": "RS-WMB RD-WMB Room Display Installation Instructions",
        "product": "RS-WMB", "product_version": "1.02.2",
        "doc_version": "REV A", "doc_date": "2019-01-21",
        "status": "current", "supersedes": [],
        "topics": ["installation","wiring","wallbus","address","CO2","temperature","humidity"],
        "key_specs": {"wallbus_max_current":"50mA","address_range":"2-15","operating_temp":"-10 to +45C"},
        "section_map": [{"section":"3","title":"Installation","pages":[1,7]}],
        "keywords": ["RS-WMB","RD-WMB","wallbus","address switch","CO2","temperature"],
    },
    "hon-ba-bms-advanced-controller-mountin-instructions-31-00553-03.pdf": {
        "title": "Advanced Controller Mounting Instructions",
        "product": "Advanced Controller", "product_version": "31-00553-03",
        "doc_version": "Rev 04-26", "doc_date": "2026-04-01",
        "status": "current", "supersedes": ["31-00553-02","31-00553-01"],
        "topics": ["mounting","DIN rail","wall mounting","wiring","antenna","WiFi","power supply"],
        "key_specs": {
            "operating_voltage_ac":"24VAC +/-20%", "operating_voltage_dc":"24VDC +/-20%",
            "operating_temp":"-25 to 60C", "storage_temp":"-28.9 to 70C",
            "humidity":"5-95% RH non-condensing", "protection":"IP20",
            "certifications":"UL, CE, BACnet BTL, FCC, RCM",
        },
        "section_map": [
            {"section":"5","title":"Mounting on DIN Rail","pages":[3,4]},
            {"section":"6","title":"Mounting on Wall using Screws","pages":[4,5]},
        ],
        "keywords": ["N-ADV","DIN rail","red clip","antenna","24VAC","BACnet","touch flake"],
    },
    "hon-ba-fire-doc-02-159-afp-3030au-datasheet.pdf": {
        "title": "AFP-3030 Intelligent Fire Alarm Control Panel",
        "product": "AFP-3030", "product_version": "Rev G",
        "doc_version": "DOC-02-159 Rev G", "doc_date": "2025-12-01",
        "status": "current", "supersedes": ["DOC-02-159 Rev F"],
        "topics": ["fire alarm","SLC loop","FlashScan","ONYX sensing","voice evacuation",
                   "networking","BACnet","Modbus"],
        "key_specs": {
            "max_slc_loops": 10, "max_devices_per_slc": 318,
            "max_detectors_per_slc": 159, "max_network_nodes": 200,
            "standards": ["AS7240.2:2018","AS7240.4:2018"],
        },
        "section_map": [
            {"section":"features","title":"Features","pages":[1,2]},
            {"section":"specs","title":"Specifications","pages":[7,8]},
        ],
        "keywords": ["AFP-3030","FlashScan","ONYX","SLC","fire alarm","BACnet","Modbus",
                     "NOTI-FIRE-NET","318","drift compensation"],
    },
    "hon-ba-bms-tc300-thermostat-bacnet-integration-guide-31-00646-05.pdf": {
        "title": "TC300 Commercial Thermostat BACnet Integration Guide",
        "product": "TC300", "product_version": "31-00646-05",
        "doc_version": "Rev 05", "doc_date": "2025-01-01",
        "status": "current", "supersedes": ["31-00646-04","31-00646-03"],
        "topics": ["BACnet","integration","object types","MS/TP","IP","commissioning"],
        "key_specs": {
            "protocols": ["BACnet MS/TP","BACnet IP"], "bacnet_standard": "ASHRAE 135",
            "supported_object_types": "AI, AO, AV, BI, BO, BV, MSV",
            "mstp_baud_rates": "9600, 19200, 38400, 76800",
            "bacnet_ip_port": "47808 (default)",
        },
        "section_map": [],
        "keywords": ["TC300","BACnet","MS/TP","BACnet IP","PICS","ASHRAE 135","object types"],
    },
    "hon-ba-bms-tc300-thermostat-user-guide-31-00644-05.pdf": {
        "title": "TC300 Commercial Thermostat User and Configuration Guide",
        "product": "TC300", "product_version": "31-00644-05",
        "doc_version": "Rev 11-25", "doc_date": "2025-11-01",
        "status": "current", "supersedes": ["31-00644-04"],
        "topics": ["configuration","setpoint","schedule","fan control","display","wiring"],
        "key_specs": {"display":"2.4in capacitive touch TFT","max_DO_current":"4A","operating_voltage":"24VAC/VDC"},
        "section_map": [],
        "keywords": ["TC300","thermostat","setpoint","schedule","fan","wiring","digital output"],
    },
    "hbt-BMS-Brochure-HoneywellRemoteBuildingManager-01-00322.pdf": {
        "title": "Honeywell Remote Building Manager",
        "product": "Remote Building Manager", "product_version": "2022",
        "doc_version": "01-00322", "doc_date": "2022-07-01",
        "status": "current", "supersedes": [],
        "topics": ["cloud BMS","subscription","gateway","BACnet","remote monitoring","Forge"],
        "key_specs": {"subscriptions":["Mini 50pts","Midi 2500pts","Maxi 5000pts"]},
        "section_map": [],
        "keywords": ["Remote Building Manager","cloud","BMS","gateway","Forge","Mini","Midi","Maxi"],
    },
    "hon-ba-fire-i56-3500-203c-fcm-1-ausn-installation-manual.pdf": {
        "title": "FCM-1-AUS Supervised Control Module Installation",
        "product": "FCM-1", "product_version": "I56-3500-203C",
        "doc_version": "NO-460-004", "doc_date": "2019-01-01",
        "status": "current", "supersedes": [],
        "topics": ["installation","wiring","NAC","notification appliances","speaker","FlashScan"],
        "key_specs": {"operating_voltage":"15-32VDC","external_supply_nac":"24VDC","speaker_max":"70.7V RMS 50W"},
        "section_map": [],
        "keywords": ["FCM-1","control module","NAC","speaker","audio","SLC"],
    },
    "hon-ba-bms-tc300-thermostat-installation-instruction-31-00642-05.pdf": {
        "title": "TC300 Thermostat Installation Instructions",
        "product": "TC300", "product_version": "31-00642-05",
        "doc_version": "Rev 05", "doc_date": "2025-01-01",
        "status": "current", "supersedes": [],
        "topics": ["installation","wiring","mounting","terminal","power"],
        "key_specs": {"operating_voltage":"24VAC/VDC"},
        "section_map": [],
        "keywords": ["TC300","installation","wiring","mounting","terminal"],
    },
    "hon-ba-bms-tr50-iaq-sensor-user-guide-31-00567m-03.pdf": {
        "title": "TR50 IAQ Sensor User Guide",
        "product": "TR50", "product_version": "31-00567M-03",
        "doc_version": "Rev 03", "doc_date": "2023-01-01",
        "status": "current", "supersedes": [],
        "topics": ["IAQ","CO2","temperature","humidity","VOC","BACnet","Modbus"],
        "key_specs": {"sensors":["CO2","temperature","humidity","VOC"]},
        "section_map": [],
        "keywords": ["TR50","IAQ","CO2","air quality","VOC","sensor"],
    },
    "hon-ba-bms-io-modules-panelbus-driver-guide-31-00591-03.pdf": {
        "title": "IO Modules PanelBus Driver Guide",
        "product": "IO Modules", "product_version": "31-00591-03",
        "doc_version": "Rev 03", "doc_date": "2023-01-01",
        "status": "current", "supersedes": [],
        "topics": ["IO modules","PanelBus","driver","digital input","digital output","wiring"],
        "key_specs": {},
        "section_map": [],
        "keywords": ["IO module","PanelBus","digital","analogue","wiring","driver"],
    },
    "hon-ba-fire-doc-01-031-i-afp-3030-aus-installation-manual.pdf": {
        "title": "AFP-3030 Fire Alarm Control Panel Installation Manual",
        "product": "AFP-3030", "product_version": "DOC-01-031",
        "doc_version": "DOC-01-031", "doc_date": "2024-01-01",
        "status": "current", "supersedes": [],
        "topics": ["installation","wiring","commissioning","SLC","NAC","programming","BACnet","Modbus"],
        "key_specs": {"max_slc_loops":10,"max_devices_per_slc":318,"bms_protocols":"BACnet, Modbus, OnyxWorks","network_nodes":200},
        "section_map": [],
        "keywords": ["AFP-3030","installation","wiring","commissioning","SLC","NAC"],
    },
    "hon-ba-hsc-domonial-en-po-e.pdf": {
        "title": "DOMONIAL Wireless Alarm System",
        "product": "DOMONIAL", "product_version": "2015",
        "doc_version": "HSFI-DOMONIAL-08-EN", "doc_date": "2015-11-01",
        "status": "current", "supersedes": [],
        "topics": ["wireless alarm","PIR","door contact","smoke detector","keyfob","GSM","PSTN"],
        "key_specs": {"communicators":["PSTN","GSM/GPRS","Ethernet"]},
        "section_map": [],
        "keywords": ["DOMONIAL","wireless","PIR","alarm","keyfob","GSM"],
    },
}

VERSION_PATTERNS = {
    "IQ4":                  r"\biq.?4\b",
    "RS-WMB":               r"\brs.?wmb\b|\brd.?wmb\b|\bwmb\b",
    "TC300":                r"\btc.?300\b|thermostat",
    "AFP-3030":             r"\bafp.?3030\b|\bfire.panel\b|\bfire.alarm\b",
    "Advanced Controller":  r"\badvanced.controller\b|\bn.adv\b",
    "Remote Building Manager": r"\bremote.building\b|\brbm\b",
    "TR50":                 r"\btr.?50\b|\biaq\b|\bair.quality\b",
    "FCM-1":                r"\bfcm.?1\b|\bcontrol.module\b",
    "IO Modules":           r"\bio.module\b|\bpanelbus\b",
    "DOMONIAL":             r"\bdomonial\b|\bwireless.alarm\b",
}

LANGUAGE_SUFFIXES = ["-fra","-ita","-deu","-esp","-nl","fra-","ita-"]


def auto_register(pdf_path: Path) -> dict:
    """Auto-generate a metadata record for unknown PDFs."""
    try:
        import fitz
        doc  = fitz.open(str(pdf_path))
        text = " ".join(doc[i].get_text()[:300] for i in range(min(3, len(doc))))
        doc.close()
    except Exception:
        text = ""

    name  = pdf_path.stem.lower()
    parts = re.split(r"[-_]", name)

    product = "Unknown"
    for kw in ["afp","iq4","tc300","wmb","tr50","fcm","fmm","domonial","remote","acm","gfp","ifp","evac"]:
        if any(kw in p for p in parts):
            product = kw.upper()
            break

    lang = "en"
    for suf in LANGUAGE_SUFFIXES:
        if suf in name:
            lang = suf.strip("-")
            break

    topics = []
    for kw, topic in [("fire","fire alarm"),("bms","building management"),
                      ("install","installation"),("user","user guide"),
                      ("bacnet","BACnet"),("modbus","Modbus"),
                      ("data","datasheet"),("config","configuration"),
                      ("cibse","CIBSE report"),("evac","evacuation")]:
        if kw in name or kw in text.lower():
            topics.append(topic)

    return {
        "title":           pdf_path.stem.replace("-"," ").replace("_"," ")[:80],
        "product":         product,
        "product_version": "unknown",
        "doc_version":     "unknown",
        "doc_date":        "unknown",
        "language":        lang,
        "status":          "current",
        "supersedes":      [],
        "topics":          topics or ["building automation"],
        "key_specs":       {},
        "section_map":     [],
        "keywords":        [p for p in parts if len(p) > 2][:10],
    }


def build_index_text(meta: dict) -> str:
    parts = [
        meta.get("title",""),
        f"Product: {meta.get('product','')}",
        f"Version: {meta.get('product_version','')}",
        f"Language: {meta.get('language','en')}",
        f"Topics: {', '.join(meta.get('topics',[]))}",
        f"Keywords: {', '.join(meta.get('keywords',[]))}",
    ]
    specs = meta.get("key_specs",{})
    if specs:
        parts.append("Specs: " + "; ".join(f"{k}={v}" for k,v in list(specs.items())[:6]))
    parts.append(
        f"{meta['title']} for {meta['product']} version {meta['product_version']}. "
        f"Covers: {', '.join(meta.get('topics',[])[:6])}."
    )
    return " | ".join(p for p in parts if p.strip())


def build(rebuild: bool = False) -> dict:
    ensure_dirs()

    if PDF_INDEX.exists() and not rebuild:
        with open(PDF_INDEX,"rb") as f:
            idx = pickle.load(f)
        print(f"Loaded existing PDF index: {len(idx['records'])} records")
        return idx

    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDFs found in {PDF_DIR}")
        print(f"Copy your PDF files to: {PDF_DIR}")
        return {}

    print(f"Building PDF index from {len(pdf_files)} PDFs...")
    records = []

    for pdf_path in pdf_files:
        fname = pdf_path.name
        # Strip "(1)" duplicates — treat as same doc
        clean_fname = re.sub(r"\s*\(1\)", "", fname)
        meta = KNOWN_DOCS.get(fname) or KNOWN_DOCS.get(clean_fname)

        if meta is None:
            meta = auto_register(pdf_path)
            tag = "auto"
        else:
            tag = "known"
            if "language" not in meta:
                meta["language"] = "en"

        rec = {
            **meta,
            "doc_id":        hashlib.md5(fname.encode()).hexdigest()[:12],
            "filename":      fname,
            "filepath":      str(pdf_path),
            "file_type":     "pdf",
            "fetch_strategy":"pdf_pages",
            "fetch_params":  {"filepath": str(pdf_path),
                              "section_map": meta.get("section_map",[])},
            "indexed_at":    datetime.now().isoformat(),
        }
        rec["index_text"] = build_index_text(meta)
        records.append(rec)
        print(f"  [{tag}] {meta['title'][:55]}")

    index_texts = [r["index_text"] for r in records]
    vec = TfidfVectorizer(ngram_range=(1,2), max_features=8000, sublinear_tf=True)
    mat = vec.fit_transform(index_texts)

    idx = {"records": records, "vec": vec, "mat": mat}
    with open(PDF_INDEX,"wb") as f:
        pickle.dump(idx, f)

    print(f"\nPDF index saved: {PDF_INDEX.name}")
    print(f"  {len(records)} records | matrix {mat.shape} | {mat.data.nbytes/1024:.0f} KB")
    return idx


if __name__ == "__main__":
    rebuild = "--rebuild" in sys.argv
    build(rebuild=rebuild)
