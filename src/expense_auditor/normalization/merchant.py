"""Deterministic merchant-name normalization and similarity."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

_LEGAL_SUFFIXES = frozenset({"SIA", "AS", "LTD", "LLC", "INC"})
_SEPARATORS = re.compile(r"[^\w&]+", flags=re.UNICODE)


def normalize_merchant(name: str) -> str:
    """Return a normalized copy of ``name``.

    The input string is left unchanged. Legal suffixes are removed only when
    they are trailing words, so meaningful merchant words stay in place.
    """
    if not isinstance(name, str):
        raise TypeError("merchant name must be text")
    text = name.upper()
    text = text.replace(" & ", " AND ")
    text = text.replace(".", "")
    text = text.replace("'", "")
    text = text.replace("’", "")
    text = _SEPARATORS.sub(" ", text)
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    tokens = [token for token in text.split(" ") if token]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def merchant_similarity(left: str, right: str) -> float:
    """Return a similarity score from 0.0 to 1.0.

    Both names are normalized before scoring. The score does not decide
    whether the merchants are the same.
    """
    normalized_left = normalize_merchant(left)
    normalized_right = normalize_merchant(right)
    if not normalized_left or not normalized_right:
        return 0.0
    score = float(fuzz.token_sort_ratio(normalized_left, normalized_right))
    return score / 100
