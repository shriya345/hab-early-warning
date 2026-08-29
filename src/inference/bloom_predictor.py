
import os
import cv2
import joblib
import rasterio
import numpy as np
import tensorflow as tf


class BloomRiskPredictor:

    def __init__(self, model_dir):

        self.model_dir = model_dir

        self.cnn_model = tf.keras.models.load_model(
            os.path.join(
                model_dir,
                "cnn_model.keras"
            )
        )

        self.lstm_model = tf.keras.models.load_model(
            os.path.join(
                model_dir,
                "lstm_model.keras"
            )
        )

        self.scaler = joblib.load(
            os.path.join(
                model_dir,
                "lstm_scaler.pkl"
            )
        )

        self.config = joblib.load(
            os.path.join(
                model_dir,
                "model_config.pkl"
            )
        )


    def _prepare_satellite_image(
        self,
        sentinel_tif_path
    ):

        with rasterio.open(
            sentinel_tif_path
        ) as src:

            img = src.read().astype(
                np.float32
            )

        # (bands, H, W)
        # ->
        # (H, W, bands)
        img = np.transpose(
            img,
            (1, 2, 0)
        )

        img = cv2.resize(
            img,
            (
                self.config[
                    "cnn_image_size"
                ],
                self.config[
                    "cnn_image_size"
                ]
            ),
            interpolation=cv2.INTER_AREA
        )

        img = img / 10000.0

        img = np.clip(
            img,
            0.0,
            2.0
        )

        return np.expand_dims(
            img,
            axis=0
        )


    def _prepare_environment(
        self,
        environmental_7day_df
    ):

        required_days = self.config[
            "lstm_window_days"
        ]

        if len(
            environmental_7day_df
        ) != required_days:

            raise ValueError(
                f"Expected exactly "
                f"{required_days} "
                f"environmental rows, "
                f"received "
                f"{len(environmental_7day_df)}."
            )

        features = self.config[
            "environmental_features"
        ]

        missing = [
            feature
            for feature in features
            if feature
            not in environmental_7day_df.columns
        ]

        if missing:

            raise ValueError(
                "Missing environmental "
                f"features: {missing}"
            )

        env_values = (
            environmental_7day_df[
                features
            ]
            .values
            .astype(np.float32)
        )

        env_scaled = (
            self.scaler
            .transform(env_values)
        )

        return np.expand_dims(
            env_scaled,
            axis=0
        )


    def predict(
        self,
        sentinel_tif_path,
        environmental_7day_df
    ):

        satellite_input = (
            self._prepare_satellite_image(
                sentinel_tif_path
            )
        )

        environment_input = (
            self._prepare_environment(
                environmental_7day_df
            )
        )

        cnn_probability = float(
            self.cnn_model.predict(
                satellite_input,
                verbose=0
            )[0][0]
        )

        lstm_probability = float(
            self.lstm_model.predict(
                environment_input,
                verbose=0
            )[0][0]
        )

        fusion_probability = (
            self.config[
                "cnn_weight"
            ]
            * cnn_probability
            +
            self.config[
                "lstm_weight"
            ]
            * lstm_probability
        )

        return {
            "cnn_probability":
                cnn_probability,

            "lstm_probability":
                lstm_probability,

            "bloom_risk_probability":
                fusion_probability,

            "bloom_risk_percent":
                fusion_probability * 100,

            "forecast_horizon_days":
                self.config[
                    "forecast_horizon_days"
                ]
        }
