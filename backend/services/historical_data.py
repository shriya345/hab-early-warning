"""Read-only display access to downloaded Karnataka research snapshots."""

from __future__ import annotations

import csv
from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "outputs/karnataka_open_data_pilot"
KGIS_ID = re.compile(r"^KA[0-9]{8}$")
BANDS = ("B2", "B3", "B4", "B8")
WEATHER_FIELDS = ("rain_sum", "precipitation_sum", "wind_speed_10m_mean",
                  "wind_speed_10m_max")
EARTH_SEARCH_COLLECTION = "https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a"
OPEN_METEO_DOCS = "https://open-meteo.com/en/docs/historical-weather-api"


class HistoricalDataError(RuntimeError):
    """A saved research snapshot is incomplete or unreadable."""


class HistoricalDataService:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.getenv("HAB_HISTORICAL_DATA_DIR", DEFAULT_ROOT)).expanduser()

    def _bundle(self, kgis_id: str) -> tuple[Path, dict] | None:
        identifier = kgis_id.strip().upper()
        if not KGIS_ID.fullmatch(identifier):
            return None
        candidates: list[tuple[date, Path]] = []
        for folder in self.root.glob(f"{identifier}_????-??-??"):
            if not folder.is_dir():
                continue
            try:
                day = date.fromisoformat(folder.name[len(identifier) + 1:])
            except ValueError:
                continue
            if day <= date.today():
                candidates.append((day, folder))
        if not candidates:
            return None
        _, folder = max(candidates)
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HistoricalDataError("The saved historical manifest could not be read.") from exc
        if (manifest.get("kgis_id") != identifier
                or manifest.get("feature_date") != folder.name[len(identifier) + 1:]
                or manifest.get("status") != "research_data_only_not_model_ready"
                or manifest.get("prediction_allowed") is not False
                or (manifest.get("raster") or {}).get("band_order") != list(BANDS)):
            raise HistoricalDataError("The saved historical manifest does not match this lake and raster.")
        return folder, manifest

    @staticmethod
    def _raster_info(folder: Path, manifest: dict) -> dict:
        import numpy as np
        import rasterio

        raster_path = folder / "sentinel2_B2_B3_B4_B8_raw_dn.tif"
        try:
            with rasterio.open(raster_path) as image:
                if (image.count != 4 or image.descriptions != BANDS
                        or image.dtypes != ("uint16",) * 4):
                    raise HistoricalDataError("The saved historical raster has the wrong band contract.")
                pixels = image.read()
                valid = int(np.all(pixels > 0, axis=0).sum())
                width, height = image.width, image.height
        except (OSError, rasterio.errors.RasterioError) as exc:
            raise HistoricalDataError("The saved historical raster could not be read.") from exc
        if valid <= 0 or valid != (manifest.get("raster") or {}).get("valid_four_band_polygon_pixel_count"):
            raise HistoricalDataError("The saved historical raster pixel count does not match its manifest.")
        return {"valid_polygon_pixels": valid, "width": width, "height": height,
                "path": raster_path}

    @staticmethod
    def _weather_rows(folder: Path, manifest: dict) -> list[dict]:
        try:
            with (folder / "historical_weather_era5.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
        except OSError as exc:
            raise HistoricalDataError("The saved historical weather file could not be read.") from exc
        feature_date = date.fromisoformat(manifest["feature_date"])
        expected = [(feature_date - timedelta(days=6) + timedelta(days=i)).isoformat()
                    for i in range(12)]
        if [row.get("date") for row in rows] != expected:
            raise HistoricalDataError("The historical weather dates do not match the satellite date.")
        clean = []
        for row in rows:
            try:
                values = {field: float(row[field]) for field in WEATHER_FIELDS}
            except (KeyError, TypeError, ValueError) as exc:
                raise HistoricalDataError("A historical weather value is missing or invalid.") from exc
            if not all(math.isfinite(value) for value in values.values()):
                raise HistoricalDataError("A historical weather value is not finite.")
            clean.append({"date": row["date"], **values})
        return clean

    def snapshot(self, kgis_id: str) -> dict:
        bundle = self._bundle(kgis_id)
        if bundle is None:
            return {
                "available": False,
                "kgis_id": kgis_id.strip().upper(),
                "message": "No downloaded historical research snapshot is stored for this water body.",
            }
        folder, manifest = bundle
        raster = self._raster_info(folder, manifest)
        weather = self._weather_rows(folder, manifest)
        scene_classes = (manifest.get("raster") or {}).get("scene_classification_counts_inside_polygon") or {}
        water_pixels = int(scene_classes.get("6", 0))
        polygon_pixels = int((manifest.get("raster") or {}).get("lake_polygon_pixel_count", 0))
        scene_id = str(manifest.get("scene_id") or "")
        return {
            "available": True,
            "type": "historical_research_snapshot",
            "kgis_id": manifest["kgis_id"],
            "lake_name": manifest["lake_name"],
            "scene_date": manifest["feature_date"],
            "scene_datetime": manifest["scene_datetime"],
            "scene_id": scene_id,
            "scene_footprint_cloud_percent": manifest["scene_footprint_cloud_percent"],
            "satellite": {
                "band_order": list(BANDS),
                "raw_dn": True,
                "resolution_metres": 10,
                "width": raster["width"],
                "height": raster["height"],
                "valid_four_band_polygon_pixels": raster["valid_polygon_pixels"],
                "scl_water_pixels": water_pixels,
                "scl_water_fraction": water_pixels / polygon_pixels if polygon_pixels else None,
                "scene_classification_counts": scene_classes,
                "source": "Element 84 Earth Search · Sentinel-2 Collection 1 L2A COG",
                "source_url": f"{EARTH_SEARCH_COLLECTION}/items/{scene_id}",
                "image_url": f"/water-bodies/{manifest['kgis_id']}/historical/true-color",
                "raster_download_url": f"/water-bodies/{manifest['kgis_id']}/historical/raster",
                "display_note": "True-colour display uses a fixed reflectance stretch; the original four-band file remains raw source DN.",
            },
            "weather": {
                "source": "Open-Meteo Historical Weather API · ERA5",
                "source_url": OPEN_METEO_DOCS,
                "rows": weather,
                "units": {"rain_sum": "mm/day", "precipitation_sum": "mm/day",
                          "wind_speed_10m_mean": "m/s", "wind_speed_10m_max": "m/s"},
                "note": "Historical gridded weather near the lake, not in-lake measurements or validated model inputs.",
            },
            "model_input_eligible": False,
            "missing_for_live_prediction": [
                "Current lake imagery",
                "Seven daily lake chlorophyll-a observations",
                "Seven daily lake surface temperature observations",
                "Verified raster and weather preprocessing compatibility",
                "Karnataka lake/model validation",
            ],
            "note": "Historical real-data snapshot for exploration. This is not a live bloom forecast.",
        }

    def raster_path(self, kgis_id: str) -> Path | None:
        bundle = self._bundle(kgis_id)
        if bundle is None:
            return None
        folder, manifest = bundle
        return self._raster_info(folder, manifest)["path"]

    def analyze(self, kgis_id: str) -> dict | None:
        """Summarize saved observations without creating a bloom prediction."""
        bundle = self._bundle(kgis_id)
        if bundle is None:
            return None
        folder, manifest = bundle
        raster_info = self._raster_info(folder, manifest)
        weather = self._weather_rows(folder, manifest)
        import numpy as np
        import rasterio

        bands = (manifest.get("raster") or {}).get("bands") or []
        if (len(bands) != 4 or [band.get("band") for band in bands] != list(BANDS)
                or any(band.get("stac_scale") != 0.0001 or band.get("stac_offset") != -0.1
                       for band in bands)):
            raise HistoricalDataError("Historical raster reflectance scaling is unverified.")
        with rasterio.open(raster_info["path"]) as image:
            raw = image.read()
        valid = np.all(raw > 0, axis=0)
        reflectance = raw.astype("float32") * 0.0001 - 0.1
        band_medians = {
            band: round(float(np.median(reflectance[index][valid])), 5)
            for index, band in enumerate(BANDS)
        }

        scene_day = manifest["feature_date"]
        preceding = [row for row in weather if row["date"] <= scene_day]
        if len(preceding) != 7 or preceding[-1]["date"] != scene_day:
            raise HistoricalDataError("The seven historical weather dates are incomplete.")
        scene_classes = (manifest.get("raster") or {}).get("scene_classification_counts_inside_polygon") or {}
        polygon_pixels = int((manifest.get("raster") or {}).get("lake_polygon_pixel_count", 0))
        water_pixels = int(scene_classes.get("6", 0))
        return {
            "type": "dated_observation_analysis",
            "water_body_id": manifest["kgis_id"],
            "lake_name": manifest["lake_name"],
            "observation_date": scene_day,
            "live": False,
            "bloom_probability": None,
            "satellite": {
                "source": "Sentinel-2 L2A",
                "band_order": list(BANDS),
                "median_surface_reflectance_inside_boundary": band_medians,
                "valid_four_band_pixels": raster_info["valid_polygon_pixels"],
                "scl_water_pixels": water_pixels,
                "scl_water_fraction": water_pixels / polygon_pixels if polygon_pixels else None,
                "scene_footprint_cloud_percent": manifest["scene_footprint_cloud_percent"],
                "reflectance_note": "Medians use all valid pixels inside the K-GIS boundary. STAC scale and offset were applied; values are not chlorophyll measurements.",
            },
            "weather": {
                "source": "ERA5 via Open-Meteo Historical Weather API",
                "start_date": preceding[0]["date"],
                "end_date": preceding[-1]["date"],
                "days": len(preceding),
                "rainfall_total_mm": round(sum(row["rain_sum"] for row in preceding), 2),
                "precipitation_total_mm": round(sum(row["precipitation_sum"] for row in preceding), 2),
                "mean_wind_speed_mps": round(sum(row["wind_speed_10m_mean"] for row in preceding) / 7, 2),
                "highest_daily_max_wind_speed_mps": round(max(row["wind_speed_10m_max"] for row in preceding), 2),
                "note": "Gridded historical estimates near the lake, not in-lake measurements.",
            },
            "interpretation": (
                "Dated satellite and weather summary only. Daily lake chlorophyll-a, lake surface "
                "temperature, and Karnataka model validation are missing, so no bloom-risk "
                "probability can be calculated from these records."
            ),
        }

    def true_color_png(self, kgis_id: str) -> bytes | None:
        bundle = self._bundle(kgis_id)
        if bundle is None:
            return None
        folder, manifest = bundle
        path = self._raster_info(folder, manifest)["path"]
        import cv2
        import numpy as np
        import rasterio

        with rasterio.open(path) as image:
            raw = image.read()
        valid = np.all(raw > 0, axis=0)
        # Element 84 COG STAC metadata for these saved scenes: scale 0.0001,
        # offset -0.1. This is a display conversion only, not model input.
        band_metadata = (manifest.get("raster") or {}).get("bands") or []
        if (len(band_metadata) != 4 or
                any(band.get("stac_scale") != 0.0001 or band.get("stac_offset") != -0.1
                    for band in band_metadata)):
            raise HistoricalDataError("Historical raster display scaling is unverified.")
        reflectance = np.maximum(raw.astype("float32") * 0.0001 - 0.1, 0)
        rgb = np.moveaxis(reflectance[[2, 1, 0]], 0, -1)
        display = (np.clip(rgb / 0.3, 0, 1) ** 0.9 * 255).astype("uint8")
        rgba = np.concatenate([display, (valid.astype("uint8") * 255)[..., None]], axis=2)
        bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
        ok, encoded = cv2.imencode(".png", bgra)
        if not ok:
            raise HistoricalDataError("The historical image preview could not be rendered.")
        return encoded.tobytes()
