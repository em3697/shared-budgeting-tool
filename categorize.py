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


# SoFi's own "Primary Category" lumps two very different things under
# "Transfers": genuine internal account movement (your own money, no person
# attached) and P2P payments to/from a specific named person (real money,
# just routed through Venmo/Zelle). Only the former belongs there — a named
# payment falling back to "Transfers" would silently disappear from the
# dashboard (Transfers is fully excluded) even though it's real money.
# These are exact prefixes seen in real generic-transfer descriptions.
GENERIC_TRANSFER_PREFIXES = [
    "venmo",
    "p2p transfer",
    "transfer from savings",
    "transfer to savings",
    "overdraft protection transfer",
    "overdraft transfer",  # "...from Savings Account XXXXXX" / "...to Spending Account XXXXXX"
    "internet transfer",   # "Internet transfer to Spending account XXXXXX"
    "standard transfer",
    "ally bank",
    "check",
    "transfer",
]


def is_generic_transfer_description(description: str) -> bool:
    """True for SoFi's own generic internal-transfer descriptions (no person
    attached) — false for anything else, including named-person P2P payments
    that SoFi also happens to primary-category as "Transfers"."""
    lower = description.strip().lower()
    return any(lower.startswith(prefix) for prefix in GENERIC_TRANSFER_PREFIXES)


def normalize_person(raw_person: str) -> str | None:
    """Case/whitespace-insensitive match against config.PEOPLE. Returns the
    canonical name, or None if it matches neither (surfaced separately rather
    than silently dropped)."""
    cleaned = (raw_person or "").strip().lower()
    for canonical in config.PEOPLE:
        if canonical.strip().lower() == cleaned:
            return canonical
    return None
