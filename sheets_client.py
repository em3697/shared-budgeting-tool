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


def clear_raw_import(sheet, tab_name: str):
    ws = sheet.worksheet(tab_name)
    values = ws.get_all_values()
    if len(values) > 1:
        ws.batch_clear([f"A2:Z{len(values)}"])
