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

import pandas as pd

import config
import sheets_client
from categorize import load_categories


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
    parser.add_argument("--file", required=True, help="Path to the SoFi CSV export")
    args = parser.parse_args()

    print(f"Reading {args.file} for {args.person}...")
    df = pd.read_csv(args.file)

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

    cat_rows = sheets_client.read_all_rows(sheet, config.CATEGORIES_TAB)
    cfg = load_categories(cat_rows)

    tx_rows = sheets_client.read_all_rows(sheet, config.TRANSACTIONS_TAB)
    existing_keys = set()
    for row in tx_rows[1:]:
        if len(row) < 3:
            continue
        try:
            existing_keys.add(make_dedup_key(row[0], row[1], float(row[2])))
        except (ValueError, IndexError):
            continue

    new_rows = []
    skipped_duplicate = 0

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

    sheets_client.append_rows(sheet, config.TRANSACTIONS_TAB, new_rows)
    print(f"Imported {len(new_rows)} new transaction(s) for {args.person} "
          f"({skipped_duplicate} skipped as duplicates).")
    print("Run build_dashboard.py to see updated numbers.")


if __name__ == "__main__":
    main()
