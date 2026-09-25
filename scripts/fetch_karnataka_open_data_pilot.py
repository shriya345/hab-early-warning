"""Fetch a dated, unvalidated Karnataka satellite/weather research sample.

Uses a K-GIS polygon, Element 84's public Sentinel-2 L2A COG archive, and
Open-Meteo historical ERA5. This does not create chlorophyll, LSWT, labels,
training examples, or live model inputs.

Run with the project's rasterio environment, for example:
    python -m scripts.fetch_karnataka_open_data_pilot --kgis-id KA20010018
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import json
from pathlib import Path

import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom

from backend.services.satellite import SatelliteService
from backend.water_bodies import KarnatakaWaterBodyService


STAC_SEARCH = "https://earth-search.aws.element84.com/v1/search"
WEATHER_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
BANDS = (("B2", "blue", "B02"), ("B3", "green", "B03"),
         ("B4", "red", "B04"), ("B8", "nir", "B08"))
WEATHER_FIELDS = ("rain_sum", "precipitation_sum", "wind_speed_10m_mean",
                  "wind_speed_10m_max")


def select_scene(body: dict, start: date, end: date) -> dict:
    bbox = SatelliteService._bbox(body)
    if not bbox or not body.get("boundary"):
        raise ValueError("The K-GIS record has no polygon and bounding box.")
    response = httpx.post(STAC_SEARCH, json={
        "collections": ["sentinel-2-c1-l2a"],
        "bbox": bbox,
        "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
        "limit": 100,
        "query": {"eo:cloud_cover": {"lt": 20}},
    }, timeout=30)
    response.raise_for_status()
    candidates = []
    for feature in response.json().get("features") or []:
        assets = feature.get("assets") or {}
        if not all(asset in assets for _, asset, _ in BANDS) or "scl" not in assets:
            continue
        properties = feature.get("properties") or {}
        try:
            observed = date.fromisoformat(properties["datetime"][:10])
            cloud = float(properties["eo:cloud_cover"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= observed <= end and np.isfinite(cloud):
            candidates.append((cloud, -observed.toordinal(), feature))
    if not candidates:
        raise RuntimeError("No four-band Sentinel-2 L2A scene met the pilot filters.")
    return min(candidates, key=lambda item: item[:2])[2]


def fetch_raster(body: dict, scene: dict, output: Path) -> dict:
    arrays = []
    valid_masks = []
    band_info = []
    crop_transform = crs = geometry = None
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        for band, asset_name, expected_name in BANDS:
            asset = scene["assets"][asset_name]
            names = [item.get("name") for item in asset.get("eo:bands") or []]
            if expected_name not in names:
                raise RuntimeError(f"STAC asset {asset_name} does not identify {band}.")
            with rasterio.open(asset["href"]) as source:
                if source.count != 1 or source.dtypes[0] != "uint16":
                    raise RuntimeError(f"Unexpected raster type for {band}.")
                transformed = transform_geom("EPSG:4326", source.crs, body["boundary"])
                image, transform = mask(source, [transformed], crop=True, filled=False)
                if crs is None:
                    crs, crop_transform, geometry = source.crs, transform, transformed
                elif source.crs != crs or transform != crop_transform or image[0].shape != arrays[0].shape:
                    raise RuntimeError("The four bands do not align on one pixel grid.")
                values = image[0]
                arrays.append(values.filled(0).astype("uint16"))
                valid_masks.append(~np.ma.getmaskarray(values))
                metadata = (asset.get("raster:bands") or [{}])[0]
                band_info.append({
                    "band": band, "asset": asset["href"],
                    "stac_scale": metadata.get("scale"),
                    "stac_offset": metadata.get("offset"),
                    "valid_polygon_pixel_count": int(valid_masks[-1].sum()),
                    "raw_dn_min": int(values.min()), "raw_dn_max": int(values.max()),
                })
        stack = np.stack(arrays)
        joint_valid = np.logical_and.reduce(valid_masks)
        if int(joint_valid.sum()) == 0:
            raise RuntimeError("No valid four-band pixels inside the K-GIS polygon.")

        height, width = stack.shape[1:]
        lake_mask = geometry_mask([geometry], out_shape=(height, width),
                                  transform=crop_transform, invert=True)
        with rasterio.open(scene["assets"]["scl"]["href"]) as scl_source:
            with WarpedVRT(scl_source, crs=crs, transform=crop_transform,
                           width=width, height=height,
                           resampling=Resampling.nearest) as vrt:
                scl = vrt.read(1)
        codes, counts = np.unique(scl[lake_mask], return_counts=True)
        scl_counts = {str(int(code)): int(count) for code, count in zip(codes, counts)}

        output.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output, "w", driver="GTiff", width=width, height=height,
                           count=4, dtype="uint16", crs=crs, transform=crop_transform,
                           nodata=0, compress="deflate") as target:
            target.write(stack)
            for index, (band, _, _) in enumerate(BANDS, 1):
                target.set_band_description(index, band)
            target.update_tags(scene_id=scene["id"], raw_dn="true",
                               model_ready="false")
    return {
        "raster_path": str(output), "width": width, "height": height,
        "crs": str(crs), "pixel_size_metres": [abs(crop_transform.a), abs(crop_transform.e)],
        "lake_polygon_pixel_count": int(lake_mask.sum()),
        "valid_four_band_polygon_pixel_count": int(joint_valid.sum()),
        "scene_classification_counts_inside_polygon": scl_counts,
        "band_order": [band for band, _, _ in BANDS], "bands": band_info,
        "raw_dn_note": "STAC scale/offset metadata must be reviewed before any trained-model preprocessing; this raw COG crop is not a model input.",
    }


def fetch_weather(body: dict, feature_date: date, output: Path) -> dict:
    start = feature_date - timedelta(days=6)
    end = feature_date + timedelta(days=5)
    params = {
        "latitude": body["latitude"], "longitude": body["longitude"],
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": ",".join(WEATHER_FIELDS), "models": "era5",
        "timezone": "Asia/Kolkata", "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
    }
    response = httpx.get(WEATHER_ARCHIVE, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    expected_dates = [(start + timedelta(days=index)).isoformat() for index in range(12)]
    if dates != expected_dates or any(len(daily.get(field) or []) != 12 for field in WEATHER_FIELDS):
        raise RuntimeError("Historical weather response does not cover the expected dates.")
    rows = [{"date": day, **{field: daily[field][index] for field in WEATHER_FIELDS}}
            for index, day in enumerate(dates)]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("date", *WEATHER_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    return {
        "weather_path": str(output), "source": WEATHER_ARCHIVE,
        "model": "ERA5", "dates": dates,
        "units": payload.get("daily_units"),
        "note": "Historical gridded weather; aggregation compatibility with the Vembanad model has not been verified.",
    }


def run(kgis_id: str, start: date, end: date, output_dir: Path) -> Path:
    body = KarnatakaWaterBodyService().get(kgis_id)
    if not body.get("boundary") or not body.get("location_resolved"):
        raise RuntimeError("The selected K-GIS water body lacks a usable location/polygon.")
    scene = select_scene(body, start, end)
    feature_date = date.fromisoformat(scene["properties"]["datetime"][:10])
    destination = output_dir / f"{body['id']}_{feature_date.isoformat()}"
    raster = fetch_raster(body, scene, destination / "sentinel2_B2_B3_B4_B8_raw_dn.tif")
    weather = fetch_weather(body, feature_date, destination / "historical_weather_era5.csv")
    manifest = {
        "status": "research_data_only_not_model_ready",
        "kgis_id": body["id"], "lake_name": body["name"],
        "kgis_source": body["catalog_source"],
        "scene_id": scene["id"],
        "scene_datetime": scene["properties"]["datetime"],
        "scene_footprint_cloud_percent": scene["properties"]["eo:cloud_cover"],
        "sentinel_source": STAC_SEARCH,
        "feature_date": feature_date.isoformat(),
        "five_day_target_date": (feature_date + timedelta(days=5)).isoformat(),
        "raster": raster, "weather": weather,
        "missing_for_training": ["seven_daily_lake_chlorophyll_observations",
                                 "seven_daily_lake_surface_temperature_observations",
                                 "chlorophyll_observation_on_five_day_target",
                                 "verified_training_compatible_weather_aggregation",
                                 "raster_harmonization_against_training_archive"],
        "prediction_allowed": False,
    }
    path = destination / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kgis-id", default="KA20010018")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 2, 10))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 2, 21))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("outputs/karnataka_open_data_pilot"))
    args = parser.parse_args()
    print(run(args.kgis_id, args.start, args.end, args.output_dir))
