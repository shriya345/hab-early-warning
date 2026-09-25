import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock
import requests
from backend.services.live_coastal import LiveCoastalService, parse_series

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
STAMP = int(datetime(2026, 9, 25, tzinfo=timezone.utc).timestamp() * 1000)

def source(name='Chlorophyll-a', unit=' &#xb5g/l', rows=None):
    return "name: '%s', type: 'area', data: %s, units: '%s'" % (name, json.dumps(rows or [[STAMP, 1.67]]), unit)

class LiveCoastalTests(unittest.TestCase):
    def test_source_units_and_timestamp(self):
        rows = parse_series(source(), 'Chlorophyll-a', 'µg/l', NOW)
        self.assertEqual(rows[0], {'time': '2026-09-25T00:00:00+00:00', 'value': 1.67})

    def test_rejects_changed_units_future_and_conflicting_records(self):
        for document in [source(unit='mg/L'), source(rows=[[STAMP + 172800000, 1]]), source(rows=[[STAMP, 1], [STAMP, 2]])]:
            with self.assertRaises(ValueError):
                parse_series(document, 'Chlorophyll-a', 'µg/l', NOW)

    def test_offline_without_cache_is_unavailable(self):
        with TemporaryDirectory() as d:
            service = LiveCoastalService(Path(d) / 'cache.json', Mock(side_effect=requests.Timeout()))
            self.assertFalse(service.snapshot()['available'])

    def test_success_persists_and_outage_preserves_observation_time(self):
        def get(url, **kwargs):
            content = source() if 'cselgraph' in url else source('Water Temperature', ' &#8451', [[STAMP, 27.054]])
            return Mock(text=content, raise_for_status=Mock())
        with TemporaryDirectory() as d:
            path = Path(d) / 'cache.json'
            first = LiveCoastalService(path, get).snapshot()
            self.assertTrue(first['available'])
            self.assertFalse(first['cached'])
            second = LiveCoastalService(path, Mock(side_effect=requests.Timeout())).snapshot()
            self.assertTrue(second['cached'])
            self.assertEqual(first['retrieved_at'], second['retrieved_at'])
            self.assertEqual(first['series']['chlorophyll_a']['latest'], second['series']['chlorophyll_a']['latest'])

if __name__ == '__main__': unittest.main()
