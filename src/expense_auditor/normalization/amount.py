"""Parse monetary text into a Decimal amount and an optional currency."""

from __future__ import annotations

import re
from decimal import Decimal

from pydantic import ValidationError

from expense_auditor.models.base import DomainModel
from expense_auditor.models.fields import OptionalCurrencyCode, PositiveMoney

_SYMBOLS = {"€": "EUR", "£": "GBP"}
_AMBIGUOUS_SYMBOLS = frozenset({"$"})
_CODE = re.compile(r"^[A-Za-z]{3}$")
_SPACES = ("\u00a0", "\u202f", "\u2009")


class AmountParseError(ValueError):
    """The text is not an unambiguous positive amount."""


class NormalizedAmount(DomainModel):
    """A parsed amount. ``currency`` is a 3-letter code, or missing."""

    amount: PositiveMoney
    currency: OptionalCurrencyCode = None


def parse_amount(value: str) -> NormalizedAmount:
    """Parse ``value`` into a positive ``Decimal`` and an optional currency.

    ``43.21``, ``43,21``, ``1 234,56``, ``1,234.56``, ``€43.21``, and
    ``43.21 EUR`` are accepted. Formats that could be read in more than one
    way are rejected.
    """
    if not isinstance(value, str):
        raise TypeError("amount must be text")
    text = _unify_spaces(value).strip()
    if not text:
        raise AmountParseError("invalid amount")
    prefix, body = _peel_prefix(text)
    suffix, body = _peel_suffix(body.strip())
    currency = _merge_currency(prefix, suffix)
    amount = _parse_decimal(body.strip())
    try:
        return NormalizedAmount(amount=amount, currency=currency)
    except ValidationError as exc:
        raise AmountParseError("invalid amount") from exc


def _unify_spaces(value: str) -> str:
    text = value
    for space in _SPACES:
        text = text.replace(space, " ")
    return text


def _currency_boundary(character: str) -> bool:
    return character.isspace() or character.isdigit()


def _peel_prefix(text: str) -> tuple[str | None, str]:
    if text[:1] in _AMBIGUOUS_SYMBOLS:
        raise AmountParseError("ambiguous currency")
    if text[:1] in _SYMBOLS:
        return _SYMBOLS[text[:1]], text[1:].strip()
    if len(text) >= 4 and _CODE.fullmatch(text[:3]) and _currency_boundary(text[3]):
        return text[:3].upper(), text[3:].strip()
    return None, text


def _peel_suffix(text: str) -> tuple[str | None, str]:
    if not text:
        return None, text
    if text[-1:] in _AMBIGUOUS_SYMBOLS:
        raise AmountParseError("ambiguous currency")
    if text[-1:] in _SYMBOLS:
        return _SYMBOLS[text[-1:]], text[:-1].strip()
    if len(text) >= 4 and _CODE.fullmatch(text[-3:]) and _currency_boundary(text[-4]):
        return text[-3:].upper(), text[:-3].strip()
    return None, text


def _merge_currency(prefix: str | None, suffix: str | None) -> str | None:
    if prefix is not None and suffix is not None and prefix != suffix:
        raise AmountParseError("conflicting currency")
    return prefix or suffix


def _parse_decimal(text: str) -> Decimal:
    if not text or not re.fullmatch(r"[\d .,]+", text):
        raise AmountParseError("invalid amount")
    has_comma = "," in text
    has_dot = "." in text
    if has_comma and has_dot:
        if " " in text:
            raise AmountParseError("invalid amount")
        return _parse_both_separators(text)
    if has_comma or has_dot:
        return _parse_one_separator(text, "," if has_comma else ".")
    return Decimal(_grouped_integer(text, " "))


def _parse_both_separators(text: str) -> Decimal:
    if text.rfind(",") > text.rfind("."):
        decimal_sep, thousands_sep = ",", "."
    else:
        decimal_sep, thousands_sep = ".", ","
    integer_part, fractional = text.rsplit(decimal_sep, 1)
    if not fractional.isdigit():
        raise AmountParseError("invalid amount")
    integer = _grouped_integer(integer_part, thousands_sep)
    return Decimal(f"{integer}.{fractional}")


def _parse_one_separator(text: str, separator: str) -> Decimal:
    if " " in text:
        integer_part, separator_and_fraction = _split_last(text, separator)
        if " " in separator_and_fraction:
            raise AmountParseError("invalid amount")
        integer = _grouped_integer(integer_part, " ")
        if not separator_and_fraction.isdigit():
            raise AmountParseError("invalid amount")
        if len(separator_and_fraction) == 3:
            raise AmountParseError("ambiguous amount")
        return Decimal(f"{integer}.{separator_and_fraction}")
    parts = text.split(separator)
    if len(parts) == 2:
        integer_part, fractional = parts
        if not fractional.isdigit() or len(fractional) == 3:
            if len(fractional) == 3 and integer_part.isdigit():
                raise AmountParseError("ambiguous amount")
            raise AmountParseError("invalid amount")
        if not integer_part.isdigit():
            raise AmountParseError("invalid amount")
        return Decimal(f"{integer_part}.{fractional}")
    return Decimal(_grouped_integer(text, separator))


def _split_last(text: str, separator: str) -> tuple[str, str]:
    if text.count(separator) != 1:
        raise AmountParseError("invalid amount")
    integer_part, fractional = text.rsplit(separator, 1)
    return integer_part, fractional


def _grouped_integer(text: str, separator: str) -> str:
    if separator not in text:
        if not text.isdigit():
            raise AmountParseError("invalid amount")
        return text
    groups = text.split(separator)
    if len(groups) < 2 or any(not group.isdigit() for group in groups):
        raise AmountParseError("invalid amount")
    if not 1 <= len(groups[0]) <= 3:
        raise AmountParseError("invalid amount")
    if any(len(group) != 3 for group in groups[1:]):
        raise AmountParseError("invalid amount")
    return "".join(groups)
