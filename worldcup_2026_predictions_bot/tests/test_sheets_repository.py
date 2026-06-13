from __future__ import annotations

import unittest
from typing import Any

from wc_predictions_bot.sheets_repository import SheetsRepository


class _Executable:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.result = result or {}

    def execute(self) -> dict[str, Any]:
        return self.result


class _FakeValues:
    def __init__(self, owner: "_FakeSheetsService") -> None:
        self.owner = owner

    def clear(self, **kwargs: Any) -> _Executable:
        self.owner.calls.append(("clear", kwargs))
        self.owner.values = []
        return _Executable()

    def update(self, **kwargs: Any) -> _Executable:
        self.owner.calls.append(("update", kwargs))
        self.owner.values = kwargs.get("body", {}).get("values", [])
        return _Executable()

    def append(self, **kwargs: Any) -> _Executable:
        self.owner.calls.append(("append", kwargs))
        values = kwargs.get("body", {}).get("values", [])
        self.owner.values.extend(values)
        return _Executable()

    def get(self, **kwargs: Any) -> _Executable:
        self.owner.calls.append(("values_get", kwargs))
        return _Executable({"values": self.owner.values})


class _FakeSpreadsheets:
    def __init__(self, owner: "_FakeSheetsService") -> None:
        self.owner = owner
        self._values = _FakeValues(owner)

    def values(self) -> _FakeValues:
        return self._values

    def get(self, **kwargs: Any) -> _Executable:
        self.owner.calls.append(("metadata_get", kwargs))
        return _Executable(
            {
                "sheets": [
                    {"properties": {"title": title, "sheetId": sheet_id}}
                    for title, sheet_id in self.owner.sheet_ids.items()
                ]
            }
        )

    def batchUpdate(self, **kwargs: Any) -> _Executable:
        self.owner.calls.append(("batchUpdate", kwargs))
        self.owner.batch_updates.append(kwargs)
        for request in kwargs.get("body", {}).get("requests", []):
            add_sheet = request.get("addSheet")
            if add_sheet:
                title = add_sheet.get("properties", {}).get("title")
                if title:
                    self.owner.sheet_ids[title] = max(self.owner.sheet_ids.values(), default=100) + 1
        return _Executable()


class _FakeSheetsService:
    def __init__(self) -> None:
        self.values: list[list[str]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.batch_updates: list[dict[str, Any]] = []
        self.sheet_ids = {
            "scoring": 101,
            "predictions_raw": 102,
            "leaderboard": 103,
        }
        self._spreadsheets = _FakeSpreadsheets(self)

    def spreadsheets(self) -> _FakeSpreadsheets:
        return self._spreadsheets


class SheetsRepositoryTest(unittest.TestCase):
    def test_replace_rows_resets_filter_to_written_range(self) -> None:
        service = _FakeSheetsService()
        repository = SheetsRepository(spreadsheet_id="spreadsheet", service_account_json_b64="unused")
        repository._service = service

        repository._replace_dict_rows(
            "scoring",
            [
                {"participant_id": "p1", "display_name": "Игрок 1", "match_id": "m1"},
                {"participant_id": "p2", "display_name": "Игрок 2", "match_id": "m2"},
            ],
        )

        self.assertEqual(len(service.batch_updates), 1)
        requests = service.batch_updates[0]["body"]["requests"]
        self.assertEqual(requests[0], {"clearBasicFilter": {"sheetId": 101}})
        filter_range = requests[1]["setBasicFilter"]["filter"]["range"]
        self.assertEqual(filter_range["sheetId"], 101)
        self.assertEqual(filter_range["startRowIndex"], 0)
        self.assertEqual(filter_range["endRowIndex"], 3)
        self.assertEqual(filter_range["startColumnIndex"], 0)
        self.assertEqual(filter_range["endColumnIndex"], 12)

    def test_append_does_not_refresh_filter_on_every_write(self) -> None:
        service = _FakeSheetsService()
        service.values = [["old header"], ["old row"]]
        repository = SheetsRepository(spreadsheet_id="spreadsheet", service_account_json_b64="unused")
        repository._service = service

        repository._append_dict(
            "predictions_raw",
            {
                "submission_id": "s1",
                "timestamp_msk": "2026-06-12T12:00:00+03:00",
                "participant_id": "p1",
                "match_id": "m1",
            },
        )

        self.assertEqual(service.batch_updates, [])
        self.assertEqual(service.calls[-1][0], "append")

    def test_leaderboard_replace_writes_compact_headers_and_formats_sheet(self) -> None:
        service = _FakeSheetsService()
        repository = SheetsRepository(spreadsheet_id="spreadsheet", service_account_json_b64="unused")
        repository._service = service

        repository.replace_leaderboard_rows(
            [
                {
                    "№": "1",
                    "Имя": "Игрок 1",
                    "№ матчей": "2",
                    "Счёт": "20",
                    "Голы": "4",
                    "Ассисты": "2",
                    "Итого": "26",
                    "Группа": "26",
                    "Плей-офф": "0",
                },
                {
                    "№": "2",
                    "Имя": "Игрок 2",
                    "№ матчей": "2",
                    "Счёт": "12",
                    "Голы": "8",
                    "Ассисты": "0",
                    "Итого": "20",
                    "Группа": "20",
                    "Плей-офф": "0",
                },
            ]
        )

        self.assertEqual(
            service.values[0],
            ["№", "Имя", "№ матчей", "Счёт", "Голы", "Ассисты", "Итого", "Группа", "Плей-офф"],
        )
        self.assertEqual(len(service.batch_updates), 2)
        filter_range = service.batch_updates[0]["body"]["requests"][1]["setBasicFilter"]["filter"]["range"]
        self.assertEqual(filter_range["sheetId"], 103)
        self.assertEqual(filter_range["endRowIndex"], 3)
        self.assertEqual(filter_range["endColumnIndex"], 9)

        format_requests = service.batch_updates[1]["body"]["requests"]
        self.assertTrue(any("updateDimensionProperties" in request for request in format_requests))
        self.assertTrue(
            any(
                request.get("repeatCell", {}).get("cell", {}).get("userEnteredFormat", {}).get("horizontalAlignment") == "CENTER"
                for request in format_requests
            )
        )
        green_cells = [
            request
            for request in format_requests
            if request.get("repeatCell", {}).get("cell", {}).get("userEnteredFormat", {}).get("backgroundColor", {}).get("green") == 0.9
        ]
        self.assertTrue(green_cells)

    def test_dynamic_analytics_sheet_is_created_and_writes_dynamic_headers(self) -> None:
        service = _FakeSheetsService()
        repository = SheetsRepository(spreadsheet_id="spreadsheet", service_account_json_b64="unused")
        repository._service = service

        repository.replace_analytics_rows(
            "leaderboard_by_game_day",
            [
                {
                    "participant_id": "p1",
                    "display_name": "Игрок 1",
                    "2026-06-11": "12",
                    "2026-06-12": "8",
                }
            ],
        )

        self.assertIn("leaderboard_by_game_day", service.sheet_ids)
        self.assertEqual(service.values[0], ["participant_id", "display_name", "2026-06-11", "2026-06-12"])
        self.assertEqual(service.calls[1][0], "batchUpdate")


if __name__ == "__main__":
    unittest.main()
