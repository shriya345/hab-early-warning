import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from backend.services.historical_prediction import archived_inputs

class HistoricalArchiveGates(unittest.TestCase):
    def test_missing_raster_is_rejected(self):
        with patch.dict('os.environ', {'HAB_REGRESSION_SENTINEL_TIF': '/missing/archive.tif'}):
            with self.assertRaisesRegex(ValueError, 'missing'):
                archived_inputs()

    def test_different_raster_is_rejected_before_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'other.tif'
            file.write_bytes(b'an unrelated image')
            with patch.dict('os.environ', {'HAB_REGRESSION_SENTINEL_TIF': str(file)}):
                with self.assertRaisesRegex(ValueError, 'not the verified'):
                    archived_inputs()
