"""Credential checks use mock bearer values and never need live secrets."""

from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import patch

from backend.diagnose_cdse import (
    CATALOG_COLLECTIONS_URL, CLMS_PRODUCTS, STATISTICS_URL,
    _evalscript, _polygon_statistic, check_authentication,
)
from backend.services.satellite import SatelliteService


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class CDSEDiagnosticTests(unittest.TestCase):
    def test_mock_access_token_takes_priority_and_checks_read_only_endpoint(self):
        claim = base64.urlsafe_b64encode(json.dumps({"exp": 2_000_000_000}).encode()).decode().rstrip("=")
        token = f"header.{claim}.signature"
        service = SatelliteService(
            client_id="client-id", client_secret="client-secret", access_token=token
        )
        with patch("backend.diagnose_cdse.httpx.get", return_value=FakeResponse(200)) as get, \
             patch("backend.services.satellite.httpx.post") as post:
            report = check_authentication(service)
        self.assertEqual(report["authentication"], "authenticated")
        self.assertEqual(report["http_status"], 200)
        self.assertEqual(report["api_endpoint"], CATALOG_COLLECTIONS_URL)
        self.assertIsNotNone(report["token_expiry_utc"])
        self.assertNotIn(token, json.dumps(report))
        self.assertEqual(get.call_args.args[0], CATALOG_COLLECTIONS_URL)
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": f"Bearer {token}"})
        post.assert_not_called()

    def test_rejected_token_returns_status_without_token(self):
        service = SatelliteService(client_id="", client_secret="", access_token="mock-secret")
        with patch("backend.diagnose_cdse.httpx.get", return_value=FakeResponse(401)):
            report = check_authentication(service)
        self.assertEqual(report["authentication"], "rejected")
        self.assertEqual(report["http_status"], 401)
        self.assertNotIn("mock-secret", json.dumps(report))

    def test_missing_credentials_are_not_reported_as_rejected(self):
        service = SatelliteService(client_id="", client_secret="", access_token="")
        with patch("backend.diagnose_cdse.httpx.get") as get:
            report = check_authentication(service)
        self.assertEqual(report["authentication"], "not_configured")
        self.assertIsNone(report["http_status"])
        get.assert_not_called()

    def test_clms_statistic_uses_polygon_mask_and_official_band_scaling(self):
        polygon = {"type": "Polygon", "coordinates": [[[77.61, 12.98], [77.62, 12.98], [77.61, 12.99], [77.61, 12.98]]]}
        response = FakeResponse(200, {"data": [{"outputs": {"value": {"bands": {"B0": {"stats": {
            "sampleCount": 12, "noDataCount": 9, "mean": 302.15,
        }}}}}}]})
        service = SatelliteService(client_id="", client_secret="", access_token="mock-secret")
        with patch("backend.diagnose_cdse.httpx.post", return_value=response) as post:
            observation = _polygon_statistic(
                service, "mock-secret", polygon,
                CLMS_PRODUCTS["lake_surface_water_temperature"], "2026-08-01",
            )
        self.assertEqual(observation["valid_pixel_count"], 3)
        self.assertEqual(observation["polygon_mean"], 302.15)
        self.assertEqual(observation["units"], "K")
        self.assertEqual(post.call_args.args[0], STATISTICS_URL)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["input"]["bounds"]["geometry"], polygon)
        self.assertEqual(payload["input"]["data"][0]["type"], CLMS_PRODUCTS["lake_surface_water_temperature"]["type"])
        self.assertIn("sample.LSWT * 0.01 + 273.15", payload["aggregation"]["evalscript"])
        self.assertIn("dataMask: [sample.dataMask]", payload["aggregation"]["evalscript"])
        self.assertEqual(payload["aggregation"]["timeRange"]["to"], "2026-08-02T00:00:00Z")
        self.assertIn("sample.CHLAMEAN", _evalscript(CLMS_PRODUCTS["chlorophyll_a"]))


if __name__ == "__main__":
    unittest.main()
