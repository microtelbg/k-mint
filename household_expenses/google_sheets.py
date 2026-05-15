from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from household_expenses.categorization import RULE_COLUMNS
from household_expenses.normalization import STANDARD_COLUMNS


REQUIRED_TABS = ["Raw Imports", "Transactions", "Category Rules", "Monthly Summary", "Dashboard"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsError(RuntimeError):
    """Raised when Google Sheets configuration or API calls fail."""


@dataclass(frozen=True)
class GoogleSheetsConfig:
    spreadsheet_id: str
    service_account_file: str = "service_account.json"


def _validate_config(config: GoogleSheetsConfig) -> None:
    if not config.spreadsheet_id:
        raise GoogleSheetsError("Add a Google Spreadsheet ID in the sidebar.")
    if not config.service_account_file:
        raise GoogleSheetsError("Add a service account JSON path in the sidebar.")
    if not Path(config.service_account_file).exists():
        raise GoogleSheetsError(
            f"Google service account file was not found: {config.service_account_file}"
        )


def _service(config: GoogleSheetsConfig):
    _validate_config(config)
    credentials = Credentials.from_service_account_file(
        config.service_account_file,
        scopes=SCOPES,
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def ensure_workbook_tabs(config: GoogleSheetsConfig) -> None:
    try:
        service = _service(config)
        spreadsheet = service.spreadsheets().get(spreadsheetId=config.spreadsheet_id).execute()
        existing_titles = {
            sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])
        }
        requests = [
            {"addSheet": {"properties": {"title": title}}}
            for title in REQUIRED_TABS
            if title not in existing_titles
        ]

        if requests:
            service.spreadsheets().batchUpdate(
                spreadsheetId=config.spreadsheet_id,
                body={"requests": requests},
            ).execute()

        _write_headers_if_empty(service, config.spreadsheet_id, "Raw Imports", STANDARD_COLUMNS)
        _write_headers_if_empty(service, config.spreadsheet_id, "Transactions", STANDARD_COLUMNS)
        _write_headers_if_empty(service, config.spreadsheet_id, "Category Rules", RULE_COLUMNS)
        _write_headers_if_empty(
            service,
            config.spreadsheet_id,
            "Monthly Summary",
            ["Month", "Type", "Category", "Subcategory", "Amount"],
        )
    except HttpError as exc:
        raise GoogleSheetsError(f"Google Sheets API error: {exc}") from exc


def _write_headers_if_empty(service, spreadsheet_id: str, tab_name: str, headers: list[str]) -> None:
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"'{tab_name}'!A1:Z1")
        .execute()
    )
    if result.get("values"):
        return

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A1",
        valueInputOption="RAW",
        body={"values": [headers]},
    ).execute()


def append_transactions(config: GoogleSheetsConfig, transactions: pd.DataFrame) -> int:
    if transactions.empty:
        return 0

    try:
        service = _service(config)
        ensure_workbook_tabs(config)
        existing_hashes = _existing_transaction_hashes(service, config.spreadsheet_id)
        rows_to_append = transactions[
            ~transactions["Transaction Hash"].astype(str).isin(existing_hashes)
        ].copy()
        if rows_to_append.empty:
            return 0

        rows = (
            rows_to_append.reindex(columns=STANDARD_COLUMNS)
            .fillna("")
            .astype(str)
            .values
            .tolist()
        )
        service.spreadsheets().values().append(
            spreadsheetId=config.spreadsheet_id,
            range="'Transactions'!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()
        return len(rows)
    except HttpError as exc:
        raise GoogleSheetsError(f"Google Sheets API error: {exc}") from exc


def _existing_transaction_hashes(service, spreadsheet_id: str) -> set[str]:
    hash_column_number = STANDARD_COLUMNS.index("Transaction Hash") + 1
    hash_column_letter = _column_letter(hash_column_number)
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'Transactions'!{hash_column_letter}2:{hash_column_letter}",
        )
        .execute()
    )
    return {
        str(row[0]).strip()
        for row in result.get("values", [])
        if row and str(row[0]).strip()
    }


def _column_letter(column_number: int) -> str:
    letters = ""
    while column_number:
        column_number, remainder = divmod(column_number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
