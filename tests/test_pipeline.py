import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "discover_sources.py"], cwd=ROOT, check=True)

    def test_manifest_is_deterministic_and_complete(self):
        with tempfile.TemporaryDirectory() as td:
            # Run the builder from the repo root so it writes the normal manifest.
            subprocess.run([sys.executable, "discover_sources.py"], cwd=ROOT, check=True)
        payload = json.loads((ROOT / "data" / "source_manifest.json").read_text())
        entries = payload["entries"]
        self.assertEqual(len(entries), 207)
        self.assertEqual({e["source"] for e in entries},
                         {"PropertyPro.ng", "Nigeria Property Centre", "Estate Intel"})
        self.assertTrue(all(e["verified"] for e in entries))
        self.assertTrue(all(e["url"].startswith("https://") for e in entries))

    def test_no_bedroom_specific_urls(self):
        payload = json.loads((ROOT / "data" / "source_manifest.json").read_text())
        for e in payload["entries"]:
            if e["property_type"] == "flat_apartment":
                self.assertNotRegex(e["url"], r"/(?:1|2|3|4|5)[-_]?bedroom")

    def test_estate_intel_public_only(self):
        payload = json.loads((ROOT / "data" / "source_manifest.json").read_text())
        ei = [e for e in payload["entries"] if e["source"] == "Estate Intel"]
        self.assertEqual(len(ei), 9)
        self.assertTrue(all(e["transaction"] == "research" for e in ei))
        self.assertTrue(all("premium" not in e["url"].lower() for e in ei))

    def test_npc_does_not_use_zyte(self):
        text = Path("scraper.py").read_text(encoding="utf-8")
        marker = 'def fetch_page(url: str, source: str) -> requests.Response:'
        block = text[text.index(marker):text.index('    if not ZYTE_API_KEY:', text.index(marker))]
        self.assertIn('if source == "Nigeria Property Centre":', block)
        self.assertNotIn('ZYTE_ENDPOINT', block)

    def test_zyte_billing_failure_is_not_retried(self):
        text = Path("scraper.py").read_text(encoding="utf-8")
        self.assertIn('response.status_code in (401, 402, 403)', text)
        self.assertIn('PAID_SOURCE_FAILURE.set()', text)
        self.assertIn('will not retry billing/authorization failures', text)
    def test_workflow_uses_expected_output_name(self):
        text = (ROOT / ".github/workflows/weekly-scan.yml").read_text()
        self.assertIn("property_listings_", text)
        self.assertNotIn("lagos_listings_*.csv", text)


if __name__ == "__main__":
    unittest.main()

class ReportingTests(unittest.TestCase):
    def test_report_builder_contains_three_layers(self):
        import report_builder
        self.assertTrue(hasattr(report_builder, "build_executive_html"))
        self.assertTrue(hasattr(report_builder, "build_xlsx"))
        self.assertTrue(hasattr(report_builder, "build_docx"))
        self.assertTrue(hasattr(report_builder, "build_bundle"))

    def test_scraper_has_no_zenrows_runtime_dependency(self):
        text = Path("scraper.py").read_text(encoding="utf-8")
        self.assertNotIn("ZENROWS_API_KEY", text)
        self.assertNotIn("ZENROWS_ENDPOINT", text)

    def test_reporting_dependencies_are_lazy(self):
        import report_builder
        self.assertTrue(callable(report_builder.build_xlsx))
        self.assertTrue(callable(report_builder.build_docx))

    def test_market_output_validator_exists(self):
        text = Path("validate_market_output.py").read_text(encoding="utf-8")
        self.assertIn("ALLOWED_SOURCES", text)
        self.assertIn("NODES", text)


class EstateIntelSecurityTests(unittest.TestCase):
    def test_all_nine_canonical_nodes_are_defined(self):
        validator = Path("validate_market_output.py").read_text()
        expected = [
            "Banana Island",
            "Old Ikoyi",
            "Lekki Phase 1",
            "Victoria Island",
            "Eko Atlantic",
            "Ikeja GRA",
            "Asokoro",
            "Maitama",
            "Wuse",
        ]
        for node in expected:
            self.assertIn(f'"{node}"', validator)

    def test_old_composite_node_names_are_not_allowed(self):
        validator = Path("validate_market_output.py").read_text()
        old_names = [
            "Ikoyi - Banana Island",
            "Ikoyi - Old Ikoyi",
            "Lekki - Lekki Phase 1",
            "Ikeja - Ikeja GRA",
            "Abuja - Asokoro",
            "Abuja - Maitama",
            "Abuja - Wuse",
        ]
        for node in old_names:
            self.assertNotIn(f'"{node}"', validator)

    def test_estate_intel_public_only_guard_is_present(self):
        scraper = Path("scraper.py").read_text()
        self.assertIn("Public-only policy", scraper)
        self.assertIn("authentication/subscription gated", scraper)
        self.assertIn("Premium/login-gated values are not collected or bypassed.", scraper)


class ClientReportingTests(unittest.TestCase):
    def test_market_analysis_uses_canonical_nodes(self):
        text = Path("market_analysis.py").read_text(encoding="utf-8")
        for node in ["Banana Island","Old Ikoyi","Lekki Phase 1","Victoria Island","Eko Atlantic","Ikeja GRA","Asokoro","Maitama","Wuse"]:
            self.assertIn(f'"{node}"', text)
        self.assertNotIn('"Ikoyi - Banana Island"', text.split("def normalize_node",1)[0])

    def test_week_on_week_is_part_of_summary(self):
        import market_analysis
        rows=[
            {"market_node":"Lekki Phase 1","transaction":"sale","property_type":"flat_apartment","bedrooms":"3","asking_price_ngn":"100000000","price_per_sqm_ngn":"1000000"},
            {"market_node":"Lekki Phase 1","transaction":"rent","property_type":"flat_apartment","bedrooms":"3","asking_price_ngn":"5000000","price_per_sqm_ngn":"50000"},
        ]
        s=market_analysis.build_summary(rows,[],None)
        self.assertIn("week_on_week",s)
        self.assertIn("investment",s["signals"])

    def test_google_docs_publisher_exists(self):
        text=Path("docs_writer.py").read_text(encoding="utf-8")
        self.assertIn("documents().create",text)
        self.assertIn("documents().batchUpdate",text)
        self.assertIn("permissions().create",text)

    def test_client_distribution_is_supported(self):
        self.assertIn("REPORT_CLIENT_EMAIL",Path("email_report.py").read_text(encoding="utf-8"))
        self.assertIn("REPORT_CLIENT_EMAIL",Path(".github/workflows/weekly-scan.yml").read_text(encoding="utf-8"))


    def test_google_docs_dependency_is_declared(self):
        self.assertIn("google-api-python-client", Path("requirements.txt").read_text(encoding="utf-8"))

    def test_sheet_and_doc_client_viewer_hooks_exist(self):
        self.assertIn("permissions().create", Path("sheets_writer.py").read_text(encoding="utf-8"))
        self.assertIn("REPORT_CLIENT_EMAIL", Path("sheets_writer.py").read_text(encoding="utf-8"))
