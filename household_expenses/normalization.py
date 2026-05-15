from __future__ import annotations

import hashlib
import re
from io import BytesIO
from typing import Iterable

import pandas as pd


STANDARD_COLUMNS = [
    "Date",
    "Month",
    "Source Bank",
    "Account",
    "Merchant",
    "Description",
    "Amount",
    "Type",
    "Category",
    "Subcategory",
    "Needs Review",
    "Notes",
    "Transaction Hash",
    "Imported At",
    "Source File",
]

INTERNAL_COLUMNS = ["_Source Row", *STANDARD_COLUMNS]
IMPORT_COLUMNS = ["transaction_type", "date", "description", "amount"]


def normalize_uploaded_csvs(
    uploaded_files: Iterable,
    source_bank: str,
    account: str,
    imported_at: str,
) -> pd.DataFrame:
    frames = [
        normalize_csv(
            uploaded_file=uploaded_file,
            source_bank=source_bank,
            account=account,
            imported_at=imported_at,
        )
        for uploaded_file in uploaded_files
    ]
    if not frames:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)
    return combined.reindex(columns=INTERNAL_COLUMNS)


def normalize_csv(uploaded_file, source_bank: str, account: str, imported_at: str) -> pd.DataFrame:
    raw = _read_csv(uploaded_file)
    raw.columns = [_normalize_column_name(column) for column in raw.columns]
    _validate_import_columns(raw)

    transaction_type = raw["transaction_type"].fillna("").astype(str).str.upper().str.strip()
    date_text = raw["date"].fillna("").astype(str).str.strip()
    parsed_dates = _parse_dates(date_text)
    date_values = parsed_dates.dt.date.astype(str)
    date_values = date_values.mask(parsed_dates.isna(), date_text)
    month_values = parsed_dates.dt.to_period("M").astype(str)
    month_values = month_values.mask(parsed_dates.isna(), "")
    description = raw["description"].fillna("").astype(str).map(_clean_text)
    merchant = description.map(_merchant_from_description)
    amount = raw["amount"].map(_parse_money).abs()
    signed_amount = amount.where(transaction_type == "CREDIT", -amount)

    transactions = pd.DataFrame(
        {
            "_Source Row": raw.index + 2,
            "Date": date_values,
            "Month": month_values,
            "Source Bank": source_bank,
            "Account": account,
            "Merchant": merchant,
            "Description": description,
            "Amount": signed_amount.round(2),
            "Type": transaction_type.map({"CREDIT": "Income", "DEBIT": "Expense"}),
            "Category": "Other",
            "Subcategory": "Uncategorized",
            "Needs Review": True,
            "Notes": "",
            "Imported At": imported_at,
            "Source File": getattr(uploaded_file, "name", "uploaded.csv"),
        }
    )
    transactions["Transaction Hash"] = transactions.apply(_transaction_hash, axis=1)
    return transactions.reindex(columns=INTERNAL_COLUMNS)


def _read_csv(uploaded_file) -> pd.DataFrame:
    content = uploaded_file.getvalue()
    for skiprows in range(0, 6):
        try:
            frame = pd.read_csv(BytesIO(content), skiprows=skiprows)
        except UnicodeDecodeError:
            frame = pd.read_csv(BytesIO(content), encoding="latin-1", skiprows=skiprows)
        if len(frame.columns) > 1:
            return frame.dropna(how="all")
    raise ValueError(f"Could not read CSV file: {getattr(uploaded_file, 'name', 'uploaded.csv')}")


def _validate_import_columns(raw: pd.DataFrame) -> None:
    missing = [column for column in IMPORT_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(
            "CSV must include these columns: "
            f"{', '.join(IMPORT_COLUMNS)}. Missing: {', '.join(missing)}"
        )

    invalid_types = sorted(
        set(raw["transaction_type"].dropna().astype(str).str.upper().str.strip())
        - {"DEBIT", "CREDIT"}
    )
    if invalid_types:
        raise ValueError(
            "transaction_type must contain only DEBIT or CREDIT. "
            f"Found: {', '.join(invalid_types)}"
        )


def _parse_money(value) -> float:
    if pd.isna(value):
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    is_parenthesized = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned in {"", "-", "."}:
        return 0.0
    amount = float(cleaned)
    return -abs(amount) if is_parenthesized else amount


def _parse_dates(date_text: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(date_text, errors="coerce", format="mixed")
    missing = parsed.isna()
    if missing.any():
        fallback = pd.to_datetime(date_text[missing], errors="coerce", dayfirst=True, format="mixed")
        parsed.loc[missing] = fallback
    return parsed


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _merchant_from_description(description: str) -> str:
    cleaned = re.sub(r"\b\d{2,}\b", "", description)
    cleaned = re.sub(r"[*#:/\\-]+", " ", cleaned)
    return _clean_text(cleaned).title()


def _normalize_column_name(column: str) -> str:
    return re.sub(r"\s+", " ", str(column).strip().lower())


def _transaction_hash(row: pd.Series) -> str:
    raw_key = "|".join(
        [
            str(row["Date"]),
            f"{float(row['Amount']):.2f}",
            str(row["Description"]).lower(),
            str(row["Account"]).lower(),
            str(row.get("_Source Row", "")),
        ]
    )
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]
