"""Parse common calendar dates into datetime.date values."""

from __future__ import annotations

import re
from datetime import date

_DOTTED = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_SLASHED = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


class DateParseError(ValueError):
    """The text is not one of the supported calendar dates."""


def parse_date(value: str) -> date:
    """Parse ``DD.MM.YYYY``, ``YYYY-MM-DD``, or ``DD/MM/YYYY``.

    Day and month may be written with or without a leading zero. Other
    layouts, including month-first dates, are rejected.
    """
    if not isinstance(value, str):
        raise TypeError("date must be text")
    text = value.strip()
    dotted = _DOTTED.fullmatch(text)
    if dotted is not None:
        return _build_date(int(dotted.group(1)), int(dotted.group(2)), int(dotted.group(3)))
    iso = _ISO.fullmatch(text)
    if iso is not None:
        return _build_date(int(iso.group(3)), int(iso.group(2)), int(iso.group(1)))
    slashed = _SLASHED.fullmatch(text)
    if slashed is not None:
        return _build_date(int(slashed.group(1)), int(slashed.group(2)), int(slashed.group(3)))
    raise DateParseError("unrecognized date")


def _build_date(day: int, month: int, year: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise DateParseError("invalid date") from exc
