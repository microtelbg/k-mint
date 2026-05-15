from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


RULE_COLUMNS = ["Keyword", "Category", "Subcategory", "Type", "Notes"]
VALID_TRANSACTION_TYPES = ["Income", "Expense", "Ignore"]
DEFAULT_CATEGORY = "Other"
DEFAULT_SUBCATEGORY = "Uncategorized"

INITIAL_CATEGORY_OPTIONS = [
    ("Income", "Salary"),
    ("Income", "Refunds"),
    ("Housing", "Mortgage"),
    ("Housing", "HOA"),
    ("Housing", "Property Tax"),
    ("Housing", "Home Insurance"),
    ("Utilities", "Electricity"),
    ("Utilities", "Water"),
    ("Utilities", "Internet"),
    ("Utilities", "Phones"),
    ("Subscriptions", "Streaming"),
    ("Subscriptions", "Software"),
    ("Shopping", "Groceries"),
    ("Shopping", "Costco"),
    ("Shopping", "Amazon"),
    ("Shopping", "Department Stores"),
    ("Insurance", "Auto Insurance"),
    ("Insurance", "Health Insurance"),
    ("Transportation", "Gas"),
    ("Transportation", "Tolls"),
    ("Food & Dining", "Restaurants"),
    ("Health", "Pharmacy"),
    ("Kids", "School"),
    ("Transfers", "Credit Card Payment"),
    ("Other", "Uncategorized"),
]


def default_category_map() -> dict[str, list[str]]:
    category_map: dict[str, list[str]] = {}
    for category, subcategory in INITIAL_CATEGORY_OPTIONS:
        category_map.setdefault(category, []).append(subcategory)
    return {category: sorted(set(subcategories)) for category, subcategories in category_map.items()}


def load_category_map(path: str | Path) -> dict[str, list[str]]:
    category_path = Path(path)
    if not category_path.exists():
        return default_category_map()

    with category_path.open("r", encoding="utf-8") as file:
        raw_map = json.load(file)

    category_map = {
        str(category).strip(): sorted(
            {str(subcategory).strip() for subcategory in subcategories if str(subcategory).strip()}
        )
        for category, subcategories in raw_map.items()
        if str(category).strip()
    }
    category_map.setdefault(DEFAULT_CATEGORY, [DEFAULT_SUBCATEGORY])
    return dict(sorted(category_map.items()))


def load_keyword_rules(path: str | Path) -> pd.DataFrame:
    rules_path = Path(path)
    if not rules_path.exists():
        return pd.DataFrame(columns=RULE_COLUMNS)

    if rules_path.suffix.lower() != ".json":
        raise ValueError("Keyword rules must be stored in JSON format.")

    with rules_path.open("r", encoding="utf-8") as file:
        groups = json.load(file)

    rows = []
    for group in groups:
        keywords = group.get("keywords", [])
        for keyword in keywords:
            rows.append(
                {
                    "Keyword": keyword,
                    "Category": group.get("category", ""),
                    "Subcategory": group.get("subcategory", ""),
                    "Type": group.get("type", ""),
                    "Notes": group.get("notes", ""),
                }
            )
    return pd.DataFrame(rows, columns=RULE_COLUMNS).fillna("")


def apply_keyword_rules(transactions: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    categorized = transactions.copy()
    categorized["Category"] = DEFAULT_CATEGORY
    categorized["Subcategory"] = DEFAULT_SUBCATEGORY
    categorized["Needs Review"] = True

    normalized_rules = rules.fillna("").copy()
    normalized_rules["Keyword"] = normalized_rules["Keyword"].astype(str).str.lower().str.strip()

    for row_index, transaction in categorized.iterrows():
        searchable_text = " ".join(
            [
                str(transaction.get("Merchant", "")),
                str(transaction.get("Description", "")),
            ]
        ).lower()
        transaction_type = str(transaction.get("Type", "")).lower()

        for _, rule in normalized_rules.iterrows():
            keyword = rule["Keyword"]
            rule_type = str(rule.get("Type", "")).lower().strip()
            if not keyword:
                continue
            if rule_type and rule_type != "ignore" and rule_type != transaction_type:
                continue
            if keyword in searchable_text:
                categorized.at[row_index, "Category"] = rule["Category"] or "Other"
                categorized.at[row_index, "Subcategory"] = rule["Subcategory"] or "Uncategorized"
                if rule_type == "ignore":
                    categorized.at[row_index, "Type"] = "Ignore"
                categorized.at[row_index, "Needs Review"] = False
                if rule.get("Notes"):
                    categorized.at[row_index, "Notes"] = rule["Notes"]
                break

    return categorized
