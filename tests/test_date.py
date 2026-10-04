"""Unit tests for date parsing."""

from __future__ import annotations

from datetime import date

import pytest

from expense_auditor.normalization.date import DateParseError, parse_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("04.10.2026", date(2026, 10, 4)),
        ("4.10.2026", date(2026, 10, 4)),
        ("2026-10-04", date(2026, 10, 4)),
        ("2026-1-4", date(2026, 1, 4)),
        ("04/10/2026", date(2026, 10, 4)),
        ("4/10/2026", date(2026, 10, 4)),
        ("10/04/2026", date(2026, 4, 10)),
        ("29.02.2024", date(2024, 2, 29)),
        (" 2026-10-04 ", date(2026, 10, 4)),
    ],
)
def test_parse_supported_dates(raw: str, expected: date) -> None:
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "04-10-2026",
            "2026/10/04",
            "02/13/2026",
        "32.01.2026",
        "31.04.2026",
        "29.02.2023",
        "2026-02-30",
        "04.10.26",
        "2026-10-04T12:00:00",
        "04.10.2026 12:00",
        "yesterday",
    ],
)
def test_parse_date_rejects_invalid_or_ambiguous_values(raw: str) -> None:
    with pytest.raises(DateParseError):
        parse_date(raw)


def test_slash_dates_are_day_first() -> None:
    assert parse_date("13/01/2026") == date(2026, 1, 13)


def test_parse_date_rejects_non_text() -> None:
    with pytest.raises(TypeError):
        parse_date(20261004)  # type: ignore[arg-type]
