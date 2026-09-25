from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from backend.services.environment import EnvironmentService, MODEL_FEATURES
from backend.services.model_inputs import ModelInputService


def water_body(model_supported=False):
    return {
        "id": "KA20010018",
        "name": "Ulsoor Lake",
        "model_supported": model_supported,
        "model_validation_status": "data_model_validation_required",
    }


class ModelInputServiceTests(unittest.TestCase):
    def test_unvalidated_catalogue_record_stops_before_satellite_acquisition(self):
        class NeverAcquireSatellite:
            def fetch_model_raster(self, _water_body):
                raise AssertionError("unvalidated body must not trigger image acquisition")

        service = ModelInputService(EnvironmentService(), NeverAcquireSatellite())
        result = service.prepare(water_body(), {}, {"model_inputs_complete": False})
        self.assertFalse(result["complete"])
        self.assertIn("not currently validated", result["readiness_message"])

    def test_model_window_requires_manifest_and_recent_seven_day_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            end = datetime.now(ZoneInfo("Asia/Kolkata")).date()
            dates = [end - timedelta(days=6 - index) for index in range(7)]
            frame = pd.DataFrame({
                "date": dates,
                "chlorophyll_a": [1.0] * 7,
                "sst": [28.0] * 7,
                "rainfall": [2.0] * 7,
                "wind_speed": [1.2] * 7,
                "chlorophyll_imputed": [0] * 7,
            })
            frame.to_csv(root / "KA20010018.csv", index=False)
            (root / "KA20010018.json").write_text(json.dumps({
                "water_body_id": "KA20010018",
                "source": "reviewed lake observation feed",
                "feature_order": list(MODEL_FEATURES),
                "units_verified_against_training_data": True,
            }))

            service = EnvironmentService(model_input_dir=root)
            window, status = service.model_window(water_body())
            self.assertIsNotNone(window)
            self.assertEqual(len(window), 7)
            self.assertEqual(status["end_date"], end.isoformat())
            self.assertTrue(status["available"])

            stale = frame.copy()
            stale["date"] = [day - timedelta(days=8) for day in dates]
            stale.to_csv(root / "KA20010018.csv", index=False)
            window, status = service.model_window(water_body())
            self.assertIsNone(window)
            self.assertFalse(status["available"])

    def test_preparation_passes_feature_date_and_selected_scene_to_raster_acquisition(self):
        end = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        frame = pd.DataFrame({
            "date": [end - timedelta(days=6 - index) for index in range(7)],
            **{feature: [0.0] * 7 for feature in MODEL_FEATURES},
        })

        class EnvironmentWindow:
            def model_window(self, _water_body):
                return frame, {"end_date": end.isoformat(), "source": "verified feed"}

        class CapturingSatellite:
            def __init__(self):
                self.kwargs = None

            def fetch_model_raster(self, _water_body, **kwargs):
                self.kwargs = kwargs
                return {
                    "local_path": "/private/model-raster.tif",
                    "observation_date": end.isoformat(),
                    "source": "Copernicus L2A",
                    "band_order": ["B2", "B3", "B4", "B8"],
                    "sample_type": "UINT16 DN, harmonized",
                    "cloud_mask_applied": False,
                    "model_input_contract_verified": True,
                }

        water = {**water_body(model_supported=True), "model_validation_status": "validated_prototype"}
        scene = {
            "scene_metadata_available": True,
            "observation_date": end.isoformat(),
            "feature_date": end.isoformat(),
        }
        environment = {
            "model_inputs_complete": True,
            "expected_model_features": list(MODEL_FEATURES),
        }
        satellite = CapturingSatellite()
        with patch.dict(os.environ, {"HAB_SATELLITE_INPUT_CONTRACT_VERIFIED": "true"}):
            result = ModelInputService(EnvironmentWindow(), satellite).prepare(
                water, scene, environment
            )
        self.assertTrue(result["complete"])
        self.assertEqual(satellite.kwargs["feature_date"], end)
        self.assertIs(satellite.kwargs["scene_coverage"], scene)


if __name__ == "__main__":
    unittest.main()
