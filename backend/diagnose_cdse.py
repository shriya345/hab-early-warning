"""Read-only CDSE authentication and CLMS lake-coverage diagnostics.

Run ``python -m backend.diagnose_cdse auth`` for a credential check, or
``python -m backend.diagnose_cdse ulsoor`` for K-GIS polygon statistics.
Credentials are read only by SatelliteService from the backend environment.
No diagnostic output contains a bearer token or OAuth secret.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import math
import sys
from typing import Any

import httpx

from backend.services.satellite import SatelliteService, SatelliteSourceUnavailable
from backend.water_bodies import KarnatakaWaterBodyService, WaterBodyNotFound, WaterBodySourceUnavailable


CATALOG_COLLECTIONS_URL = "https://sh.dataspace.copernicus.eu/catalog/v1/collections"
STAC_SEARCH_URL = "https://stac.dataspace.copernicus.eu/v1/search"
STATISTICS_URL = "https://sh.dataspace.copernicus.eu/statistics/v1"
ULSOOR_ID = "KA20010018"
CLMS_PRODUCTS = {
    "chlorophyll_a": {
        "collection": "clms_lwq-nrt_global_100m_10daily_v2_cog",
        "type": "byoc-c320caa8-4d97-40e1-90c6-e34dd5e42b8b",
        "band": "CHLAMEAN",
        "units": "mg/m3",
        "nominal_resolution_m": 100,
        "expression": "sample.CHLAMEAN",
    },
    "lake_surface_water_temperature": {
        "collection": "clms_lswt-nrt_global_1km_10daily_v1_cog",
        "type": "byoc-401ca642-a169-4783-b1cf-cbd33e98eccb",
        "band": "LSWT",
        "units": "K",
        "nominal_resolution_m": 1000,
        "expression": "sample.LSWT * 0.01 + 273.15",
    },
}


def _jwt_expiry(token: str) -> str | None:
    """Read the unverified JWT expiry claim locally; never include the token."""
    try:
        part = token.split(".")[1]
        claim = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        expiry = claim.get("exp")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
            return None
        return datetime.fromtimestamp(expiry, timezone.utc).isoformat()
    except (IndexError, ValueError, TypeError, OverflowError):
        return None


def check_authentication(service: SatelliteService) -> dict[str, Any]:
    """Test the bearer with the authenticated, read-only Sentinel Hub Catalog API."""
    report: dict[str, Any] = {
        "authentication": "not_configured",
        "http_status": None,
        "api_endpoint": CATALOG_COLLECTIONS_URL,
        "token_expiry_utc": None,
    }
    if not service.credentials_configured:
        return report
    try:
        token = service._access_token()
    except SatelliteSourceUnavailable:
        report["authentication"] = "rejected"
        return report
    report["token_expiry_utc"] = _jwt_expiry(token)
    try:
        response = httpx.get(
            CATALOG_COLLECTIONS_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=service.timeout,
        )
    except httpx.HTTPError:
        report["authentication"] = "unverified"
        return report
    report["http_status"] = response.status_code
    report["authentication"] = (
        "authenticated" if 200 <= response.status_code < 300 else
        "rejected" if response.status_code in {401, 403} else "unverified"
    )
    return report


def _catalogue_dates(collection: str, bbox: list[float], *, timeout: float) -> list[str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=180)
    response = httpx.post(
        STAC_SEARCH_URL,
        json={
            "collections": [collection],
            "bbox": bbox,
            "datetime": f"{start.isoformat()}/{end.isoformat()}",
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            "limit": 30,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    dates = []
    for feature in response.json().get("features") or []:
        timestamp = (feature.get("properties") or {}).get("datetime")
        try:
            observation = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        if observation.tzinfo and start <= observation.astimezone(timezone.utc) <= end:
            dates.append(observation.date().isoformat())
    return sorted(set(dates), reverse=True)


def _evalscript(product: dict[str, Any]) -> str:
    # Official CLMS definitions: CHLAMEAN is already mg/m3; LSWT is raw
    # INT16 requiring scale 0.01 and offset 273.15 K. Sentinel Hub requires
    # dataMask to exclude missing/outside-polygon pixels from statistics.
    return (
        "//VERSION=3\n"
        "function setup() { return { input: [{ bands: [\"" + product["band"] +
        "\", \"dataMask\"] }], output: ["
        "{ id: \"value\", bands: 1, sampleType: \"FLOAT32\" },"
        "{ id: \"dataMask\", bands: 1 }] }; }\n"
        "function evaluatePixel(sample) { return { value: [" + product["expression"] +
        "], dataMask: [sample.dataMask] }; }"
    )


def _polygon_statistic(
    service: SatelliteService, token: str, geometry: dict, product: dict, day: str
) -> dict[str, Any]:
    tomorrow = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    # CRS84 degrees. A 0.0009-degree output grid resolves the 100 m LWQ
    # product and samples the native 1 km LSWT product without claiming finer
    # native information.
    payload = {
        "input": {
            "bounds": {
                "geometry": geometry,
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [{"type": product["type"]}],
        },
        "aggregation": {
            "timeRange": {"from": f"{day}T00:00:00Z", "to": f"{tomorrow}T00:00:00Z"},
            "aggregationInterval": {"of": "P1D"},
            "evalscript": _evalscript(product),
            "resx": 0.0009,
            "resy": 0.0009,
        },
    }
    response = httpx.post(
        STATISTICS_URL,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=max(service.timeout, 60),
    )
    if response.status_code != 200:
        return {"date": day, "http_status": response.status_code, "valid_pixel_count": 0}
    try:
        intervals = response.json().get("data") or []
        stats = intervals[0]["outputs"]["value"]["bands"]["B0"]["stats"]
        count = int(stats["sampleCount"]) - int(stats.get("noDataCount", 0))
        mean = float(stats["mean"])
    except (ValueError, TypeError, KeyError, IndexError):
        return {"date": day, "http_status": 200, "result": "unparseable"}
    if count <= 0 or not math.isfinite(mean):
        return {"date": day, "http_status": 200, "valid_pixel_count": 0}
    return {
        "date": day, "http_status": 200, "valid_pixel_count": count,
        "polygon_mean": mean, "units": product["units"],
    }


def diagnose_ulsoor(service: SatelliteService) -> dict[str, Any]:
    auth = check_authentication(service)
    report: dict[str, Any] = {
        "authentication": auth,
        "water_body_id": ULSOOR_ID,
        "products": {},
        "genuine_seven_daily_observations_available": False,
    }
    try:
        body = KarnatakaWaterBodyService().get(ULSOOR_ID)
        geometry = body.get("boundary")
        bbox = service._bbox(body)
        if not geometry or not bbox:
            report["error"] = "K-GIS polygon unavailable"
            return report
    except (WaterBodyNotFound, WaterBodySourceUnavailable):
        report["error"] = "K-GIS polygon lookup unavailable"
        return report
    token = service._access_token() if auth["authentication"] == "authenticated" else None
    for name, product in CLMS_PRODUCTS.items():
        entry: dict[str, Any] = {
            "band": product["band"], "units": product["units"],
            "nominal_resolution_m": product["nominal_resolution_m"],
            "product_cadence": "10-daily",
            "stac_candidate_dates": [], "lake_pixel_observations": [],
            "lake_coverage": "unverified",
        }
        report["products"][name] = entry
        try:
            dates = _catalogue_dates(product["collection"], bbox, timeout=service.timeout)
        except (httpx.HTTPError, ValueError):
            entry["catalogue_status"] = "unavailable"
            continue
        entry["stac_candidate_dates"] = dates
        if token is None:
            continue
        # Public STAC items have global footprints. Only polygon statistics
        # with valid dataMask pixels establish actual Ulsoor coverage.
        for day in dates[:3]:
            try:
                entry["lake_pixel_observations"].append(
                    _polygon_statistic(service, token, geometry, product, day)
                )
            except httpx.HTTPError:
                entry["lake_pixel_observations"].append(
                    {"date": day, "http_status": None, "valid_pixel_count": 0}
                )
        observations = entry["lake_pixel_observations"]
        if any(item.get("valid_pixel_count", 0) > 0 for item in observations):
            entry["lake_coverage"] = "valid_polygon_pixels_found"
        elif observations and all(
            item.get("http_status") == 200 and item.get("valid_pixel_count") == 0
            for item in observations
        ):
            entry["lake_coverage"] = "no_valid_pixels_on_tested_dates"
    return report


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "auth"
    if command not in {"auth", "ulsoor"}:
        print("Usage: python -m backend.diagnose_cdse [auth|ulsoor]", file=sys.stderr)
        raise SystemExit(2)
    service = SatelliteService()
    result = check_authentication(service) if command == "auth" else diagnose_ulsoor(service)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
