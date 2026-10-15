"""Regression tests for Google Sheets publication helpers."""
import unittest
from unittest.mock import Mock, patch
import json
import os

from sheets_writer import share_viewer

import gspread
from sheets_writer import _retry_sheets_write, _verify_sheet_readback


class FakeSheetsResponse:
    def __init__(self, status_code, message):
        self.status_code = status_code
        self._payload = {"error": {"code": status_code, "message": message, "status": "RESOURCE_EXHAUSTED"}}

    def json(self):
        return self._payload


class FakeSheetsAPIError(gspread.exceptions.APIError):
    def __init__(self, status_code, message):
        super().__init__(FakeSheetsResponse(status_code, message))



class SheetSharingTests(unittest.TestCase):
    def test_share_viewer_uses_service_account_credentials_not_gspread_client_auth(self):
        drive = Mock()
        drive.permissions.return_value.list.return_value.execute.return_value = {
            "permissions": [{
                "id": "perm-1", "type": "user",
                "emailAddress": "client@example.com", "role": "reader",
            }]
        }
        service_credentials = object()
        with patch.dict(os.environ, {
            "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"client_email": "svc@example.com"})
        }), patch(
            "sheets_writer.Credentials.from_service_account_info",
            return_value=service_credentials,
        ) as make_credentials, patch(
            "googleapiclient.discovery.build", return_value=drive
        ) as build:
            share_viewer("sheet-123", "client@example.com")
        make_credentials.assert_called_once()
        build.assert_called_once_with(
            "drive", "v3", credentials=service_credentials, cache_discovery=False
        )
        drive.permissions.return_value.list.assert_called_once()

class SheetReadbackTests(unittest.TestCase):
    def test_accepts_google_sheets_omitting_trailing_blanks(self):
        # Excel uses merged A1:C1 and A2:C2 cells on the Executive Summary.
        # The Sheets values API returns only non-empty cells at each row's end.
        expected = [
            ["Weekly property market report", None, None],
            ["12 October 2026", None, None],
            ["Metric", "Current", "Week-on-week"],
            ["Listings tracked", 120, "—"],
        ]
        returned = [
            ["Weekly property market report"],
            ["12 October 2026"],
            ["Metric", "Current", "Week-on-week"],
            ["Listings tracked", 120.0, "—"],
        ]
        _verify_sheet_readback("Executive Summary", expected, returned)

    def test_still_fails_on_real_value_mismatch(self):
        expected = [
            ["Metric", "Current", "Week-on-week"],
            ["Listings tracked", 120, "—"],
        ]
        returned = [
            ["Metric", "Current", "Week-on-week"],
            ["Listings tracked", 121.0, "—"],
        ]
        with self.assertRaisesRegex(
            RuntimeError,
            r"worksheet 'Executive Summary' at B2",
        ):
            _verify_sheet_readback("Executive Summary", expected, returned)

    def test_accepts_equivalent_integer_and_float_numeric_values(self):
        _verify_sheet_readback(
            "Area Scorecard",
            [["Area", "Count", "Price"], ["Lekki", 12, 1250000]],
            [["Area", "Count", "Price"], ["Lekki", 12.0, 1250000.0]],
        )

    def test_does_not_confuse_numeric_value_with_numeric_text(self):
        with self.assertRaisesRegex(RuntimeError, r"at B2"):
            _verify_sheet_readback("Summary", [["Metric", "Count"], ["Open", 12]],
                                   [["Metric", "Count"], ["Open", "12"]])

    def test_preserves_zero_instead_of_treating_it_as_blank(self):
        _verify_sheet_readback("Summary", [["Metric", "Count"], ["Open listings", 0]],
                               [["Metric", "Count"], ["Open listings", "0"]])

    def test_pads_missing_trailing_rows_but_not_missing_values(self):
        _verify_sheet_readback("Summary", [["Title", None], [None, None]],
                               [["Title"]])
        with self.assertRaisesRegex(RuntimeError, r"at A2"):
            _verify_sheet_readback("Summary", [["Title"], ["Required metric"]],
                                   [["Title"]])


class SheetsQuotaRetryTests(unittest.TestCase):
    def test_retries_http_429_with_exponential_backoff(self):
        calls = {"count": 0}

        def write():
            calls["count"] += 1
            if calls["count"] < 3:
                raise FakeSheetsAPIError(429, "Quota exceeded for write requests")
            return "written"

        with patch("sheets_writer.time.sleep") as sleep:
            result = _retry_sheets_write("test write", write, max_attempts=4)

        self.assertEqual(result, "written")
        self.assertEqual(calls["count"], 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10])

    def test_does_not_retry_non_transient_api_errors(self):
        calls = {"count": 0}

        def forbidden_write():
            calls["count"] += 1
            raise FakeSheetsAPIError(403, "Permission denied")

        with patch("sheets_writer.time.sleep") as sleep:
            with self.assertRaisesRegex(FakeSheetsAPIError, "Permission denied"):
                _retry_sheets_write("forbidden write", forbidden_write)

        self.assertEqual(calls["count"], 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
