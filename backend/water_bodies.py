"""Karnataka water-body lookup backed by the public K-GIS ArcGIS service."""

from __future__ import annotations

import math
import re
from typing import Any

import httpx


LAYER_URL = (
    "https://kgis.ksrsac.in/kgismaps2/rest/services/Tank/"
    "Tank_Ownership/MapServer/1"
)
SOURCE_NAME = "Karnataka GIS (K-GIS) Tank Ownership layer"
SOURCE_URL = LAYER_URL
SOURCE_DATASET = "Tank_Ownership · Karnataka K-GIS"
MODEL_STATUS = "data_model_validation_required"
OUT_FIELDS = (
    "UniqueTankID,TankName,KGISTankID,KGISDistrictName,KGISTalukName,"
    "KGISHobliName,KGISVillageName,Latitude,Longitude,TankArea_Ha"
)
ID_PATTERN = re.compile(r"^KA[A-Z0-9]+$", re.IGNORECASE)


class WaterBodySourceUnavailable(RuntimeError):
    """The Karnataka source service could not answer a request."""


class WaterBodyNotFound(LookupError):
    """The requested ID is not in the Karnataka source layer."""


class InvalidWaterBodyQuery(ValueError):
    """The search query is empty, too short, or contains unsupported characters."""


class KarnatakaWaterBodyService:
    """Resolve named Karnataka tank/lake records from K-GIS.

    K-GIS publishes polygon geometry and administrative IDs. The search path
    requests attributes only; the selected-record path fetches the boundary.
    Coordinates come from the source or its boundary; users never enter them.
    """

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout

    def _query(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.get(f"{LAYER_URL}/query", params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WaterBodySourceUnavailable(
                "The Karnataka water-body catalogue service is temporarily unavailable."
            ) from exc
        if payload.get("error"):
            detail = payload["error"].get("message", "K-GIS query failed")
            raise WaterBodySourceUnavailable(
                f"The Karnataka water-body catalogue service returned an error: {detail}"
            )
        return payload

    @staticmethod
    def _valid_coordinate_pair(latitude: Any, longitude: Any) -> tuple[float, float] | None:
        try:
            lat, lon = float(latitude), float(longitude)
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(lat) and math.isfinite(lon)):
            return None
        # Loose Karnataka envelope used to reject malformed/out-of-state records.
        if not (10.5 <= lat <= 19.0 and 72.5 <= lon <= 79.0):
            return None
        return lat, lon

    @staticmethod
    def _record(feature: dict[str, Any]) -> dict[str, Any] | None:
        attributes = feature.get("attributes") or feature.get("properties") or {}
        identifier = str(attributes.get("UniqueTankID") or "").strip()
        name = " ".join(str(attributes.get("TankName") or "").split())
        if not identifier or not name:
            return None

        coordinates = KarnatakaWaterBodyService._valid_coordinate_pair(
            attributes.get("Latitude"), attributes.get("Longitude")
        )
        latitude, longitude = coordinates if coordinates else (None, None)
        try:
            area_ha = float(attributes["TankArea_Ha"])
            if not math.isfinite(area_ha) or area_ha < 0:
                area_ha = None
        except (KeyError, TypeError, ValueError):
            area_ha = None

        return {
            "id": identifier,
            "lake_id": identifier,  # compatibility for the current frontend until Phase 3
            "name": name,
            "district": attributes.get("KGISDistrictName"),
            "taluk": attributes.get("KGISTalukName"),
            "hobli": attributes.get("KGISHobliName"),
            "village": attributes.get("KGISVillageName"),
            "state": "Karnataka",
            "latitude": latitude,
            "longitude": longitude,
            "area_ha": area_ha,
            "source_record_id": attributes.get("KGISTankID"),
            "boundary_available": True,
            "location_resolved": coordinates is not None,
            "model_supported": False,
            "model_status": MODEL_STATUS,
            "model_validation_status": "data_model_validation_required",
            "catalog_source": SOURCE_NAME,
        }

    def search_page(self, query: str, limit: int = 25, offset: int = 0) -> dict[str, Any]:
        text = query.strip()
        if len(text) < 2 or len(text) > 80:
            raise InvalidWaterBodyQuery("Enter 2–80 characters to search the Karnataka catalogue.")
        if any(char in text for char in ("%", "_", "\x00", ";")):
            raise InvalidWaterBodyQuery("Search using a water-body name without wildcard characters.")
        if not 1 <= limit <= 50:
            raise InvalidWaterBodyQuery("Search result limit must be between 1 and 50.")
        if not 0 <= offset <= 100_000:
            raise InvalidWaterBodyQuery("Search offset must be between 0 and 100,000.")

        # Use one distinctive ArcGIS predicate: multi-predicate searches are
        # rejected by the source's WAF. Match remaining tokens locally below.
        tokens = re.findall(r"[^\W_]+", text.upper(), flags=re.UNICODE)
        if not tokens:
            raise InvalidWaterBodyQuery("Search using a water-body name or name fragment.")
        source_token = max(tokens, key=len)
        source_offset = offset
        items: list[dict[str, Any]] = []
        # Scan every source page needed to fill a result page. The provider can
        # return many names containing the longest token before a multiword
        # match, so a single capped query silently misses valid lakes.
        while True:
            payload = self._query({
                "where": f"TankName IS NOT NULL AND UPPER(TankName) LIKE '%{source_token}%'",
                "outFields": OUT_FIELDS,
                "returnGeometry": "false",
                "orderByFields": "TankName ASC, UniqueTankID ASC",
                "resultOffset": source_offset,
                "resultRecordCount": 200,
                "f": "json",
            })
            features = payload.get("features") or []
            for feature in features:
                record = self._record(feature)
                source_offset += 1
                normalized_name = (
                    " ".join(re.findall(r"[^\W_]+", record["name"].upper(), flags=re.UNICODE))
                    if record else ""
                )
                if record and all(token in normalized_name for token in tokens):
                    if len(items) == limit:
                        return {"items": items, "next_offset": source_offset - 1, "has_more": True}
                    items.append(record)
            if not features or not payload.get("exceededTransferLimit", False):
                return {"items": items, "next_offset": None, "has_more": False}

    def search(self, query: str, limit: int = 25) -> list[dict[str, Any]]:
        """Compatibility wrapper for callers that only need the first page."""
        return self.search_page(query, limit)["items"]

    @staticmethod
    def _boundary_center(geometry: dict[str, Any]) -> tuple[float, float] | None:
        points: list[tuple[float, float]] = []

        def collect(value: Any) -> None:
            if not isinstance(value, list):
                return
            if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
                pair = KarnatakaWaterBodyService._valid_coordinate_pair(value[1], value[0])
                if pair:
                    points.append(pair)
            else:
                for child in value:
                    collect(child)

        collect(geometry.get("coordinates"))
        if not points:
            return None
        return (
            (min(lat for lat, _ in points) + max(lat for lat, _ in points)) / 2,
            (min(lon for _, lon in points) + max(lon for _, lon in points)) / 2,
        )

    def get(self, water_body_id: str) -> dict[str, Any]:
        identifier = water_body_id.strip().upper()
        if not ID_PATTERN.fullmatch(identifier):
            raise WaterBodyNotFound("Water body not found in the Karnataka catalogue.")

        payload = self._query({
            "where": f"UniqueTankID = '{identifier}'",
            "outFields": OUT_FIELDS,
            "returnGeometry": "true",
            "outSR": 4326,
            "f": "geojson",
        })
        features = payload.get("features") or []
        if not features:
            raise WaterBodyNotFound("Water body not found in the Karnataka catalogue.")

        feature = features[0]
        record = self._record(feature)
        if not record:
            raise WaterBodySourceUnavailable(
                "This catalogue record is missing a name or usable location."
            )
        geometry = feature.get("geometry")
        record["boundary"] = geometry if geometry and geometry.get("type") in {
            "Polygon", "MultiPolygon"
        } else None
        record["boundary_available"] = record["boundary"] is not None
        if not record["location_resolved"] and record["boundary"]:
            center = self._boundary_center(record["boundary"])
            if center:
                record["latitude"], record["longitude"] = center
                record["location_resolved"] = True
        return record

    def count_named(self) -> int:
        payload = self._query({
            "where": "TankName IS NOT NULL",
            "returnCountOnly": "true",
            "f": "json",
        })
        return int(payload.get("count", 0))
