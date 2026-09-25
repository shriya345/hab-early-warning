"""Open-Meteo daily weather adapter for any lake centroid."""

from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import HTTPException

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def get_daily_weather(latitude: float, longitude: float, start_date: date, days: int = 7):
    """Fetch daily air/weather context; never label air temperature as lake SST."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise HTTPException(status_code=422, detail="Latitude/longitude are outside valid WGS84 ranges.")
    if not (1 <= days <= 16):
        raise HTTPException(status_code=422, detail="days must be between 1 and 16.")
    end_date = start_date + timedelta(days=days - 1)
    today = datetime.now(timezone.utc).date()
    if end_date < today - timedelta(days=5):
        endpoint = ARCHIVE_URL
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": "temperature_2m_mean,precipitation_sum,wind_speed_10m_max",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
            "timezone": "auto",
        }
        source = "Open-Meteo Historical Weather API (reanalysis)"
    else:
        endpoint = FORECAST_URL
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_mean,precipitation_sum,wind_speed_10m_max",
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "precipitation_unit": "mm",
            "timezone": "auto",
            "past_days": max(0, (today - start_date).days),
            "forecast_days": max(1, (end_date - today).days + 1),
        }
        source = "Open-Meteo Forecast API"

    try:
        response = httpx.get(endpoint, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Weather provider request failed: {exc}") from exc

    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    series = {
        "air_temperature_c": daily.get("temperature_2m_mean") or [],
        "rainfall_mm": daily.get("precipitation_sum") or [],
        "wind_speed_ms": daily.get("wind_speed_10m_max") or [],
    }
    rows = []
    for index, day in enumerate(times):
        if not (start_date.isoformat() <= day <= end_date.isoformat()):
            continue
        rows.append({
            "date": day,
            "air_temperature_c": series["air_temperature_c"][index],
            "rainfall_mm": series["rainfall_mm"][index],
            "wind_speed_ms": series["wind_speed_ms"][index],
        })
    if not rows:
        raise HTTPException(status_code=502, detail="Weather provider returned no daily rows for this location and date range.")
    return {
        "latitude": payload.get("latitude", latitude),
        "longitude": payload.get("longitude", longitude),
        "elevation_m": payload.get("elevation"),
        "timezone": payload.get("timezone"),
        "source": source,
        "units": {"air_temperature_c": "°C", "rainfall_mm": "mm/day", "wind_speed_ms": "m/s"},
        "rows": rows,
        "limitations": [
            "Weather variables represent a gridded location near the lake, not in-lake measurements.",
            "Air temperature is not lake surface temperature.",
        ],
    }
