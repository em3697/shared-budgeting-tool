"""
Weekly import script.

Usage:
    python import_sofi.py --person Elise --file ~/Downloads/sofi_export.csv
    python import_sofi.py --person Matt --file ~/Downloads/sofi_export.csv

Reads a SoFi CSV export, skips pending transactions, categorizes each row
(your keyword rules first, falling back to SoFi's own category), dedupes
against everything already in the Transactions tab, and appends only the
new rows.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
import sheets_client
from categorize import load_categories

# SoFi's downloaded filename looks like:
#   1786904674519_SoFi-Relay-All-Transactions_2026-08-16.csv
# (a numeric ID, then this fixed label, then the export date)
SOFI_FILENAME_PATTERN = "SoFi-Relay-All-Transactions_*.csv"


def find_latest_export(downloads_dir: Path) -> Path | None:
    """Finds the most recently modified SoFi export in the given folder,
    matching the pattern SoFi uses for its downloaded filename. Returns None
    if nothing matches."""
    matches = list(downloads_dir.glob(SOFI_FILENAME_PATTERN))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def get_week_label(date: datetime) -> str:
    # Monday that starts the week, e.g. "2026-07-27"
    monday = date - pd.Timedelta(days=date.weekday())
    return monday.strftime("%Y-%m-%d")


def get_month_label(date: datetime) -> str:
    return date.strftime("%Y-%m")


def make_dedup_key(date_str: str, description: str, amount: float) -> str:
    return f"{date_str}|{description.strip().lower()}|{amount:.2f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--person", required=True, choices=config.PEOPLE)
    parser.add_argument(
        "--file", default=None,
        help="Path to the SoFi CSV export. If omitted, auto-detects the most "
             "recently downloaded matching file in --downloads-dir."
    )
    parser.add_argument(
        "--downloads-dir", default=str(Path.home() / "Downloads"),
        help="Folder to search when --file is omitted (default: ~/Downloads)"
    )
    args = parser.parse_args()

    if args.file:
        csv_path = Path(args.file)
    else:
        downloads_dir = Path(args.downloads_dir)
        found = find_latest_export(downloads_dir)
        if found is None:
            print(f"ERROR: No file matching '{SOFI_FILENAME_PATTERN}' found in {downloads_dir}")
            print("Either export a fresh SoFi CSV to that folder, or pass --file explicitly.")
            sys.exit(1)
        csv_path = found
        print(f"Auto-detected: {csv_path.name}")

    print(f"Reading {csv_path} for {args.person}...")
    df = pd.read_csv(csv_path)

    expected_cols = {
        "Authorized Date", "Posted Date", "Status", "Account Name",
        "Description", "Primary Category", "Detailed Category", "Amount",
    }
    missing = expected_cols - set(df.columns)
    if missing:
        print(f"ERROR: CSV is missing expected columns: {missing}")
        print(f"Found columns: {list(df.columns)}")
        sys.exit(1)

    # Only posted transactions — pending ones get imported once they post,
    # to avoid counting a charge twice.
    df = df[df["Status"].str.strip().str.lower() == "posted"].copy()
    if df.empty:
        print("No posted transactions found in this export.")
        return

    sheet = sheets_client.get_spreadsheet()

    mapping_rows = sheets_client.read_all_rows(sheet, config.CATEGORY_MAPPINGS_TAB)
    budget_rows = sheets_client.read_all_rows(sheet, config.CATEGORIES_TAB)
    cfg = load_categories(mapping_rows, budget_rows)

    tx_rows = sheets_client.read_all_rows(sheet, config.TRANSACTIONS_TAB)
    existing_keys = set()
    for row in tx_rows[1:]:
        if len(row) < 3:
            continue
        try:
            # Column A comes back as whatever Sheets displays it as (e.g.
            # "7/29/2026" for a real date value), so normalize to ISO before
            # keying — otherwise this never matches the "YYYY-MM-DD" keys
            # built from the CSV below.
            row_date_iso = pd.to_datetime(row[0]).strftime("%Y-%m-%d")
            existing_keys.add(make_dedup_key(row_date_iso, row[1], float(row[2])))
        except (ValueError, TypeError, IndexError):
            continue

    new_rows = []
    skipped_duplicate = 0
    new_categories = []
    seen_new_categories = set()

    for _, r in df.iterrows():
        posted = str(r.get("Posted Date", "")).strip()
        authorized = str(r.get("Authorized Date", "")).strip()
        date_str = posted or authorized
        if not date_str or date_str == "nan":
            continue

        try:
            date_obj = pd.to_datetime(date_str)
        except (ValueError, TypeError):
            continue

        description = str(r.get("Description", "")).strip()
        try:
            amount = float(r.get("Amount"))
        except (ValueError, TypeError):
            continue

        date_iso = date_obj.strftime("%Y-%m-%d")
        key = make_dedup_key(date_iso, description, amount)
        if key in existing_keys:
            skipped_duplicate += 1
            continue

        sofi_category = str(r.get("Primary Category", "")).strip()
        category = cfg.match_category(description) or sofi_category or "Uncategorized"

        if category not in cfg.types and category not in seen_new_categories:
            seen_new_categories.add(category)
            new_categories.append(category)

        new_rows.append([
            date_iso,
            description,
            f"{amount:.2f}",
            category,
            args.person,
            get_week_label(date_obj),
            get_month_label(date_obj),
            "SoFi",
        ])
        existing_keys.add(key)

    if not new_rows:
        print(f"No new transactions to import ({skipped_duplicate} already existed).")
        return

    start_row = len(tx_rows) + 1  # tx_rows includes the header, rows are 1-indexed
    sheets_client.append_rows(sheet, config.TRANSACTIONS_TAB, new_rows)
    sheets_client.set_real_dates(sheet, config.TRANSACTIONS_TAB, start_row, [row[0] for row in new_rows])

    print(f"Imported {len(new_rows)} new transaction(s) for {args.person} "
          f"({skipped_duplicate} skipped as duplicates).")

    if new_categories:
        # Blank budget — this is just a placeholder row so the category shows
        # up for review instead of silently having no budget line on the
        # dashboard. Fill in the budget (and add a keyword rule on the
        # Category Mappings tab, if useful) by hand.
        category_rows = [[cat, args.person, "", "Expense"] for cat in sorted(new_categories)]
        sheets_client.append_rows(sheet, config.CATEGORIES_TAB, category_rows)
        print(f"Added {len(new_categories)} new categor{'y' if len(new_categories) == 1 else 'ies'} "
              f"to the Categories tab (no budget set yet): {', '.join(sorted(new_categories))}")

    print("Run build_dashboard.py to see updated numbers.")


if __name__ == "__main__":
    main()