import unittest

from scraper import detect_price_period
from market_analysis import clean_rows
from enhance_client_report import data_quality_audit


class RentPeriodTests(unittest.TestCase):
    def test_explicit_monthly_period_is_detected(self):
        self.assertEqual(detect_price_period("₦1,000,000 per month", "rent"), "monthly")

    def test_explicit_annual_period_is_detected(self):
        self.assertEqual(detect_price_period("₦12,000,000 per annum", "rent"), "annual")

    def test_unspecified_period_is_not_guessed(self):
        self.assertEqual(detect_price_period("₦12,000,000", "rent"), "unspecified")

    def test_unknown_rent_period_is_excluded_from_annual_comparison(self):
        row = {
            "record_id": "r1",
            "source": "Nigeria Property Centre",
            "source_url": "https://nigeriapropertycentre.com/for-rent/flats-apartments/lagos/banana-island/123",
            "market_node": "Banana Island",
            "location": "Banana Island",
            "transaction": "rent",
            "property_type": "flat_apartment",
            "bedrooms": "3",
            "asking_price_ngn": "12000000",
            "price_period": "unspecified",
        }
        result = clean_rows([row])[0]
        self.assertEqual(result["asking_price_ngn"], "")
        self.assertEqual(result["source_asking_price_ngn"], 12000000.0)

    def test_two_listing_extreme_spread_is_flagged(self):
        base = {
            "source": "Nigeria Property Centre",
            "market_node": "Victoria Island",
            "location": "Victoria Island",
            "transaction": "rent",
            "property_type": "flat_apartment",
            "bedrooms": "1",
            "price_period": "annual",
        }
        rows = [
            {**base, "record_id": "low", "asking_price_ngn": "9000000",
             "source_url": "https://nigeriapropertycentre.com/for-rent/flats-apartments/lagos/victoria-island/low"},
            {**base, "record_id": "high", "asking_price_ngn": "590000000",
             "source_url": "https://nigeriapropertycentre.com/for-rent/flats-apartments/lagos/victoria-island/high"},
        ]
        findings = data_quality_audit(rows)
        self.assertTrue(any(x["type"] == "wide_price_spread_review" for x in findings))


if __name__ == "__main__":
    unittest.main()
