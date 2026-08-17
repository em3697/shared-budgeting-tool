"""
Shared configuration. Edit the two values below before running anything.
"""

# The Sheet's ID — the long string in its URL:
# https://docs.google.com/spreadsheets/d/THIS_PART/edit
SPREADSHEET_ID = "1rhxvEqScx2U3c7z_sEkiNBAuAgsz3UiHo5eaGMwxo3M"

# Must match the Owner column in your Categories tab exactly.
PEOPLE = ["Elise", "Matt"]

# Path to the service account JSON key file (see README.md for how to create
# one). Keep this file OUT of any git repo — it's a credential.
SERVICE_ACCOUNT_FILE = "service_account.json"

TRANSACTIONS_TAB = "Transactions"
CATEGORIES_TAB = "Categories"                # Category | Owner | Monthly Budget | Type
CATEGORY_MAPPINGS_TAB = "Category Mappings"  # Keyword | Category

def raw_import_tab_for(person: str) -> str:
    return f"Raw Import - {person}"
