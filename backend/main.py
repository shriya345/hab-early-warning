
import sys
sys.path.insert(0, "/content/hab-early-warning")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from datetime import datetime, timedelta
import os

from src.inference.bloom_predictor import BloomRiskPredictor


MODEL_DIR = "/content/hab-early-warning/models"

ENV_CSV = (
    "/content/hab-early-warning/data/environmental/"
    "processed/environmental_lstm_ready.csv"
)

SENTINEL_TIF = (
    "/content/drive/MyDrive/"
    "hab_early_warning_sentinel_clean/"
    "2024-12-23.tif"
)


app = FastAPI(
    title="HAB Early-Warning API",
    version="0.1.0"
)

# Development CORS configuration.
# This will be restricted appropriately before deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Load models once when the API starts.
predictor = BloomRiskPredictor(MODEL_DIR)


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "HAB Early-Warning API"
    }


@app.get("/predict/vembanad")
def predict_vembanad():

    # Verify required files.
    if not os.path.exists(ENV_CSV):
        raise HTTPException(
            status_code=500,
            detail="Environmental dataset not found."
        )

    if not os.path.exists(SENTINEL_TIF):
        raise HTTPException(
            status_code=500,
            detail="Sentinel-2 TIFF not found."
        )

    # Load environmental data.
    env_df = pd.read_csv(
        ENV_CSV,
        parse_dates=["date"]
    )

    start_date = pd.Timestamp("2024-12-17")
    prediction_date = pd.Timestamp("2024-12-23")

    # Exact seven-day LSTM window.
    window = env_df[
        (env_df["date"] >= start_date) &
        (env_df["date"] <= prediction_date)
    ].copy()

    window = (
        window
        .sort_values("date")
        .reset_index(drop=True)
    )

    if len(window) != 7:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Expected 7 environmental rows, "
                f"got {len(window)}."
            )
        )

    # REAL CNN + LSTM inference.
    result = predictor.predict(
        sentinel_tif_path=SENTINEL_TIF,
        environmental_7day_df=window
    )

    horizon = result["forecast_horizon_days"]

    forecast_date = (
        prediction_date +
        timedelta(days=int(horizon))
    )

    return {
        "lake": "Vembanad Lake",
        "prediction_date":
            prediction_date.strftime("%Y-%m-%d"),

        "forecast_date":
            forecast_date.strftime("%Y-%m-%d"),

        "cnn_probability":
            result["cnn_probability"],

        "lstm_probability":
            result["lstm_probability"],

        "fusion_probability":
            result["bloom_risk_probability"],

        "bloom_risk_percent":
            result["bloom_risk_percent"],

        "satellite_acquisition_date":
            "2024-12-23",

        "environmental_window": {
            "start": "2024-12-17",
            "end": "2024-12-23"
        },

        "forecast_horizon_days":
            horizon
    }
