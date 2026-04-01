from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


VENUE_COORDS = {
    "Wankhede Stadium": (18.9388, 72.8258),
    "MA Chidambaram Stadium": (13.0628, 80.2796),
    "M. Chinnaswamy Stadium": (12.9788, 77.5996),
    "Eden Gardens": (22.5646, 88.3433),
    "Arun Jaitley Stadium": (28.6379, 77.2438),
    "Narendra Modi Stadium": (23.0918, 72.5970),
    "Rajiv Gandhi International Stadium": (17.4065, 78.5506),
    "Punjab Cricket Association Stadium": (30.6900, 76.7373),
    "Sawai Mansingh Stadium": (26.8946, 75.8032),
    "Ekana Cricket Stadium": (26.8126, 80.9975),
    "HPCA Stadium": (32.1940, 76.3321),
    "Brabourne Stadium": (18.9290, 72.8205),
    "DY Patil Stadium": (19.0326, 73.0297),
    "Maharashtra Cricket Association Stadium": (18.6749, 73.7065),
}


def _read_json(url: str, timeout_sec: int = 8) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"User-Agent": "ipl-predictor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _load_snapshot() -> dict[str, Any]:
    snapshot_path = Path(__file__).resolve().parents[1] / "data" / "processed" / "live_weather_snapshot.json"
    if not snapshot_path.exists():
        return {}
    try:
        return json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _dew_risk_from_weather(temp_c: float, rh: float) -> float:
    # Higher humidity + lower night temperature usually increases dew chance.
    temp_score = max(0.0, min(1.0, (28.0 - temp_c) / 12.0))
    humid_score = max(0.0, min(1.0, (rh - 45.0) / 45.0))
    return max(0.0, min(1.0, 0.4 * temp_score + 0.6 * humid_score))


def fetch_live_weather_context(venue: str) -> dict[str, float]:
    snapshot = _load_snapshot()
    snapshot_row = snapshot.get(venue)
    if isinstance(snapshot_row, dict):
        try:
            return {
                "temperature_c": float(snapshot_row.get("temperature_c", 28.0)),
                "relative_humidity": float(snapshot_row.get("relative_humidity", 60.0)),
                "wind_kph": float(snapshot_row.get("wind_kph", 12.0)),
                "dew_risk": float(snapshot_row.get("dew_risk", 0.5)),
            }
        except Exception:
            pass

    lat_lon = VENUE_COORDS.get(venue)
    if not lat_lon:
        return {
            "temperature_c": 28.0,
            "relative_humidity": 60.0,
            "wind_kph": 12.0,
            "dew_risk": 0.5,
        }

    lat, lon = lat_lon
    query = urllib.parse.urlencode(
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            "timezone": "auto",
        }
    )
    url = f"https://api.open-meteo.com/v1/forecast?{query}"
    data = _read_json(url, timeout_sec=2)

    if not data or "current" not in data:
        return {
            "temperature_c": 28.0,
            "relative_humidity": 60.0,
            "wind_kph": 12.0,
            "dew_risk": 0.5,
        }

    current = data.get("current", {})
    temp_c = float(current.get("temperature_2m", 28.0))
    rh = float(current.get("relative_humidity_2m", 60.0))
    wind = float(current.get("wind_speed_10m", 12.0))

    return {
        "temperature_c": temp_c,
        "relative_humidity": rh,
        "wind_kph": wind,
        "dew_risk": _dew_risk_from_weather(temp_c, rh),
    }
