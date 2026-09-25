from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.services.satellite import (
    CNN_INPUT_EVALSCRIPT,
    SatelliteService,
    SatelliteSourceUnavailable,
)
from backend.water_bodies import KarnatakaWaterBodyService


class CatalogAndSatelliteTests(unittest.TestCase):
    def test_name_search_uses_official_source_without_featured_id_allowlist(self):
        service = KarnatakaWaterBodyService()
        features = [
            {"attributes": {
                "UniqueTankID": "KA26040001",
                "TankName": "Kukkarahalli Lake",
                "KGISDistrictName": "Mysuru",
                "Latitude": 12.3,
                "Longitude": 76.6,
                "TankArea_Ha": 60.0,
            }},
            {"attributes": {
                "UniqueTankID": "KA20020236",
                "TankName": "Gattigere Palya Lake",
                "KGISDistrictName": "Bengaluru (Urban)",
                "Latitude": 12.9,
                "Longitude": 77.5,
                "TankArea_Ha": 0.2,
            }},
        ]
        with patch.object(service, "_query", return_value={"features": features}) as query:
            records = service.search("lake", limit=25)
        where = query.call_args.args[0]["where"]
        self.assertIn("UPPER(TankName) LIKE '%LAKE%'", where)
        self.assertNotIn("UniqueTankID IN", where)
        self.assertEqual({record["id"] for record in records}, {"KA26040001", "KA20020236"})

    def test_multiword_search_uses_one_source_filter_and_matches_tokens_locally(self):
        service = KarnatakaWaterBodyService()
        features = [
            {"attributes": {
                "UniqueTankID": "KA20020236",
                "TankName": "Gattigere Palya  (Sompura) Lake",
                "KGISDistrictName": "Bengaluru (Urban)",
                "Latitude": 12.9,
                "Longitude": 77.5,
                "TankArea_Ha": 0.2,
            }},
            {"attributes": {
                "UniqueTankID": "KA20020237",
                "TankName": "Gattigere Palya North Lake",
                "KGISDistrictName": "Bengaluru (Urban)",
                "Latitude": 12.9,
                "Longitude": 77.5,
                "TankArea_Ha": 0.4,
            }},
        ]
        with patch.object(service, "_query", return_value={"features": features}) as query:
            records = service.search("Gattigere Palya (Sompura) Lake")
        where = query.call_args.args[0]["where"]
        self.assertIn("LIKE '%GATTIGERE%'", where)
        self.assertEqual(where.count("LIKE"), 1)
        self.assertEqual(records[0]["name"], "Gattigere Palya (Sompura) Lake")
        self.assertEqual(len(records), 1)

    def test_cnn_evalscript_keeps_verified_band_order_and_type(self):
        self.assertIn('bands: ["B02", "B03", "B04", "B08"]', CNN_INPUT_EVALSCRIPT)
        self.assertIn('units: "DN"', CNN_INPUT_EVALSCRIPT)
        self.assertIn('sampleType: "UINT16"', CNN_INPUT_EVALSCRIPT)
        self.assertIn("[sample.B02, sample.B03, sample.B04, sample.B08]", CNN_INPUT_EVALSCRIPT)

    def test_public_stac_scene_metadata_is_available_without_pixel_credentials(self):
        service = SatelliteService(client_id="", client_secret="")
        water_body = {
            "id": "KA20010018",
            "latitude": 12.98,
            "longitude": 77.62,
            "boundary_available": True,
        }
        scene = {
            "id": "S2C_MSIL2A_20260924T050651_N0513_R019_T43PGQ_20260924T100421",
            "properties": {
                "datetime": "2026-09-24T05:06:51.025000Z",
                "eo:cloud_cover": 90.48,
            },
        }
        with patch.object(service, "_search_latest_scene", return_value=scene):
            status = service.coverage(water_body)
        self.assertEqual(status["status"], "scene_metadata_found")
        self.assertTrue(status["scene_metadata_available"])
        self.assertEqual(status["observation_date"], "2026-09-24")
        self.assertEqual(
            status["scene_catalog_url"],
            "https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a/items/S2C_MSIL2A_20260924T050651_N0513_R019_T43PGQ_20260924T100421",
        )
        self.assertEqual(status["scene_cloud_cover_percent"], 90.48)
        self.assertEqual(
            status["scene_cloud_cover_scope"],
            "Sentinel-2 product footprint; not lake-specific",
        )
        self.assertFalse(status["preview_available"])
        self.assertFalse(status["model_ingestion_ready"])
        with self.assertRaisesRegex(SatelliteSourceUnavailable, "preview pixels require"):
            service.preview(water_body)
        with self.assertRaises(SatelliteSourceUnavailable):
            service.fetch_model_raster(water_body, feature_date="2026-09-24")

    def test_public_stac_search_needs_no_authorization_header(self):
        service = SatelliteService(client_id="", client_secret="")

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"features": [{"id": "scene", "properties": {"datetime": "2026-09-24T05:00:00Z"}}]}

        import backend.services.satellite as satellite_module
        with patch.object(satellite_module.httpx, "post", return_value=FakeResponse()) as post:
            item = service._search_latest_scene([77.6, 12.9, 77.7, 13.0])
        self.assertEqual(item["id"], "scene")
        args, kwargs = post.call_args
        self.assertEqual(args[0], satellite_module.STAC_SEARCH_URL)
        self.assertNotIn("headers", kwargs)
        self.assertEqual(kwargs["json"]["collections"], ["sentinel-2-l2a"])
        self.assertEqual(
            kwargs["json"]["fields"]["include"],
            ["id", "properties.datetime", "properties.eo:cloud_cover"],
        )

    @unittest.skipUnless(importlib.util.find_spec("rasterio"), "Rasterio is not installed.")
    def test_model_raster_adapter_requests_and_writes_the_cnn_contract(self):
        import numpy as np
        import rasterio
        from rasterio.io import MemoryFile

        with MemoryFile() as memory:
            with memory.open(
                driver="GTiff", width=2, height=2, count=4, dtype="uint16"
            ) as dataset:
                for band, sample in enumerate((2_000, 3_000, 4_000, 8_000), start=1):
                    dataset.write(np.full((2, 2), sample, dtype=np.uint16), band)
            process_tiff = memory.read()

        class FakeResponse:
            def __init__(self, content=b"", json_payload=None):
                self.content = content
                self.json_payload = json_payload or {}

            def raise_for_status(self):
                return None

            def json(self):
                return self.json_payload

        service = SatelliteService(client_id="test-client", client_secret="test-secret")
        water_body = {
            "id": "KA20010018",
            "boundary": {
                "type": "Polygon",
                "coordinates": [[
                    [77.5, 12.9],
                    [77.50005, 12.9],
                    [77.50005, 12.90005],
                    [77.5, 12.90005],
                    [77.5, 12.9],
                ]],
            },
            "boundary_available": True,
        }
        aligned_scene = {
            "scene_metadata_available": True,
            "observation_date": "2026-09-24",
            "scene_datetime": "2026-09-24T05:06:51.025000Z",
            "scene_id": "S2C_MSIL2A_20260924T050651_N0513_R019_T43PGQ_20260924T100421",
            "feature_date": "2026-09-25",
            "source": "test scene",
        }
        with patch.object(service, "coverage", return_value=aligned_scene):
            import backend.services.satellite as satellite_module
            requests = []

            def fake_post(url, **kwargs):
                if url == satellite_module.TOKEN_URL:
                    return FakeResponse(json_payload={"access_token": "test-token", "expires_in": 3600})
                if url == satellite_module.PROCESS_URL:
                    requests.append(kwargs["json"])
                    return FakeResponse(content=process_tiff)
                raise AssertionError(f"Unexpected provider URL: {url}")

            with tempfile.TemporaryDirectory() as cache_dir, patch.object(
                satellite_module.httpx, "post", side_effect=fake_post
            ):
                result = service.fetch_model_raster(
                    water_body, feature_date="2026-09-25", cache_dir=cache_dir
                )

                self.assertTrue(Path(result["local_path"]).is_file())
                self.assertEqual(result["band_order"], ["B2", "B3", "B4", "B8"])
                self.assertEqual(result["sample_type"], "UINT16 DN, harmonized")
                self.assertFalse(result["cloud_mask_applied"])
                self.assertTrue(result["model_input_contract_verified"])
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]["evalscript"], CNN_INPUT_EVALSCRIPT)
                self.assertEqual(requests[0]["output"]["responses"][0]["format"]["type"], "image/tiff")
                time_range = requests[0]["input"]["data"][0]["dataFilter"]["timeRange"]
                self.assertGreaterEqual(
                    datetime.fromisoformat(time_range["from"].replace("Z", "+00:00")),
                    datetime.fromisoformat("2026-09-24T05:05:51+00:00"),
                )
                self.assertLessEqual(
                    datetime.fromisoformat(time_range["to"].replace("Z", "+00:00")),
                    datetime.fromisoformat("2026-09-25T23:59:59+00:00"),
                )
                with rasterio.open(result["local_path"]) as output:
                    self.assertEqual(output.count, 4)
                    self.assertEqual(output.dtypes, ("uint16",) * 4)
                    self.assertEqual(output.descriptions, ("B2", "B3", "B4", "B8"))
                    self.assertEqual(output.tags()["scene_id"], aligned_scene["scene_id"])
                    self.assertEqual(
                        [int(output.read(index)[0, 0]) for index in range(1, 5)],
                        [2_000, 3_000, 4_000, 8_000],
                    )


if __name__ == "__main__":
    unittest.main()
