"""Assemble private, model-contract-checked inputs for a water body."""

from __future__ import annotations

from datetime import date
import os

from backend.services.environment import EnvironmentService
from backend.services.satellite import SatelliteService, SatelliteSourceUnavailable


class ModelInputService:
    """Join a validated lake's current environmental window and satellite raster.

    Catalogue lookup alone never makes a lake eligible. Before acquiring model
    pixels, this service requires an explicit per-water-body validation record,
    seven current environmental rows with verified units/order, nearby scene
    metadata, and an operator attestation that the satellite source contract was
    checked against the archived training pipeline.
    """

    def __init__(
        self,
        environment_service: EnvironmentService,
        satellite_service: SatelliteService,
    ):
        self.environment_service = environment_service
        self.satellite_service = satellite_service

    @staticmethod
    def _incomplete(reason: str) -> dict:
        return {"complete": False, "readiness_message": reason}

    def prepare(self, water_body: dict, satellite_coverage: dict, environment_coverage: dict) -> dict:
        if not (
            water_body.get("model_supported") is True
            and water_body.get("model_validation_status") == "validated_prototype"
        ):
            return self._incomplete("Prediction is not currently validated for this water body.")

        if not environment_coverage.get("model_inputs_complete"):
            details = (environment_coverage.get("model_window") or {}).get("message")
            return self._incomplete(details or "Environmental data is incomplete for the required model window.")
        if environment_coverage.get("expected_model_features") != [
            "chlorophyll_a", "sst", "rainfall", "wind_speed", "chlorophyll_imputed"
        ]:
            return self._incomplete("Environmental features do not match the trained model contract.")

        window, window_status = self.environment_service.model_window(water_body)
        if window is None:
            return self._incomplete(
                window_status.get("message") or "Environmental data is incomplete for the required model window."
            )

        observation_date = satellite_coverage.get("observation_date")
        if not satellite_coverage.get("scene_metadata_available") or not observation_date:
            return self._incomplete(
                satellite_coverage.get("message") or "Satellite imagery is unavailable for this water body."
            )

        try:
            scene_day = date.fromisoformat(str(observation_date)[:10])
            window_end = date.fromisoformat(str(window_status["end_date"]))
        except (KeyError, TypeError, ValueError):
            return self._incomplete("Satellite and environmental dates could not be aligned.")
        if (window_end - scene_day).days not in range(0, 6):
            return self._incomplete(
                "Satellite imagery is not within five days of the environmental model window."
            )
        if satellite_coverage.get("feature_date") != window_end.isoformat():
            return self._incomplete(
                "Satellite scene search was not aligned with the environmental feature date."
            )

        if os.getenv("HAB_SATELLITE_INPUT_CONTRACT_VERIFIED", "").strip().casefold() not in {
            "1", "true", "yes"
        }:
            return self._incomplete(
                "Satellite input format is known, but archived scene-selection compatibility has not been attested."
            )

        try:
            raster = self.satellite_service.fetch_model_raster(
                water_body,
                feature_date=window_end,
                scene_coverage=satellite_coverage,
            )
        except SatelliteSourceUnavailable as exc:
            return self._incomplete(str(exc))

        if (
            raster.get("band_order") != ["B2", "B3", "B4", "B8"]
            or raster.get("sample_type") != "UINT16 DN, harmonized"
            or raster.get("cloud_mask_applied") is not False
            or not raster.get("model_input_contract_verified")
        ):
            return self._incomplete("Satellite raster did not pass the verified CNN input contract.")
        return {
            "complete": True,
            "satellite_model_input_contract_verified": True,
            "satellite_raster_path": raster["local_path"],
            "satellite_observation_date": raster["observation_date"],
            "environment_window_end_date": window_status["end_date"],
            "environmental_window": window,
            "environment_window_source": window_status["source"],
            "satellite_source": raster.get("source"),
        }
