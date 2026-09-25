# ALGAEWATCH — Lake Early Warning System

Research prototype for Karnataka-wide water-body discovery and HAB early warning.
The available CNN/LSTM was trained only on Vembanad Lake in Kerala and is not
validated for Karnataka lakes.

## Ryder / Integration Track

Current implementation includes:

- Input schema validation
- Satellite/environmental date alignment
- No-future-image leakage check
- Provisional chlorophyll-a-based bloom labels
- 5-day-ahead target creation
- Chronological train/test split
- Random Forest baseline model
- Accuracy, precision, recall, F1 and confusion matrix

## Important

Current baseline metrics were generated using mock data only to verify that the software pipeline works.

They are not scientific project results.

Real project inputs will later be supplied as:

### Satellite
`data/sentinel2/sentinel_index.csv`

Columns:

`date,image_path,cloud_percentage`

### Environmental
`data/environmental/processed/environmental_dataset.csv`

Columns:

`date,lat,lon,chlorophyll_a,sst,rainfall,wind_speed`


## Model probability and limitations

The Random Forest baseline also produces a model-estimated probability
of bloom occurrence five days ahead using `predict_proba()`.

The CNN/LSTM output is a model probability for its prototype target. It is not
a biological certainty, validated public-health threshold, or a categorical
low/medium/high alert. The Karnataka catalogue does not currently make a lake
eligible for a live probability: Karnataka model/data validation is required.

Current mock-data probabilities and evaluation metrics are used only
to verify that the end-to-end forecasting pipeline functions correctly.

## HAB Early-Warning Website

The project includes a React dashboard in `frontend/` and a FastAPI service in
`backend/main.py`. The dashboard searches named records in the official
Karnataka K-GIS layer across the state, resolves source records by stable ID,
and reports data coverage. Small urban records remain searchable. A lake's
presence in the catalogue does not make it eligible for a bloom probability;
lake-specific model validation and compatible inputs are required.

Use a Python environment with all entries in `requirements.txt` installed
(the saved-model demo was verified with Python 3.11). Run the API from the
repository root with that environment's `uvicorn backend.main:app --reload`.
Run the website with `cd frontend && npm run dev`; Vite proxies `/api` requests
to the API on port 8000. The API expects the Python dependencies used by
`src/inference/bloom_predictor.py` and the model files in `models/`.

The API accepts `HAB_MODEL_DIR`, `HAB_ENV_CSV`,
`HAB_ENVIRONMENTAL_MODEL_DIR`, `HAB_SATELLITE_CACHE`, backend-only
`CDSE_CLIENT_ID`/`CDSE_CLIENT_SECRET`, and the satellite contract attestation
`HAB_SATELLITE_INPUT_CONTRACT_VERIFIED`. `HAB_MODEL_VALIDATION_DIR` optionally
points to backend-only, per-water-body JSON validation manifests. A manifest
must match its K-GIS ID, declare `status: "validated_prototype"`, set
`reviewed: true`, and include a model version, validation note, and evidence
reference before inference can be enabled for that lake. No Karnataka lake
manifest is currently configured. The satellite attestation must also be
enabled before raw satellite rasters can enter inference; it is not needed for
metadata or RGB previews.
`GET /water-bodies/search?q=ulsoor` searches named records across the public
K-GIS inventory. It returns up to 25 records plus `has_more` and `next_offset`;
pass `offset=<next_offset>` to continue through all source matches. Multiword
search scans successive source pages so matching lakes beyond the first page
are included. `backend/curated_catalog.py` contains featured example lakes,
not an allowlist; unlisted named K-GIS records remain searchable.
`GET /water-bodies/{id}` resolves a selected body and returns `map_view` with
its source point and GeoJSON boundary. The website centers an OpenStreetMap
basemap on the boundary, or the point when no boundary is available. Neither
location nor boundary requires manual entry.
`GET /water-bodies/{id}/coverage` and
`GET /water-bodies/{id}/prediction` defaults to `mode=live` and reports that
body's inputs, model compatibility, and forecast eligibility. Karnataka records
currently return `prediction: null` with a validation-required status. The live path is
generic and requires an explicitly validated lake, a current seven-day
environmental input with verified units/order, and an aligned compatible
satellite raster.

