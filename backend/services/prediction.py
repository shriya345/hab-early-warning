"""Prediction eligibility and water-body response assembly."""

from datetime import timedelta
import math

FORECAST_HORIZON_DAYS = 5
MODEL_FEATURES = ("chlorophyll_a", "sst", "rainfall", "wind_speed", "chlorophyll_imputed")


class PredictionService:
    """Gate generic model inference on lake-specific status and complete inputs."""

    def status(self, water_body: dict, satellite: dict, environment: dict) -> dict:
        missing_inputs = [
            feature
            for feature, status in environment["model_features"].items()
            if not status["available"] or not status["model_compatible"]
        ]
        validated = (
            water_body.get("model_supported") is True
            and water_body.get("model_validation_status") == "validated_prototype"
        )
        model_status = {
            "status": "validated_prototype" if validated else "data_model_validation_required",
            "validated_for_water_body": validated,
            "model_version": water_body.get("model_version", "Vembanad CNN/LSTM prototype"),
            "note": water_body.get(
                "model_validation_note",
                "The available trained model is not validated for this water body.",
            ),
        }
        blocking_conditions = []
        if not validated:
            blocking_conditions.append("water_body_model_validation_required")
        if not satellite.get("available") or not satellite.get("model_compatible"):
            blocking_conditions.append("satellite_imagery_unavailable_or_incompatible")
        if not environment.get("model_inputs_complete"):
            blocking_conditions.append("model_compatible_environmental_inputs_missing")
        if not validated:
            reason = "Prediction is not currently validated for this water body."
        elif not satellite.get("available") or not satellite.get("model_compatible"):
            reason = "Satellite imagery is unavailable or incompatible with the model input contract."
        elif not environment.get("model_inputs_complete"):
            reason = "Environmental data is incomplete for the required seven-day model window."
        else:
            reason = None
        data_status = {
            "status": "prediction_unavailable" if blocking_conditions else "inputs_ready",
            "reason": reason,
            "missing_model_inputs": missing_inputs,
            "blocking_conditions": blocking_conditions,
            "satellite_available": satellite.get("available", False),
            "satellite_scene_metadata_available": satellite.get("scene_metadata_available", False),
            "model_inputs_complete": environment["model_inputs_complete"],
        }
        return {
            "water_body": {
                "id": water_body["id"],
                "name": water_body["name"],
                "state": water_body["state"],
                "district": water_body.get("district"),
                "taluk": water_body.get("taluk"),
            },
            "location": {
                "resolved": water_body.get("location_resolved", False),
                "boundary_available": water_body.get("boundary_available", False),
            },
            "prediction": None,
            "forecast_horizon_days": FORECAST_HORIZON_DAYS,
            "satellite_source": satellite,
            "environment_sources": environment,
            "model_status": model_status,
            "data_status": data_status,
            "provenance": {
                "water_body_catalogue": water_body.get("catalog_source"),
                "weather_context": environment["weather_context"].get("source"),
                "bloom_labels": "Vembanad chlorophyll-threshold proxy; not confirmed toxic-HAB observations",
            },
        }

    def predict_if_ready(
        self,
        water_body: dict,
        satellite: dict,
        environment: dict,
        model_inputs: dict | None = None,
        predictor_factory=None,
    ) -> dict:
        """Run the existing CNN/LSTM only after validation and input gates pass.

        Raster paths and the environmental frame are carried separately in
        ``model_inputs`` so they cannot leak through the public coverage fields.
        Current Karnataka records lack both lake-specific model validation and
        compatible chlorophyll-a/SST, so they return status only.
        """
        response = self.status(water_body, satellite, environment)
        model_inputs = model_inputs or {}
        if not model_inputs.get("complete"):
            readiness_message = model_inputs.get("readiness_message")
            if readiness_message:
                response["data_status"]["model_input_readiness"] = readiness_message
                if response["model_status"]["validated_for_water_body"]:
                    response["data_status"]["reason"] = readiness_message
        validated = (
            water_body.get("model_supported") is True
            and water_body.get("model_validation_status") == "validated_prototype"
        )
        image_path = model_inputs.get("satellite_raster_path")
        window = model_inputs.get("environmental_window")
        if (
            not validated
            or not image_path
            or not model_inputs.get("complete")
            or model_inputs.get("satellite_model_input_contract_verified") is not True
            or not environment.get("model_inputs_complete")
            or environment.get("expected_model_features") != list(MODEL_FEATURES)
            or window is None
        ):
            return response

        from pathlib import Path

        import pandas as pd

        if not Path(image_path).is_file() or len(window) != 7:
            return response
        if any(feature not in window.columns for feature in MODEL_FEATURES) or "date" not in window.columns:
            return response
        dates = pd.to_datetime(window["date"], errors="coerce")
        if dates.isna().any() or dates.duplicated().any():
            return response
        if any((right - left).days != 1 for left, right in zip(dates, dates.iloc[1:])):
            return response
        try:
            values = window.loc[:, list(MODEL_FEATURES)].astype(float)
        except (TypeError, ValueError):
            return response
        if not all(math.isfinite(float(value)) for value in values.to_numpy().ravel()):
            return response
        if not set(values["chlorophyll_imputed"]).issubset({0.0, 1.0}):
            return response
        if predictor_factory is None:
            return response

        result = predictor_factory().predict(
            sentinel_tif_path=str(image_path),
            environmental_7day_df=window,
        )
        probability = float(result["bloom_risk_probability"])
        horizon = int(result["forecast_horizon_days"])
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            return response
        if horizon != FORECAST_HORIZON_DAYS:
            return response
        response["prediction"] = {
            "probability": probability,
            "percent": probability * 100.0,
            "label": "Model-estimated bloom risk probability",
        }
        response["forecast_horizon_days"] = horizon
        response["model_status"].update({
            "status": "validated_prototype",
            "validated_for_water_body": True,
        })
        response["satellite_source"].update({
            "available": True,
            "image_available": True,
            "model_compatible": True,
            "observation_date": model_inputs.get(
                "satellite_observation_date",
                response["satellite_source"].get("observation_date"),
            ),
            "model_input_contract_verified": True,
        })
        response["data_status"] = {
            "status": "prediction_available",
            "reason": None,
            "missing_model_inputs": [],
            "blocking_conditions": [],
            "satellite_available": True,
            "satellite_scene_metadata_available": satellite.get("scene_metadata_available", False),
            "model_inputs_complete": True,
        }
        response["provenance"]["satellite_source"] = satellite.get("source")
        response["provenance"]["environment_window_source"] = model_inputs.get("environment_window_source")
        return response
