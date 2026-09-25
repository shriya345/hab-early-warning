"""Read public INCOIS numerical chart series without executing source JavaScript."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import re
import threading
import time

import requests

SOURCES = {
    "chlorophyll_a": ("water_quality_cselgraph.jsp", "Chlorophyll-a", "µg/L", "µg/l"),
    "water_temperature": ("water_quality_selgraph.jsp", "Water Temperature", "°C", "℃"),
}
CACHE = Path(__file__).resolve().parents[2] / "outputs/incois_kochi_live_cache.json"


def parse_series(document, expected_name, expected_unit, now):
    pattern = r"name:\s*'([^']+)'\s*,\s*type:\s*'[^']+'\s*,\s*data:\s*(\[.*?\])\s*,\s*units:\s*'([^']*)'"
    for match in re.finditer(pattern, document, re.S):
        if match[1].strip() != expected_name:
            continue
        if html.unescape(match[3]).strip() != expected_unit:
            raise ValueError("The source measurement units changed.")
        rows = json.loads(match[2])
        clean = {}
        for row in rows:
            if not isinstance(row, list) or len(row) != 2:
                raise ValueError("Invalid source record.")
            stamp, value = row
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in row):
                raise ValueError("Non-numeric source record.")
            if stamp <= 0 or stamp > now.timestamp() * 1000:
                raise ValueError("Invalid or future source timestamp.")
            if stamp in clean and clean[stamp] != value:
                raise ValueError("Conflicting source timestamps.")
            clean[stamp] = value
        if not clean:
            raise ValueError("No observations in the source feed.")
        return [{"time": datetime.fromtimestamp(t / 1000, timezone.utc).isoformat(), "value": v}
                for t, v in sorted(clean.items())]
    raise ValueError("The expected numerical source series was not found.")


class LiveCoastalService:
    def __init__(self, cache_path=CACHE, getter=requests.get):
        self.cache_path = Path(cache_path)
        self.getter = getter
        self.lock = threading.Lock()
        self.last_attempt = 0
        self.data = None
        self.error = None
        try:
            cached = json.loads(self.cache_path.read_text())
            if cached.get("station_id") == "incois-kochi" and set(cached.get("series", {})) == set(SOURCES):
                self.data = cached
        except (OSError, ValueError):
            pass

    def _fetch(self, key, now):
        page, name, unit, raw_unit = SOURCES[key]
        url = f"https://incois.gov.in/site/services/{page}?location=Kochi"
        response = self.getter(url, timeout=(5, 15))
        response.raise_for_status()
        records = parse_series(response.text, name, raw_unit, now)
        times = [datetime.fromisoformat(r["time"]) for r in records]
        return key, {"name": name, "unit": unit, "source_url": url, "records": records,
                     "latest": records[-1], "count": len(records),
                     "gaps_over_60_minutes": sum((b - a).total_seconds() > 3600 for a, b in zip(times, times[1:]))}

    def snapshot(self):
        with self.lock:
            now = datetime.now(timezone.utc)
            if time.monotonic() - self.last_attempt >= 60:
                self.last_attempt = time.monotonic()
                try:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        series = dict(pool.map(lambda k: self._fetch(k, now), SOURCES))
                    self.data = {"station_id": "incois-kochi", "station_name": "Kochi coastal buoy",
                                 "provider": "INCOIS", "retrieved_at": datetime.now(timezone.utc).isoformat(),
                                 "series": series}
                    self.error = None
                    try:
                        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                        temporary = self.cache_path.with_suffix(".tmp")
                        temporary.write_text(json.dumps(self.data))
                        temporary.replace(self.cache_path)
                    except OSError:
                        pass  # Successful live readings remain available in memory.
                except (requests.RequestException, ValueError, TypeError, OverflowError):
                    self.error = "INCOIS could not be refreshed. The source may be unavailable or its format may have changed."
            if self.data is None:
                return {"available": False, "error": self.error, "station_name": "Kochi coastal buoy"}
            result = json.loads(json.dumps(self.data))
            for series in result["series"].values():
                age = max(0, (now - datetime.fromisoformat(series["latest"]["time"])).total_seconds() / 3600)
                series["age_hours"] = round(age, 1)
                series["delayed"] = age > 24
            result.update(available=True, cached=bool(self.error), error=self.error,
                          checked_at=now.isoformat(), refresh_interval_seconds=300,
                          note="Public coastal buoy readings. Observation times are shown separately from retrieval time. These readings do not enable the lake bloom model.")
            return result
