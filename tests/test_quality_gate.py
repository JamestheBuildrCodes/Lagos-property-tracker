import unittest

from quality_gate import is_bulk_multi_unit_listing


class BulkMultiUnitQualityTests(unittest.TestCase):
    def test_twenty_six_unit_block_is_not_single_apartment_comparable(self):
        row = {
            "property_type": "flat_apartment",
            "title": "Premium 25",
            "source_excerpt": "26 units block of flats available for rent in Victoria Island",
        }
        self.assertTrue(is_bulk_multi_unit_listing(row))

    def test_normal_one_bedroom_listing_is_not_quarantined_by_title_alone(self):
        row = {
            "property_type": "flat_apartment",
            "title": "1 bedroom apartment for rent in Victoria Island",
            "source_excerpt": "One-bedroom apartment; annual asking rent ₦9,000,000.",
        }
        self.assertFalse(is_bulk_multi_unit_listing(row))


if __name__ == "__main__":
    unittest.main()
