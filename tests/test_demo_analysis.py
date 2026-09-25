"""Explicit demo inference stays separate from the validated live path."""

from __future__ import annotations

from datetime import date
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import numpy as np

from backend.main import app
from backend.services.demo_analysis import DemoAnalysisError, generate_demo_inputs, run_demo_analysis
from backend.services.prediction import MODEL_FEATURES


LAKE = {
    "id": "KA20010018", "name": "Ulsoor Lake", "state": "Karnataka",
    "district": "Bengaluru Urban", "taluk": "Bengaluru East",
    "location_resolved": True, "boundary_available": True,
    "latitude": 12.9826, "longitude": 77.6195,
    "boundary": {"type": "Polygon", "coordinates": [[[77.61, 12.98], [77.62, 12.98], [77.61, 12.99], [77.61, 12.98]]]},
}


class RecordingPredictor:
    config = {
        "environmental_features": list(MODEL_FEATURES),
        "lstm_window_days": 7, "cnn_image_size": 128, "cnn_bands": 4,
        "forecast_horizon_days": 5, "cnn_weight": 0.5, "lstm_weight": 0.5,
    }

    def __init__(self):
        self.calls = 0

    def predict(self, *, sentinel_tif_path, environmental_7day_df):
        import rasterio

        self.calls += 1
        self.last_features = list(environmental_7day_df.columns)
        self.last_days = len(environmental_7day_df)
        with rasterio.open(sentinel_tif_path) as raster:
            self.last_raster_shape = raster.read().shape
            self.last_bands = raster.descriptions
            self.last_dtype = raster.dtypes
        return {
            "cnn_probability": 0.3,
            "lstm_probability": 0.5,
            "bloom_risk_probability": 0.4,
            "forecast_horizon_days": 5,
        }


class DemoAnalysisTests(unittest.TestCase):
    def test_synthetic_inputs_have_exact_features_shape_and_are_deterministic(self):
        day = date(2026, 9, 26)
        first_frame, first_raster = generate_demo_inputs(LAKE["id"], day)
        second_frame, second_raster = generate_demo_inputs(LAKE["id"], day)
        self.assertEqual(list(first_frame.columns), ["date", *MODEL_FEATURES])
        self.assertEqual(len(first_frame), 7)
        self.assertEqual((first_frame.date.iloc[-1] - first_frame.date.iloc[0]).days, 6)
        self.assertEqual(first_raster.shape, (4, 128, 128))
        self.assertEqual(first_raster.dtype, np.uint16)
        self.assertTrue((first_raster <= 20000).all())
        self.assertTrue(first_frame.equals(second_frame))
        np.testing.assert_array_equal(first_raster, second_raster)
        changed_frame, changed_raster = generate_demo_inputs("KA20010019", day)
        self.assertFalse(first_frame.equals(changed_frame))
        self.assertFalse(np.array_equal(first_raster, changed_raster))

    def test_demo_uses_existing_predictor_interface_without_lake_validation(self):
        predictor = RecordingPredictor()
        first = run_demo_analysis(LAKE, date(2026, 9, 26), predictor)
        second = run_demo_analysis(LAKE, date(2026, 9, 26), predictor)
        self.assertEqual(first, second)
        self.assertEqual(predictor.calls, 2)
        self.assertEqual(predictor.last_features, ["date", *MODEL_FEATURES])
        self.assertEqual(predictor.last_days, 7)
        self.assertEqual(predictor.last_raster_shape, (4, 128, 128))
        self.assertEqual(predictor.last_bands, ("B2", "B3", "B4", "B8"))
        self.assertEqual(predictor.last_dtype, ("uint16",) * 4)
        self.assertIs(first["simulated"], True)
        self.assertEqual(first["mode"], "demo")
        self.assertEqual(first["cnn_probability"], 0.3)
        self.assertEqual(first["lstm_probability"], 0.5)
        self.assertEqual(first["fused_probability"], 0.4)
        self.assertEqual(first["horizon_days"], 5)
        self.assertIn("not a real prediction", first["disclaimer"])
        self.assertNotIn("sentinel_tif_path", json.dumps(first))

    def test_incompatible_saved_model_contract_stops_before_inference(self):
        predictor = RecordingPredictor()
        predictor.config = {**predictor.config, "cnn_weight": 0.7}
        with self.assertRaisesRegex(DemoAnalysisError, "50/50 fusion"):
            run_demo_analysis(LAKE, date(2026, 9, 26), predictor)
        self.assertEqual(predictor.calls, 0)

    def test_demo_endpoint_works_without_validation_and_live_stays_unavailable(self):
        predictor = RecordingPredictor()
        environment = {
            "model_features": {feature: {"available": False, "model_compatible": False} for feature in MODEL_FEATURES},
            "model_inputs_complete": False,
            "expected_model_features": list(MODEL_FEATURES),
            "model_window": {"end_date": None},
            "weather_context": {"source": "test context"},
        }
        satellite = {"available": False, "model_compatible": False, "scene_metadata_available": False}
        with patch("backend.main.water_body_service.get", return_value=LAKE), \
             patch("backend.main.get_predictor", return_value=predictor), \
             patch("backend.main.environment_service.coverage", return_value=environment), \
             patch("backend.main.satellite_service.coverage", return_value=satellite):
            client = TestClient(app)
            demo = client.get("/water-bodies/KA20010018/prediction?mode=demo&feature_date=2026-09-26")
            live = client.get("/water-bodies/KA20010018/prediction")
        self.assertEqual(demo.status_code, 200)
        self.assertIs(demo.json()["simulated"], True)
        self.assertEqual(demo.json()["water_body"], "Ulsoor Lake")
        self.assertEqual(demo.json()["fused_probability"], 0.4)
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json()["mode"], "live")
        self.assertIs(live.json()["simulated"], False)
        self.assertIsNone(live.json()["prediction"])
        self.assertEqual(live.json()["data_status"]["status"], "prediction_unavailable")
        self.assertEqual(predictor.calls, 1)


if __name__ == "__main__":
    unittest.main()
