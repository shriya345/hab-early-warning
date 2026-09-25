"""Public Copernicus scene discovery and on-demand RGB preview.

Scene metadata comes from CDSE's public STAC catalogue and does not require
credentials. Fetching preview pixels or a model raster still uses the
authenticated Sentinel Hub Process API. The RGB preview is visual context
only and does not change the archived CNN's four-band preprocessing contract.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any
from urllib.parse import quote

import httpx


TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)
STAC_SEARCH_URL = "https://stac.dataspace.copernicus.eu/v1/search"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/process/v1"
SOURCE = "Copernicus Data Space Sentinel-2 L2A"
CATALOG_SOURCE = "Copernicus Data Space Sentinel-2 L2A STAC catalogue"
CACHE_SECONDS = 6 * 60 * 60
MAX_MODEL_SCENE_AGE_DAYS = 5
MISSING_CREDENTIALS_MESSAGE = (
    "Copernicus raster acquisition is not configured. Set CDSE_ACCESS_TOKEN or both "
    "CDSE_CLIENT_ID and CDSE_CLIENT_SECRET in the backend process environment."
)

RGB_PREVIEW_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B04", "B03", "B02"], units: "REFLECTANCE" }],
    output: { bands: 3, sampleType: "AUTO" }
  };
}
function evaluatePixel(sample) {
  return [2.5 * sample.B04, 2.5 * sample.B03, 2.5 * sample.B02];
}
"""

CNN_INPUT_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02", "B03", "B04", "B08"], units: "DN" }],
    output: { bands: 4, sampleType: "UINT16" }
  };
}
function evaluatePixel(sample) {
  return [sample.B02, sample.B03, sample.B04, sample.B08];
}
"""


class SatelliteSourceUnavailable(RuntimeError):
    """The optional Copernicus data source could not satisfy a request."""


def _utc_datetime(value: str) -> datetime:
    """Parse an ISO timestamp and reject timestamps without a timezone."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Satellite scene timestamp has no timezone.")
    return parsed.astimezone(timezone.utc)


def _feature_date(value: date | str) -> date:
    if isinstance(value, datetime):
        raise ValueError("Prediction feature date must be a date without a time.")
    return value if isinstance(value, date) else date.fromisoformat(value)


