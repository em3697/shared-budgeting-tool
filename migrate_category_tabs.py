"""
One-time migration: splits the combined Categories tab
(Keyword | Category | Owner | Monthly Budget | Type) into two tabs:

  - Category Mappings (new): Keyword | Category
  - Categories (rewritten in place): Category | Owner | Monthly Budget | Type

Run with no flags first — it only prints what would change. Pass --apply to
actually write it.

Usage:
    python migrate_category_tabs.py            (dry run)
    python migrate_category_tabs.py --apply    (writes the two tabs for real)
"""

import argparse

import config
import sheets_client

MAPPINGS_TAB = "Category Mappings"


def is_header_row(row: list[str]) -> bool:
    return row[0].strip().lower() == "keyword" and row[1].strip().lower() == "category"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                         help="Actually write the changes. Without this, only prints the plan.")
    args = parser.parse_args()

    sheet = sheets_client.get_spreadsheet()
    rows = sheets_client.read_all_rows(sheet, config.CATEGORIES_TAB)

    data_rows = []
    header_seen_at = None
    for i, row in enumerate(rows):
        row = row + [""] * (5 - len(row))
        if is_header_row(row):
            if header_seen_at is not None:
                print(f"WARNING: header row appears more than once (row {header_seen_at + 1} and row {i + 1})")
            header_seen_at = i
            continue
        data_rows.append(row)

    if header_seen_at is None:
        print("WARNING: no header row (Keyword/Category in columns A/B) found anywhere in the tab.")
    elif header_seen_at != 0:
        print(f"NOTE: the header row is currently at sheet row {header_seen_at + 1}, not row 1. That means "
              f"every script has been silently skipping row 1's real data (treating it as the header) and "
              f"mis-parsing the actual header row as if it were a data row. This migration fixes both.")

    # ---- Category Mappings: unique (keyword, category) pairs ----
    mapping_pairs = []
    seen_pairs = set()
    for row in data_rows:
        keyword = row[0].strip()
        category = row[1].strip()
        if not keyword or not category:
            continue
        key = (keyword.lower(), category)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        mapping_pairs.append((keyword, category))

    # ---- Categories (budgets): one row per (category, owner) ----
    budget_info = {}  # (category, owner) -> {"budgets": set(), "types": set()}
    order = []
    for row in data_rows:
        category = row[1].strip()
        owner = row[2].strip() or "Household"
        budget_raw = row[3].strip()
        type_ = row[4].strip() or "Expense"
        if not category:
            continue
        key = (category, owner)
        if key not in budget_info:
            budget_info[key] = {"budgets": set(), "types": set()}
            order.append(key)
        if budget_raw:
            budget_info[key]["budgets"].add(budget_raw)
        budget_info[key]["types"].add(type_)

    conflicts = []
    budget_rows = []
    for key in order:
        category, owner = key
        info = budget_info[key]
        if len(info["budgets"]) > 1:
            conflicts.append(f"{category} / {owner}: conflicting budgets {sorted(info['budgets'])} "
                              f"— keeping {sorted(info['budgets'])[-1]}")
        if len(info["types"]) > 1:
            conflicts.append(f"{category} / {owner}: conflicting types {sorted(info['types'])} "
                              f"— keeping {sorted(info['types'])[-1]}")
        budget = sorted(info["budgets"])[-1] if info["budgets"] else ""
        type_ = sorted(info["types"])[-1] if info["types"] else "Expense"
        budget_rows.append([category, owner, budget, type_])

    owner_order = {"Household": 0}
    budget_rows.sort(key=lambda r: (owner_order.get(r[1], 1), r[1], r[0]))
    mapping_pairs.sort(key=lambda p: (p[1], p[0]))

    print(f"\nCategory Mappings: {len(mapping_pairs)} keyword -> category rule(s)")
    print(f"Categories (budgets): {len(budget_rows)} category/owner row(s)")
    if conflicts:
        print(f"\n{len(conflicts)} conflict(s) found while deduping (kept the last value alphabetically — review after migrating):")
        for c in conflicts:
            print(f"  {c}")

    if not args.apply:
        print("\n--- DRY RUN — pass --apply to write these changes ---")
        print(f"\n'{MAPPINGS_TAB}' tab would contain:")
        for kw, cat in mapping_pairs:
            print(f"  {kw} -> {cat}")
        print(f"\n'{config.CATEGORIES_TAB}' tab would be rewritten to:")
        for row in budget_rows:
            print(f"  {row}")
        return

    sheets_client.replace_tab_contents(
        sheet, MAPPINGS_TAB,
        [["Keyword", "Category"]] + [[kw, cat] for kw, cat in mapping_pairs],
        create_if_missing=True,
    )
    sheets_client.replace_tab_contents(
        sheet, config.CATEGORIES_TAB,
        [["Category", "Owner", "Monthly Budget", "Type"]] + budget_rows,
    )

    print(f"\nDone. '{MAPPINGS_TAB}' now has {len(mapping_pairs)} row(s), "
          f"'{config.CATEGORIES_TAB}' now has {len(budget_rows)} row(s).")


if __name__ == "__main__":
    main()
