"""Evidence checks for reconciliation matches.

``CONFIRMED`` is decided here. A caller cannot turn a weak candidate into a
confirmed match by setting the status alone. Thresholds come from
``MatchingSettings``.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from expense_auditor.config import MatchingSettings


class MatchValidationError(ValueError):
    """The match does not have the evidence its status requires."""


def currency_safe_amount_equal(
    left_amount: Decimal | None,
    left_currency: str | None,
    right_amount: Decimal | None,
    right_currency: str | None,
    *,
    tolerance: Decimal,
) -> bool | None:
    """Return whether two amounts are a currency-safe match.

    Both amount and currency must be present. Different currencies do not
    match, including ``10.00 EUR`` and ``10.00 GBP``. A missing currency or
    amount returns ``None`` rather than an exact match. Amounts use ``Decimal``.
    ``tolerance`` comes from configuration; zero requires equal amounts.
    """
    if (
        left_amount is None
        or right_amount is None
        or left_currency is None
        or right_currency is None
    ):
        return None
    if left_currency != right_currency:
        return False
    return abs(left_amount - right_amount) <= tolerance


def ensure_confirmed(
    *,
    score: float | None,
    amount_exact: Sequence[bool | None],
    settings: MatchingSettings,
) -> None:
    """Reject a confirmed match that lacks currency-safe amount evidence.

    Every cited document must have ``amount_exact`` set from
    ``currency_safe_amount_equal``. The score must be present and at least
    ``settings.confirmed_threshold``.
    """
    flags = tuple(amount_exact)
    if not flags or any(flag is not True for flag in flags):
        raise MatchValidationError("confirmed match requires a currency-safe exact amount")
    if score is None:
        raise MatchValidationError("confirmed match requires a score")
    if score < settings.confirmed_threshold:
        raise MatchValidationError("confirmed match score is below the configured threshold")
