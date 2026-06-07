from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from wc_predictions_bot.import_compact_xlsx import parse_matches


class FakeSheet:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def iter_rows(self, *, min_row: int, values_only: bool) -> list[tuple[object, ...]]:
        self.assert_parse_args(min_row, values_only)
        return self.rows

    @staticmethod
    def assert_parse_args(min_row: int, values_only: bool) -> None:
        if min_row != 5 or not values_only:
            raise AssertionError("Unexpected parse_matches iter_rows arguments.")


class ImportCompactXlsxTest(unittest.TestCase):
    def test_match_deadline_is_five_minutes_before_kickoff(self) -> None:
        kickoff = datetime(2026, 6, 11, 22, 0)
        sheet_deadline = kickoff - timedelta(minutes=30)

        rows = parse_matches(
            FakeSheet(
                [
                    ("A", "1", None, kickoff, sheet_deadline, "Мексика - ЮАР"),
                ]
            )
        )

        self.assertEqual(rows[0][0], "MexSAf")
        self.assertEqual(rows[0][3], "2026-06-11T22:00:00+03:00")
        self.assertEqual(rows[0][4], "2026-06-11T21:55:00+03:00")


if __name__ == "__main__":
    unittest.main()
