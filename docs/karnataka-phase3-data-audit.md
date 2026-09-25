# Karnataka Phase 3 data audit — 2026-09-26

## Decision

**Stop after the data audit.** The available material contains no verified
Karnataka lake-level training sample. In particular, it contains no verified
daily lake chlorophyll-a and lake surface water temperature series or +5-day
chlorophyll targets. A later online-data dry run acquired raw B2/B3/B4/B8
pixels for nine selected lakes, but these are not yet training-compatible. The
published CLMS candidates are 10-daily composites; they cannot be relabelled
as seven consecutive measured daily observations. Training or evaluating a
Karnataka model from these inputs would be unsupported.

The per-record inventory is
[`outputs/karnataka_phase3_coverage.csv`](../outputs/karnataka_phase3_coverage.csv).
`area` is K-GIS `TankArea_Ha` in hectares. A `satellite_dates` value for one
of the nine pilot lakes means a raw four-band polygon crop was reopened and
pixel-checked; it does **not** mean model-ready imagery. `not_verified` means
no actual lake pixels or observations were validated and does **not** mean
that the provider has no data for that lake. `rainfall_dates` and `wind_dates`
identify downloaded historical weather ranges for pilot lakes; `not_queried`
means the statewide weather provider was not called for that record.
`usable_periods=0` means zero
**verified, fully aligned** periods in the available data, not proven zero
periods in nature. The polygon check confirms basic K-GIS coordinate structure
only, not water-mask overlap or topological validity.

## Inventory and source checks

| Check | Result |
| --- | ---: |
| K-GIS `TankName IS NOT NULL` records | 8,887 |
| Unique K-GIS IDs in coverage report | 8,887 |
| Named records with basic polygon coordinates | 8,886 |
| Non-null but blank name, flagged unusable (`KA15010162`) | 1 |
| Named records under 1 ha | 1,275 |
| Karnataka lake environmental model-input files and manifests found | 0 |
| Karnataka lake model-validation manifests found | 0 |
| Karnataka B2/B3/B4/B8 GeoTIFFs present before the online-data pilot | 0 |
| Raw Karnataka four-band pilot crops subsequently fetched | 9 |
| Training-compatible Karnataka four-band rasters validated | 0 |
| CDSE credential configuration available to this process | No |

