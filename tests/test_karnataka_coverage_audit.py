import unittest

from scripts.audit_karnataka_coverage import FIELDS, audit_row, basic_polygon_available


POLYGON = {"type": "Polygon", "coordinates": [[[77.5, 13.0], [77.6, 13.0],
                                                [77.6, 13.1], [77.5, 13.0]]]}


class KarnatakaCoverageAuditTests(unittest.TestCase):
    def test_basic_polygon_requires_real_coordinate_structure(self):
        self.assertTrue(basic_polygon_available(POLYGON))
        self.assertFalse(basic_polygon_available({"type": "Point", "coordinates": [77.5, 13]}))
        self.assertFalse(basic_polygon_available({
            "type": "Polygon", "coordinates": [[[77.5, 13]] * 4],
        }))

    def test_catalogue_feature_does_not_become_verified_observation(self):
        feature = {"properties": {
            "UniqueTankID": "KA20010018", "TankName": "Ulsoor Lake",
            "KGISDistrictName": "Bengaluru (Urban)", "TankArea_Ha": 41.8,
            "Latitude": 13.0, "Longitude": 77.5,
        }, "geometry": POLYGON}
        row = audit_row(feature)
        self.assertEqual(tuple(row), FIELDS)
        self.assertEqual(row["kgis_id"], "KA20010018")
        self.assertEqual(row["geometry_status"], "basic_polygon_coordinates_present")
        self.assertEqual(row["satellite_dates"], "not_verified")
        self.assertEqual(row["chlorophyll_dates"], "not_verified")
        self.assertEqual(row["lswt_dates"], "not_verified")
        self.assertEqual(row["usable_periods"], 0)

    def test_unusable_catalogue_record_is_retained_and_flagged(self):
        row = audit_row({"properties": {
            "UniqueTankID": "KA00000000", "TankName": "  ",
        }, "geometry": POLYGON})
        self.assertEqual(row["lake_name"], "")
        self.assertIn("unusable_catalogue_record", row["quality_flags"])


if __name__ == "__main__":
    unittest.main()
