"""Shared field types for monetary values, currency codes, and text."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator


def _required_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected text")
    text = value.strip()
    if not text:
        raise ValueError("text must not be empty")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expected text")
    text = value.strip()
    return text or None


def _currency_code(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("currency must be a 3-letter code")
    code = value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("currency must be a 3-letter code")
    return code


def _optional_currency(value: object) -> str | None:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    return _currency_code(value)


def _positive_money(value: object) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("monetary amount must be Decimal, int, or str")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, str):
        try:
            amount = Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError("invalid monetary amount") from exc
    elif isinstance(value, int):
        amount = Decimal(value)
    else:
        raise ValueError("monetary amount must be Decimal, int, or str")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("monetary amount must be a finite value greater than zero")
    return amount


def _optional_positive_money(value: object) -> Decimal | None:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    return _positive_money(value)


def _required_path(value: object) -> Path:
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError("path must not be empty")
        path = Path(raw)
    elif isinstance(value, Path):
        path = value
    else:
        raise ValueError("expected a filesystem path")
    if path.as_posix() in {"", "."}:
        raise ValueError("path must not be empty")
    return path


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected an integer starting at 1")
    if value < 1:
        raise ValueError("expected an integer starting at 1")
    return value


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError("expected a boolean")
    return value


def _optional_similarity(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("merchant similarity must be between 0 and 1")
    if isinstance(value, float) and math.isnan(value):
        raise ValueError("merchant similarity must be between 0 and 1")
    score = float(value)
    if score < 0 or score > 1:
        raise ValueError("merchant similarity must be between 0 and 1")
    return score


def _optional_day_offset(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("date proximity must be a non-negative number of days")
    if value < 0:
        raise ValueError("date proximity must be a non-negative number of days")
    return value


RequiredText = Annotated[str, BeforeValidator(_required_text)]
OptionalText = Annotated[str | None, BeforeValidator(_optional_text)]
CurrencyCode = Annotated[str, BeforeValidator(_currency_code)]
OptionalCurrencyCode = Annotated[str | None, BeforeValidator(_optional_currency)]
PositiveMoney = Annotated[Decimal, BeforeValidator(_positive_money)]
OptionalPositiveMoney = Annotated[Decimal | None, BeforeValidator(_optional_positive_money)]
RequiredPath = Annotated[Path, BeforeValidator(_required_path)]
OptionalPositiveInt = Annotated[int | None, BeforeValidator(_optional_positive_int)]
OptionalBool = Annotated[bool | None, BeforeValidator(_optional_bool)]
OptionalSimilarity = Annotated[float | None, BeforeValidator(_optional_similarity)]
OptionalDayOffset = Annotated[int | None, BeforeValidator(_optional_day_offset)]
