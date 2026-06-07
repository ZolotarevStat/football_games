from __future__ import annotations

import argparse
import base64
import json

from .sheet_schema import SCORING_RULE_ROWS, SHEET_HEADERS


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
    spreadsheet = service.spreadsheets().get(spreadsheetId=args.spreadsheet_id).execute()
    existing = {sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])}
    requests = [
        {"addSheet": {"properties": {"title": sheet_name}}}
        for sheet_name in SHEET_HEADERS
        if sheet_name not in existing
    ]
    if requests:
        service.spreadsheets().batchUpdate(
            spreadsheetId=args.spreadsheet_id,
            body={"requests": requests},
        ).execute()

    values = service.spreadsheets().values()
    for sheet_name, headers in SHEET_HEADERS.items():
        values.update(
            spreadsheetId=args.spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": [headers]},
        ).execute()
    values.update(
        spreadsheetId=args.spreadsheet_id,
        range="scoring_rules!A2",
        valueInputOption="USER_ENTERED",
        body={"values": SCORING_RULE_ROWS},
    ).execute()
    print("Sheets schema is ready.")


if __name__ == "__main__":
    main()
