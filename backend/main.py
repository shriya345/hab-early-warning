"""FastAPI entry point for the Karnataka HAB early-warning prototype."""

import os
from datetime import date, datetime
from pathlib import Path
import sys
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.curated_catalog import (  # noqa: E402
    FEATURED_KARNATAKA_WATER_BODIES,
)
from backend.water_bodies import (  # noqa: E402
    InvalidWaterBodyQuery,
    KarnatakaWaterBodyService,
    SOURCE_URL,
    WaterBodyNotFound,
    WaterBodySourceUnavailable,
)
from backend.services.environment import EnvironmentService  # noqa: E402
from backend.services.historical_prediction import run_historical_prediction  # noqa: E402
from backend.services.live_coastal import LiveCoastalService  # noqa: E402
from backend.services.historical_data import HistoricalDataError, HistoricalDataService  # noqa: E402
from backend.services.demo_analysis import DemoAnalysisError, run_demo_analysis  # noqa: E402
from backend.services.model_inputs import ModelInputService  # noqa: E402
from backend.services.model_validation import ModelValidationService  # noqa: E402
from backend.services.prediction import PredictionService  # noqa: E402
from backend.services.satellite import SatelliteService, SatelliteSourceUnavailable  # noqa: E402

MODEL_DIR = Path(os.getenv("HAB_MODEL_DIR", REPO_ROOT / "models"))
ENV_CSV = Path(os.getenv(
    "HAB_ENV_CSV",
    REPO_ROOT / "data/environmental/processed/environmental_lstm_ready.csv",
))
SUPPORTED_LAKES = {
    "vembanad": {
        "lake_id": "vembanad",
        "name": "Vembanad Lake",
        "state": "Kerala",
        "latitude": 9.6,
        "longitude": 76.4,
        "supported": True,
        "model_supported": True,
        "model_validation_status": "validated_prototype",
        "model_version": "Vembanad CNN/LSTM prototype",
        "model_domain": "Vembanad 2024 dataset",
        "label_basis": "chlorophyll-a threshold proxy; not confirmed toxic-HAB observations",
        "model_validation_note": "In-domain research prototype only; target labels are chlorophyll-a threshold proxies.",
        "confirmed_toxic_hab_labels": False,
    }
}

app = FastAPI(title="HAB Early-Warning API", version="0.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
predictor = None
water_body_service = KarnatakaWaterBodyService()
satellite_service = SatelliteService()
environment_service = EnvironmentService()
historical_data_service = HistoricalDataService()
live_coastal_service = LiveCoastalService()
model_input_service = ModelInputService(environment_service, satellite_service)
prediction_service = PredictionService()
model_validation_service = ModelValidationService()


def get_predictor():
    global predictor
    if predictor is None:
        # Keep catalog and weather routes usable in lightweight deployments
        # that have not installed the optional TensorFlow/OpenCV model stack.
        try:
            from src.inference.bloom_predictor import BloomRiskPredictor
        except ModuleNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Vembanad model inference is unavailable because its Python dependencies "
                    "are not installed. Install the project requirements to enable this research route."
                ),
            ) from exc

        predictor = BloomRiskPredictor(str(MODEL_DIR))
    return predictor


def load_environment() -> pd.DataFrame:
    if not ENV_CSV.exists():
        raise HTTPException(status_code=503, detail=f"Environmental dataset not found: {ENV_CSV}")
    frame = pd.read_csv(ENV_CSV, parse_dates=["date"]).sort_values("date")
    return frame


@app.get("/")
def root():
    return {"status": "online", "service": "HAB Early-Warning API"}


@app.get("/data/coverage")
def data_coverage():
    frame = load_environment()
    return {
        "environmental_coverage": {
            "start": frame.date.min().date().isoformat(),
            "end": frame.date.max().date().isoformat(),
        },
        "note": "Chlorophyll-a and water temperature are historical. Current-date predictions are not supported.",
    }


@app.get("/lakes")
def list_lakes():
    """Return model-domain metadata without public coordinates."""
    return {
        "items": [public_model_lake(lake) for lake in SUPPORTED_LAKES.values()],
        "total": len(SUPPORTED_LAKES),
    }


def public_model_lake(lake: dict) -> dict:
    """Keep model-domain coordinates in the backend."""
    return {key: value for key, value in lake.items() if key not in {"latitude", "longitude"}}


