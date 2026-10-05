"""Transaction-to-document matching."""

from expense_auditor.matching.matcher import match_transactions
from expense_auditor.matching.validation import (
    MatchValidationError,
    currency_safe_amount_equal,
    ensure_confirmed,
)

__all__ = [
    "MatchValidationError",
    "currency_safe_amount_equal",
    "ensure_confirmed",
    "match_transactions",
]