`GET /water-bodies/{id}/prediction?mode=demo` explicitly runs the **saved**
CNN, LSTM, and 50/50 fusion on deterministic backend-generated synthetic
inputs. Optional `feature_date=YYYY-MM-DD` fixes the demonstration date;
otherwise the current India date is used. The response includes the separate
CNN, LSTM, and fused probabilities, `simulated: true`, a five-day model horizon,
and the seven synthetic environmental rows and synthetic four-band raster
description. Demo input generation uses the K-GIS ID and date only; K-GIS
coordinates and boundary remain real map context. The website labels every
demo value and the result as synthetic. Demo outputs are **not** Karnataka
observations or validated lake predictions. The live gates and warnings remain
in force when Live mode is selected.

For the nine saved Karnataka data-pilot lakes, the website also offers **Run
historical analysis** in the Historical data section.
`GET /water-bodies/{id}/historical/analysis` calculates boundary-wide median
B2/B3/B4/B8 surface reflectance after applying the source STAC scale and
offset, the SCL water-pixel fraction, and rainfall/wind summaries for the
seven days ending on the image date. This is a dated observation summary, not
CNN/LSTM inference or a live bloom probability. The endpoint returns 404 for
lakes without a saved snapshot and does not change the live prediction gate.

The backend queries the public K-GIS `Tank_Ownership` polygon layer. Search
with `GET /water-bodies/search?q=ulsoor`, then retrieve a selected record and
its boundary with `GET /water-bodies/{id}`. The layer uses stable
`UniqueTankID` values and provides water-body name, district/taluk/village,
latitude/longitude, area, and polygon geometry. A broader source inspection
observed 37,782 records, of which 8,887 have a name; 5,375 named records were
under 10 ha and 1,275 were under 1 ha (observed 2026-09-25). These source-wide
counts do not establish complete or current lake coverage. Featured examples
in `backend/curated_catalog.py` include Ulsoor, Varthur, Bellandur, Mysuru's
Kukkarahalli and Karanjikere, plus four Bengaluru urban records under 1 ha.
K-GIS metadata is published by the Karnataka State
Remote Sensing Applications Centre; see
the [K-GIS ArcGIS layer](https://kgis.ksrsac.in/kgismaps2/rest/services/Tank/Tank_Ownership/MapServer/1)
and [OGD Karnataka WaterBody catalog](https://www.data.gov.in/catalog/waterbody).

The display shortcuts are maintained in `backend/curated_catalog.py`; they do
not restrict the statewide search. The selected-record endpoint sends source
boundary geometry to the browser for map display when available. K-GIS records without names are
not assigned invented lake names. The source layer does not publish an explicit
update schedule or reuse license in its service metadata, so review those terms
before a public deployment. The map uses standard OpenStreetMap tiles with
visible attribution; a public deployment should assess its expected traffic
against the [OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

Catalogue presence does not authorize a prediction. Every Karnataka water body
currently reports `data_model_validation_required`; only the existing
Vembanad-trained model is available, and Vembanad is outside Karnataka. The
frontend has no manual coordinate or prediction-date controls. Open-Meteo can
supply gridded rainfall/wind and air-temperature context for a selected body;
this is not in-lake chlorophyll-a or SST, and it is not substituted into the
current trained model.

Provider credentials are not entered in the browser. Open-Meteo weather access
and recent Sentinel-2 STAC metadata search are keyless in this prototype. CDSE
STAC results provide the observation date and product-footprint cloud cover;
the latter is not lake-specific. Fetching Sentinel-2 pixels for a true-colour
preview or model raster uses backend-only `CDSE_ACCESS_TOKEN` when present, or
`CDSE_CLIENT_ID` and `CDSE_CLIENT_SECRET` from a CDSE OAuth client otherwise.
Set either the token or both OAuth variables in the backend process environment;
absent values produce an error naming the alternatives. Credentials
must never be placed in frontend code or committed in `.env`. The
RGB preview is not the CNN's four-band model input.

`python -m backend.diagnose_cdse auth` makes a read-only authenticated Catalog
API request and reports only authentication status, HTTP status, endpoint, and
locally decoded token expiry. `python -m backend.diagnose_cdse ulsoor` resolves
Ulsoor's K-GIS boundary, lists public CLMS product dates, and, when CDSE
credentials are configured, samples valid CHLAMEAN and LSWT pixels inside that
polygon with the Sentinel Hub Statistical API. CLMS products are 10-daily and
cannot supply the model's seven consecutive daily observations by themselves.

The backend's `fetch_model_raster` adapter requires the environmental feature
date. It searches the public Sentinel-2 L2A STAC catalogue within the five
preceding days and that date, rejects future or out-of-window scenes, and
restricts the authenticated Process API request to the selected acquisition
time. It requests
the verified B2/B3/B4/B8 order as harmonized UINT16 DNs, at the archive's
unmasked 10 m grid, and tiles large ROIs below the synchronous Process API
dimension limit. It verifies the four-band TIFF and writes only to the backend
cache. The existing predictor then resizes to 128×128, divides by 10,000,
and clips to [0, 2]. Acquiring a raster does not by itself
enable inference. The current Karnataka catalogue has no model-validated lake
or compatible live chlorophyll-a/SST window, so the user-facing analysis gate
remains closed.

CDSE references: [OAuth client credentials](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview/Authentication.html), [Sentinel-2 L2A data and DN units](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L2A.html), [STAC scene search](https://documentation.dataspace.copernicus.eu/APIs/STAC.html), and [Process API TIFF examples](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process/Examples/S2L2A.html).

The optional `HAB_ENVIRONMENTAL_MODEL_DIR` holds per-water-body `<id>.csv` and
`<id>.json` pairs. The manifest must identify the K-GIS ID and source, declare
the exact ordered feature names, and confirm the units were checked against
the model training data. The CSV must contain seven consecutive recent rows.
No compatible live chlorophyll-a/SST records are currently configured.

The archived CNN input contract was checked against the local
`ryder_satellite_check.ipynb` and the indexed 2024-02-22 TIFF. The notebook's
bulk export uses `COPERNICUS/S2_SR_HARMONIZED`, mosaics scenes from each date,
selects B2/B3/B4/B8, clips to `[76.30, 9.50, 76.50, 9.90]`, and exports at
10 m. That bulk-export path contains no SCL cloud mask. Google Earth Engine
documents SR values as UINT16 scaled by 10,000; the inference preprocessor
divides by 10,000, resizes to 128×128, then clips to [0, 2]. Scene/date
selection criteria before entries were added to the index are not recorded.
This confirms the archived input processing contract, not model validation for
other lakes. TIFFs remain outside the repository checkout. The Vembanad
historical regression test accepts an explicit image path and is not exposed as
a live website forecast. See
[lake support and data status](docs/lake-support-and-data-status.md).

Run service-gate tests with `python -m unittest discover -s tests -v`. To run
the model regression with the archived image, set
`HAB_REGRESSION_SENTINEL_TIF=/path/to/2024-02-22.tif` and run
`python -m unittest discover -s tests -p 'test_vembanad_regression.py' -v`.
The checked-in reference output is 39.2533% for the 2024-02-22 Vembanad sample;
this is a historical model-regression value, not a current bloom forecast.

The model's training labels are based on a Vembanad chlorophyll threshold, not
confirmed toxic-HAB observations. Its risk output is a research estimate and
must not be represented as a validated public-health alert or applied to other
lakes.

## Historical model prediction

The website now runs the archived Vembanad 2024-02-22 inputs through the saved
CNN/LSTM with a forecast target of 2024-02-27. Open `#historical-prediction`
and click **Run historical prediction**. See [the archive guide](docs/historical-bloom-prediction.md).
The Kochi ingestion dashboard has been removed from the website.
