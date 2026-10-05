"""Turn contract text into the invoices that text actually requires.

The deterministic analyzer is the first implementation. A later analyzer can
follow ``ContractAnalyzer`` without changing the folder check.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Protocol, Self

from pydantic import model_validator

from expense_auditor.models.base import DomainModel
from expense_auditor.models.fields import OptionalCurrencyCode, OptionalPositiveMoney, OptionalText
from expense_auditor.normalization.amount import AmountParseError, NormalizedAmount, parse_amount

_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTH_NAME = "|".join(name.capitalize() for name in _MONTHS)
_POINT = (
    rf"(?:(?:{_MONTH_NAME})\s+20\d{{2}}"
    rf"|20\d{{2}}-(?:0[1-9]|1[0-2])"
    rf"|\d{{1,2}}\.\d{{1,2}}\.20\d{{2}})"
)
_RANGE = re.compile(
    rf"(?i)(?:contract|service)\s+period\s*[:\-]?\s*({_POINT})\s*(?:-|–|—|\bto\b)\s*({_POINT})"
)
_MONTHLY = re.compile(
    r"(?i)\binvoices?\s+(?:are\s+)?issued\s+monthly\b|\bmonthly\s+invoices?\b|\bissued\s+monthly\b"
)
_FEE = re.compile(r"(?i)monthly\s+(?:service\s+)?fee\b(.*)")
_EXPLICIT = re.compile(
    rf"(?im)^[ \t]*((?:{_MONTH_NAME})\s+20\d{{2}}|20\d{{2}}-(?:0[1-9]|1[0-2]))"
    rf"[ \t]+(?:—|-|–)?[ \t]*((?:EUR|USD|GBP)[ \t]+\d[\d.,]*|\d[\d.,]*[ \t]+(?:EUR|USD|GBP))"
    rf"[ \t]*$"
)
_UNABLE = "The contract does not clearly specify the invoice schedule/amount."
_MAX_MONTHS = 60


class ExpectedInvoice(DomainModel):
    """One invoice the contract says should exist."""

    period: OptionalText = None
    amount: OptionalPositiveMoney = None
    currency: OptionalCurrencyCode = None
    description: OptionalText = None
    invoice_number: OptionalText = None


class ContractRequirements(DomainModel):
    """Invoices required by a contract, or an explicit failure to determine them."""

    determined: bool
    reason: str | None = None
    invoices: tuple[ExpectedInvoice, ...] = ()

    @model_validator(mode="after")
    def requirements_agree(self) -> Self:
        if self.determined and not self.invoices:
            raise ValueError("a determined contract needs at least one invoice")
        if not self.determined and self.invoices:
            raise ValueError("an undetermined contract cannot list invoices")
        return self


class ContractAnalyzer(Protocol):
    """Read contract text and return the invoices it requires."""

    def analyze(self, text: str) -> ContractRequirements:
        """Return requirements found in ``text``."""


class DeterministicContractAnalyzer:
    """Read monthly fees, contract periods, and explicit invoice lines.

    A missing schedule or amount produces no invoices.
    """

    def analyze(self, text: str) -> ContractRequirements:
        """Return the invoices ``text`` states, or an undetermined result."""
        if not isinstance(text, str) or not text.strip():
            return _unable("The contract text is empty.")
        explicit = _explicit_invoices(text)
        if explicit is not None:
            return explicit
        return _monthly_invoices(text)


def _unable(detail: str) -> ContractRequirements:
    reason = _UNABLE if detail == _UNABLE else f"{_UNABLE} {detail}"
    return ContractRequirements(determined=False, reason=reason, invoices=())


def _explicit_invoices(text: str) -> ContractRequirements | None:
    found: list[ExpectedInvoice] = []
    periods: set[str] = set()
    for match in _EXPLICIT.finditer(text):
        period = _period_point(match.group(1))
        amount = _parse_amount(match.group(2))
        if period is None or amount is None or amount.currency is None:
            return _unable("An invoice line does not give a period, amount, and currency.")
        if period in periods:
            return _unable("The same invoice period is listed more than once.")
        periods.add(period)
        found.append(
            ExpectedInvoice(
                period=period,
                amount=amount.amount,
                currency=amount.currency,
                description=None,
                invoice_number=None,
            )
        )
    if not found:
        return None
    return ContractRequirements(determined=True, invoices=tuple(found))


def _monthly_invoices(text: str) -> ContractRequirements:
    if _MONTHLY.search(text) is None:
        return _unable("No monthly invoice schedule was stated.")
    fee = _monthly_fee(text)
    if fee is None:
        return _unable("No single monthly fee was stated.")
    period = _RANGE.search(text)
    if period is None:
        return _unable("No contract period was stated.")
    start = _period_point(period.group(1))
    end = _period_point(period.group(2))
    if start is None or end is None or start > end:
        return _unable("The contract period could not be read.")
    months = _month_span(start, end)
    if len(months) > _MAX_MONTHS:
        return _unable("The contract period is too long to list reliably.")
    invoices = tuple(
        ExpectedInvoice(
            period=month,
            amount=fee.amount,
            currency=fee.currency,
            description="Monthly service fee",
            invoice_number=None,
        )
        for month in months
    )
    return ContractRequirements(determined=True, invoices=invoices)


def _monthly_fee(text: str) -> NormalizedAmount | None:
    amounts: list[NormalizedAmount] = []
    for match in _FEE.finditer(text):
        amount = _parse_amount(match.group(1))
        if amount is None or amount.currency is None:
            return None
        amounts.append(amount)
    unique = {(item.amount, item.currency) for item in amounts}
    if len(unique) != 1:
        return None
    return amounts[0]


def _parse_amount(fragment: str) -> NormalizedAmount | None:
    cleaned = fragment.strip(" :-\t—–")
    if not cleaned:
        return None
    try:
        return parse_amount(cleaned)
    except AmountParseError:
        return None


def _period_point(value: str) -> str | None:
    text = value.strip()
    named = re.fullmatch(rf"(?i)({_MONTH_NAME})\s+(20\d{{2}})", text)
    if named is not None:
        month = _MONTHS.index(named.group(1).lower()) + 1
        return f"{named.group(2)}-{month:02d}"
    iso = re.fullmatch(r"(20\d{2})-(0[1-9]|1[0-2])", text)
    if iso is not None:
        return f"{iso.group(1)}-{iso.group(2)}"
    dotted = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})", text)
    if dotted is not None:
        month = int(dotted.group(2))
        if month < 1 or month > 12:
            return None
        return f"{dotted.group(3)}-{month:02d}"
    return None


def _month_span(start: str, end: str) -> tuple[str, ...]:
    cursor = _month_date(start)
    last = _month_date(end)
    months: list[str] = []
    while cursor <= last:
        months.append(f"{cursor.year:04d}-{cursor.month:02d}")
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return tuple(months)


def _month_date(period: str) -> date:
    year, month = period.split("-")
    return date(int(year), int(month), 1)
