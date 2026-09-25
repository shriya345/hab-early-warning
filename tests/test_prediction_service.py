from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backend.services.prediction import MODEL_FEATURES, PredictionService


def make_inputs():
    end = date(2026, 9, 25)
    frame = pd.DataFrame({
        "date": [end - timedelta(days=6 - index) for index in range(7)],
        "chlorophyll_a": [1.0] * 7,
        "sst": [29.0] * 7,
        "rainfall": [2.0] * 7,
        "wind_speed": [1.0] * 7,
        "chlorophyll_imputed": [0] * 7,
    })
    environment = {
        "model_features": {
            feature: {
                "available": True,
                "model_compatible": True,
                "source": "test fixture",
            }
            for feature in MODEL_FEATURES
        },
        "model_inputs_complete": True,
        "expected_model_features": list(MODEL_FEATURES),
        "weather_context": {"source": "test fixture"},
    }
    satellite = {
        "available": True,
        "model_compatible": True,
        "scene_metadata_available": True,
        "source": "test fixture",
    }
    water_body = {
        "id": "KA00000001",
        "name": "Test Lake",
        "state": "Karnataka",
        "model_supported": True,
        "model_validation_status": "validated_prototype",
        "model_version": "test-model",
        "catalog_source": "test fixture",
    }
    return water_body, satellite, environment, frame


class FakePredictor:
    def __init__(self, probability=0.45, horizon=5):
        self.probability = probability
        self.horizon = horizon

    def predict(self, *, sentinel_tif_path, environmental_7day_df):
        assert len(environmental_7day_df) == 7
        assert Path(sentinel_tif_path).is_file()
        return {
            "bloom_risk_probability": self.probability,
            "bloom_risk_percent": self.probability * 100,
            "forecast_horizon_days": self.horizon,
        }


class PredictionServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = PredictionService()

    def test_unvalidated_water_body_never_calls_predictor(self):
        water_body, satellite, environment, frame = make_inputs()
        water_body["model_supported"] = False
        with tempfile.NamedTemporaryFile() as raster:
            response = self.service.predict_if_ready(
                water_body,
                satellite,
                environment,
                model_inputs={
                    "complete": True,
                    "satellite_model_input_contract_verified": True,
                    "satellite_raster_path": raster.name,
                    "environmental_window": frame,
                },
                predictor_factory=lambda: (_ for _ in ()).throw(AssertionError("must not infer")),
            )
        self.assertIsNone(response["prediction"])
        self.assertEqual(response["model_status"]["status"], "data_model_validation_required")

    def test_validated_complete_inputs_return_probability_without_internal_paths(self):
        water_body, satellite, environment, frame = make_inputs()
        with tempfile.NamedTemporaryFile() as raster:
            response = self.service.predict_if_ready(
                water_body,
                satellite,
                environment,
                model_inputs={
                    "complete": True,
                    "satellite_model_input_contract_verified": True,
                    "satellite_raster_path": raster.name,
                    "satellite_observation_date": "2026-09-25",
                    "environment_window_source": "reviewed fixture",
                    "environmental_window": frame,
                },
                predictor_factory=lambda: FakePredictor(),
            )
        self.assertEqual(response["prediction"]["percent"], 45.0)
        self.assertEqual(response["forecast_horizon_days"], 5)
        self.assertEqual(response["data_status"]["status"], "prediction_available")
        self.assertNotIn(raster.name, repr(response))

    def test_nonconsecutive_environmental_window_does_not_run(self):
        water_body, satellite, environment, frame = make_inputs()
        frame.loc[3, "date"] = frame.loc[2, "date"]
        with tempfile.NamedTemporaryFile() as raster:
            response = self.service.predict_if_ready(
                water_body,
                satellite,
                environment,
                model_inputs={
                    "complete": True,
                    "satellite_raster_path": raster.name,
                    "environmental_window": frame,
                },
                predictor_factory=lambda: (_ for _ in ()).throw(AssertionError("must not infer")),
            )
        self.assertIsNone(response["prediction"])

    def test_missing_satellite_contract_attestation_does_not_run(self):
        water_body, satellite, environment, frame = make_inputs()
        with tempfile.NamedTemporaryFile() as raster:
            response = self.service.predict_if_ready(
                water_body,
                satellite,
                environment,
                model_inputs={
                    "complete": True,
                    "satellite_raster_path": raster.name,
                    "environmental_window": frame,
                },
                predictor_factory=lambda: (_ for _ in ()).throw(AssertionError("must not infer")),
            )
        self.assertIsNone(response["prediction"])

    def test_wrong_environment_feature_order_does_not_run(self):
        water_body, satellite, environment, frame = make_inputs()
        environment["expected_model_features"] = list(reversed(MODEL_FEATURES))
        with tempfile.NamedTemporaryFile() as raster:
            response = self.service.predict_if_ready(
                water_body,
                satellite,
                environment,
                model_inputs={
                    "complete": True,
                    "satellite_model_input_contract_verified": True,
                    "satellite_raster_path": raster.name,
                    "environmental_window": frame,
                },
                predictor_factory=lambda: (_ for _ in ()).throw(AssertionError("must not infer")),
            )
        self.assertIsNone(response["prediction"])


if __name__ == "__main__":
    unittest.main()
