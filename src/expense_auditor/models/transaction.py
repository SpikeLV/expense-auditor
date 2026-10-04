"""Bank transaction recorded on a statement."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import model_validator

from expense_auditor.models.base import DomainModel
from expense_auditor.models.fields import (
    CurrencyCode,
    OptionalPositiveInt,
    OptionalText,
    PositiveMoney,
    RequiredPath,
    RequiredText,
)
from expense_auditor.normalization.merchant import normalize_merchant


class TransactionDirection(StrEnum):
    """Direction of money relative to the account holder.

    Reconciliation uses ``OUTGOING`` only. ``UNKNOWN`` is an unclassified row
    and is not treated as outgoing.
    """

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    UNKNOWN = "unknown"


class Transaction(DomainModel):
    """One bank-statement line.

    ``amount`` is always a positive ``Decimal``. ``description`` keeps the
    statement text. ``merchant_raw`` is the extracted name, and
    ``merchant_normalized`` is filled from it before matching.
    ``source_file`` is the statement file this row was read from.
    """

    id: RequiredText
    posted_date: date
    direction: TransactionDirection
    amount: PositiveMoney
    currency: CurrencyCode
    description: RequiredText
    merchant_raw: OptionalText = None
    merchant_normalized: OptionalText = None
    source_file: RequiredPath
    source_page: OptionalPositiveInt = None
    source_row: OptionalPositiveInt = None

    @model_validator(mode="before")
    @classmethod
    def fill_merchant(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        raw = payload.get("merchant_raw")
        expected = _normalized_merchant(raw if isinstance(raw, str) else None)
        supplied = payload.get("merchant_normalized", None)
        if isinstance(supplied, str) and not supplied.strip():
            supplied = None
        if supplied is None:
            payload["merchant_normalized"] = expected
        elif isinstance(supplied, str) and supplied.strip() != expected:
            raise ValueError("merchant_normalized does not match merchant_raw")
        return payload

    @model_validator(mode="after")
    def merchant_fields_agree(self) -> Self:
        expected = _normalized_merchant(self.merchant_raw)
        if self.merchant_normalized != expected:
            raise ValueError("merchant_normalized does not match merchant_raw")
        return self


def normalize_transaction(transaction: Transaction) -> Transaction:
    """Return ``transaction`` with ``merchant_normalized`` filled from ``merchant_raw``.

    ``description`` and ``merchant_raw`` are kept. Matching should run after
    this step.
    """
    expected = _normalized_merchant(transaction.merchant_raw)
    if transaction.merchant_normalized == expected:
        return transaction
    payload = transaction.model_dump()
    payload["merchant_normalized"] = expected
    return Transaction.model_validate(payload)


def _normalized_merchant(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    return normalize_merchant(raw) or None