@app.get("/water-bodies/search")
def search_water_bodies(q: str, limit: int = 25, offset: int = 0):
    """Search named records across the official Karnataka K-GIS layer."""
    try:
        page = water_body_service.search_page(q, limit, offset)
    except InvalidWaterBodyQuery as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WaterBodySourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    public_items = [public_water_body(model_validation_service.apply(item)) for item in page["items"]]
    return {
        "items": public_items,
        "next_offset": page["next_offset"],
        "has_more": page["has_more"],
        "region": "Karnataka",
        "catalog_source": "Karnataka GIS (K-GIS) Tank Ownership layer",
        "catalog_note": (
            "Search covers named records in the official K-GIS Karnataka water-body layer, "
            "including small urban lakes. Catalogue membership is not model validation."
        ),
        "model_validation_note": "Karnataka catalogue records require water-body-specific data and model validation before a probability can be shown.",
        "message": None if public_items else "Water body not found in the Karnataka catalogue.",
    }


def public_water_body(record: dict) -> dict:
    """Keep map geometry out of search results and summary metadata."""
    return {
        key: value
        for key, value in record.items()
        if key not in {"latitude", "longitude", "boundary"}
    }


def resolve_water_body_or_404(water_body_id: str) -> dict:
    identifier = water_body_id.strip().upper()
    try:
        return model_validation_service.apply(water_body_service.get(identifier))
    except WaterBodyNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WaterBodySourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def water_body_coverage_record(record: dict) -> dict:
    environment = environment_service.coverage(record)
    feature_date = (environment.get("model_window") or {}).get("end_date")
    satellite = satellite_service.coverage(record, feature_date=feature_date)
    return prediction_service.status(record, satellite, environment)


@app.get("/water-bodies/{water_body_id}/coverage")
def water_body_coverage(water_body_id: str):
    """Report current source coverage and model-input gaps for a catalogue ID."""
    return water_body_coverage_record(resolve_water_body_or_404(water_body_id))


@app.get("/water-bodies/{water_body_id}/satellite/preview")
def water_body_satellite_preview(water_body_id: str):
    """Return an on-demand RGB satellite preview, never a model prediction input."""
    record = resolve_water_body_or_404(water_body_id)
    try:
        image_bytes, observation_date = satellite_service.preview(record)
    except SatelliteSourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=21600",
            "X-Satellite-Observation-Date": observation_date,
            "X-Satellite-Source": "Copernicus Sentinel-2 L2A",
        },
    )


@app.get("/live-stations/kochi")
def kochi_live_readings():
    return live_coastal_service.snapshot()


@app.post("/historical-predictions/vembanad")
def historical_vembanad_prediction():
    try:
        return run_historical_prediction(get_predictor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Archived model execution failed ({type(exc).__name__}).") from exc


@app.get("/water-bodies/{water_body_id}/historical")
def water_body_historical(water_body_id: str):
    """Expose downloaded real-data context without changing prediction readiness."""
    record = resolve_water_body_or_404(water_body_id)
    try:
        return historical_data_service.snapshot(record["id"])
    except HistoricalDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/water-bodies/{water_body_id}/historical/true-color")
def water_body_historical_true_color(water_body_id: str):
    record = resolve_water_body_or_404(water_body_id)
    try:
        content = historical_data_service.true_color_png(record["id"])
    except HistoricalDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if content is None:
        raise HTTPException(status_code=404, detail="No historical satellite image is stored for this water body.")
    return Response(content=content, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=3600"})


@app.get("/water-bodies/{water_body_id}/historical/analysis")
def water_body_historical_analysis(water_body_id: str):
    """Analyze saved dated pixels and weather; never return a bloom prediction."""
    record = resolve_water_body_or_404(water_body_id)
    try:
        result = historical_data_service.analyze(record["id"])
    except HistoricalDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="No historical snapshot is stored for this water body.")
    return result


@app.get("/water-bodies/{water_body_id}/historical/raster")
def water_body_historical_raster(water_body_id: str):
    record = resolve_water_body_or_404(water_body_id)
    try:
        path = historical_data_service.raster_path(record["id"])
    except HistoricalDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if path is None:
        raise HTTPException(status_code=404, detail="No historical satellite raster is stored for this water body.")
    return FileResponse(path, media_type="image/tiff", filename=f"{record['id']}_B2_B3_B4_B8_raw_dn.tif")


@app.get("/water-bodies/{water_body_id}/prediction")
def water_body_prediction_status(
    water_body_id: str,
    mode: Literal["live", "demo"] = "live",
    feature_date: date | None = None,
):
    """Keep live gates intact; run synthetic inference only by explicit demo mode."""
    record = resolve_water_body_or_404(water_body_id)
    if mode == "demo":
        day = feature_date or datetime.now(ZoneInfo("Asia/Kolkata")).date()
        if day > datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise HTTPException(status_code=422, detail="Demo feature date cannot be in the future.")
        try:
            return run_demo_analysis(record, day, get_predictor())
        except DemoAnalysisError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"The saved CNN/LSTM model could not load ({type(exc).__name__}).",
            ) from exc
    environment = environment_service.coverage(record)
    feature_date = (environment.get("model_window") or {}).get("end_date")
    satellite = satellite_service.coverage(record, feature_date=feature_date)
    model_inputs = model_input_service.prepare(record, satellite, environment)
    result = prediction_service.predict_if_ready(
        record,
        satellite,
        environment,
        model_inputs=model_inputs,
        predictor_factory=get_predictor,
    )
    result["mode"] = "live"
    result["simulated"] = False
    return result


