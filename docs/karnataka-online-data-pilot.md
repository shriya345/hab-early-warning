# Karnataka public-data acquisition dry run — 2026-09-26

This is a **real-data acquisition test**, not a bloom-prediction dataset. It
downloaded public Sentinel-2 L2A image pixels and historical gridded weather
for the nine featured K-GIS lakes. No synthetic observations, chlorophyll
targets, or model probabilities were created. Existing live validation gates
and the Live prediction path were not changed. The website now includes a
separately labelled historical observation analysis for these downloaded files;
it does not estimate bloom risk.

## Sources and method

- K-GIS `Tank_Ownership` supplied each lake's ID and polygon.
- [AWS Open Data's Sentinel-2 COG archive](https://registry.opendata.aws/sentinel-2-l2a-cogs/)
  and [Element 84 Earth Search](https://github.com/Element84/earth-search)
  supplied an actual Level-2A scene and remote B02, B03, B04, B08 GeoTIFF
  pixels. The four one-band COGs were checked for a common 10 m grid, cropped
  and masked to the K-GIS polygon, and saved as a four-band uint16 GeoTIFF in
  B2/B3/B4/B8 order. The scene-classification layer was sampled inside the
  same polygon to show image quality. These are **raw source DNs**. The asset
  metadata specifies scale 0.0001 and offset -0.1; the model's archived
  imagery used a different harmonized-DN contract. Therefore the pilot TIFFs
  are not model-ready and must not simply be divided by 10,000 for inference.
- The [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
  returned ERA5 daily `rain_sum`, `precipitation_sum`, mean 10 m wind speed,
  and maximum 10 m wind speed, in mm and m/s. Each lake has twelve dated rows:
  the six days before its satellite date, that date, and the following five
  days. These are gridded weather estimates, not in-lake measurements, and
  their aggregation has not been matched to the old Vembanad training data.
- The [official Sentinel-2 L2A SCL code list](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L2A.html)
  assigns code 6 to water, 5 to bare soils, and 7 to low-probability cloud or
  unclassified pixels. SCL is 20 m and was sampled onto the 10 m band grid;
  these classifications are quality indicators, not a field survey.

The public COG search used 2025-02-10–2025-02-21 and picked the scene with
lowest **scene-footprint** cloud percentage for each lake. Low footprint
cloud cover does not guarantee lake-specific water quality. Every manifest
contains the exact scene, date, public asset URLs, raster scale/offset,
SCL counts, weather units, and outstanding input requirements.

## Acquired files

| Lake (K-GIS ID) | Scene date | Four-band polygon pixels | SCL water pixels | Historical weather rows |
| --- | --- | ---: | ---: | ---: |
| Ulsoor (`KA20010018`) | 2025-02-16 | 4,178 | 3,551 | 12 |
| Varthur (`KA20040088`) | 2025-02-16 | 17,888 | 1,741 | 12 |
| Bellandur (`KA20020207`) | 2025-02-16 | 35,236 | 6,045 | 12 |
| Kukkarahalli (`KA26040001`) | 2025-02-19 | 6,007 | 3,725 | 12 |
| Karanjikere (`KA26040054`) | 2025-02-19 | 2,281 | 316 | 12 |
| Gattigere Palya (`KA20020236`) | 2025-02-16 | 20 | 0 | 12 |
| Chikkegowdanapalya (`KA20020235`) | 2025-02-16 | 45 | 0 | 12 |
| Bettahalli (`KA20050109`) | 2025-02-16 | 47 | 0 | 12 |
| Srinivasapura (`KA20050107`) | 2025-02-16 | 94 | 0 | 12 |

Total: **9 four-band raster crops, 65,796 pixels inside polygons across all
four bands, and 108 historical weather rows**. “Four-band polygon pixels”
means each of B2/B3/B4/B8 has a non-nodata sample at that position; it does
not establish that the pixel is water. Four small lakes had zero pixels
classified as water in the selected scene and are especially unsuitable as
lake-water examples on that date. Low SCL-water fractions in other lakes also
need manual review; they are not automatically invalid or valid.

Files for each lake live under
`outputs/karnataka_open_data_pilot/<KGIS_ID>_<scene_date>/`:

- `sentinel2_B2_B3_B4_B8_raw_dn.tif`
- `historical_weather_era5.csv`
- `manifest.json`

The one-row-per-lake index is
[`outputs/karnataka_open_data_pilot/summary.csv`](../outputs/karnataka_open_data_pilot/summary.csv).
The acquisition can be repeated with, for example,
`python -m scripts.fetch_karnataka_open_data_pilot --kgis-id KA20010018`
in the project's rasterio environment. Coordinates and boundaries come from
the selected K-GIS ID; no manual latitude/longitude or file selection is used.

## Remaining blockers

The files do **not** include chlorophyll-a, lake surface water temperature,
or a real chlorophyll observation at the five-day target date. An anonymous
request for a CLMS product download returned HTTP 401. CDSE credentials were
not configured. Official [CLMS chlorophyll](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/water-bodies/lake-water-quality/lwq-nrt_global_100m_10daily_v2.html)
and [lake temperature](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/temperature-and-reflectance/lake-surface-water-temperature/lswt-nrt_global_1km_10daily_v1.html)
products have 10-daily cadence. Even authenticated CLMS pixels would not
automatically provide seven consecutive daily lake observations or a target
exactly five days ahead.

The Karnataka government also publishes [Bengaluru lake/tank water-quality
index data](https://karnataka.data.gov.in/catalog/water-quality-lakestanks-bangalore-urban-and-rural-districts),
but the listed 2020–21 resource has annual granularity and cannot fill the
current daily chlorophyll/LSWT contract. It remains a possible contextual or
independent validation source after its fields are reviewed.

**No Karnataka training sample or live forecast became valid in this dry run.**

## Pilot path to live analysis

Start with Ulsoor (`KA20010018`). Collect a dated, lake-specific daily series
of chlorophyll-a and surface-water temperature. Preserve measurement location,
depth, instrument or laboratory method, original units, calibration/quality
flags, and any missing or imputed value indicators. Continue beyond seven days
so an observed chlorophyll-a value exists five days after each candidate input
window. Do not relabel 10-daily CLMS composites as daily measurements.

Before creating the backend's `<KGIS_ID>.csv` and `<KGIS_ID>.json` model-input
pair, verify the Vembanad training series' units and aggregation provenance,
then map real observations to the exact ordered columns `date,chlorophyll_a,
sst,rainfall,wind_speed,chlorophyll_imputed`. Pair them with a date-aligned,
training-compatible B2/B3/B4/B8 raster. Review lake-specific model performance
and its evidence before adding a model-validation record. The historical
observation analysis endpoint is independent of this process and never marks
a lake validated.
