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


def read_all_rows_safe(sheet, tab_name: str) -> list[list[str]]:
    """Like read_all_rows, but returns [] instead of raising if the tab
    doesn't exist yet — e.g. a History tab that hasn't been created by the
    first snapshot."""
    try:
        return read_all_rows(sheet, tab_name)
    except gspread.exceptions.WorksheetNotFound:
        return []


def append_rows(sheet, tab_name: str, rows: list[list]):
    if not rows:
        return
    ws = sheet.worksheet(tab_name)
    ws.append_rows(rows, value_input_option="RAW")


def set_column_values(sheet, tab_name: str, column_letter: str, start_row: int, values: list[str]):
    """Writes a single contiguous column range in one call, via USER_ENTERED
    so Sheets parses each value into its native type (a real date, a real
    boolean) instead of leaving it as plain text. Only safe for values with
    no locale-ambiguous parsing risk — ISO dates, "TRUE"/"FALSE" — never for
    free text or things like Month values ("2026-08" would get coerced into
    a date)."""
    if not values:
        return
    ws = sheet.worksheet(tab_name)
    end_row = start_row + len(values) - 1
    ws.update(f"{column_letter}{start_row}:{column_letter}{end_row}", [[v] for v in values], value_input_option="USER_ENTERED")


def set_real_dates(sheet, tab_name: str, start_row: int, date_strs: list[str]):
    """Rewrites the Date column (A) for the given 1-indexed row range so
    Sheets parses each "YYYY-MM-DD" string into a real date value instead of
    leaving it as plain text."""
    set_column_values(sheet, tab_name, "A", start_row, date_strs)


def update_cells(sheet, tab_name: str, cell_values: dict[str, str], value_input_option: str = "RAW"):
    """Writes each cell (keyed by A1 notation, e.g. 'D42'). Defaults to RAW —
    plain text, no parsing — which is the safe choice for anything Sheets
    could misread, like category labels or month strings. Pass
    value_input_option="USER_ENTERED" only for values with no
    locale-ambiguous parsing risk, e.g. "TRUE"/"FALSE" for a boolean column."""
    if not cell_values:
        return
    ws = sheet.worksheet(tab_name)
    ws.batch_update(
        [{"range": a1, "values": [[value]]} for a1, value in cell_values.items()],
        value_input_option=value_input_option,
    )


def set_boolean_data_validation(sheet, tab_name: str, column_letter: str, start_row: int, end_row: int):
    """Applies checkbox data validation to a column range so it renders as
    native Sheets checkboxes. The rule stays attached to the range going
    forward, so rows appended later (within end_row) render as checkboxes
    too without needing to reapply this."""
    ws = sheet.worksheet(tab_name)
    sheet.batch_update({
        "requests": [{
            "setDataValidation": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": start_row - 1,
                    "endRowIndex": end_row,
                    "startColumnIndex": gspread.utils.a1_to_rowcol(f"{column_letter}1")[1] - 1,
                    "endColumnIndex": gspread.utils.a1_to_rowcol(f"{column_letter}1")[1],
                },
                "rule": {"condition": {"type": "BOOLEAN"}, "strict": True},
            }
        }]
    })


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
