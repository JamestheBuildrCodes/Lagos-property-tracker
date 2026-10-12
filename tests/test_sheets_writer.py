"""Regression tests for writing workbook grids to Google Sheets."""
import unittest

from sheets_writer import _verify_sheet_readback


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
            ["Listings tracked", "120", "—"],
        ]
        _verify_sheet_readback("Executive Summary", expected, returned)

    def test_still_fails_on_real_value_mismatch(self):
        expected = [
            ["Metric", "Current", "Week-on-week"],
            ["Listings tracked", 120, "—"],
        ]
        returned = [
            ["Metric", "Current", "Week-on-week"],
            ["Listings tracked", "121", "—"],
        ]
        with self.assertRaisesRegex(
            RuntimeError,
            r"worksheet 'Executive Summary' at B2",
        ):
            _verify_sheet_readback("Executive Summary", expected, returned)

    def test_preserves_zero_instead_of_treating_it_as_blank(self):
        _verify_sheet_readback("Summary", [["Metric", "Count"], ["Open listings", 0]],
                               [["Metric", "Count"], ["Open listings", "0"]])

    def test_pads_missing_trailing_rows_but_not_missing_values(self):
        _verify_sheet_readback("Summary", [["Title", None], [None, None]],
                               [["Title"]])
        with self.assertRaisesRegex(RuntimeError, r"at A2"):
            _verify_sheet_readback("Summary", [["Title"], ["Required metric"]],
                                   [["Title"]])


if __name__ == "__main__":
    unittest.main()
