"""Single source of truth for reporting parameters.

These values feed both the SQL layer (through the `params` and
`review_intervals` tables) and the independent Python recomputation, so the
two sides can never silently drift apart.
"""
from datetime import date
from decimal import Decimal

DEFAULT_SEED = 42

# Reporting period (inclusive on both ends, applied to the booking date).
PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 9, 30)

# Transactions at or above this amount appear in the large transaction extract.
LARGE_TXN_THRESHOLD = Decimal("10000.00")

# Maximum number of months allowed between two KYB reviews, by risk rating.
REVIEW_INTERVAL_MONTHS = {"high": 12, "medium": 24, "low": 36}

# Deliberate data quality problems injected by the generator. They are recorded
# in data/injected_issues.json so tests can compare what the pipeline finds
# against what was planted.
INJECTED = {
    "null_counterparty_country": 120,
    "orphan_account": 40,
    "null_amount": 15,
    "zero_amount": 8,
    "negative_amount": 7,
    "exact_duplicates": 150,
    "restated_duplicates": 20,
    "customers_never_reviewed": 8,
}