@app.get("/water-bodies/{water_body_id}")
def water_body_detail(water_body_id: str):
    """Resolve a Karnataka catalogue ID to administrative metadata and boundary."""
    record = resolve_water_body_or_404(water_body_id)
    return {
        "water_body": public_water_body(record),
        "map_view": {
            "center": {
                "latitude": record["latitude"],
                "longitude": record["longitude"],
            } if record["location_resolved"] else None,
            "boundary": record["boundary"],
            "source_url": SOURCE_URL,
        },
        "location": {
            "state": record["state"],
            "district": record["district"],
            "taluk": record["taluk"],
            "village": record["village"],
            "location_resolved": record["location_resolved"],
            "boundary_available": record["boundary_available"],
        },
        "model_status": {
            "status": record["model_validation_status"],
            "validated_for_water_body": record["model_supported"],
            "model_version": record.get("model_version"),
            "note": record.get("model_validation_note"),
        },
        "data_status": "catalogue_location_available" if record["location_resolved"] else "location_unavailable",
        "source": "Karnataka GIS (K-GIS) Tank Ownership layer",
    }


@app.get("/lakes/catalog")
def search_lake_catalog(q: str, limit: int = 25):
    """Legacy route alias for the statewide named K-GIS inventory."""
    try:
        items = water_body_service.search(q, limit)
    except InvalidWaterBodyQuery as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except WaterBodySourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "items": [public_water_body(model_validation_service.apply(item)) for item in items],
        "available": True,
        "total_matches": len(items),
        "region": "Karnataka",
        "catalog_source": "Karnataka GIS (K-GIS) Tank Ownership layer",
        "message": None if items else "Water body not found in the Karnataka catalogue.",
    }


@app.get("/lakes/catalog/status")
def lake_catalog_status():
    """Report live statewide source size and the featured examples count."""
    try:
        total = water_body_service.count_named()
    except WaterBodySourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "available": True,
        "region": "Karnataka",
        "source": "Karnataka GIS (K-GIS) Tank Ownership layer",
        "source_named_records": total,
        "featured_examples": len(FEATURED_KARNATAKA_WATER_BODIES),
        "message": (
            f"K-GIS catalogue online · {total:,} named records · "
            f"{len(FEATURED_KARNATAKA_WATER_BODIES)} featured examples"
        ),
        "note": (
            "Only named K-GIS records are searchable. The featured examples include small "
            "urban lakes; catalogue inclusion does not imply model validation."
        ),
    }


@app.get("/lakes/{lake_id}")
def get_lake(lake_id: str):
    """Return metadata for a supported lake; polygon support is an extension point."""
    lake = SUPPORTED_LAKES.get(lake_id.casefold())
    if lake is None:
        raise HTTPException(status_code=404, detail="This lake is not in the curated supported list.")
    return {**public_model_lake(lake), "boundary": None}