The live [K-GIS Tank Ownership layer](https://kgis.ksrsac.in/kgismaps2/rest/services/Tank/Tank_Ownership/MapServer/1)
was paged in K-GIS ID order. Its records have geometry, names, districts and
areas, including Ulsoor (41.804 ha), Varthur (178.891 ha), Bellandur (352.495
ha), and Gattigere Palya (0.208 ha). The one blank-name record is retained in
the CSV with a quality flag. These counts are a source snapshot, not a count
of model-supported lakes.

The repository's `data/environmental/processed` and `data/integration` CSVs
contain the **Vembanad, Kerala** 2024 prototype series. The 31 entries in
`data/sentinel2/sentinel_index.csv` reference Vembanad images; the TIFFs are
not in this checkout. Those records are excluded from Karnataka counts. The
Practice Analysis synthetic generator is also excluded.

### Source pilot: Ulsoor Lake

- Public CDSE STAC returned 16 nearby catalogue dates each for CLMS
  `clms_lwq-nrt_global_100m_10daily_v2_cog` and
  `clms_lswt-nrt_global_1km_10daily_v1_cog`, from 2026-04-01 through
  2026-09-01. These are global product candidates, **not confirmed Ulsoor
  pixels or observations**. The diagnostic's polygon-statistics path could
  not run because `CDSE_ACCESS_TOKEN` and the
  `CDSE_CLIENT_ID`/`CDSE_CLIENT_SECRET` pair were absent.
- The [CLMS lake-water-quality definition](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/water-bodies/lake-water-quality/lwq-nrt_global_100m_10daily_v2.html)
  identifies `CHLAMEAN` as mean chlorophyll-a in mg/m³, at 100 m and 10-daily
  cadence. It describes coverage for a large number of medium and large lakes,
  not every K-GIS tank.
- The [CLMS lake-temperature definition](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/temperature-and-reflectance/lake-surface-water-temperature/lswt-nrt_global_1km_10daily_v1.html)
  identifies `LSWT` as a 1 km, 10-daily lake-surface-skin-temperature
  composite. Its Kelvin value uses scale 0.01 and offset 273.15. At 1 km,
  lake-specific pixels for small urban water bodies especially need direct
  validation.
- Public Sentinel-2 L2A STAC returned 2026-09-24 scene metadata for Ulsoor,
  Varthur, Bellandur, and Gattigere Palya. The returned 90.48% cloud figure is
  for the scene footprint. No B2/B3/B4/B8 pixels were retrieved or checked
  inside these four lake polygons **during the original audit**. A separate
  public COG acquisition later retrieved actual 2025 pixels for nine featured
  lakes, described below. The [CDSE STAC documentation](https://documentation.dataspace.copernicus.eu/APIs/STAC.html)
  describes catalogue discovery; a scene hit alone is not a usable raster.
- The existing Open-Meteo historical adapter returned seven complete daily
  rainfall and wind rows for Ulsoor, 2025-02-01–2025-02-07, with reported
  mm/day and m/s units. This verifies that the [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
  can supply a historical gridded pilot series, not that its aggregation or
  spatial scale matches the Vembanad training series. The current code requests
  `precipitation_sum` (rain plus snow) and `wind_speed_10m_max`; the historical
  training data's aggregation provenance is not documented. No statewide
  weather backfill was run because the required lake variables are missing.

## Training sample eligibility and counts

A sample would need seven **consecutive dated** rows in the exact feature
order `chlorophyll_a, sst, rainfall, wind_speed, chlorophyll_imputed`, a
lake-aligned B2/B3/B4/B8 raster acquired no later than the feature date,
and a real chlorophyll observation exactly five days later. Raster
preprocessing must remain 128×128, divide by 10,000, clip to [0, 2]. A
chlorophyll-proxy threshold must be chosen from a documented standard or the
**training partition only**, then frozen before validation/test. The old
prototype's 75th-percentile Vembanad threshold is provisional and cannot be
assumed to represent Karnataka toxic HABs.

| Required report item | Verified result |
| --- | ---: |
| Karnataka lakes with usable training data | 0 |
| Usable aligned observations | 0 |
| Usable seven-day windows | 0 |
| Usable Karnataka four-band Sentinel-2 images | 0 |
| Positive / negative +5-day target examples | 0 / 0 |
| Lakes in train / validation / test | 0 / 0 / 0 |
| Persistence baseline and old-model metrics | Not computed: no held-out samples |
| New-model metrics | Not computed: no model trained |
| Data sufficient for Karnataka-specific training | No |

The zeros are counts **verified from material available to this audit**. They
do not establish absence of historical observations at external providers.
The later raw-raster pilot increased the count of **retrieved** four-band
Karnataka crops to nine but did not create a complete training example:
source scale/offset compatibility, lake-water pixel quality, daily
chlorophyll/LSWT, and +5-day targets remain unresolved. Thus the
training-usable count remains zero.
Even if CLMS lake pixels are later confirmed, its documented 10-daily cadence
does not by itself provide the required daily seven-day environmental window
or a measured target exactly five days after each feature date. A reliable
Phase 3 dataset requires genuine daily lake chlorophyll-a and LSWT/SST
observations (including future target dates), with source, units, quality
flags, and coverage linked to K-GIS IDs; cloud-screened four-band Sentinel-2
pixels; and compatible historical rainfall/wind provenance. A different
10-daily forecasting objective would require a separately specified and
validated model contract.

## Reproduction and scope

Run `python -m scripts.audit_karnataka_coverage` to refresh the K-GIS inventory.
Run `python -m backend.diagnose_cdse ulsoor` to repeat the public candidate-date
check and, when backend credentials exist, test actual polygon pixels. The
audit did not train, evaluate, version, or deploy a Karnataka model. The
existing CNN/LSTM weights, prediction gates, and frontend were not changed.

## Subsequent online-data dry run

The separate [online-data pilot summary](../outputs/karnataka_open_data_pilot/summary.csv)
and per-lake manifests now contain nine raw Sentinel-2 L2A COG crops and 108
historical ERA5 weather rows for the nine featured K-GIS lakes. The crops
contain actual B2/B3/B4/B8 pixels from 2025-02-16 or 2025-02-19, cut to each
K-GIS polygon. They have not been supplied to the trained model. The public
COG STAC metadata assigns scale 0.0001 and offset -0.1 to those raw uint16
pixels; blindly dividing their stored DNs by 10,000 would violate the existing
model's harmonized input contract. The full acquisition provenance and quality
limits are in `docs/karnataka-online-data-pilot.md`.
