"""Unit tests for merchant normalization and similarity."""

from __future__ import annotations

import pytest

from expense_auditor.normalization.merchant import merchant_similarity, normalize_merchant


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rimi Latvia SIA", "RIMI LATVIA"),
        (" RIMI LATVIA, SIA ", "RIMI LATVIA"),
        ("rimi   latvia", "RIMI LATVIA"),
        ("Latvenergo AS", "LATVENERGO"),
        ("Acme Ltd", "ACME"),
        ("Acme LLC", "ACME"),
        ("Acme Inc", "ACME"),
        ("Acme SIA LTD", "ACME"),
        ("SIA.", ""),
        ("Acme L.L.C.", "ACME"),
        ("Maxima, SIA.", "MAXIMA"),
        ("H&M", "H&M"),
        ("McDonald's", "MCDONALDS"),
        ("THE SIA STORE", "THE SIA STORE"),
        ("GAS STATION", "GAS STATION"),
    ],
)
def test_normalize_merchant(raw: str, expected: str) -> None:
    assert normalize_merchant(raw) == expected


def test_normalize_merchant_does_not_change_the_original() -> None:
    original = " RIMI LATVIA, SIA "
    assert normalize_merchant(original) == "RIMI LATVIA"
    assert original == " RIMI LATVIA, SIA "


def test_normalize_merchant_is_stable() -> None:
    assert normalize_merchant(normalize_merchant("Rimi Latvia SIA")) == "RIMI LATVIA"


def test_merchant_similarity_ignores_case_and_legal_suffix() -> None:
    assert merchant_similarity("Rimi Latvia SIA", " RIMI LATVIA, SIA ") == 1.0


def test_merchant_similarity_is_symmetric_and_not_a_decision() -> None:
    left = "RIMI"
    right = "RIMI LATVIA"
    score = merchant_similarity(left, right)
    assert isinstance(score, float)
    assert not isinstance(score, bool)
    assert 0.0 < score < 1.0
    assert merchant_similarity(right, left) == score


def test_merchant_similarity_of_different_names_is_low() -> None:
    assert merchant_similarity("AAAA", "ZZZZ") == 0.0


def test_merchant_similarity_of_empty_name_is_zero() -> None:
    assert merchant_similarity("SIA", "RIMI") == 0.0


def test_merchant_normalization_rejects_non_text() -> None:
    with pytest.raises(TypeError):
        normalize_merchant(123)  # type: ignore[arg-type]
