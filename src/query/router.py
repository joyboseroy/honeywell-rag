"""
query/router.py
Classifies a natural language query into retrieval lanes.
Returns ordered list: which lane to hit first.

No data is touched here — routing is sub-1ms pure regex.
"""

import re

INTENT_RULES = {
    "sensor": (
        r"(temperature|co2|humidity|occupancy|sensor|reading|live|current|now|"
        r"real.?time|trend|last hour|today|co2 level|temp level|active alarm|"
        r"current reading|what is the.*level|how hot|how cold|"
        r"fire alarm|temp alert|co2 alert|any alarm|any alert|any fire|"
        r"hvac power|power consumption|alerts in|alarms in|alarms right)"
    ),
    "excel": (
        r"(asset|maintenance|equipment|cost|energy|report|kwh|carbon|service|"
        r"warranty|technician|work order|fault|status|budget|variance|consumption|"
        r"commissioning|failure|fail|snag|overdue|most fault|test result|"
        r"which equipment|expired|open snag|alarm count|device count|"
        r"show me|find assets|list equipment)"
    ),
    "pdf": (
        r"(how do i|how to|configure|protocol|bacnet|spec|manual|guide|procedure|"
        r"step|wiring|mounting|integration|standard|what is|maximum number|"
        r"address range|operating temp|power requirement|what protocol|how many|"
        r"what voltage|install|connect|set up|commissioning procedure)"
    ),
}


def route(query: str) -> list:
    """
    Returns ordered list of lanes to query.
    e.g. ["excel","sensor","pdf"] means: hit Excel first, then sensor DB, then PDFs.
    """
    q = query.lower()
    scores = {
        lane: len(re.findall(pattern, q))
        for lane, pattern in INTENT_RULES.items()
    }

    # If nothing matched, default to all three with PDF first
    if all(v == 0 for v in scores.values()):
        return ["pdf", "excel", "sensor"]

    return sorted(scores, key=scores.get, reverse=True)


def explain_route(query: str) -> str:
    """Human-readable explanation of routing decision. Used in verbose mode."""
    q = query.lower()
    hits = {}
    for lane, pattern in INTENT_RULES.items():
        matched = re.findall(pattern, q)
        if matched:
            hits[lane] = matched

    if not hits:
        return "No keywords matched — default routing: PDF → Excel → Sensor"

    parts = []
    for lane, matched in hits.items():
        parts.append(f"{lane}: {matched[:3]}")
    return "Routing signals: " + " | ".join(parts)
