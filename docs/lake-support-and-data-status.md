# Lake support and data status

## Product scope and model status

The product discovery scope is Karnataka. The current CNN/LSTM remains a
Vembanad research prototype, and Vembanad is in Kerala. No Karnataka water body
has been validated for model predictions. Karnataka catalogue records therefore
report `data_model_validation_required`; a probability must not be returned for
them until lake-specific data and validation support it.

The model configuration specifies a five-day forecast, seven environmental
input days, five LSTM features, four CNN input bands, and 50/50 CNN/LSTM fusion.
The environmental feature order is `chlorophyll_a`, `sst`, `rainfall`,
`wind_speed`, `chlorophyll_imputed`. Training labels are derived from a
Vembanad chlorophyll-a threshold, not independently confirmed toxic-HAB
observations.

## Karnataka water-body catalogue

`GET /water-bodies/search?q=ulsoor` searches named records in the public
Karnataka GIS (K-GIS) `Tank_Ownership` feature layer statewide.
`GET /water-bodies/{id}` resolves a selected record by its `UniqueTankID`. The
backend retains source coordinates and polygon for data services; public
responses expose only whether those are available, not coordinate fields or
polygon geometry. `backend/curated_catalog.py` stores example shortcuts and
does not restrict the source search.

The named source inventory includes major urban lakes such as Ulsoor, Varthur,
Bellandur, Mysuru's Kukkarahalli Lake and Karanjikere, as well as thousands of
smaller named water bodies. The UI example shortcuts also include four
Bengaluru Urban records under 1 ha: Gattigere Palya (Sompura),
Chikkegowdanapalya, Bettahalli, and Srinivasapura. K-GIS catalogue membership
is only a discovery result. Karnataka records remain
`data_model_validation_required`; a source record is not evidence of model
validation or a confirmed bloom observation.

The K-GIS layer metadata exposes `UniqueTankID`, `KGISTankID`, `TankName`,
district/taluk/hobli/village, `Latitude`, `Longitude`, area in hectares, and
polygon geometry. It is a Karnataka tank/water-body layer and includes named
urban lakes such as Ulsoor, Varthur, and Bellandur. It contains no explicit
rural/urban flag in this layer. The live service returned 37,782 features, with
8,887 named records; 5,375 named records were under 10 ha and 1,275 were under
1 ha when inspected on 2026-09-25. These figures describe the live source, not
a validated model-support list. They do not prove complete lake coverage or a
regular update cadence.

Sources:

