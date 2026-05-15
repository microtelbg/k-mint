from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from household_expenses.categorization import (
    VALID_TRANSACTION_TYPES,
    apply_keyword_rules,
    default_category_map,
    load_category_map,
    load_keyword_rules,
)
from household_expenses.normalization import STANDARD_COLUMNS, normalize_uploaded_csvs


DEFAULT_RULES_PATH = Path("config/keyword_rules.json")
DEFAULT_CATEGORIES_PATH = Path("config/categories.json")
DEFAULT_SOURCE_BANK = "CSV Upload"
DEFAULT_ACCOUNT = "Monthly CSV"
APP_STATE_VERSION = "json-config-only-v7"


st.set_page_config(page_title="K-Mint Household Expenses", layout="wide")

if st.session_state.get("app_state_version") != APP_STATE_VERSION:
    st.session_state.step = "upload"
    st.session_state.mapped_transactions = pd.DataFrame(columns=STANDARD_COLUMNS)
    st.session_state.summary = pd.DataFrame(columns=["Type", "Category", "Subcategory", "Total"])
    st.session_state.category_map = load_category_map(DEFAULT_CATEGORIES_PATH)
    st.session_state.uploaded_file_signature = ""
    st.session_state.app_state_version = APP_STATE_VERSION

if "step" not in st.session_state:
    st.session_state.step = "upload"
if "mapped_transactions" not in st.session_state:
    st.session_state.mapped_transactions = pd.DataFrame(columns=STANDARD_COLUMNS)
if "category_map" not in st.session_state:
    st.session_state.category_map = load_category_map(DEFAULT_CATEGORIES_PATH)
if "summary" not in st.session_state:
    st.session_state.summary = pd.DataFrame(columns=["Type", "Category", "Subcategory", "Total"])
if "uploaded_file_signature" not in st.session_state:
    st.session_state.uploaded_file_signature = ""


def reset_flow() -> None:
    st.session_state.step = "upload"
    st.session_state.mapped_transactions = pd.DataFrame(columns=STANDARD_COLUMNS)
    st.session_state.summary = pd.DataFrame(columns=["Type", "Category", "Subcategory", "Total"])
    st.session_state.uploaded_file_signature = ""


def subcategories_for(category: str) -> list[str]:
    category_map = st.session_state.category_map or default_category_map()
    options = category_map.get(category) or category_map.get("Other") or ["Uncategorized"]
    return sorted(options)


def initialize_review_widget_state(transactions: pd.DataFrame) -> None:
    category_map = st.session_state.category_map or default_category_map()
    for row_index, transaction in transactions.iterrows():
        category_key = review_key("category", row_index, transaction)
        subcategory_key = review_key("subcategory", row_index, transaction)
        type_key = review_key("type", row_index, transaction)
        notes_key = review_key("notes", row_index, transaction)

        st.session_state.setdefault(type_key, transaction.get("Type", "Expense"))
        st.session_state.setdefault(category_key, transaction.get("Category", "Other"))
        st.session_state.setdefault(subcategory_key, transaction.get("Subcategory", "Uncategorized"))
        st.session_state.setdefault(notes_key, transaction.get("Notes", ""))
        if st.session_state[type_key] not in VALID_TRANSACTION_TYPES:
            st.session_state[type_key] = "Expense"
        if st.session_state[category_key] not in category_map:
            st.session_state[category_key] = "Other"
        if st.session_state[subcategory_key] not in subcategories_for(st.session_state[category_key]):
            st.session_state[subcategory_key] = subcategories_for(st.session_state[category_key])[0]


def review_key(field: str, row_index: int, transaction: pd.Series) -> str:
    row_id = transaction.get("Transaction Hash") or row_index
    return f"review_{field}_{row_id}"


def build_reviewed_transactions(transactions: pd.DataFrame) -> pd.DataFrame:
    reviewed = transactions.copy()
    for row_index, transaction in reviewed.iterrows():
        reviewed.at[row_index, "Type"] = st.session_state[review_key("type", row_index, transaction)]
        reviewed.at[row_index, "Category"] = st.session_state[
            review_key("category", row_index, transaction)
        ]
        reviewed.at[row_index, "Subcategory"] = st.session_state[
            review_key("subcategory", row_index, transaction)
        ]
        reviewed.at[row_index, "Notes"] = st.session_state[review_key("notes", row_index, transaction)]
    return reviewed


def render_review_table(transactions: pd.DataFrame) -> None:
    header_cols = st.columns([0.9, 2.2, 1, 1, 1.4, 1.6, 1.4])
    headers = ["Date", "Description", "Amount", "Type", "Category", "Subcategory", "Notes"]
    for column, header in zip(header_cols, headers):
        column.markdown(f"**{header}**")

    category_options = sorted(st.session_state.category_map.keys())
    for row_index, transaction in transactions.iterrows():
        type_key = review_key("type", row_index, transaction)
        category_key = review_key("category", row_index, transaction)
        subcategory_key = review_key("subcategory", row_index, transaction)
        notes_key = review_key("notes", row_index, transaction)

        selected_category = st.session_state.get(category_key, "Other")
        subcategory_options = subcategories_for(selected_category)

        row_cols = st.columns([0.9, 2.2, 1, 1, 1.4, 1.6, 1.4])
        row_cols[0].write(transaction.get("Date", ""))
        row_cols[1].write(transaction.get("Description", ""))
        row_cols[2].write(f"${float(transaction.get('Amount', 0.0)):,.2f}")
        row_cols[3].selectbox(
            "Type",
            options=VALID_TRANSACTION_TYPES,
            key=type_key,
            label_visibility="collapsed",
        )
        row_cols[4].selectbox(
            "Category",
            options=category_options,
            key=category_key,
            label_visibility="collapsed",
        )
        row_cols[5].selectbox(
            "Subcategory",
            options=subcategory_options,
            key=subcategory_key,
            label_visibility="collapsed",
        )
        row_cols[6].text_input("Notes", key=notes_key, label_visibility="collapsed")


