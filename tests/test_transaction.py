"""Unit tests for the bank transaction model."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from expense_auditor.models import Transaction, TransactionDirection

_SOURCE = Path("data/2026/10-October/bank/statement.pdf")


def _transaction(**overrides: object) -> Transaction:
    payload: dict[str, object] = {
        "id": "txn-1",
        "posted_date": date(2026, 10, 4),
        "direction": TransactionDirection.OUTGOING,
        "amount": Decimal("19.90"),
        "currency": "EUR",
        "description": "CARD PAYMENT ACME",
        "source_file": _SOURCE,
    }
    payload.update(overrides)
    return Transaction.model_validate(payload)


def test_outgoing_transaction_keeps_exact_amount() -> None:
    transaction = _transaction(merchant_raw="  Acme  ", source_page=2)

    assert transaction.amount == Decimal("19.90")
    assert transaction.currency == "EUR"
    assert transaction.direction is TransactionDirection.OUTGOING
    assert transaction.merchant_raw == "Acme"
    assert transaction.merchant_normalized == "ACME"
    assert transaction.description == "CARD PAYMENT ACME"
    assert transaction.source_page == 2
    assert transaction.source_row is None


def test_amount_accepts_int_and_plain_decimal_string() -> None:
    from_int = _transaction(amount=20)
    from_string = _transaction(amount=" 20.00 ")

    assert from_int.amount == Decimal("20")
    assert from_string.amount == Decimal("20.00")


def test_currency_code_is_uppercased() -> None:
    transaction = _transaction(currency=" eur ")

    assert transaction.currency == "EUR"


@pytest.mark.parametrize(
    "amount",
    [
        10.5,
        True,
        Decimal("0"),
        Decimal("-1.00"),
        Decimal("NaN"),
        Decimal("Infinity"),
        "19,90",
        "",
        None,
    ],
)
def test_amount_rejects_inexact_or_non_positive_values(amount: object) -> None:
    with pytest.raises(ValidationError):
        _transaction(amount=amount)


@pytest.mark.parametrize("currency", ["EU", "EURO", "E1R", "", None])
def test_currency_rejects_non_codes(currency: object) -> None:
    with pytest.raises(ValidationError):
        _transaction(currency=currency)


@pytest.mark.parametrize("field", ["id", "description"])
def test_required_text_rejects_blank_values(field: str) -> None:
    with pytest.raises(ValidationError):
        _transaction(**{field: "   "})


def test_blank_merchant_is_stored_as_missing() -> None:
    transaction = _transaction(merchant_raw="   ")

    assert transaction.merchant_raw is None
    assert transaction.merchant_normalized is None


def test_incoming_transaction_uses_a_positive_amount() -> None:
    transaction = _transaction(direction=TransactionDirection.INCOMING, amount=Decimal("5.00"))

    assert transaction.direction is TransactionDirection.INCOMING
    assert transaction.amount == Decimal("5.00")


@pytest.mark.parametrize("field", ["source_page", "source_row"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_source_locator_starts_at_one(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _transaction(**{field: value})


def test_source_file_is_required() -> None:
    with pytest.raises(ValidationError):
        _transaction(source_file="")


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _transaction(balance=Decimal("1.00"))


def test_transaction_is_frozen() -> None:
    transaction = _transaction()

    with pytest.raises(ValidationError):
        transaction.amount = Decimal("1.00")  # type: ignore[misc]


def test_json_round_trip_preserves_decimal_amount() -> None:
    transaction = _transaction(source_row=4)
    dumped = transaction.model_dump(mode="json")

    assert isinstance(dumped["amount"], str)
    assert Decimal(dumped["amount"]) == Decimal("19.90")
    assert Transaction.model_validate(dumped) == transaction


def test_equal_transactions_hash_equal() -> None:
    assert hash(_transaction()) == hash(_transaction())
