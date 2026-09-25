"""Location-aware environmental coverage and weather context."""

from datetime import datetime, timedelta
import json
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from fastapi import HTTPException
import pandas as pd

from backend.weather_data import get_daily_weather


MODEL_FEATURES = (
    "chlorophyll_a",
    "sst",
    "rainfall",
    "wind_speed",
    "chlorophyll_imputed",
)
WATER_BODY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{2,80}$")
ENVIRONMENT_FEATURE_ORDER = list(MODEL_FEATURES)


class EnvironmentService:
    """Fetches external weather context and reports the model-feature gaps."""

    def __init__(self, weather_provider=None, model_input_dir: str | Path | None = None):
        self.weather_provider = weather_provider or get_daily_weather
        self.model_input_dir = Path(model_input_dir or os.getenv(
            "HAB_ENVIRONMENTAL_MODEL_DIR",
            Path(__file__).resolve().parents[2] / "data/environmental/lakes",
        )).expanduser()

    def model_window(self, water_body: dict) -> tuple[pd.DataFrame | None, dict]:
        """Load a current, explicitly sourced seven-day model feature window.

        A lake data directory contains ``<id>.csv`` and ``<id>.json``. The
        manifest must state the ordered feature contract and affirm that its
        units were checked against the trained model. This prevents weather
        context or undocumented measurements from being silently substituted.
        """
        body_id = str(water_body.get("id") or "")
        unavailable = {
            "available": False,
            "source": None,
            "end_date": None,
            "message": "No verified seven-day environmental model-input file is configured for this water body.",
        }
        if not WATER_BODY_ID_PATTERN.fullmatch(body_id):
            return None, unavailable

        csv_path = self.model_input_dir / f"{body_id}.csv"
        manifest_path = self.model_input_dir / f"{body_id}.json"
        if not csv_path.is_file() or not manifest_path.is_file():
            return None, unavailable

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                str(manifest.get("water_body_id", "")).casefold() != body_id.casefold()
                or manifest.get("feature_order") != ENVIRONMENT_FEATURE_ORDER
                or manifest.get("units_verified_against_training_data") is not True
                or not str(manifest.get("source") or "").strip()
            ):
                return None, {
                    **unavailable,
                    "message": "Environmental input metadata does not verify the lake ID, feature order, source, and training-compatible units.",
                }

            frame = pd.read_csv(csv_path, parse_dates=["date"])
            if "date" not in frame.columns or any(feature not in frame.columns for feature in MODEL_FEATURES):
                return None, {
                    **unavailable,
                    "message": "Environmental input file is missing the date or a required model feature.",
                }
            frame = frame[["date", *MODEL_FEATURES]].sort_values("date").reset_index(drop=True)
            if frame.date.isna().any() or frame.date.duplicated().any():
                return None, {
                    **unavailable,
                    "message": "Environmental input dates are invalid or duplicated.",
                }
            for feature in MODEL_FEATURES:
                frame[feature] = pd.to_numeric(frame[feature], errors="coerce")

            latest = datetime.now(ZoneInfo("Asia/Kolkata")).date()
            for end_index in range(len(frame) - 1, 5, -1):
                window = frame.iloc[end_index - 6 : end_index + 1].copy().reset_index(drop=True)
                dates = window.date.dt.date.tolist()
                if any((right - left).days != 1 for left, right in zip(dates, dates[1:])):
                    continue
                if (latest - dates[-1]).days not in range(0, 6):
                    continue
                values = window.loc[:, list(MODEL_FEATURES)]
                if values.isna().any().any() or not all(
                    math.isfinite(float(value)) for value in values.to_numpy().ravel()
                ):
                    continue
                if not set(window["chlorophyll_imputed"].astype(float)).issubset({0.0, 1.0}):
                    continue
                return window, {
                    "available": True,
                    "source": str(manifest["source"]).strip(),
                    "end_date": dates[-1].isoformat(),
                    "message": "Seven consecutive current days match the declared model feature contract.",
                }
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None, {
                **unavailable,
                "message": "The configured environmental model-input file could not be read or validated.",
            }

        return None, {
            **unavailable,
            "message": "No complete seven-day environmental window is available within the recent-data limit.",
        }

    def coverage(self, water_body: dict) -> dict:
        weather_context = {
            "available": False,
            "source": "Open-Meteo Forecast API",
            "units": {"air_temperature_c": "°C", "rainfall_mm": "mm/day", "wind_speed_ms": "m/s"},
            "rows": [],
            "limitations": [
                "Weather variables are gridded context near the water body, not in-lake measurements.",
                "Air temperature is not lake surface temperature.",
            ],
        }
        location = water_body.get("location") or water_body
        latitude, longitude = location.get("latitude"), location.get("longitude")
        if latitude is None or longitude is None:
            weather_context["message"] = "Weather context unavailable because the catalogue has no usable coordinates."
        else:
            try:
                result = self.weather_provider(
                    latitude=latitude,
                    longitude=longitude,
                    start_date=datetime.now(ZoneInfo("Asia/Kolkata")).date(),
                    days=7,
                )
                # The browser receives weather values but not the source coordinates.
                weather_context.update({
                    "available": bool(result.get("rows")),
                    "source": result.get("source", weather_context["source"]),
                    "timezone": result.get("timezone"),
                    "units": result.get("units", weather_context["units"]),
                    "rows": result.get("rows", []),
                    "limitations": result.get("limitations", weather_context["limitations"]),
                })
                if not weather_context["available"]:
                    weather_context["message"] = "Weather provider returned no daily records for this location."
            except HTTPException as exc:
                weather_context["message"] = str(exc.detail)
            except (KeyError, TypeError, ValueError) as exc:
                weather_context["message"] = f"Weather context unavailable: {exc}"

        _, model_window = self.model_window(water_body)
        model_window_available = model_window["available"]
        model_window_source = model_window.get("source")
        unavailable_use = model_window.get("message") or "No compatible environmental model inputs are configured."
        feature_status = {
            feature: {
                "available": model_window_available,
                "model_compatible": model_window_available,
                "source": model_window_source,
                "use": (
                    f"verified model input from {model_window_source}"
                    if model_window_available
                    else unavailable_use
                ),
            }
            for feature in MODEL_FEATURES
        }
        return {
            "model_features": feature_status,
            "expected_model_features": list(MODEL_FEATURES),
            "model_inputs_complete": model_window_available,
            "model_window": model_window,
            "weather_context": weather_context,
        }