def summarize(transactions: pd.DataFrame) -> pd.DataFrame:
    summary_source = transactions.copy()
    summary_source = summary_source[summary_source["Type"] != "Ignore"]
    summary_source["Summary Amount"] = summary_source["Amount"].abs()
    return (
        summary_source.groupby(["Type", "Category", "Subcategory"], as_index=False)["Summary Amount"]
        .sum()
        .rename(columns={"Summary Amount": "Total"})
        .sort_values(["Type", "Category", "Subcategory"])
        .reset_index(drop=True)
    )


def type_totals(summary: pd.DataFrame) -> tuple[float, float, float]:
    totals = summary.groupby("Type")["Total"].sum()
    income = float(totals.get("Income", 0.0))
    expense = float(totals.get("Expense", 0.0))
    return income, expense, income - expense


def table_height(row_count: int) -> int:
    header_height = 38
    row_height = 35
    padding = 12
    return header_height + padding + (max(row_count, 1) * row_height)


def file_signature(uploaded_file) -> str:
    content = uploaded_file.getvalue()
    return hashlib.sha256(
        b"|".join(
            [
                uploaded_file.name.encode("utf-8"),
                str(uploaded_file.size).encode("utf-8"),
                content,
            ]
        )
    ).hexdigest()


def upload_step() -> None:
    st.title("K-Mint Household Expenses")

    uploaded_file = st.file_uploader(
        "Upload monthly CSV file",
        type=["csv"],
        accept_multiple_files=False,
        label_visibility="collapsed",
    )

    if uploaded_file is None:
        st.info("Drop one monthly CSV export here to begin.")
        return

    signature = file_signature(uploaded_file)
    if signature != st.session_state.uploaded_file_signature:
        st.session_state.mapped_transactions = pd.DataFrame(columns=STANDARD_COLUMNS)
        st.session_state.summary = pd.DataFrame(columns=["Type", "Category", "Subcategory", "Total"])

    st.success(f"Ready to import {uploaded_file.name}.")
    if st.button("Next", type="primary"):
        imported_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            rules = load_keyword_rules(DEFAULT_RULES_PATH)
            normalized = normalize_uploaded_csvs(
                uploaded_files=[uploaded_file],
                source_bank=DEFAULT_SOURCE_BANK,
                account=DEFAULT_ACCOUNT,
                imported_at=imported_at,
            )
            mapped = apply_keyword_rules(normalized, rules)
            st.session_state.mapped_transactions = mapped
            st.session_state.uploaded_file_signature = signature
            st.session_state.step = "review"
            st.rerun()
        except Exception as exc:
            st.error(f"Import failed: {exc}")


def review_step() -> None:
    st.title("Review Proposed Mapping")

    transactions = st.session_state.mapped_transactions.copy()
    if transactions.empty:
        st.warning("No imported transactions found.")
        if st.button("Upload CSV"):
            reset_flow()
            st.rerun()
        return

    source_rows = transactions["_Source Row"].count() if "_Source Row" in transactions.columns else len(transactions)
    st.caption(
        f"Read {source_rows:,} CSV rows. Showing {len(transactions):,} mapped rows. "
        "Use the dropdowns to adjust the proposed category and subcategory for each row."
    )

    initialize_review_widget_state(transactions)
    render_review_table(transactions)

    col1, col2, _ = st.columns([1, 1, 4])
    if col1.button("Back"):
        reset_flow()
        st.rerun()
    if col2.button("Done", type="primary"):
        edited = build_reviewed_transactions(transactions).reindex(columns=STANDARD_COLUMNS)
        st.session_state.mapped_transactions = edited
        st.session_state.summary = summarize(edited)
        st.session_state.step = "summary"
        st.rerun()


def summary_step() -> None:
    st.title("Monthly Summary")

    summary = st.session_state.summary
    if summary.empty:
        st.warning("No summary is available yet.")
        if st.button("Upload CSV"):
            reset_flow()
            st.rerun()
        return

    income, expense, budget = type_totals(summary)
    metric_cols = st.columns(3)
    metric_cols[0].metric("Income", f"${income:,.2f}")
    metric_cols[1].metric("Expense", f"${expense:,.2f}")
    metric_cols[2].metric("Budget (Income - Expense)", f"${budget:,.2f}")

    st.dataframe(
        summary,
        use_container_width=True,
        height=table_height(len(summary)),
        hide_index=True,
        column_config={"Total": st.column_config.NumberColumn("Total", format="$%.2f")},
    )

    st.download_button(
        "Export summary CSV",
        data=summary.to_csv(index=False).encode("utf-8"),
        file_name="monthly_summary.csv",
        mime="text/csv",
        type="primary",
    )

    if st.button("Start over"):
        reset_flow()
        st.rerun()


if st.session_state.step == "upload":
    upload_step()
elif st.session_state.step == "review":
    review_step()
else:
    summary_step()