class SatelliteService:
    """Find scene metadata while explicitly withholding unacquired pixels."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: float = 15.0,
        access_token: str | None = None,
    ):
        self.client_id = client_id if client_id is not None else os.getenv("CDSE_CLIENT_ID")
        self.client_secret = (
            client_secret if client_secret is not None else os.getenv("CDSE_CLIENT_SECRET")
        )
        self.access_token = (
            access_token if access_token is not None else os.getenv("CDSE_ACCESS_TOKEN")
        )
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._scene_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._scene_records: dict[str, dict[str, Any]] = {}
        self._preview_cache: dict[str, tuple[float, bytes, str]] = {}

    @staticmethod
    def _bbox(water_body: dict) -> list[float] | None:
        geometry = water_body.get("boundary")
        coordinates = (geometry or {}).get("coordinates")
        pairs: list[tuple[float, float]] = []

        def collect(value: Any) -> None:
            if not isinstance(value, (list, tuple)):
                return
            if len(value) >= 2 and all(isinstance(part, (int, float)) for part in value[:2]):
                longitude, latitude = float(value[0]), float(value[1])
                if -180 <= longitude <= 180 and -90 <= latitude <= 90:
                    pairs.append((longitude, latitude))
                return
            for child in value:
                collect(child)

        collect(coordinates)
        if not pairs:
            location = water_body.get("location") or water_body
            try:
                latitude = float(location["latitude"])
                longitude = float(location["longitude"])
            except (KeyError, TypeError, ValueError):
                return None
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                return None
            # A small catalogue-search window around the resolved point only.
            return [longitude - 0.01, latitude - 0.01, longitude + 0.01, latitude + 0.01]

        longitudes = [point[0] for point in pairs]
        latitudes = [point[1] for point in pairs]
        return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]

    def _access_token(self) -> str:
        if self.access_token and self.access_token.strip():
            return self.access_token.strip()
        now = time.monotonic()
        if self._token and now < self._token_expires_at - 30:
            return self._token
        if not self.client_id or not self.client_secret:
            raise SatelliteSourceUnavailable(MISSING_CREDENTIALS_MESSAGE)
        try:
            response = httpx.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SatelliteSourceUnavailable(
                "Copernicus OAuth authentication failed. Verify backend CDSE_CLIENT_ID "
                "and CDSE_CLIENT_SECRET."
            ) from exc
        token = payload.get("access_token")
        if not token:
            raise SatelliteSourceUnavailable("Copernicus OAuth did not return an access token.")
        self._token = str(token)
        self._token_expires_at = now + max(60, int(payload.get("expires_in", 300)))
        return self._token

    @property
    def credentials_configured(self) -> bool:
        return bool(
            (self.access_token and self.access_token.strip())
            or (self.client_id and self.client_secret)
        )

    def _search_scene(
        self, bbox: list[float], start: datetime, end: datetime
    ) -> dict[str, Any] | None:
        """Search public L2A metadata, then independently enforce the time range."""
        payload = {
            "collections": ["sentinel-2-l2a"],
            "bbox": bbox,
            "datetime": f"{start.isoformat()}/{end.isoformat()}",
            "limit": 50,
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            "fields": {"include": ["id", "properties.datetime", "properties.eo:cloud_cover"]},
        }
        response = httpx.post(
            STAC_SEARCH_URL,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        candidates = []
        for item in (response.json() or {}).get("features") or []:
            try:
                observed = _utc_datetime(str((item.get("properties") or {})["datetime"]))
            except (KeyError, TypeError, ValueError):
                continue
            if item.get("id") and start <= observed <= end:
                candidates.append((observed, item))
        return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else None

    def _search_latest_scene(self, bbox: list[float]) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        return self._search_scene(bbox, now - timedelta(days=30), now)

    def _search_aligned_scene(
        self, bbox: list[float], feature_date: date
    ) -> dict[str, Any] | None:
        start = datetime.combine(
            feature_date - timedelta(days=MAX_MODEL_SCENE_AGE_DAYS),
            datetime.min.time(), tzinfo=timezone.utc,
        )
        end = min(
            datetime.combine(feature_date, datetime.max.time(), tzinfo=timezone.utc),
            datetime.now(timezone.utc),
        )
        return self._search_scene(bbox, start, end) if start <= end else None

    def coverage(self, water_body: dict, feature_date: date | str | None = None) -> dict:
        body_id = str(water_body.get("id") or "")
        try:
            aligned_date = _feature_date(feature_date) if feature_date is not None else None
        except (TypeError, ValueError) as exc:
            raise SatelliteSourceUnavailable("Prediction feature date is invalid.") from exc
        cache_key = f"{body_id}:{aligned_date.isoformat() if aligned_date else 'latest'}"
        cached = self._scene_cache.get(cache_key)
        now = time.monotonic()
        if cached and now < cached[0]:
            return dict(cached[1])

        contract_attested = os.getenv(
            "HAB_SATELLITE_INPUT_CONTRACT_VERIFIED", ""
        ).strip().casefold() in {"1", "true", "yes"}
        credentials_configured = self.credentials_configured
        base = {
            "available": False,
            "image_available": False,
            "scene_metadata_available": False,
            "source": CATALOG_SOURCE,
            "observation_date": None,
            "scene_datetime": None,
            "feature_date": aligned_date.isoformat() if aligned_date else None,
            "scene_cloud_cover_percent": None,
            "scene_cloud_cover_scope": "Sentinel-2 product footprint; not lake-specific",
            "preview_available": False,
            "preview_requires_backend_credentials": not credentials_configured,
            "boundary_available": bool(water_body.get("boundary_available")),
            "model_compatible": False,
            "model_input_contract_verified": False,
            "model_input_contract_attested": contract_attested,
            "model_ingestion_ready": False,
        }
        bbox = self._bbox(water_body)
        if bbox is None:
            base.update({
                "status": "water_body_geometry_unavailable",
                "message": "Satellite scene search needs a water-body boundary or resolved catalogue location.",
            })
            return base

        try:
            scene = (
                self._search_aligned_scene(bbox, aligned_date)
                if aligned_date else self._search_latest_scene(bbox)
            )
        except (httpx.HTTPError, ValueError, RuntimeError):
            base.update({
                "status": "provider_unavailable",
                "message": "The public Copernicus Sentinel-2 catalogue is temporarily unavailable.",
            })
            return base

        if scene is None:
            base.update({
                "status": "no_recent_scene_found",
                "message": (
                    "No Sentinel-2 L2A scene was found from five days before the "
                    "prediction feature date through that date."
                    if aligned_date else
                    "No Sentinel-2 L2A scene was found for this search area in the last 30 days."
                ),
            })
            self._scene_cache[cache_key] = (now + CACHE_SECONDS, base)
            return base

        properties = scene.get("properties") or {}
        observed = str(properties.get("datetime") or "")
        scene_id = str(scene.get("id") or "")
        base.update({
            "scene_metadata_available": True,
            "status": "scene_metadata_found",
            "scene_id": scene_id or None,
            "scene_catalog_url": (
                f"https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a/items/{quote(scene_id, safe='')}"
                if scene_id else None
            ),
            "observation_date": observed[:10] or None,
            "scene_datetime": observed or None,
            "scene_cloud_cover_percent": properties.get("eo:cloud_cover"),
            "preview_available": credentials_configured,
            "model_ingestion_ready": credentials_configured and contract_attested,
            "message": (
                f"Sentinel-2 scene metadata found for {observed[:10] or 'a recent date'}. "
                + (
                    "A display preview can be fetched on request; preview pixels are not model inputs."
                    if credentials_configured
                    else "Only scene metadata is available; preview pixels require backend-only CDSE credentials. "
                    + MISSING_CREDENTIALS_MESSAGE
                )
            ),
        })
        self._scene_records[body_id] = scene
        self._scene_cache[cache_key] = (now + CACHE_SECONDS, base)
        return dict(base)

    def preview(self, water_body: dict) -> tuple[bytes, str]:
        """Fetch and cache a 512 px RGB preview for the latest located scene."""
        body_id = str(water_body.get("id") or "")
        cached = self._preview_cache.get(body_id)
        now = time.monotonic()
        if cached and now < cached[0]:
            return cached[1], cached[2]

        status = self.coverage(water_body)
        if not status.get("scene_metadata_available"):
            raise SatelliteSourceUnavailable(status.get("message", "No recent satellite scene is available."))
        if not self.credentials_configured:
            raise SatelliteSourceUnavailable(
                "Public scene metadata is available, but image preview pixels require backend-only Copernicus Data Space credentials. "
                + MISSING_CREDENTIALS_MESSAGE
            )
        bbox = self._bbox(water_body)
        if bbox is None:
            raise SatelliteSourceUnavailable("Satellite preview needs a resolved water-body boundary or location.")

        observation_date = status.get("observation_date")
        if not observation_date:
            raise SatelliteSourceUnavailable("The satellite catalogue result has no acquisition date.")

        min_lon, min_lat, max_lon, max_lat = bbox
        mid_latitude = (min_lat + max_lat) / 2
        aspect = (
            (max_lon - min_lon) * max(0.05, abs(math.cos(math.radians(mid_latitude))))
        ) / max(max_lat - min_lat, 1e-9)
        if aspect >= 1:
            width, height = 512, max(128, min(512, round(512 / aspect)))
        else:
            height, width = 512, max(128, min(512, round(512 * aspect)))

        token = self._access_token()
        request_payload = {
            "input": {
                "bounds": {
                    "bbox": bbox,
                    "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
                },
                "data": [{
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": f"{observation_date}T00:00:00Z",
                            "to": f"{observation_date}T23:59:59Z",
                        },
                        "mosaickingOrder": "mostRecent",
                    },
                    "processing": {"harmonizeValues": "true"},
                }],
            },
            "output": {
                "width": width,
                "height": height,
                "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
            },
            "evalscript": RGB_PREVIEW_EVALSCRIPT,
        }
        try:
            response = httpx.post(
                PROCESS_URL,
                json=request_payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SatelliteSourceUnavailable(
                "Copernicus could not return the satellite preview for this water body."
            ) from exc

        content = response.content
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SatelliteSourceUnavailable("Copernicus returned an unexpected preview image format.")
        self._preview_cache[body_id] = (now + CACHE_SECONDS, content, observation_date)
        return content, observation_date

    def fetch_model_raster(
        self,
        water_body: dict,
        *,
        feature_date: date | str,
        scene_coverage: dict | None = None,
        cache_dir: str | Path | None = None,
    ) -> dict:
        """Acquire a four-band, unmasked UINT16 GeoTIFF in the CNN band order.

        This creates a model-shaped source raster but does not assert that the
        model is scientifically valid for the selected water body. Callers
        must enforce per-water-body model validation and complete LSTM inputs.
        """
        if not self.credentials_configured:
            raise SatelliteSourceUnavailable(MISSING_CREDENTIALS_MESSAGE)
        try:
            feature_day = _feature_date(feature_date)
        except (TypeError, ValueError) as exc:
            raise SatelliteSourceUnavailable("Prediction feature date is invalid.") from exc
        body_id = str(water_body.get("id") or "")
        status = scene_coverage or self.coverage(water_body, feature_date=feature_day)
        if not status.get("scene_metadata_available"):
            raise SatelliteSourceUnavailable(status.get("message", "No aligned satellite scene is available."))
        if status.get("feature_date") != feature_day.isoformat():
            raise SatelliteSourceUnavailable("Selected satellite scene was not searched for the prediction feature date.")
        scene_id = str(status.get("scene_id") or "")
        try:
            scene_time = _utc_datetime(str(status["scene_datetime"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise SatelliteSourceUnavailable("Selected satellite scene has no valid acquisition timestamp.") from exc
        if not scene_id or (feature_day - scene_time.date()).days not in range(MAX_MODEL_SCENE_AGE_DAYS + 1):
            raise SatelliteSourceUnavailable("Selected satellite scene is outside the feature-date alignment window.")
        if scene_time > datetime.now(timezone.utc):
            raise SatelliteSourceUnavailable("Selected satellite scene is in the future.")
        bbox = self._bbox(water_body)
        if bbox is None:
            raise SatelliteSourceUnavailable("Satellite raster ingestion needs a resolved water-body ROI.")

        observed = scene_time.date().isoformat()
        if status.get("observation_date") != observed:
            raise SatelliteSourceUnavailable("Selected satellite scene has inconsistent acquisition dates.")
        earliest = datetime.combine(
            feature_day - timedelta(days=MAX_MODEL_SCENE_AGE_DAYS),
            datetime.min.time(), tzinfo=timezone.utc,
        )
        latest = min(
            datetime.combine(feature_day, datetime.max.time(), tzinfo=timezone.utc),
            datetime.now(timezone.utc),
        )
        request_start = max(scene_time - timedelta(minutes=1), earliest)
        request_end = min(scene_time + timedelta(minutes=1), latest)
        if request_start >= request_end:
            raise SatelliteSourceUnavailable("Selected satellite scene has no valid acquisition interval.")
        time_range = {
            "from": request_start.isoformat().replace("+00:00", "Z"),
            "to": request_end.isoformat().replace("+00:00", "Z"),
        }

        cache_root = Path(cache_dir or os.getenv(
            "HAB_SATELLITE_CACHE", "~/.cache/algaewatch/sentinel2"
        )).expanduser()
        body_key = hashlib.sha256(f"{body_id}:{scene_id}".encode("utf-8")).hexdigest()[:20]
        target = cache_root / f"{body_key}_{observed}.tif"
        try:
            import numpy as np
            import rasterio
            from rasterio.io import MemoryFile
            from rasterio.transform import from_bounds
        except ModuleNotFoundError as exc:
            raise SatelliteSourceUnavailable(
                "Satellite raster validation requires the project's Rasterio and NumPy dependencies."
            ) from exc

        if target.is_file():
            try:
                with rasterio.open(target) as existing:
                    if (
                        existing.count == 4
                        and all(dtype == "uint16" for dtype in existing.dtypes)
                        and existing.descriptions == ("B2", "B3", "B4", "B8")
                        and existing.tags().get("scene_id") == scene_id
                        and existing.tags().get("feature_date") == feature_day.isoformat()
                    ):
                        return {
                            "local_path": str(target),
                            "observation_date": observed,
                            "scene_id": scene_id,
                            "source": SOURCE,
                            "band_order": ["B2", "B3", "B4", "B8"],
                            "sample_type": "UINT16 DN, harmonized",
                            "cloud_mask_applied": False,
                            "model_input_contract_verified": True,
                        }
            except rasterio.errors.RasterioError:
                target.unlink(missing_ok=True)

        min_lon, min_lat, max_lon, max_lat = bbox
        if not (min_lon < max_lon and min_lat < max_lat):
            raise SatelliteSourceUnavailable("The water-body ROI is too small or invalid for satellite raster export.")

        # The inspected archive uses a WGS84 grid close to 10 m at the equator.
        # Keep that grid convention and include the final edge pixel as in the
        # original rectangular Earth Engine exports.
        degrees_per_pixel = 10.0 / 111319.49079327358
        width = max(1, math.ceil((max_lon - min_lon) / degrees_per_pixel) + 1)
        height = max(1, math.ceil((max_lat - min_lat) / degrees_per_pixel) + 1)
        tile_size = 2400  # below the Process API's documented 2500 px side limit
        columns = math.ceil(width / tile_size)
        rows = math.ceil(height / tile_size)
        if columns * rows > 16:
            raise SatelliteSourceUnavailable(
                "The water-body ROI is too large for safe synchronous satellite acquisition."
            )

        token = self._access_token()
        values = np.empty((4, height, width), dtype=np.uint16)
        for row_start in range(0, height, tile_size):
            row_end = min(height, row_start + tile_size)
            tile_top = max_lat - (max_lat - min_lat) * row_start / height
            tile_bottom = max_lat - (max_lat - min_lat) * row_end / height
            for col_start in range(0, width, tile_size):
                col_end = min(width, col_start + tile_size)
                tile_left = min_lon + (max_lon - min_lon) * col_start / width
                tile_right = min_lon + (max_lon - min_lon) * col_end / width
                payload = {
                    "input": {
                        "bounds": {
                            "bbox": [tile_left, tile_bottom, tile_right, tile_top],
                            "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
                        },
                        "data": [{
                            "type": "sentinel-2-l2a",
                            "dataFilter": {
                                "timeRange": {
                                        **time_range,
                                },
                                "mosaickingOrder": "mostRecent",
                            },
                            "processing": {"harmonizeValues": "true"},
                        }],
                    },
                    "output": {
                        "width": col_end - col_start,
                        "height": row_end - row_start,
                        "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
                    },
                    "evalscript": CNN_INPUT_EVALSCRIPT,
                }
                try:
                    response = httpx.post(
                        PROCESS_URL,
                        json=payload,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=max(self.timeout, 60.0),
                    )
                    response.raise_for_status()
                    with MemoryFile(response.content) as memory:
                        with memory.open() as src:
                            if src.count != 4 or any(dtype != "uint16" for dtype in src.dtypes):
                                raise SatelliteSourceUnavailable(
                                    "Copernicus returned raster bands or types that do not match the CNN input contract."
                                )
                            if (src.height, src.width) != (row_end - row_start, col_end - col_start):
                                raise SatelliteSourceUnavailable(
                                    "Copernicus returned a raster with unexpected dimensions."
                                )
                            values[:, row_start:row_end, col_start:col_end] = src.read()
                except SatelliteSourceUnavailable:
                    raise
                except (httpx.HTTPError, rasterio.errors.RasterioError) as exc:
                    raise SatelliteSourceUnavailable(
                        "Copernicus could not return a model-contract satellite raster for this water body."
                    ) from exc

        if not np.any(values):
            raise SatelliteSourceUnavailable(
                "Copernicus returned no nonzero B2/B3/B4/B8 pixels for the selected scene and ROI."
            )
        cache_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temp_name = tempfile.mkstemp(prefix=f"{body_key}_", suffix=".tif", dir=cache_root)
        os.close(fd)
        try:
            profile = {
                "driver": "GTiff",
                "width": width,
                "height": height,
                "count": 4,
                "dtype": "uint16",
                "crs": "EPSG:4326",
                "transform": from_bounds(min_lon, min_lat, max_lon, max_lat, width, height),
                "compress": "deflate",
            }
            with rasterio.open(temp_name, "w", **profile) as dst:
                dst.write(values)
                for band_number, name in enumerate(("B2", "B3", "B4", "B8"), start=1):
                    dst.set_band_description(band_number, name)
                dst.update_tags(
                    satellite_source="Copernicus Data Space Sentinel-2 L2A",
                    acquisition_date=observed,
                    scene_id=scene_id,
                    feature_date=feature_day.isoformat(),
                    input_band_order="B2,B3,B4,B8",
                    value_units="harmonized DN; Sentinel-2 optical DN = 10000 x reflectance",
                    cloud_mask_applied="false",
                    roi="water-body bounding box from catalogue boundary",
                )
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

        return {
            "local_path": str(target),
            "observation_date": observed,
            "scene_id": scene_id,
            "source": SOURCE,
            "band_order": ["B2", "B3", "B4", "B8"],
            "sample_type": "UINT16 DN, harmonized",
            "cloud_mask_applied": False,
            "model_input_contract_verified": True,
        }
