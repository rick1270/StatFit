from pathlib import Path
from typing import Any

import google.auth
import gspread
from google.oauth2.service_account import Credentials

from statfit import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def connect_sheet() -> gspread.Spreadsheet:
    """Locally, authenticate with the service account JSON key. In Cloud Run
    (where no key file is shipped), fall back to Application Default
    Credentials — the job runs as the same service account, so no key
    material needs to leave the laptop."""
    if Path(config.GOOGLE_SERVICE_ACCOUNT_FILE).exists():
        creds = Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    else:
        creds, _ = google.auth.default(scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(config.GOOGLE_SHEET_ID)


def ensure_worksheet(spreadsheet: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=1000, cols=26)


def upsert_rows(worksheet: gspread.Worksheet, rows: list[dict[str, Any]], key_field: str) -> None:
    """Insert or update rows keyed on `key_field`. New fields encountered in
    `rows` that aren't already columns get appended to the header row —
    field sets vary by activity type/device, so the schema grows as needed
    rather than being fixed up front."""
    if not rows:
        return

    existing = worksheet.get_all_values()
    headers = list(existing[0]) if existing else []

    seen = set(headers)
    for row in rows:
        for key in row:
            if key not in seen:
                headers.append(key)
                seen.add(key)

    if not existing or headers != existing[0]:
        worksheet.update(values=[headers], range_name="A1")

    key_col_index = headers.index(key_field)
    row_number_by_key = {}
    for i, row_vals in enumerate(existing[1:], start=2):
        if key_col_index < len(row_vals) and row_vals[key_col_index]:
            row_number_by_key[row_vals[key_col_index]] = i

    batch_data = []
    appends = []
    for row in rows:
        key_val = str(row.get(key_field, ""))
        values = [row.get(h, "") for h in headers]
        row_number = row_number_by_key.get(key_val)
        if row_number:
            end_a1 = gspread.utils.rowcol_to_a1(row_number, len(values))
            start_a1 = gspread.utils.rowcol_to_a1(row_number, 1)
            batch_data.append({"range": f"{start_a1}:{end_a1}", "values": [values]})
        else:
            appends.append(values)

    if batch_data:
        worksheet.batch_update(batch_data, value_input_option="RAW")
    if appends:
        worksheet.append_rows(appends, value_input_option="RAW")


def update_columns(worksheet: gspread.Worksheet, key_field: str, updates: dict[str, dict[str, Any]]) -> int:
    """Set specific fields on existing rows, matched on `key_field`, leaving
    every other cell untouched (unlike upsert_rows, which rewrites whole rows).
    For backfilling newly derived fields. Returns the number of rows updated."""
    existing = worksheet.get_all_values()
    headers = list(existing[0])
    new_fields = sorted({f for fields in updates.values() for f in fields} - set(headers))
    if new_fields:
        headers += new_fields
        if len(headers) > worksheet.col_count:
            worksheet.add_cols(len(headers) - worksheet.col_count)
        worksheet.update(values=[headers], range_name="A1")

    key_col_index = headers.index(key_field)
    batch_data = []
    updated_rows = 0
    for row_number, row_vals in enumerate(existing[1:], start=2):
        if key_col_index >= len(row_vals) or row_vals[key_col_index] not in updates:
            continue
        updated_rows += 1
        for field, value in updates[row_vals[key_col_index]].items():
            a1 = gspread.utils.rowcol_to_a1(row_number, headers.index(field) + 1)
            batch_data.append({"range": a1, "values": [[value]]})

    if batch_data:
        worksheet.batch_update(batch_data, value_input_option="RAW")
    return updated_rows
