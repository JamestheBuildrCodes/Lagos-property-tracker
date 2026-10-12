import unittest
from unittest.mock import patch

import client_doc_report


def land_row(price, size, url_suffix):
    return {
        "market_node": "Banana Island",
        "transaction": "land_sale",
        "property_type": "land",
        "asking_price_ngn": str(price),
        "size_sqm": str(size),
        "source": "Nigeria Property Centre",
        "source_url": f"https://nigeriapropertycentre.com/for-sale/land/lagos/ikoyi/banana-island/{url_suffix}",
        "listing_date": "2026-10-10",
        "date_scraped": "2026-10-12",
        "listing_age_days": "2",
    }


class ClientReportQualityTests(unittest.TestCase):
    def test_single_listing_is_not_mislabelled_as_a_median_and_land_ppsqm_is_shown(self):
        rows = [land_row(45_000_000, 500, "plot-a")]
        with patch.object(client_doc_report, "clean_rows", return_value=rows):
            result = client_doc_report._source_breakdown_rows(
                rows, "Banana Island", "land"
            )

        self.assertEqual(len(result), 1)
        self.assertIn("single observed asking price", result[0]["value"])
        self.assertEqual(result[0]["plot_size"], "500 sqm")
        self.assertEqual(result[0]["price_per_sqm"], "₦90,000/sqm")
        self.assertEqual(result[0]["sample"], "1")

    def test_two_listing_midpoint_is_explicitly_flagged_as_unstable(self):
        rows = [
            land_row(9_000_000, 300, "plot-a"),
            land_row(590_000_000, 600, "plot-b"),
        ]
        with patch.object(client_doc_report, "clean_rows", return_value=rows):
            result = client_doc_report._source_breakdown_rows(
                rows, "Banana Island", "land"
            )

        self.assertEqual(len(result), 1)
        self.assertIn("midpoint of 2 listings", result[0]["value"])
        self.assertEqual(result[0]["range"], "₦9,000,000 – ₦590,000,000")
        self.assertEqual(result[0]["plot_size"], "300–600 sqm")
        self.assertEqual(result[0]["price_per_sqm"], "₦506,667/sqm")


    def test_area_scorecard_does_not_substitute_other_bedroom_prices_for_3br(self):
        import market_analysis

        rows = [
            {
                "market_node": "Victoria Island",
                "transaction": "rent",
                "property_type": "flat_apartment",
                "bedrooms": "1",
                "asking_price_ngn": "590000000",
                "source": "Nigeria Property Centre",
                "source_url": "https://nigeriapropertycentre.com/for-rent/flats-apartments/lagos/victoria-island/one-bedroom-a",
                "title": "1 bedroom apartment in Victoria Island",
            },
            {
                "market_node": "Victoria Island",
                "transaction": "sale",
                "property_type": "flat_apartment",
                "bedrooms": "1",
                "asking_price_ngn": "350000000",
                "source": "Nigeria Property Centre",
                "source_url": "https://nigeriapropertycentre.com/for-sale/flats-apartments/lagos/victoria-island/one-bedroom-b",
                "title": "1 bedroom apartment in Victoria Island",
            },
        ]
        vi = next(
            row for row in market_analysis.area_scorecard(rows)
            if row["market_node"] == "Victoria Island"
        )
        self.assertIsNone(vi["rent_3br_median"])
        self.assertIsNone(vi["sale_3br_median"])
        self.assertEqual(vi["rent_3br_count"], 0)
        self.assertEqual(vi["sale_3br_count"], 0)


if __name__ == "__main__":
    unittest.main()
