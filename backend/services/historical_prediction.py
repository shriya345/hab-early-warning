"""Explicit, date-bound replay of the archived Vembanad model inputs."""
from datetime import date, timedelta
from pathlib import Path
import math
import hashlib
import os
import threading

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ['chlorophyll_a', 'sst', 'rainfall', 'wind_speed', 'chlorophyll_imputed']
DAY = date(2024, 2, 22)
LOCK = threading.Lock()


def archived_inputs():
    raster = Path(os.getenv('HAB_REGRESSION_SENTINEL_TIF', ROOT / 'data/sentinel2/processed/2024-02-22.tif')).expanduser()
    if not raster.is_file():
        raise ValueError('The archived 2024-02-22 Vembanad four-band TIFF is missing. Configure HAB_REGRESSION_SENTINEL_TIF on the backend.')
    with raster.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != '63ec3b427c4af11001478ca935e9f66edb78cc12a3c0a754793e77a3561f5e34':
        raise ValueError('The raster is not the verified 2024-02-22 Vembanad archive file.')
    import rasterio
    from rasterio.warp import transform_bounds
    with rasterio.open(raster) as src:
        if src.count != 4 or src.descriptions != ('B2', 'B3', 'B4', 'B8') or src.dtypes != ('uint16',) * 4:
            raise ValueError('The archived raster does not match the trained band contract.')
        bounds = transform_bounds(src.crs, 'EPSG:4326', *src.bounds) if str(src.crs) != 'EPSG:4326' else tuple(src.bounds)
        if not (76.2 < bounds[0] < 76.4 and 9.4 < bounds[1] < 9.6 and 76.4 < bounds[2] < 76.6 and 9.8 < bounds[3] < 10):
            raise ValueError('Raster bounds do not match the archived Vembanad region.')
    frame = pd.read_csv(ROOT / 'data/environmental/processed/environmental_lstm_ready.csv', parse_dates=['date'])
    window = frame.loc[(frame.date.dt.date >= DAY - timedelta(days=6)) & (frame.date.dt.date <= DAY)].sort_values('date').reset_index(drop=True)
    expected = [(DAY - timedelta(days=6) + timedelta(days=i)) for i in range(7)]
    if window.date.dt.date.tolist() != expected:
        raise ValueError('The archived environmental window must contain seven consecutive days.')
    values = window[FEATURES].astype(float)
    if not all(math.isfinite(v) for v in values.to_numpy().ravel()) or not set(values.chlorophyll_imputed).issubset({0, 1}):
        raise ValueError('The archived environmental values are invalid.')
    return raster, window


def run_historical_prediction(predictor_factory):
    raster, window = archived_inputs()
    with LOCK:
        predictor = predictor_factory()
        cfg = predictor.config
        if (cfg['environmental_features'] != FEATURES or cfg['cnn_image_size'] != 128
                or cfg['lstm_window_days'] != 7 or cfg['forecast_horizon_days'] != 5
                or cfg['cnn_weight'] != 0.5 or cfg['lstm_weight'] != 0.5):
            raise ValueError('Saved model configuration differs from the historical contract.')
        scores = predictor.predict(str(raster), window)
    for key in ['cnn_probability', 'lstm_probability', 'bloom_risk_probability']:
        if not math.isfinite(scores[key]) or not 0 <= scores[key] <= 1:
            raise ValueError('The saved model returned an invalid probability.')
    return {
        'mode': 'historical', 'water_body': 'Vembanad Lake, Kerala', 'simulated': False,
        'observation_date': DAY.isoformat(), 'forecast_target_date': (DAY + timedelta(days=5)).isoformat(),
        **scores, 'environment_start': (DAY - timedelta(days=6)).isoformat(),
        'environmental_features': FEATURES,
        'environmental_rows': [{'date': row.date.date().isoformat(), **{f: float(row[f]) for f in FEATURES}} for _, row in window.iterrows()],
        'imputed_chlorophyll_days': int(window.chlorophyll_imputed.sum()),
        'source': 'Project Vembanad 2024 environmental archive and indexed Sentinel-2 SR Harmonized TIFF',
        'note': 'Historical research estimate for 27 February 2024 using inputs ending 22 February 2024. Labels represent a chlorophyll threshold proxy, not confirmed toxic HABs. This archive replay is not an independent validation or a current forecast.'
    }
