"""
Loads category config and provides matching/lookup helpers.

Two tabs feed this:
  - Category Mappings: Keyword | Category
  - Categories:         Category | Owner | Monthly Budget | Type
"""

from dataclasses import dataclass, field
import config


@dataclass
class CategoryConfig:
    rules: list[tuple[str, str]] = field(default_factory=list)  # (keyword_lower, category)
    budgets: dict[str, float] = field(default_factory=dict)     # "category||owner" -> amount
    types: dict[str, str] = field(default_factory=dict)         # category -> Expense/Income
    personal_owners: set[str] = field(default_factory=set)      # owners that aren't Household

    def match_category(self, description: str) -> str | None:
        lower = description.lower()
        for keyword, category in self.rules:
            if keyword in lower:
                return category
        return None

    def budget_for(self, category: str, owner: str) -> float:
        return self.budgets.get(f"{category}||{owner}", 0.0)

    def is_household_category(self, category: str) -> bool:
        return f"{category}||Household" in self.budgets

    def type_of(self, category: str) -> str:
        return self.types.get(category, "Expense")


def load_categories(mapping_rows: list[list[str]], budget_rows: list[list[str]]) -> CategoryConfig:
    cfg = CategoryConfig()

    for row in mapping_rows[1:]:  # skip header
        row = row + [""] * (2 - len(row))  # pad short rows
        keyword = row[0].strip().lower()
        category = row[1].strip()
        if keyword and category:
            cfg.rules.append((keyword, category))

    for row in budget_rows[1:]:  # skip header
        row = row + [""] * (4 - len(row))  # pad short rows
        category = row[0].strip()
        owner = row[1].strip() or "Household"
        budget_raw = row[2].strip()
        type_ = row[3].strip() or "Expense"

        if not category:
            continue

        cfg.types[category] = type_
        if budget_raw:
            try:
                cfg.budgets[f"{category}||{owner}"] = float(budget_raw)
            except ValueError:
                pass
        if owner != "Household":
            cfg.personal_owners.add(owner)

    return cfg


def normalize_person(raw_person: str) -> str | None:
    """Case/whitespace-insensitive match against config.PEOPLE. Returns the
    canonical name, or None if it matches neither (surfaced separately rather
    than silently dropped)."""
    cleaned = (raw_person or "").strip().lower()
    for canonical in config.PEOPLE:
        if canonical.strip().lower() == cleaned:
            return canonical
    return None
