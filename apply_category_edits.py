"""
Applies category edits made in the dashboard back to the Transactions tab.

The dashboard (dashboard.html) lets you re-categorize a transaction, but it
never writes to the Sheet directly — it has no credential to do that with.
Instead it downloads a small JSON file describing the change(s). Run this
script afterward to actually apply them.

Usage:
    python apply_category_edits.py --file ~/Downloads/category-edits_2026-08-17T12-00-00.json
    python apply_category_edits.py   (auto-detects the newest category-edits_*.json in ~/Downloads)
"""

import argparse
import json
import sys
from pathlib import Path

import config
import sheets_client
from categorize import load_categories

EDITS_FILENAME_PATTERN = "category-edits_*.json"


def find_latest_edits(downloads_dir: Path) -> Path | None:
    matches = list(downloads_dir.glob(EDITS_FILENAME_PATTERN))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--file", default=None,
        help="Path to a category-edits JSON file downloaded from the dashboard. "
             "If omitted, auto-detects the most recently downloaded one in --downloads-dir."
    )
    parser.add_argument(
        "--downloads-dir", default=str(Path.home() / "Downloads"),
        help="Folder to search when --file is omitted (default: ~/Downloads)"
    )
    args = parser.parse_args()

    if args.file:
        edits_path = Path(args.file)
    else:
        downloads_dir = Path(args.downloads_dir)
        found = find_latest_edits(downloads_dir)
        if found is None:
            print(f"ERROR: No file matching '{EDITS_FILENAME_PATTERN}' found in {downloads_dir}")
            print("Download a changes file from the dashboard first, or pass --file explicitly.")
            sys.exit(1)
        edits_path = found
        print(f"Auto-detected: {edits_path.name}")

    edits = json.loads(edits_path.read_text())
    if not edits:
        print("No edits in this file.")
        return

    sheet = sheets_client.get_spreadsheet()
    tx_rows = sheets_client.read_all_rows(sheet, config.TRANSACTIONS_TAB)
    mapping_rows = sheets_client.read_all_rows(sheet, config.CATEGORY_MAPPINGS_TAB)
    budget_rows = sheets_client.read_all_rows(sheet, config.CATEGORIES_TAB)
    cfg = load_categories(mapping_rows, budget_rows)

    cell_updates = {}
    new_categories = {}  # category -> person who first introduced it, for the placeholder row's Owner
    applied = 0
    skipped = []

    for edit in edits:
        row = edit["row"]
        idx = row - 1  # tx_rows[0] is the header (sheet row 1), so sheet row N is tx_rows[N - 1]
        if idx < 1 or idx >= len(tx_rows):
            skipped.append((edit, "row no longer exists"))
            continue

        current = tx_rows[idx] + [""] * (8 - len(tx_rows[idx]))
        current_description = current[1].strip()
        try:
            current_amount = float(current[2])
        except ValueError:
            current_amount = None

        # Only overwrite if the row still holds the same transaction the
        # dashboard showed — the sheet may have changed since it was generated.
        if (current_description != str(edit["description"]).strip()
                or current_amount is None
                or abs(current_amount - float(edit["amount"])) > 0.005):
            skipped.append((edit, "row content changed since the dashboard was generated"))
            continue

        new_category = str(edit["newCategory"]).strip()
        if not new_category:
            skipped.append((edit, "blank new category"))
            continue

        cell_updates[f"D{row}"] = new_category
        applied += 1

        if new_category not in cfg.types and new_category not in new_categories:
            new_categories[new_category] = edit.get("person", "")

    if cell_updates:
        sheets_client.update_cells(sheet, config.TRANSACTIONS_TAB, cell_updates)

    if new_categories:
        category_rows = [[cat, owner, "", "Expense"] for cat, owner in sorted(new_categories.items())]
        sheets_client.append_rows(sheet, config.CATEGORIES_TAB, category_rows)
        print(f"Added {len(new_categories)} new categor{'y' if len(new_categories) == 1 else 'ies'} "
              f"to the Categories tab (no budget set yet): {', '.join(sorted(new_categories))}")

    print(f"Applied {applied} category change(s).")
    if skipped:
        print(f"Skipped {len(skipped)} edit(s):")
        for edit, reason in skipped:
            print(f"  Row {edit.get('row', '?')} ({edit.get('description', '?')}): {reason}")

    print("Run build_dashboard.py to see updated numbers.")


if __name__ == "__main__":
    main()
