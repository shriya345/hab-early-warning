from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from backend.services.model_validation import ModelValidationService


class ModelValidationServiceTests(unittest.TestCase):
    def setUp(self):
        self.body = {"id": "KA20010018", "name": "Ulsoor Lake", "model_supported": False}

    def test_missing_or_unreviewed_manifest_keeps_body_unvalidated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = ModelValidationService(temp_dir)
            self.assertFalse(service.apply(self.body)["model_supported"])

            Path(temp_dir, "KA20010018.json").write_text(json.dumps({
                "water_body_id": "KA20010018",
                "status": "validated_prototype",
                "reviewed": False,
                "model_version": "test-model",
                "note": "Test note",
                "validation_evidence": "Test protocol reference",
            }))
            self.assertFalse(service.apply(self.body)["model_supported"])

    def test_reviewed_evidence_backed_manifest_enables_named_model_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "KA20010018.json").write_text(json.dumps({
                "water_body_id": "KA20010018",
                "status": "validated_prototype",
                "reviewed": True,
                "model_version": "lake-model-v1",
                "note": "Validation against the documented lake holdout.",
                "validation_evidence": "protocol:lake-holdout-v1",
            }))
            result = ModelValidationService(temp_dir).apply(self.body)
        self.assertTrue(result["model_supported"])
        self.assertEqual(result["model_version"], "lake-model-v1")

    def test_manifest_for_a_different_lake_id_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "KA20010018.json").write_text(json.dumps({
                "water_body_id": "KA20040088",
                "status": "validated_prototype",
                "reviewed": True,
                "model_version": "other-lake-model",
                "note": "Other lake only.",
                "validation_evidence": "protocol:other-lake",
            }))
            result = ModelValidationService(temp_dir).apply(self.body)
        self.assertFalse(result["model_supported"])


if __name__ == "__main__":
    unittest.main()
