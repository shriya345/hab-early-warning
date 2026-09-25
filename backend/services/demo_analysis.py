"""Explicit synthetic-input demonstration of the saved CNN/LSTM/fusion model."""

from __future__ import annotations

from datetime import date, timedelta
import hashlib
import math
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

from backend.services.prediction import FORECAST_HORIZON_DAYS, MODEL_FEATURES


DEMO_DISCLAIMER = (
    "Simulated demonstration using synthetic inputs. This is not a real "
    "prediction for this water body."
)
RASTER_BANDS = ("B2", "B3", "B4", "B8")


class DemoAnalysisError(RuntimeError):
    """Saved model or its required input contract cannot run the demonstration."""


def generate_demo_inputs(water_body_id: str, feature_date: date) -> tuple[pd.DataFrame, np.ndarray]:
    """Create deterministic *synthetic* model-shaped inputs from ID and date only.

    K-GIS geometry and coordinates are deliberately excluded from generation;
    they remain real map context and are not represented as observations.
    The raster is four-band uint16 DN in the trained B2/B3/B4/B8 order.
    BloomRiskPredictor applies the existing resize, /10000, and [0, 2] clip.
    """
    seed = int.from_bytes(
        hashlib.sha256(f"algaewatch-demo-v1:{water_body_id}:{feature_date.isoformat()}".encode()).digest()[:8],
        "big",
    )
    rng = np.random.default_rng(seed)
    days = [feature_date - timedelta(days=6 - index) for index in range(7)]
    frame = pd.DataFrame({
        "date": days,
        "chlorophyll_a": np.round(rng.uniform(1.2, 5.5, 7), 4),
        "sst": np.round(rng.uniform(27.0, 32.0, 7), 4),
        "rainfall": np.round(rng.uniform(0.0, 16.0, 7), 4),
        "wind_speed": np.round(rng.uniform(0.7, 3.1, 7), 4),
        "chlorophyll_imputed": np.zeros(7, dtype=np.uint8),
    })
    # Simple bounded artificial texture; no real Sentinel-2 pixels or lake
    # observations are downloaded, copied, or inferred from location.
    base = np.array([1400, 1900, 1650, 3200], dtype=np.float32)[:, None, None]
    texture = rng.normal(0.0, 240.0, size=(4, 128, 128))
    raster = np.clip(base + texture, 0, 20000).astype(np.uint16)
    return frame, raster


def _validate_saved_contract(predictor) -> None:
    config = predictor.config
    if (
        config.get("environmental_features") != list(MODEL_FEATURES)
        or config.get("lstm_window_days") != 7
        or config.get("cnn_image_size") != 128
        or config.get("cnn_bands") != 4
        or config.get("forecast_horizon_days") != FORECAST_HORIZON_DAYS
        or config.get("cnn_weight") != 0.5
        or config.get("lstm_weight") != 0.5
    ):
        raise DemoAnalysisError(
            "The saved CNN/LSTM configuration does not match the five-feature, "
            "seven-day, four-band, 128-pixel, 50/50 fusion demonstration contract."
        )


def run_demo_analysis(water_body: dict, feature_date: date, predictor) -> dict:
    """Call the existing predictor with a temporary synthetic GeoTIFF."""
    _validate_saved_contract(predictor)
    frame, raster = generate_demo_inputs(str(water_body["id"]), feature_date)
    if list(frame.columns) != ["date", *MODEL_FEATURES] or raster.shape != (4, 128, 128):
        raise DemoAnalysisError("Synthetic inputs do not match the saved model input shape.")
    try:
        import rasterio
        from rasterio.transform import from_origin
    except ModuleNotFoundError as exc:
        raise DemoAnalysisError("Demo analysis requires Rasterio to pass a four-band GeoTIFF to the saved CNN.") from exc

    with tempfile.TemporaryDirectory(prefix="algaewatch-demo-") as directory:
        path = Path(directory) / "synthetic-four-band.tif"
        with rasterio.open(
            path, "w", driver="GTiff", width=128, height=128,
            count=4, dtype="uint16", transform=from_origin(0, 128, 1, 1),
        ) as output:
            output.write(raster)
            for band_number, name in enumerate(RASTER_BANDS, start=1):
                output.set_band_description(band_number, name)
        try:
            result = predictor.predict(
                sentinel_tif_path=str(path), environmental_7day_df=frame,
            )
        except Exception as exc:
            raise DemoAnalysisError(
                "The saved CNN/LSTM could not process the synthetic four-band raster "
                f"and seven-day feature window ({type(exc).__name__})."
            ) from exc

    try:
        cnn = float(result["cnn_probability"])
        lstm = float(result["lstm_probability"])
        fused = float(result["bloom_risk_probability"])
        horizon = int(result["forecast_horizon_days"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DemoAnalysisError("The saved predictor returned an incompatible result contract.") from exc
    if (
        not all(math.isfinite(value) and 0 <= value <= 1 for value in (cnn, lstm, fused))
        or not math.isclose(fused, (cnn + lstm) / 2, rel_tol=0, abs_tol=1e-6)
        or horizon != FORECAST_HORIZON_DAYS
    ):
        raise DemoAnalysisError("The saved predictor returned an invalid probability, fusion, or forecast horizon.")

    return {
        "mode": "demo",
        "simulated": True,
        "water_body": water_body["name"],
        "water_body_id": water_body["id"],
        "feature_date": feature_date.isoformat(),
        "cnn_probability": cnn,
        "lstm_probability": lstm,
        "fused_probability": fused,
        "horizon_days": horizon,
        "disclaimer": DEMO_DISCLAIMER,
        "demo_inputs": {
            "label": "Synthetic / demonstration only",
            "environmental_features": list(MODEL_FEATURES),
            "environmental_rows": [
                {"date": row["date"].isoformat(), **{
                    feature: float(row[feature]) for feature in MODEL_FEATURES
                }}
                for row in frame.to_dict("records")
            ],
            "satellite_raster": {
                "label": "Synthetic / demonstration only",
                "bands": list(RASTER_BANDS),
                "shape": [4, 128, 128],
                "dtype": "uint16",
                "preprocessing": "existing model: 128×128 resize, divide by 10000, clip to [0, 2]",
            },
        },
    }
