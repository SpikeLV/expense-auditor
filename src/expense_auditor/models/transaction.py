"""Bank transaction recorded on a statement."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from expense_auditor.models.base import DomainModel
from expense_auditor.models.fields import (
    CurrencyCode,
    OptionalPositiveInt,
    OptionalText,
    PositiveMoney,
    RequiredPath,
    RequiredText,
)


class TransactionDirection(StrEnum):
    """Direction of money relative to the account holder."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"


class Transaction(DomainModel):
    """One bank-statement line.

    ``amount`` is always a positive ``Decimal``. ``direction`` says whether the
    money left the account or arrived. V0.1 reconciliation uses outgoing lines.
    ``description`` keeps the statement text. ``merchant`` is optional until a
    later normalization step fills it.
    """

    id: RequiredText
    posted_date: date
    direction: TransactionDirection
    amount: PositiveMoney
    currency: CurrencyCode
    description: RequiredText
    merchant: OptionalText = None
    source_path: RequiredPath
    source_page: OptionalPositiveInt = None
    source_row: OptionalPositiveInt = None
