"""Per-water-body model validation registry loaded from backend-only manifests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re


WATER_BODY_ID_PATTERN = re.compile(r"^KA[A-Z0-9]+$", re.IGNORECASE)
UNVALIDATED_STATUS = "data_model_validation_required"


class ModelValidationService:
    """Require a reviewed, evidence-backed manifest before enabling inference.

    A K-GIS catalogue record alone never confers model support. The optional
    manifest lives outside public API responses and is keyed by its stable ID.
    """

    def __init__(self, validation_dir: str | Path | None = None):
        self.validation_dir = Path(validation_dir or os.getenv(
            "HAB_MODEL_VALIDATION_DIR",
            Path(__file__).resolve().parents[2] / "data/model-validation",
        )).expanduser()

    @staticmethod
    def _unvalidated() -> dict:
        return {
            "model_supported": False,
            "model_validation_status": UNVALIDATED_STATUS,
            "model_status": UNVALIDATED_STATUS,
            "model_validation_note": (
                "No reviewed lake-specific model-validation record is configured."
            ),
        }

    def apply(self, water_body: dict) -> dict:
        body_id = str(water_body.get("id") or "")
        result = {**water_body, **self._unvalidated()}
        if not WATER_BODY_ID_PATTERN.fullmatch(body_id):
            return result

        path = self.validation_dir / f"{body_id.upper()}.json"
        if not path.is_file():
            return result

        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return result

        model_version = str(manifest.get("model_version") or "").strip()
        note = str(manifest.get("note") or "").strip()
        evidence = str(manifest.get("validation_evidence") or "").strip()
        approved = (
            str(manifest.get("water_body_id") or "").casefold() == body_id.casefold()
            and manifest.get("status") == "validated_prototype"
            and manifest.get("reviewed") is True
            and bool(model_version)
            and bool(note)
            and bool(evidence)
        )
        if not approved:
            return result

        result.update({
            "model_supported": True,
            "model_validation_status": "validated_prototype",
            "model_status": "validated_prototype",
            "model_version": model_version,
            "model_validation_note": note,
        })
        return result
