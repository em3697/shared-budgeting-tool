"""
Recomputes this month's budget-vs-actual numbers from the shared Sheet and
writes a self-contained dashboard.html (data embedded, no server needed —
just open the file). Run this any time after importing new transactions.

Usage:
    python build_dashboard.py
"""

import json
import webbrowser
from datetime import datetime
from pathlib import Path

import config
import sheets_client
from categorize import load_categories, normalize_person

OUTPUT_FILE = Path(__file__).parent / "dashboard.html"
TEMPLATE_FILE = Path(__file__).parent / "dashboard_template.html"


def compute_dashboard_data() -> dict:
    sheet = sheets_client.get_spreadsheet()

    mapping_rows = sheets_client.read_all_rows(sheet, config.CATEGORY_MAPPINGS_TAB)
    budget_rows = sheets_client.read_all_rows(sheet, config.CATEGORIES_TAB)
    cfg = load_categories(mapping_rows, budget_rows)

    tx_rows = sheets_client.read_all_rows(sheet, config.TRANSACTIONS_TAB)
    current_month = datetime.now().strftime("%Y-%m")

    household_actuals: dict[str, float] = {}
    personal_actuals: dict[str, dict[str, float]] = {}
    personal_income: dict[str, float] = {}
    unmatched_people: dict[str, float] = {}
    matched_month_count = 0
    transactions = []  # expense rows shown in a category section, for the dashboard's expand-to-view-expenses

    for i, row in enumerate(tx_rows[1:]):
        sheet_row = i + 2  # tx_rows includes the header at index 0, i.e. sheet row 1
        row = row + [""] * (8 - len(row))
        date, description, amount_str, category, person, _, month, _ = row[:8]

        if month != current_month:
            continue
        matched_month_count += 1

        try:
            raw_amt = float(amount_str)
        except ValueError:
            raw_amt = 0.0

        category = category.strip()
        person_key = normalize_person(person)
        cat_type = cfg.type_of(category)

        # Transfers (moving money between your own accounts, Venmo/Zelle
        # round-trips, etc.) aren't real spending — summing their absolute
        # value double-counts every leg of the same money moving around.
        # Keep the sign so inflows and outflows net against each other.
        amt = raw_amt if cat_type == "Transfer" else abs(raw_amt)

        if person_key is None:
            raw_label = (person or "Unknown").strip() or "Unknown"
            unmatched_people[raw_label] = unmatched_people.get(raw_label, 0) + amt
            continue

        if cat_type == "Income":
            personal_income[person_key] = personal_income.get(person_key, 0) + amt
            continue

        if cfg.is_household_category(category):
            household_actuals[category] = household_actuals.get(category, 0) + amt
        else:
            personal_actuals.setdefault(person_key, {})
            personal_actuals[person_key][category] = personal_actuals[person_key].get(category, 0) + amt

        transactions.append({
            "row": sheet_row, "date": date, "description": description,
            "amount": amt, "category": category, "person": person_key,
        })

    def build_category_list(categories, actuals_map, owner):
        section_total = 0.0
        items = []
        for category in categories:
            budget = cfg.budget_for(category, owner)
            actual = actuals_map.get(category, 0.0)
            section_total += actual
            remaining = budget - actual
            if remaining < 0:
                status = "over"
            elif budget > 0 and actual / budget > 0.8:
                status = "close"
            else:
                status = "ontrack"
            items.append({
                "category": category, "budget": budget, "actual": actual,
                "remaining": remaining, "status": status,
            })

        # Categories with real spending but no budget line (new/unrecognized
        # category, or a known category never budgeted for this owner) would
        # otherwise just be summed into actuals_map and never looked at
        # below — show them instead of silently dropping the dollars.
        for category in sorted(set(actuals_map) - set(categories)):
            actual = actuals_map[category]
            section_total += actual
            items.append({
                "category": category, "budget": 0.0, "actual": actual,
                "remaining": -actual, "status": "unbudgeted",
            })

        return items, section_total

    household_categories = sorted({
        k.split("||")[0] for k in cfg.budgets if k.endswith("||Household")
        and cfg.type_of(k.split("||")[0]) != "Income"
    })
    household_list, household_total = build_category_list(household_categories, household_actuals, "Household")

    people = {}
    grand_income = 0.0
    grand_expenses = household_total

    for owner in cfg.personal_owners:
        owner_categories = sorted({
            k.split("||")[0] for k in cfg.budgets if k.endswith(f"||{owner}")
            and cfg.type_of(k.split("||")[0]) != "Income"
        })
        actuals_map = personal_actuals.get(owner, {})
        items, section_total = build_category_list(owner_categories, actuals_map, owner)
        income = personal_income.get(owner, 0.0)
        grand_income += income
        grand_expenses += section_total
        people[owner] = {
            "categories": items,
            "income": income,
            "expenses": section_total,
            "net": income - section_total,
        }

    return {
        "month": current_month,
        "household": household_list,
        "people": people,
        "combined": {
            "income": grand_income,
            "expenses": grand_expenses,
            "net": grand_income - grand_expenses,
        },
        "unmatched": [{"name": k, "amount": v} for k, v in unmatched_people.items()],
        "transactions": transactions,
        "categories": sorted(cfg.types.keys()),
        "_debug": {
            "totalTransactionRows": len(tx_rows) - 1,
            "rowsMatchingCurrentMonth": matched_month_count,
            "categoryBudgetRowCount": len(cfg.budgets),
            "peopleFound": list(people.keys()),
        },
    }


def main():
    data = compute_dashboard_data()

    if not TEMPLATE_FILE.exists():
        print(f"ERROR: {TEMPLATE_FILE} not found. Make sure it's in the same folder as this script.")
        return

    template = TEMPLATE_FILE.read_text()
    # Raw transaction descriptions are embedded in this JSON — escape "</" so
    # a description containing "</script>" can't prematurely close the tag
    # it's embedded in and break the page.
    embedded_json = json.dumps(data).replace("</", "<\\/")
    rendered = template.replace("__DASHBOARD_DATA__", embedded_json)
    OUTPUT_FILE.write_text(rendered)

    print(f"Wrote {OUTPUT_FILE}")
    print(f"  Month: {data['month']}")
    print(f"  Household categories: {len(data['household'])}")
    print(f"  People: {list(data['people'].keys())}")
    print(f"  Combined net: ${data['combined']['net']:.2f}")
    if data["unmatched"]:
        print(f"  ⚠ Unmatched person values: {data['unmatched']}")

    webbrowser.open(f"file://{OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
