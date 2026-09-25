"""Focused checks for date-bound Copernicus scene search and CNN raster input."""

from __future__ import annotations

from datetime import date
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from backend.services.satellite import SatelliteService, SatelliteSourceUnavailable


WATER_BODY = {
    "id": "KA20010018",
    "latitude": 12.9826,
    "longitude": 77.6195,
    "boundary_available": True,
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class SatelliteAcquisitionTests(unittest.TestCase):
    def test_credentials_are_backend_environment_configuration(self):
        with patch.dict(os.environ, {"CDSE_ACCESS_TOKEN": "", "CDSE_CLIENT_ID": "", "CDSE_CLIENT_SECRET": ""}):
            service = SatelliteService()
        with self.assertRaisesRegex(SatelliteSourceUnavailable, "CDSE_CLIENT_ID and CDSE_CLIENT_SECRET"):
            service.fetch_model_raster(WATER_BODY, feature_date="2025-04-10")

    def test_oauth_uses_client_credentials_and_caches_token(self):
        service = SatelliteService(client_id="client-id", client_secret="client-secret", access_token="")
        import backend.services.satellite as satellite_module

        with patch.object(
            satellite_module.httpx, "post",
            return_value=FakeResponse({"access_token": "test-token", "expires_in": 3600}),
        ) as post:
            self.assertEqual(service._access_token(), "test-token")
            self.assertEqual(service._access_token(), "test-token")
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], satellite_module.TOKEN_URL)
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "client_credentials")
        self.assertEqual(post.call_args.kwargs["data"]["client_id"], "client-id")

    def test_scene_search_selects_latest_scene_not_after_feature_date(self):
        service = SatelliteService(client_id="", client_secret="", access_token="")
        scenes = [
            {"id": "future", "properties": {"datetime": "2025-04-11T05:00:00Z"}},
            {"id": "aligned", "properties": {"datetime": "2025-04-09T05:00:00Z"}},
            {"id": "too-old", "properties": {"datetime": "2025-04-04T05:00:00Z"}},
        ]
        import backend.services.satellite as satellite_module

        with patch.object(
            satellite_module.httpx, "post",
            return_value=FakeResponse({"features": scenes}),
        ) as post:
            selected = service._search_aligned_scene([77.6, 12.9, 77.7, 13.0], date(2025, 4, 10))
        self.assertEqual(selected["id"], "aligned")
        request = post.call_args.kwargs["json"]
        self.assertEqual(request["collections"], ["sentinel-2-l2a"])
        self.assertTrue(request["datetime"].startswith("2025-04-05T00:00:00+00:00/"))
        self.assertTrue(request["datetime"].endswith("2025-04-10T23:59:59.999999+00:00"))
        self.assertEqual(request["bbox"], [77.6, 12.9, 77.7, 13.0])

    def test_raster_rejects_future_stale_and_unaligned_scene_before_download(self):
        service = SatelliteService(client_id="client-id", client_secret="client-secret", access_token="")
        base = {
            "scene_metadata_available": True,
            "scene_id": "scene-id",
            "scene_datetime": "2025-04-09T05:00:00Z",
            "observation_date": "2025-04-09",
            "feature_date": "2025-04-10",
        }
        cases = [
            ({**base, "scene_datetime": "2025-04-11T05:00:00Z", "observation_date": "2025-04-11"}, "alignment"),
            ({**base, "scene_datetime": "2025-04-04T05:00:00Z", "observation_date": "2025-04-04"}, "alignment"),
            ({**base, "feature_date": "2025-04-09"}, "feature date"),
        ]
        with patch.object(service, "_access_token", side_effect=AssertionError("must not download")):
            for scene, message in cases:
                with self.subTest(scene=scene), self.assertRaisesRegex(SatelliteSourceUnavailable, message):
                    service.fetch_model_raster(
                        WATER_BODY, feature_date="2025-04-10", scene_coverage=scene
                    )

    @unittest.skipUnless(
        all(importlib.util.find_spec(name) for name in ("numpy", "rasterio", "cv2")),
        "NumPy, Rasterio and OpenCV are required for CNN raster preparation.",
    )
    def test_existing_cnn_preprocessing_resizes_scales_and_clips_four_bands(self):
        import numpy as np
        import rasterio

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "four-bands.tif"
            with rasterio.open(
                path, "w", driver="GTiff", width=2, height=2,
                count=4, dtype="uint16",
            ) as output:
                for index, value in enumerate((0, 5000, 10000, 30000), start=1):
                    output.write(np.full((2, 2), value, dtype=np.uint16), index)

            # This method does not use TensorFlow; avoid loading model files.
            with patch.dict(sys.modules, {"tensorflow": ModuleType("tensorflow")}):
                module = importlib.import_module("src.inference.bloom_predictor")
            predictor = module.BloomRiskPredictor.__new__(module.BloomRiskPredictor)
            predictor.config = {"cnn_image_size": 128}
            prepared = predictor._prepare_satellite_image(str(path))

        self.assertEqual(prepared.shape, (1, 128, 128, 4))
        np.testing.assert_allclose(prepared[0, 0, 0], [0.0, 0.5, 1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
