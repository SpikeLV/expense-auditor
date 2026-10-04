"""Unit tests for amount parsing."""

from __future__ import annotations

from decimal import Decimal

import pytest

from expense_auditor.normalization.amount import AmountParseError, parse_amount


@pytest.mark.parametrize(
    ("raw", "amount", "currency"),
    [
        ("43.21", Decimal("43.21"), None),
        ("43,21", Decimal("43.21"), None),
        ("1 234,56", Decimal("1234.56"), None),
        ("1,234.56", Decimal("1234.56"), None),
        ("1.234,56", Decimal("1234.56"), None),
        ("€43.21", Decimal("43.21"), "EUR"),
        ("€ 43.21", Decimal("43.21"), "EUR"),
        ("43.21 EUR", Decimal("43.21"), "EUR"),
        ("43.21EUR", Decimal("43.21"), "EUR"),
        ("EUR43.21", Decimal("43.21"), "EUR"),
        ("eur 43,21", Decimal("43.21"), "EUR"),
        ("€43.21 EUR", Decimal("43.21"), "EUR"),
        ("£10.50", Decimal("10.50"), "GBP"),
        ("1 234 567.89", Decimal("1234567.89"), None),
        ("1,234,567", Decimal("1234567"), None),
        ("43", Decimal("43"), None),
    ],
)
def test_parse_supported_amounts(raw: str, amount: Decimal, currency: str | None) -> None:
    parsed = parse_amount(raw)
    assert parsed.amount == amount
    assert parsed.currency == currency
    assert type(parsed.amount) is Decimal


def test_decimal_precision_is_exact() -> None:
    parsed = parse_amount("0.10")
    assert parsed.amount == Decimal("0.10")
    assert parsed.amount.as_tuple().exponent == -2
    assert parsed.amount != Decimal(0.10)


def test_trailing_zeros_are_preserved() -> None:
    assert parse_amount("43.20").amount == Decimal("43.20")
    assert parse_amount("43,2100").amount == Decimal("43.2100")


def test_narrow_space_is_a_thousands_separator() -> None:
    parsed = parse_amount("1\u202f234,56 EUR")
    assert parsed.amount == Decimal("1234.56")
    assert parsed.currency == "EUR"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "abc",
        "1,234",
        "1.234",
        "$43.21",
        "43.21$",
        "€43.21 USD",
        "1 23,45",
        "10.20.30",
        "-43.21",
        "0.00",
        "0",
        "43.21 EURO",
        "1e2",
    ],
)
def test_parse_amount_rejects_invalid_or_ambiguous_values(raw: str) -> None:
    with pytest.raises(AmountParseError):
        parse_amount(raw)


def test_ambiguous_currency_is_distinct_from_a_bad_number() -> None:
    with pytest.raises(AmountParseError, match="ambiguous currency"):
        parse_amount("$43.21")


def test_conflicting_currency_is_rejected() -> None:
    with pytest.raises(AmountParseError, match="conflicting currency"):
        parse_amount("€43.21 USD")


def test_ambiguous_grouping_is_rejected() -> None:
    with pytest.raises(AmountParseError, match="ambiguous amount"):
        parse_amount("1,234")
