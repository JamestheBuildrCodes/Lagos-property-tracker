import csv
import tempfile
import unittest
from pathlib import Path

import client_doc_report
from report_builder import build_xlsx_from_data
from market_analysis import build_summary

ROOT = Path(__file__).resolve().parents[1]


class ClientDocReportTests(unittest.TestCase):
    def sample_rows(self):
        return [
            {"date_scraped":"2026-09-29", "market_node":"Lekki Phase 1", "location":"Lekki Phase 1",
             "source":"PropertyPro.ng", "source_url":"https://propertypro.ng/property/lekki-phase-1-example-listing",
             "transaction":"sale", "property_type":"flat_apartment", "bedrooms":"3",
             "asking_price_ngn":"700000000", "price_per_sqm_ngn":"1400000", "title":"3 bedroom apartment"},
            {"date_scraped":"2026-09-28", "market_node":"Lekki Phase 1", "location":"Lekki Phase 1",
             "source":"PropertyPro.ng", "source_url":"https://propertypro.ng/agent/bad-record",
             "transaction":"sale", "property_type":"flat_apartment", "bedrooms":"3",
             "asking_price_ngn":"700000000", "price_per_sqm_ngn":"1400000", "title":"agent profile"},
        ]

    def test_breakdown_requires_auditable_listing_url(self):
        rows = client_doc_report.bedroom_breakdown(self.sample_rows(), "Lekki Phase 1", "sale")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sample"], "1 listing")
        self.assertEqual(rows[0]["link"], "https://propertypro.ng/property/lekki-phase-1-example-listing")

    def test_docx_contains_clickable_source_hyperlink_and_style(self):
        from market_analysis import clean_rows
        rows = clean_rows(self.sample_rows())
        summary = build_summary(rows, [], None)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "client.docx"
            client_doc_report.build_docx(rows, summary, str(out))
            self.assertTrue(out.exists())
            from zipfile import ZipFile
            with ZipFile(out) as z:
                document_xml = z.read("word/document.xml").decode("utf-8")
                rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
            self.assertIn("View source", document_xml)
            self.assertIn("propertypro.ng/property/lekki-phase-1-example-listing", rels)
            self.assertIn("D9D9D9", document_xml)

    def test_xlsx_headline_currency_and_percent_formats(self):
        from market_analysis import clean_rows
        rows = clean_rows(self.sample_rows())
        summary = build_summary(rows, [], None)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "report.xlsx"
            build_xlsx_from_data(rows, [], [], summary, str(out))
            from openpyxl import load_workbook
            wb = load_workbook(out, data_only=False)
            ws = wb["Executive Summary"]
            sale_row = next(r for r in range(1, ws.max_row+1) if ws.cell(r,1).value == "Median apartment sale")
            self.assertEqual(ws.cell(sale_row,2).value, "₦700,000,000")
            score = wb["Area Scorecard"]
            self.assertEqual(score["C2"].number_format, "#,##0")
            self.assertIn("%", score["E2"].number_format)
            self.assertNotEqual(score["E2"].number_format, "#,##0.00")


    def test_xlsx_has_explicit_estate_intel_public_research_status(self):
        from market_analysis import clean_rows
        rows = clean_rows(self.sample_rows())
        summary = build_summary(rows, [], None)
        research = [{
            "market_node": "Lekki Phase 1",
            "title": "Public research overview",
            "url": "https://estateintel.com/insights/example",
            "date_scraped": "2026-09-29",
            "public_sale_price_ngn": "",
            "land_area_sqm": "",
            "size_units": "",
        }]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "report.xlsx"
            build_xlsx_from_data(rows, [], research, summary, str(out))
            from openpyxl import load_workbook
            wb = load_workbook(out, data_only=True)
            self.assertIn("Estate Intel Public", wb.sheetnames)
            self.assertIn("Source Health", wb.sheetnames)
            health = wb["Source Health"]
            row = next(i for i in range(2, health.max_row + 1) if health.cell(i, 1).value == "Estate Intel")
            self.assertEqual(health.cell(row, 2).value, 1)
            self.assertEqual(health.cell(row, 3).value, 0)
            self.assertIn("Public research only", health.cell(row, 6).value)

    def test_docs_writer_formats_currency_and_uses_real_bullets(self):
        import docs_writer
        from market_analysis import clean_rows
        summary = build_summary(clean_rows(self.sample_rows()), [], None)
        text = docs_writer.report_text(summary)
        self.assertIn("₦700,000,000", text)
        requests = docs_writer._format_requests(text)
        self.assertTrue(any("createParagraphBullets" in request for request in requests))
        # The API requests remove the literal glyph before applying a real bullet.
        self.assertTrue(any("deleteContentRange" in request for request in requests))


    def test_google_doc_is_created_new_and_has_requested_table_styles(self):
        source = Path(client_doc_report.__file__).read_text(encoding="utf-8")
        self.assertIn('drive.files().create(body=', source)
        self.assertIn('GOOGLE_OAUTH_TOKEN_JSON', source)
        self.assertNotIn('GOOGLE_DOC_ID', source)
        self.assertIn('"updateTableCellStyle"', source)
        self.assertIn('"link": {"url": rows[ri - 1].get("link")}', source)
        self.assertIn('"MAILJET_API_KEY"', source)
        self.assertIn('"MAILJET_SECRET_KEY"', source)
        self.assertIn('"How to Read This Report"', source)
        self.assertIn('"What This Snapshot Covers — and What\'s Next"', source)
        self.assertIn('"Estate Intel — Public Research Context"', source)

    def test_narrative_discloses_missing_port_harcourt_and_estate_intel_context(self):
        from market_analysis import clean_rows
        rows = clean_rows(self.sample_rows())
        summary = build_summary(rows, [], None)
        narrative = client_doc_report._narrative_lines(rows, summary, research=[
            {"market_node": "Lekki Phase 1", "title": "Public research page",
             "url": "https://estateintel.com/insights/public-example",
             "date_scraped": "2026-09-29", "public_sale_price_ngn": ""}])
        rendered = "\n".join(value for kind, value in narrative if kind != "table")
        self.assertIn("Port Harcourt is not currently tracked", rendered)
        self.assertIn("Estate Intel", rendered)
        self.assertIn("How to Read This Report", rendered)
        self.assertIn("What This Snapshot Covers — and What's Next", rendered)

    def test_scraper_rejects_promo_copy_from_listing_cards(self):
        import scraper
        html = """<div class='results'>
        <div class='promo'>Premium Plus Top promoted listing. Email you when a new listing matches. Get alerts.</div>
        <div class='property-card'><a href='/property/3-bedroom-flat-for-sale-old-ikoyi-ikoyi-lagos-AAA11'>3 Bedroom Flat Old Ikoyi</a><span>₦500,000,000</span><span>Updated 14 Sep 2026</span><span>3 Beds</span></div>
        <div class='property-card'><a href='/property/4-bedroom-flat-for-sale-old-ikoyi-ikoyi-lagos-BBB22'>4 Bedroom Flat Old Ikoyi</a><span>₦700,000,000</span><span>Updated 14 Sep 2026</span><span>4 Beds</span></div>
        </div>"""
        cards = scraper.candidate_cards(html, "PropertyPro.ng", "https://propertypro.ng/property-for-sale/flat-apartment/in/lagos/ikoyi/old-ikoyi")
        self.assertEqual(len(cards), 2)
        self.assertTrue(all("premium plus" not in text.lower() for _, text in cards))
        self.assertTrue(all("email you when a new listing matches" not in text.lower() for _, text in cards))


if __name__ == "__main__":
    unittest.main()
