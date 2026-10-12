"""
Weekly import script.

Usage:
    python import_sofi.py --person Elise --file ~/Downloads/sofi_export.csv
    python import_sofi.py --person Matt --file ~/Downloads/sofi_export.csv

Reads a SoFi CSV export, categorizes each row (your keyword rules first,
falling back to SoFi's own category), dedupes against everything already in
the Transactions tab, and appends only the new rows.

Both posted AND pending transactions are imported, so you can see true
month-to-date spending before a pending charge finalizes (e.g. before paying
a credit card bill at month-end). A pending charge is matched to its later
posted counterpart by person + Authorized Date (within MATCH_WINDOW_DAYS,
since SoFi can shift the date itself by a day or so once a charge clears)
plus an exact amount match or a matching description — neither amount nor
description alone is reliable (a tip can be added; "AMAZON MKTPLACE PMTS"
posts as plain "Amazon") — and updated in place rather than appended as a
second row. Category/Shared/Split % are left untouched on reconciliation, so
a manual edit made while it was pending survives.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
import sheets_client
from categorize import is_generic_transfer_description, load_categories

# SoFi's downloaded filename looks like:
#   1786904674519_SoFi-Relay-All-Transactions_2026-08-16.csv
# (a numeric ID, then this fixed label, then the export date)
SOFI_FILENAME_PATTERN = "SoFi-Relay-All-Transactions_*.csv"

# Authorized Date isn't perfectly stable across the pending -> posted
# transition — SoFi has been seen to shift it by a day once a charge clears
# (e.g. a late hold attributed to the next day once settled). An exact-date
# match missed those, leaving the old pending row stuck forever alongside a
# freshly-appended posted duplicate. This window absorbs that drift while
# still keeping candidates to charges from around the same time, so it can't
# accidentally merge two unrelated charges days apart.
MATCH_WINDOW_DAYS = 3


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

    df["Status"] = df["Status"].str.strip().str.lower()
    df = df[df["Status"].isin(["posted", "pending"])].copy()
    if df.empty:
        print("No posted or pending transactions found in this export.")
        return

    sheet = sheets_client.get_spreadsheet()

    mapping_rows = sheets_client.read_all_rows(sheet, config.CATEGORY_MAPPINGS_TAB)
    budget_rows = sheets_client.read_all_rows(sheet, config.CATEGORIES_TAB)
    cfg = load_categories(mapping_rows, budget_rows)

    tx_rows = sheets_client.read_all_rows(sheet, config.TRANSACTIONS_TAB)

    posted_keys = set()  # (date_iso, description, amount) — already-finalized transactions
    # person -> [(sheet row number, auth date, pending amount, description_lower), ...] —
    # rows still marked Pending, so a later "posted" line can be matched back
    # to the same charge and update it in place. Description is NOT part of
    # the match condition (see the acceptable-candidate check below) — SoFi
    # has been seen to report a cleaned-up merchant name once a charge posts
    # (e.g. pending "AMAZON MKTPLACE PMTS" / "Amazon.com" -> posted "Amazon"),
    # so requiring it to match exactly missed real reconciliations. The auth
    # date isn't required to match exactly either (see MATCH_WINDOW_DAYS).
    # What anchors the match instead is the amount: within the date window,
    # an exact amount match (or, failing that, a matching description) is
    # what identifies "this is the same charge" rather than a coincidentally
    # nearby unrelated one.
    pending_index: dict[str, list[tuple[int, pd.Timestamp, float, str]]] = {}

    for i, row in enumerate(tx_rows[1:], start=2):
        row = row + [""] * (12 - len(row))
        row_date, row_desc, row_amount_str, _, row_person, _, _, _, _, _, row_auth_date, row_pending = row[:12]

        if row_pending.strip().upper() == "TRUE":
            try:
                auth_dt = pd.to_datetime(row_auth_date)
                row_amount = float(row_amount_str)
            except (ValueError, TypeError):
                continue
            pending_index.setdefault(row_person.strip(), []).append(
                (i, auth_dt, row_amount, row_desc.strip().lower())
            )
        else:
            try:
                # Column A comes back as whatever Sheets displays it as (e.g.
                # "7/29/2026" for a real date value), so normalize to ISO
                # before keying — otherwise this never matches the
                # "YYYY-MM-DD" keys built from the CSV below.
                row_date_iso = pd.to_datetime(row_date).strftime("%Y-%m-%d")
                posted_keys.add(make_dedup_key(row_date_iso, row_desc, float(row_amount_str)))
            except (ValueError, TypeError):
                continue

    new_rows = []
    shared_defaults = []
    auth_date_defaults = []
    pending_defaults = []
    reconciled_updates = {}  # sheet row number -> {"date_iso", "amount", "week", "month"}
    seen_pending_this_batch = set()  # guards against a duplicate pending line within the same CSV
    skipped_duplicate = 0
    new_categories = []
    seen_new_categories = set()

    def try_parse_date(value) -> pd.Timestamp | None:
        # Pending rows have no Posted Date yet, and SoFi doesn't leave it
        # truly blank — different exports have used "nan" (pandas' string
        # for a missing cell) and a literal "/" placeholder, and there's no
        # guarantee those are the only two. Rather than special-case each
        # placeholder string we've happened to see, just attempt the parse
        # and treat anything that fails as "not available." Failure has two
        # different shapes here: pd.to_datetime raises on genuine garbage
        # (e.g. "/"), but silently returns NaT — not None, and *truthy* in a
        # boolean context — for things like "nan", so an explicit pd.isna
        # check is required too or a NaT slips through as if it were a real
        # date and crashes later on .strftime().
        s = str(value or "").strip()
        if not s:
            return None
        try:
            parsed = pd.to_datetime(s)
        except (ValueError, TypeError):
            return None
        return None if pd.isna(parsed) else parsed

    for _, r in df.iterrows():
        status = r["Status"]
        posted_obj = try_parse_date(r.get("Posted Date"))
        auth_obj = try_parse_date(r.get("Authorized Date"))
        date_obj = posted_obj or auth_obj
        if date_obj is None:
            continue
        if auth_obj is None:
            auth_obj = date_obj
        auth_iso = auth_obj.strftime("%Y-%m-%d")

        description = str(r.get("Description", "")).strip()
        try:
            amount = float(r.get("Amount"))
        except (ValueError, TypeError):
            continue

        date_iso = date_obj.strftime("%Y-%m-%d")
        description_lower = description.strip().lower()

        if status == "posted":
            dedup_key = make_dedup_key(date_iso, description, amount)
            if dedup_key in posted_keys:
                skipped_duplicate += 1
                continue

            candidates = pending_index.get(args.person, [])
            # "Same charge" requires the auth date to be close AND (an exact
            # amount match OR a matching description) — either signal alone
            # can drift (see the comment on pending_index above), but both
            # drifting at once alongside a coincidentally nearby auth date
            # would be a false match, so at least one has to hold exactly.
            acceptable = [
                idx for idx, c in enumerate(candidates)
                if abs((c[1] - auth_obj).days) <= MATCH_WINDOW_DAYS
                and (abs(c[2] - amount) < 0.01 or c[3] == description_lower)
            ]
            if acceptable:
                # This charge was previously imported while pending — update
                # that row in place with the now-final date/amount instead of
                # appending a second row. Category/Shared/Split % are left
                # alone so any manual edit made while it was pending sticks.
                # Pick whichever acceptable candidate's pending amount is
                # closest to the posted amount, in case more than one pending
                # charge for this person falls in the window.
                best_idx = min(acceptable, key=lambda idx: abs(candidates[idx][2] - amount))
                row_num, _, _, _ = candidates.pop(best_idx)
                reconciled_updates[row_num] = {
                    "date_iso": date_iso, "amount": amount,
                    "week": get_week_label(date_obj), "month": get_month_label(date_obj),
                }
                posted_keys.add(dedup_key)
                continue
            # else: a brand new posted transaction, never seen as pending — falls through to append below
        else:  # pending
            # Same "close date + (exact amount or matching description)" test
            # as above — this is "is the literal same charge already tracked
            # as pending from a previous import," not a fuzzy guess.
            batch_key = (description_lower, args.person, amount)
            already_pending = any(
                abs((auth_dt - auth_obj).days) <= MATCH_WINDOW_DAYS
                and (abs(a - amount) < 0.01 or desc == description_lower)
                for _, auth_dt, a, desc in pending_index.get(args.person, [])
            )
            if already_pending or batch_key in seen_pending_this_batch:
                # Already tracked as pending from a previous import (or a
                # repeated line within this same CSV) — don't re-add it every
                # week until it posts.
                skipped_duplicate += 1
                continue
            seen_pending_this_batch.add(batch_key)
            # falls through to append below

        sofi_category = str(r.get("Primary Category", "")).strip()
        matched_category = cfg.match_category(description)
        if matched_category:
            category = matched_category
        elif sofi_category == "Transfers" and not is_generic_transfer_description(description):
            # A named-person P2P payment (e.g. "Matt Freer 'Movers'") isn't
            # an internal transfer just because SoFi defaults it there —
            # fall back to Uncategorized so it surfaces for review instead
            # of silently vanishing into the fully-excluded Transfers bucket.
            category = "Uncategorized"
        else:
            category = sofi_category or "Uncategorized"

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
        # No auto-inference here — every new transaction defaults to
        # unshared and gets marked Shared explicitly (via the dashboard's
        # checkbox) on a case-by-case basis.
        shared_defaults.append("FALSE")
        auth_date_defaults.append(auth_iso)
        pending_defaults.append("TRUE" if status == "pending" else "FALSE")
        if status == "posted":
            posted_keys.add(make_dedup_key(date_iso, description, amount))

    if reconciled_updates:
        raw_cell_updates = {}
        date_cell_updates = {}
        for row_num, vals in reconciled_updates.items():
            date_cell_updates[f"A{row_num}"] = vals["date_iso"]
            raw_cell_updates[f"C{row_num}"] = f"{vals['amount']:.2f}"
            raw_cell_updates[f"F{row_num}"] = vals["week"]
            raw_cell_updates[f"G{row_num}"] = vals["month"]
            raw_cell_updates[f"L{row_num}"] = "FALSE"
        sheets_client.update_cells(sheet, config.TRANSACTIONS_TAB, raw_cell_updates)
        sheets_client.update_cells(sheet, config.TRANSACTIONS_TAB, date_cell_updates, value_input_option="USER_ENTERED")
        print(f"Reconciled {len(reconciled_updates)} pending charge(s) that have now posted.")

    if not new_rows:
        if not reconciled_updates:
            print(f"No new transactions to import ({skipped_duplicate} already existed).")
        return

    start_row = len(tx_rows) + 1  # tx_rows includes the header, rows are 1-indexed
    sheets_client.append_rows(sheet, config.TRANSACTIONS_TAB, new_rows)
    sheets_client.set_real_dates(sheet, config.TRANSACTIONS_TAB, start_row, [row[0] for row in new_rows])
    sheets_client.set_column_values(sheet, config.TRANSACTIONS_TAB, "I", start_row, shared_defaults)
    sheets_client.set_column_values(sheet, config.TRANSACTIONS_TAB, "K", start_row, auth_date_defaults)
    sheets_client.set_column_values(sheet, config.TRANSACTIONS_TAB, "L", start_row, pending_defaults)

    pending_count = sum(1 for p in pending_defaults if p == "TRUE")
    print(f"Imported {len(new_rows)} new transaction(s) for {args.person} "
          f"({pending_count} still pending, {skipped_duplicate} skipped as duplicates).")

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
