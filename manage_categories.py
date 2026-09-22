"""
Upserts Categories-tab rows (budget amounts, and brand-new categories) from
the dashboard's UI. Adjusting an existing category's budget and adding a new
one are the same underlying operation here — find the (category, owner) row
and update it, or append a fresh row if it doesn't exist yet.
"""

import config
import sheets_client


def upsert_categories(sheet, budget_rows: list[list[str]], edits: list[dict]) -> tuple[int, list[dict]]:
    """Each edit: {"category": str, "owner": str, "budget": number, "type": str (optional)}.
    Returns (applied_count, errors) — errors is a list of the original edit
    dicts each with a "reason" key added; never raised for a single bad edit."""
    index: dict[tuple[str, str], int] = {}  # (category, owner) -> sheet row (1-indexed)
    known_type: dict[str, str] = {}  # category -> type, from whichever owner's row has one

    for i, row in enumerate(budget_rows[1:], start=2):
        row = row + [""] * (4 - len(row))
        category, owner, _, type_ = row[0].strip(), row[1].strip() or "Household", row[2].strip(), row[3].strip()
        if not category:
            continue
        index[(category, owner)] = i
        if type_:
            known_type.setdefault(category, type_)

    cell_updates = {}
    pending_new: dict[tuple[str, str], list[str]] = {}  # keeps last value if the same new (category, owner) appears twice in one batch
    applied = 0
    errors = []

    for edit in edits:
        category = str(edit.get("category", "")).strip()
        owner = str(edit.get("owner", "")).strip() or "Household"
        if not category:
            errors.append({**edit, "reason": "category name is required"})
            continue

        try:
            budget = float(edit["budget"])
        except (TypeError, ValueError, KeyError):
            errors.append({**edit, "reason": "invalid budget amount"})
            continue
        if budget < 0:
            errors.append({**edit, "reason": "budget cannot be negative"})
            continue

        requested_type = str(edit.get("type", "")).strip()
        type_ = requested_type or known_type.get(category) or "Expense"

        key = (category, owner)
        if key in index:
            row_num = index[key]
            cell_updates[f"C{row_num}"] = f"{budget:.2f}"
            if requested_type:
                cell_updates[f"D{row_num}"] = type_
        else:
            pending_new[key] = [category, owner, f"{budget:.2f}", type_]

        known_type.setdefault(category, type_)
        applied += 1

    if cell_updates:
        sheets_client.update_cells(sheet, config.CATEGORIES_TAB, cell_updates)
    if pending_new:
        sheets_client.append_rows(sheet, config.CATEGORIES_TAB, list(pending_new.values()))

    return applied, errors
