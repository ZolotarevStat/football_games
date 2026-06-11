from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .sheet_schema import SHEET_HEADERS


def build_service(service_account_json_b64: str, service_account_file: str):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if service_account_json_b64:
        info = json.loads(base64.b64decode(service_account_json_b64).decode("utf-8"))
        credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    elif service_account_file:
        credentials = service_account.Credentials.from_service_account_file(service_account_file, scopes=scopes)
    else:
        raise RuntimeError("Pass --service-account-json-b64 or --service-account-file")
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet-id", required=True)
    parser.add_argument("--service-account-json-b64", default="")
    parser.add_argument("--service-account-file", default="")
    args = parser.parse_args()

    service = build_service(args.service_account_json_b64, args.service_account_file)
    values = service.spreadsheets().values()
    tz = ZoneInfo("Europe/Moscow")
    now = datetime.now(tz).replace(microsecond=0)
    future_kickoff = now + timedelta(days=1)
    past_kickoff = now - timedelta(hours=1)

    seed = {
        "participants": [
            [
                "test_anton",
                "Anton Test",
                "organizer_username",
                "",
                "TESTANTON",
                "active",
                now.isoformat(),
                "",
                "admin",
            ],
            [
                "test_user",
                "Test User",
                "",
                "",
                "TESTUSER",
                "active",
                now.isoformat(),
                "",
                "",
            ],
        ],
        "matches": [
            [
                "test_future",
                "TEST",
                "1",
                future_kickoff.isoformat(),
                (future_kickoff - timedelta(minutes=5)).isoformat(),
                "Аргентина",
                "Франция",
                "open",
            ],
            [
                "test_past",
                "TEST",
                "1",
                past_kickoff.isoformat(),
                (past_kickoff - timedelta(minutes=5)).isoformat(),
                "Бразилия",
                "Испания",
                "open",
            ],
        ],
        "players": [
            ["Аргентина", "FW", "Месси", "Messi", "", "", "0", "0", "1", "1", "TRUE"],
            ["Аргентина", "FW", "Альварес", "Alvarez", "", "", "0", "0", "2", "2", "TRUE"],
            ["Франция", "FW", "Мбаппе", "Mbappe", "", "", "0", "0", "1", "1", "TRUE"],
            ["Франция", "MF", "Гризманн", "Griezmann", "", "", "0", "0", "2", "2", "TRUE"],
            ["Бразилия", "FW", "Винисиус", "Vinicius", "", "", "0", "0", "1", "1", "TRUE"],
            ["Испания", "FW", "Ямаль", "Yamal", "", "", "0", "0", "1", "1", "TRUE"],
        ],
        "leaderboard": [
            ["1", "test_anton", "Anton Test", "1", "12", "0", "12", "12", now.isoformat()],
            ["2", "test_user", "Test User", "0", "0", "0", "0", "0", now.isoformat()],
        ],
    }

    for sheet_name, rows in seed.items():
        headers = SHEET_HEADERS[sheet_name]
        current = values.get(spreadsheetId=args.spreadsheet_id, range=f"{sheet_name}!A:Z").execute().get("values", [])
        existing_keys = {row[0] for row in current[1:] if row}
        rows_to_append = [row for row in rows if row[0] not in existing_keys]
        if not rows_to_append:
            continue
        values.append(
            spreadsheetId=args.spreadsheet_id,
            range=f"{sheet_name}!A:{chr(ord('A') + len(headers) - 1)}",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows_to_append},
        ).execute()
        print(f"{sheet_name}: appended {len(rows_to_append)}")


if __name__ == "__main__":
    main()
