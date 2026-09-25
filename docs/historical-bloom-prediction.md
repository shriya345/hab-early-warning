# Historical Vembanad bloom prediction

Open http://127.0.0.1:5173/#historical-prediction and click **Run historical prediction**.
The frontend calls `POST /historical-predictions/vembanad`. Each request executes
the saved CNN and LSTM with 50/50 fusion; the displayed percentage is not a stored
fixture or generated input demonstration.

The supported archive pair is fixed to Vembanad: the Sentinel-2 TIFF dated
2024-02-22 and seven environmental rows from 2024-02-16 through 2024-02-22.
The forecast target is 2024-02-27. The TIFF was copied from the user's Downloads
archive into `data/sentinel2/processed/2024-02-22.tif`. Its SHA256, named band
order, dtype and region are checked before use. Set `HAB_REGRESSION_SENTINEL_TIF`
to another location of that identical archive if needed. Do not substitute
another lake or date under this configuration.

The existing preprocessing remains 128×128, division by 10,000, clipping to
[0,2], and the original environmental scaler and feature order. All seven
chlorophyll flags are zero for this example. The wider environmental archive
contains imputed values, which must remain disclosed when adding other windows.

The saved models produced CNN 30.1166%, LSTM 48.3899%, fusion 39.2533%.
The archive is associated with the model's development data, so this replay
is not an independent evaluation. Labels are chlorophyll-threshold proxies,
not confirmed toxic-HAB events. The estimate describes a dated five-day
forecast, not a permanent property of the lake.

The Kochi ingestion dashboard is removed from the UI. Its backend adapter and
cached data remain available for future work but are not requested by the page.
Karnataka live prediction gates are unchanged.