- [K-GIS Tank Ownership layer](https://kgis.ksrsac.in/kgismaps2/rest/services/Tank/Tank_Ownership/MapServer/1)
- [OGD Karnataka WaterBody catalog](https://www.data.gov.in/catalog/waterbody), published by Karnataka's Department of Personnel and Administrative Reforms / Karnataka State Remote Sensing Applications Centre.

The K-GIS service metadata does not state an update schedule or a reuse
license. Confirm those terms with the publisher before distributing a public
service based on bulk copies. The app queries the source at runtime; it does
not check in a bulk catalogue snapshot.

The First Census 2017–18 CSV remains a potential secondary inventory. The
Karnataka 2023 census KML mirror inspected during this phase contains 27,013
point features and stable census IDs but no water-body name field or placemark
names, so it was not used for name search. Its source is cited as Jal Shakti and
its mirror marks the resource public domain, but the K-GIS layer is the better
fit for named, boundary-aware search.

## Existing data and input contracts

- Environmental series: 366 daily Vembanad rows from 2024-01-01 through
  2024-12-31. It contains chlorophyll-a, SST, rainfall, wind speed, and the
  chlorophyll imputation flag; 120 rows have the flag set.
- Satellite index: 31 2024 image entries. The indexed 2024-02-22 TIFF was found
  in the user's Downloads archive, not in this checkout, and is also referenced
  by the aligned and supervised datasets. Its GeoTIFF metadata names samples
  1–4 as B2, B3, B4, B8. The image is 2228×4454, four-band unsigned 16-bit
  integer, LZW-compressed GeoTIFF. Decoding a temporary uncompressed copy gave
  maxima of 28,168 / 25,000 / 22,424 / 19,464 and exact-zero fractions of
  0.0586% / 0.0122% / 0.0139% / 0.0484% for bands 1–4.
- The local `ryder_satellite_check.ipynb` includes a bulk-export path driven by
  the project's Sentinel index. It uses
  `COPERNICUS/S2_SR_HARMONIZED`, mosaics scenes acquired on each date, selects
  bands B2/B3/B4/B8 in that order, clips to the rectangle
  `[76.30, 9.50, 76.50, 9.90]`, and exports at 10 m. Its export cells do not
  apply an SCL cloud/shadow mask. The date-selection or cloud-screening steps
  before dates entered the index are not recorded, and the local TIFF does not
  contain a cloud mask or `GDAL_NODATA` tag. The notebook recipe and TIFF
  metadata are consistent with the same archive format and crop.
- Google Earth Engine documents this harmonized surface-reflectance collection
  as UINT16 samples scaled by 10,000. This verifies the source scale for the
  notebook's collection. Some observed values are high: B2 reaches 28,168 and
  3.08% of its pixels exceed 20,000; the model's current preprocessing clips
  the normalized raster at 2. These values and any cloudy pixels therefore
  pass through the same unmasked training/inference preprocessing. The original
  CNN code reads all four bands, resizes to 128×128 with area interpolation,
  divides by 10,000, and clips to [0, 2].
- Sources: [Earth Engine Sentinel-2 SR Harmonized collection](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED), [Copernicus Sentinel-2 L2A units and harmonization](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L2A.html).
- Current Sentinel-2 scene metadata uses the public [Copernicus Data Space STAC catalogue](https://documentation.dataspace.copernicus.eu/APIs/STAC.html). Anonymous catalogue queries return scene identifiers, acquisition dates, and scene-wide cloud cover. These metadata do not prove lake-pixel quality or model suitability. Pixel assets are stored in CDSE's S3 object storage; fetching previews or rasters uses authenticated processing and backend-only credentials.
- The verified 2024-02-22 archive TIFF is now copied into the local checkout.
  The website supports `POST /historical-predictions/vembanad` for this fixed
  archive pair. See [historical prediction](historical-bloom-prediction.md).
- Open-Meteo supplies gridded air temperature, rainfall, and wind. It is not an
  in-lake chlorophyll-a or SST provider. Prepared 2024 chlorophyll-a and SST
  must not be described as current data.
- Open-data research candidates exist but are not configured as model inputs:
  Copernicus CLMS publishes a global Lake Water Quality NRT product at 100 m
  every 10 days (from September 2024), including a mean chlorophyll-a band in
  mg/m³ and a floating-cyanobacteria probability band. The product is described
  for a large number of medium and large lakes; coverage of each K-GIS lake,
  especially sub-hectare urban lakes, has not been verified. CLMS also publishes
  global lake surface water temperature at 1 km every 10 days, with Kelvin
  values. These products are research/context candidates: their sampling
  cadence, spatial support, product units, and source-defined coverage do not
  establish compatibility with the model's seven consecutive daily inputs.
  Do not repeat a 10-day observation into daily rows or send these products to
  the CNN/LSTM until source coverage and training-unit compatibility are
  reviewed. Official references: [CLMS Lake Water Quality NRT 100m 10-daily
  V2](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/water-bodies/lake-water-quality/lwq-nrt_global_100m_10daily_v2.html)
  and [CLMS Lake Surface Water Temperature NRT global 1km 10-daily
  V1](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/clms/bio-geophysical-parameters/temperature-and-reflectance/lake-surface-water-temperature/lswt-nrt_global_1km_10daily_v1.html).
- The public CDSE STAC endpoint can return recent Sentinel-2 L2A scene metadata
  without credentials. The website reports acquisition date and
  `eo:cloud_cover`; that percentage is for the full Sentinel-2 product
  footprint, not the selected lake. It is not a cloud-free observation claim.
  Fetching an RGB preview or the four-band model raster still requires
  backend-only `CDSE_CLIENT_ID` and `CDSE_CLIENT_SECRET`. The preview is fetched
  only on request and is not the CNN input. The historical Vembanad archive
  does not provide current Karnataka imagery.
- CDSE's public STAC collection catalogue also lists the global CLMS Lake Water
  Quality and Lake Surface Water Temperature products. The website does not
  yet retrieve or sample those pixels. Their COG assets reference CDSE S3
  object storage, which requires generated S3 credentials; catalogue-level
  footprint intersection alone is not evidence that a usable pixel exists
  inside a small urban lake boundary. Confirmed current chlorophyll-a/SST model
  windows therefore remain unconfigured.
- The backend's internal `SatelliteService.fetch_model_raster` adapter requests
  B2/B3/B4/B8 in order, as harmonized UINT16 DNs, with no cloud mask, at the
  archive's WGS84 10 m grid. It searches L2A scenes from the environmental
  feature date back five days, rejects future acquisitions, and constrains
  Process API acquisition to the selected scene's timestamp. It tiles larger
  requests and validates the TIFF count/type before caching it under the
  backend's private cache. Backend-only CDSE OAuth credentials are required:
  `CDSE_CLIENT_ID` and `CDSE_CLIENT_SECRET`. This only
  verifies the raster input format; a lake-specific validation record and a
  complete seven-day environmental model window are still required before the
  prediction service can invoke CNN/LSTM inference. Because archived scene
  selection criteria are unknown, the backend also requires the explicit
  `HAB_SATELLITE_INPUT_CONTRACT_VERIFIED` attestation before model raster
  ingestion.
- Optional environmental model inputs live in the backend-only
  `HAB_ENVIRONMENTAL_MODEL_DIR` as `<water_body_id>.csv` and
  `<water_body_id>.json`. The manifest must identify the source and exact
  feature order and attest that units match the training inputs. The loader
  requires seven consecutive, recent days and does not treat Open-Meteo context
  as model features. No compatible live lake-specific Chl-a/SST dataset is
  currently configured.
- Optional per-lake validation records live in the backend-only
  `HAB_MODEL_VALIDATION_DIR` as `<water_body_id>.json`. Each manifest must
  match the selected K-GIS ID, set `status` to `validated_prototype`, set
  `reviewed` to `true`, and provide `model_version`, `note`, and a
  `validation_evidence` reference. Missing, malformed, mismatched, or
  unreviewed records keep the lake in `data_model_validation_required` state.
  No Karnataka lake has a validation manifest today. The manifest is an
  operator-maintained record; adding one does not itself establish scientific
  validity.

## Current API and frontend

- Catalogue service: `/water-bodies/search` pages through the statewide named
  K-GIS source using `next_offset` and `has_more`, including matches beyond the
  first provider batch. `/water-bodies/{id}` returns a selected lake's source
  point and GeoJSON polygon in `map_view`. The browser uses the stable K-GIS ID
  and fits the map to the boundary, or centers on the point if no usable
  boundary exists; users do not enter coordinates or dates.
- `/water-bodies/{id}/coverage` reports optional satellite scene-metadata and
  environmental source availability, model-compatible inputs, and provenance.
  Weather can be shown as gridded context only; it is not treated as lake SST
  or a compatible input. Scene metadata is not image data.
- `/water-bodies/{id}/satellite/preview` fetches a display-only RGB preview on
  demand when Copernicus credentials are configured; it is never passed to the
  prediction path.
- `/water-bodies/{id}/prediction` currently returns `prediction: null`, a
  five-day horizon, missing-input details, and `data_model_validation_required`
  for Karnataka water bodies. The route assembles inputs only after model
  validation, compatible environmental inputs, aligned scene metadata, and the
  satellite contract attestation are all present. Local raster paths never
  enter the public response.
- The frontend is Karnataka-first and searches the named K-GIS inventory,
  including small urban lakes. Its few example shortcuts are not a search
  allowlist. It renders per-water-body coverage and never
  shows an unvalidated percentage or a risk category. It sends an analysis
  request only when the backend reports a validated model and compatible
  inputs; if a prediction is returned, it displays the percentage directly.

The model regression test runs the unmodified CNN/LSTM on the archived
2024-02-22 Vembanad TIFF with the seven environmental rows ending that day. The
reference output is CNN 0.30116573, LSTM 0.48389933, fused probability
0.39253253 (39.2533%), with a five-day horizon. It is historical and tests
model-file/preprocessing stability only; it is not a current forecast or
evidence of toxic-HAB validation. Run it with
`HAB_REGRESSION_SENTINEL_TIF=/path/to/2024-02-22.tif python -m unittest discover -s tests -p 'test_vembanad_regression.py' -v`.

## Validation guardrails

1. Never run the Vembanad model for Karnataka records merely because the
   catalogue supplies coordinates or a boundary.
2. Require the matching, reviewed, evidence-backed per-water-body validation
   manifest before inference.
3. Keep the exact five LSTM features, order, and model input shapes unchanged.
4. Do not treat Open-Meteo air temperature as in-lake SST.
5. Do not show low/medium/high thresholds or a historical percentage as a live
   bloom forecast.
6. Preserve the existing model artifacts and use the current Vembanad case as
   the regression reference with the archived B2/B3/B4/B8, 10 m, unmasked
   export contract. Do not apply this model to Karnataka catalogue records.
