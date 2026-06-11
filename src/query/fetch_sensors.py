"""
query/fetch_sensors.py
Executes SQL queries against the IoT sensor database.
Handles: temperature, CO2, humidity, HVAC, fire alarms.
All computation is in SQL — LLM never sees raw numbers to calculate.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import re
import sqlite3
from pathlib import Path
from config import DB_PATH

TYPE_MAP = {
    "temperature": "TEMP", "temp": "TEMP", "thermal": "TEMP",
    "co2":         "CO2",  "carbon dioxide": "CO2", "air quality": "CO2",
    "humidity":    "HUM",  "humid": "HUM",
    "occupancy":   "OCC",  "occupied": "OCC",
    "hvac":        "HVAC", "power": "HVAC", "energy": "HVAC",
    "fire":        "FIRE", "alarm": "FIRE", "smoke": "FIRE",
}

BUILDING_MAP = {
    "atlanta":    "Honeywell HQ Atlanta",
    "bangalore":  "Honeywell Bangalore Campus",
    "singapore":  "Honeywell Singapore Tower",
    "bracknell":  "Honeywell UK Bracknell",
    "uk":         "Honeywell UK Bracknell",
}

ALERT_THRESHOLDS = {
    "TEMP":  ("°C",   "alert > 26°C"),
    "CO2":   ("ppm",  "alert > 1000ppm"),
    "HUM":   ("%RH",  "alert > 80%RH"),
    "OCC":   ("count","occupancy count"),
    "HVAC":  ("kW",   "HVAC power draw"),
    "FIRE":  ("binary","LIFE SAFETY — any non-zero is an alarm"),
}


def fetch(query: str, window_hours: int = 168) -> dict:
    """
    Execute a sensor query and return formatted results.
    window_hours: how many hours of history to query (default: last 24h)
    """
    if not DB_PATH.exists():
        return {
            "lane":   "IoT Sensors",
            "source": "honeywell_sensors.db",
            "text":   f"[Sensor DB not found at {DB_PATH}. Run: python3 src/ingestion/simulate_data.py]",
        }

    q_lower = query.lower()

    # Detect sensor type and building from query
    sensor_type = next((v for k,v in TYPE_MAP.items() if k in q_lower), None)
    building    = next((v for k,v in BUILDING_MAP.items() if k in q_lower), None)

    # For fire alarms, always show active alerts
    if sensor_type == "FIRE":
        return _fire_query(window_hours)

    return _general_query(sensor_type, building, window_hours)


def _general_query(sensor_type: str, building: str, window_hours: int) -> dict:
    """General sensor aggregation query."""
    where  = [f"r.timestamp > datetime('now', '-{window_hours} hours')"]
    params = []

    if sensor_type:
        where.append("s.sensor_type = ?")
        params.append(sensor_type)
    if building:
        where.append("s.building = ?")
        params.append(building)

    sql = f"""
        SELECT s.sensor_id, s.building, s.floor, s.sensor_type, s.unit,
               ROUND(AVG(r.value), 2) avg_val,
               ROUND(MIN(r.value), 2) min_val,
               ROUND(MAX(r.value), 2) max_val,
               SUM(r.alert_flag) alerts,
               MAX(r.timestamp) latest
        FROM sensors s
        JOIN readings r ON s.sensor_id = r.sensor_id
        WHERE {' AND '.join(where)}
        GROUP BY s.sensor_id
        ORDER BY alerts DESC, avg_val DESC
        LIMIT 12
    """

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        return {
            "lane":   "IoT Sensors",
            "source": "honeywell_sensors.db",
            "text":   f"[SQL error: {e}]",
        }

    if not rows:
        return {
            "lane":   "IoT Sensors",
            "source": "honeywell_sensors.db",
            "text":   "No sensor data found matching query.",
        }

    stype_label = sensor_type or "all sensor types"
    unit_info   = ALERT_THRESHOLDS.get(sensor_type, ("", ""))[0] if sensor_type else ""
    alert_info  = ALERT_THRESHOLDS.get(sensor_type, ("",""))[1] if sensor_type else ""

    alerts_rows  = [r for r in rows if r["alerts"] > 0]
    normal_rows  = [r for r in rows if r["alerts"] == 0]

    lines = [
        f"Sensor data — {stype_label} | Last {window_hours}h | {len(rows)} sensors",
    ]
    if alert_info:
        lines.append(f"Alert threshold: {alert_info}")

    if alerts_rows:
        lines.append(f"\n⚠  {len(alerts_rows)} ALERT(S):")
        for r in alerts_rows[:4]:
            lines.append(
                f"  {r['sensor_id']} | {r['building']} {r['floor']} | "
                f"avg={r['avg_val']}{unit_info} max={r['max_val']}{unit_info} | "
                f"alerts={r['alerts']} | latest: {r['latest']}"
            )

    lines.append(f"\nNormal ({len(normal_rows)} sensors):")
    for r in normal_rows[:6]:
        lines.append(
            f"  {r['sensor_id']} | {r['building']} {r['floor']} | "
            f"avg={r['avg_val']}{unit_info} | latest: {r['latest']}"
        )

    return {
        "lane":    "IoT Sensors",
        "source":  "honeywell_sensors.db",
        "version": "live",
        "text":    "\n".join(lines),
    }


def _fire_query(window_hours: int) -> dict:
    """Targeted fire alarm query — always shows active alerts first."""
    sql = f"""
        SELECT s.sensor_id, s.building, s.floor, s.zone,
               MAX(r.value) triggered,
               SUM(r.alert_flag) total_alerts,
               MAX(r.timestamp) latest
        FROM sensors s
        JOIN readings r ON s.sensor_id = r.sensor_id
        WHERE s.sensor_type = 'FIRE'
          AND r.timestamp > datetime('now', '-{window_hours} hours')
        GROUP BY s.sensor_id
        ORDER BY total_alerts DESC
        LIMIT 20
    """
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        return {"lane":"IoT Sensors","source":"honeywell_sensors.db","text":f"[SQL error: {e}]"}

    active = [r for r in rows if r["triggered"] > 0]
    lines  = [f"FIRE ALARM STATUS — Last {window_hours}h | LIFE SAFETY"]

    if active:
        lines.append(f"\n🔴  {len(active)} ACTIVE FIRE ALARM(S):")
        for r in active:
            lines.append(
                f"  {r['sensor_id']} | {r['building']} {r['floor']} {r['zone']} | "
                f"latest: {r['latest']}"
            )
    else:
        lines.append("✅  No active fire alarms in the last 24 hours.")

    lines.append(f"\n{len(rows)} fire sensors monitored.")
    return {
        "lane":    "IoT Sensors",
        "source":  "honeywell_sensors.db",
        "version": "live",
        "text":    "\n".join(lines),
    }
