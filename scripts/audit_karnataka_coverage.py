"""Inventory named K-GIS lakes without treating catalogue hits as model data.

This script checks basic polygon availability and any previously downloaded,
pixel-checked research-pilot files. It does not fetch external observations;
public product/scene metadata are not counted as actual lake pixels.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import httpx
import numpy as np
import rasterio

from backend.water_bodies import LAYER_URL, OUT_FIELDS, KarnatakaWaterBodyService


FIELDS = (
    "kgis_id", "lake_name", "district", "area", "geometry_status",
    "satellite_dates", "chlorophyll_dates", "lswt_dates", "rainfall_dates",
    "wind_dates", "usable_periods", "missing_variables", "quality_flags",
)
PAGE_SIZE = 200


def load_pilot_evidence(root: Path) -> dict[str, dict]:
    """Accept dated pilot pixels only after reopening their local raster."""
    evidence = {}
    for manifest_path in root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            identifier = manifest["kgis_id"]
            day = manifest["feature_date"]
            raster = manifest["raster"]
            if (manifest["status"] != "research_data_only_not_model_ready"
                    or manifest["prediction_allowed"] is not False
                    or raster["band_order"] != ["B2", "B3", "B4", "B8"]):
                continue
            raster_path = manifest_path.parent / "sentinel2_B2_B3_B4_B8_raw_dn.tif"
            with rasterio.open(raster_path) as image:
                if (image.count != 4 or image.descriptions != ("B2", "B3", "B4", "B8")
                        or image.dtypes != ("uint16",) * 4):
                    continue
                pixels = image.read()
                valid = int(np.all(pixels > 0, axis=0).sum())
            if valid != raster["valid_four_band_polygon_pixel_count"] or valid <= 0:
                continue
            weather_path = manifest_path.parent / "historical_weather_era5.csv"
            with weather_path.open(newline="", encoding="utf-8") as stream:
                weather = list(csv.DictReader(stream))
            dates = [row["date"] for row in weather]
            if dates != manifest["weather"]["dates"] or len(dates) != 12:
                continue
            if any(not row["rain_sum"] or not row["wind_speed_10m_mean"]
                   for row in weather):
                continue
            evidence[identifier] = {
                "satellite_dates": day,
                "rainfall_dates": f"{dates[0]}..{dates[-1]}",
                "wind_dates": f"{dates[0]}..{dates[-1]}",
                "valid_pixels": valid,
                "scl_water_pixels": int(raster["scene_classification_counts_inside_polygon"].get("6", 0)),
            }
        except (OSError, KeyError, TypeError, ValueError, rasterio.errors.RasterioError):
            continue
    return evidence


def _rings(geometry: dict) -> list[list]:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        return coordinates[:1]
    if kind == "MultiPolygon":
        return [polygon[0] for polygon in coordinates if polygon]
    return []


def basic_polygon_available(geometry: dict | None) -> bool:
    """Check the coordinate structure, not topological or water-mask validity."""
    if not isinstance(geometry, dict):
        return False
    rings = _rings(geometry)
    for ring in rings:
        if len(ring) < 4:
            continue
        try:
            pairs = [(float(point[0]), float(point[1])) for point in ring]
        except (IndexError, TypeError, ValueError):
            continue
        if (len(set(pairs)) >= 3 and
                all(math.isfinite(lon) and math.isfinite(lat) and
                    72.5 <= lon <= 79.0 and 10.5 <= lat <= 19.0
                    for lon, lat in pairs)):
            return True
    return False


def audit_row(feature: dict) -> dict | None:
    record = KarnatakaWaterBodyService._record(feature)
    attributes = feature.get("properties") or feature.get("attributes") or {}
    if record is None:
        identifier = str(attributes.get("UniqueTankID") or "").strip()
        return {
            "kgis_id": identifier,
            "lake_name": " ".join(str(attributes.get("TankName") or "").split()),
            "district": attributes.get("KGISDistrictName") or "",
            "area": attributes.get("TankArea_Ha") or "",
            "geometry_status": "not_audited_unusable_catalogue_record",
            "satellite_dates": "not_verified", "chlorophyll_dates": "not_verified",
            "lswt_dates": "not_verified", "rainfall_dates": "not_queried",
            "wind_dates": "not_queried", "usable_periods": 0,
            "missing_variables": "valid_catalogue_name_or_id;verified_B2_B3_B4_B8_pixels;daily_chlorophyll_a;daily_lswt;aligned_weather;future_chlorophyll_target",
            "quality_flags": "unusable_catalogue_record;no_verified_Karnataka_training_samples",
        }
    geometry_status = (
        "basic_polygon_coordinates_present" if basic_polygon_available(feature.get("geometry"))
        else "polygon_missing_or_basic_check_failed"
    )
    return {
        "kgis_id": record["id"],
        "lake_name": record["name"],
        "district": record["district"] or "",
        "area": record["area_ha"] if record["area_ha"] is not None else "",
        "geometry_status": geometry_status,
        "satellite_dates": "not_verified",
        "chlorophyll_dates": "not_verified",
        "lswt_dates": "not_verified",
        "rainfall_dates": "not_queried",
        "wind_dates": "not_queried",
        "usable_periods": 0,
        "missing_variables": "verified_B2_B3_B4_B8_pixels;daily_chlorophyll_a;daily_lswt;aligned_weather;future_chlorophyll_target",
        "quality_flags": "no_verified_Karnataka_training_samples;external_pixel_coverage_unknown;CLMS_products_10_daily",
    }


def fetch_named_features(client: httpx.Client):
    offset = 0
    while True:
        response = client.get(f"{LAYER_URL}/query", params={
            "where": "TankName IS NOT NULL",
            "outFields": OUT_FIELDS,
            "returnGeometry": "true",
            "outSR": 4326,
            "orderByFields": "UniqueTankID ASC",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
            "f": "geojson",
        })
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"K-GIS query failed at offset {offset}")
        features = payload.get("features") or []
        if not features:
            break
        yield from features
        offset += len(features)
        if not payload.get("exceededTransferLimit", False):
            break


def run(output: Path, pilot_root: Path = Path("outputs/karnataka_open_data_pilot")) -> dict:
    expected = KarnatakaWaterBodyService(timeout=30).count_named()
    pilots = load_pilot_evidence(pilot_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    total = polygons = 0
    with httpx.Client(timeout=60) as client, output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for feature in fetch_named_features(client):
            total += 1
            row = audit_row(feature)
            if row is None:
                continue
            if row["kgis_id"] in seen:
                raise RuntimeError(f"Duplicate K-GIS ID: {row['kgis_id']}")
            seen.add(row["kgis_id"])
            pilot = pilots.get(row["kgis_id"])
            if pilot:
                row.update({key: pilot[key] for key in
                            ("satellite_dates", "rainfall_dates", "wind_dates")})
                row["missing_variables"] = (
                    "daily_chlorophyll_a;daily_lswt;future_chlorophyll_target;"
                    "verified_weather_aggregation;raster_harmonization"
                )
                row["quality_flags"] = (
                    f"raw_four_band_pixels_verified={pilot['valid_pixels']};"
                    f"scl_water_pixels={pilot['scl_water_pixels']};"
                    "not_model_ready;CLMS_products_10_daily"
                )
            polygons += row["geometry_status"] == "basic_polygon_coordinates_present"
            writer.writerow(row)
    if total != expected:
        raise RuntimeError(f"K-GIS page count changed during audit: {total} vs {expected}")
    return {"source_named_features": total, "report_rows": len(seen),
            "basic_polygons": polygons, "geometry_unverified": len(seen) - polygons,
            "raw_pilot_rasters_verified": len(pilots)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("outputs/karnataka_phase3_coverage.csv"))
    parser.add_argument("--pilot-dir", type=Path,
                        default=Path("outputs/karnataka_open_data_pilot"))
    args = parser.parse_args()
    print(run(args.output, args.pilot_dir))
