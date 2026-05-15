# K-Mint

K-Mint is a small local Streamlit app for reviewing household expenses from monthly bank and credit card CSV exports. It keeps bank credentials out of the app entirely: CSV files are processed locally, categorized by rules, reviewed by you, and summarized into an exportable CSV.

## Project Structure

```text
k-mint/
  app.py
  requirements.txt
  config/
    categories.json
    keyword_rules.json
  household_expenses/
    __init__.py
    categorization.py
    normalization.py
```

Normalized transactions use these standard columns internally:

`Date`, `Month`, `Source Bank`, `Account`, `Merchant`, `Description`, `Amount`, `Type`, `Category`, `Subcategory`, `Needs Review`, `Notes`, `Transaction Hash`, `Imported At`, `Source File`

## Setup

1. Create a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies.

```bash
pip install -r requirements.txt
```

3. Run the app.

```bash
streamlit run app.py
```

## Categories And Rules

Dropdown options live in [config/categories.json](/Users/agnesakrastev/code-projects/k-mint/config/categories.json). This file maps each category to the subcategories that belong to it:

```json
{
  "Transportation": ["Gas", "Parking", "Tolls"],
  "Food & Dining": ["Restaurants"]
}
```

During review, the Category dropdown is populated from this file. After you pick a Category, the Subcategory dropdown only shows the subcategories for that Category.

Keyword mappings live in [config/keyword_rules.json](/Users/agnesakrastev/code-projects/k-mint/config/keyword_rules.json). This format lets many keywords map to the same category/subcategory pair:

```json
{
  "type": "Expense",
  "category": "Transportation",
  "subcategory": "Gas",
  "keywords": ["shell", "chevron", "exxon", "circle k"]
}
```

Rule fields:

- `keywords`: matched against merchant and description
- `category`: top-level category
- `subcategory`: detailed category
- `type`: `Income`, `Expense`, or `Ignore`
- `notes`: optional note copied into matched transactions

For `Income` and `Expense` rules, `type` filters the rule so it only applies to that transaction type. For `Ignore` rules, the matching transaction is marked as `Ignore` and excluded from monthly totals. The first matching rule group wins, so put more specific groups above broader groups.

## CSV Import Behavior

K-Mint expects the monthly CSV to have exactly this transaction format:

```csv
transaction_type,date,description,amount
DEBIT,2026-05-01,COSTCO WHOLESALE,42.50
CREDIT,2026-05-02,ACME PAYROLL,2500.00
```

Column meanings:

- `transaction_type`: must be `DEBIT` or `CREDIT`
- `date`: transaction date
- `description`: transaction description; category keywords are matched here
- `amount`: positive transaction amount

Transactions are normalized into the standard schema and assigned a transaction hash from date, amount, description, account, and source row.

## Workflow

1. Upload one monthly CSV file.
2. Click `Next`.
3. Review the proposed category and subcategory mapping.
4. Use dropdowns to change category or subcategory when needed.
5. Click `Done`.
6. Review the summary by category and subcategory.
7. Click `Export summary CSV`.

The summary page shows total income, total expenses, and `Budget (Income - Expense)`. Transactions with `Type = Ignore` remain visible during review but are excluded from the summary totals and exported summary CSV.

The exported summary has exactly these columns:

`Type`, `Category`, `Subcategory`, `Total`

## Privacy Notes

- The app never asks for or stores bank login credentials.
- CSV processing happens locally.
- Category rules can stay local in `config/keyword_rules.json`.
- The current UI exports a local summary CSV and does not send transaction data anywhere.
