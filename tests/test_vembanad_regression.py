from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
REGRESSION = json.loads(
    (Path(__file__).parent / "fixtures/vembanad_regression_2024-02-22.json").read_text()
)


class VembanadInferenceRegressionTests(unittest.TestCase):
    def test_archived_vembanad_model_output(self):
        raster_path = Path(os.getenv("HAB_REGRESSION_SENTINEL_TIF", "")).expanduser()
        if not raster_path.is_file():
            self.skipTest("Set HAB_REGRESSION_SENTINEL_TIF to the archived 2024-02-22 Vembanad TIFF.")

        try:
            import cv2  # noqa: F401
            import joblib  # noqa: F401
            import rasterio  # noqa: F401
            import sklearn  # noqa: F401
            import tensorflow  # noqa: F401
        except ModuleNotFoundError as exc:
            self.skipTest(f"Model inference dependency is unavailable: {exc.name}")

        from src.inference.bloom_predictor import BloomRiskPredictor

        target = pd.Timestamp(REGRESSION["target_date"])
        frame = pd.read_csv(
            ROOT / "data/environmental/processed/environmental_lstm_ready.csv",
            parse_dates=["date"],
        ).sort_values("date")
        window = frame.loc[
            (frame.date >= target - pd.Timedelta(days=6)) & (frame.date <= target)
        ].reset_index(drop=True)
        self.assertEqual(len(window), 7)
        self.assertEqual(window.date.iloc[0].date().isoformat(), REGRESSION["environmental_window_start"])
        self.assertEqual(window.date.iloc[-1].date().isoformat(), REGRESSION["environmental_window_end"])
        self.assertTrue((window.date.diff().dropna() == pd.Timedelta(days=1)).all())

        result = BloomRiskPredictor(str(ROOT / "models")).predict(
            sentinel_tif_path=str(raster_path),
            environmental_7day_df=window,
        )
        tolerance = float(REGRESSION["tolerance"])
        for key, expected in REGRESSION["expected"].items():
            self.assertAlmostEqual(float(result[key]), float(expected), delta=tolerance, msg=key)


if __name__ == "__main__":
    unittest.main()
