"""
Thin wrapper around gspread. Everything is written and read as plain text
(value_input_option="RAW") on purpose — this is what sidesteps the entire
class of bugs the Apps Script version hit, where Sheets silently converted
strings like "2026-07" into real Date objects. We parse dates/numbers
ourselves in Python instead of letting Sheets guess.
"""

import gspread
from google.oauth2.service_account import Credentials
import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_spreadsheet():
    creds = Credentials.from_service_account_file(config.SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(config.SPREADSHEET_ID)


def read_all_rows(sheet, tab_name: str) -> list[list[str]]:
    """Returns all rows (including header) as raw strings, no type coercion."""
    ws = sheet.worksheet(tab_name)
    return ws.get_all_values()


def append_rows(sheet, tab_name: str, rows: list[list]):
    if not rows:
        return
    ws = sheet.worksheet(tab_name)
    ws.append_rows(rows, value_input_option="RAW")


def set_real_dates(sheet, tab_name: str, start_row: int, date_strs: list[str]):
    """Rewrites the Date column (A) for the given 1-indexed row range using
    USER_ENTERED, so Sheets parses each "YYYY-MM-DD" string into a real date
    value instead of leaving it as plain text. Only ever call this on column
    A — every other column must stay RAW to avoid the auto-date-coercion bug
    described above (e.g. Month values like "2026-08")."""
    if not date_strs:
        return
    ws = sheet.worksheet(tab_name)
    end_row = start_row + len(date_strs) - 1
    ws.update(f"A{start_row}:A{end_row}", [[d] for d in date_strs], value_input_option="USER_ENTERED")


def update_cells(sheet, tab_name: str, cell_values: dict[str, str]):
    """Writes each cell (keyed by A1 notation, e.g. 'D42') as plain text —
    RAW, same reasoning as append_rows: these are category labels, never
    dates, so nothing here should go through Sheets' USER_ENTERED parsing."""
    if not cell_values:
        return
    ws = sheet.worksheet(tab_name)
    ws.batch_update(
        [{"range": a1, "values": [[value]]} for a1, value in cell_values.items()],
        value_input_option="RAW",
    )


def replace_tab_contents(sheet, tab_name: str, rows: list[list], create_if_missing: bool = False):
    """Clears a tab and writes rows fresh starting at A1 (RAW — same
    plain-text-only reasoning as everywhere else in this file). If the tab
    doesn't exist and create_if_missing is True, creates it first."""
    try:
        ws = sheet.worksheet(tab_name)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        if not create_if_missing:
            raise
        cols = max((len(r) for r in rows), default=2)
        ws = sheet.add_worksheet(title=tab_name, rows=max(len(rows), 10), cols=max(cols, 2))
    if rows:
        ws.update("A1", rows, value_input_option="RAW")


def clear_raw_import(sheet, tab_name: str):
    ws = sheet.worksheet(tab_name)
    values = ws.get_all_values()
    if len(values) > 1:
        ws.batch_clear([f"A2:Z{len(values)}"])
