"""Score one transaction against one document or a same-currency combination.

Weights, date bands, and merchant bands come from ``MatchingSettings``.
Signals are 0–1. A missing signal is ``None`` and adds nothing. Amounts are
``Decimal`` values compared with ``currency_safe_amount_equal``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from expense_auditor.config import MatchingSettings
from expense_auditor.matching.validation import currency_safe_amount_equal
from expense_auditor.models.document import Document
from expense_auditor.models.transaction import Transaction
from expense_auditor.normalization.merchant import merchant_similarity, normalize_merchant


@dataclass(frozen=True)
class DocumentSignals:
    """Signals for one cited document."""

    document: Document
    amount_exact: bool | None
    merchant_similarity: float | None
    date_delta_days: int | None


@dataclass(frozen=True)
class MatchSignals:
    """Signals for a candidate, before status is chosen."""

    documents: tuple[DocumentSignals, ...]
    amount_score: float | None
    currency_score: float | None
    merchant_score: float | None
    date_score: float | None
    reference_score: float | None
    group_amount_exact: bool
    total: float


def score_document(
    transaction: Transaction,
    document: Document,
    settings: MatchingSettings,
) -> MatchSignals:
    """Score one document against ``transaction``."""
    linked = _document_signals(transaction, document, settings)
    amount_score = _flag_score(linked.amount_exact)
    currency_score = _currency_score(transaction.currency, document.currency)
    reference_score = reference_signal(transaction, document, settings)
    total = _weighted(
        settings,
        amount_score=amount_score,
        currency_score=currency_score,
        merchant_score=linked.merchant_similarity,
        date_score=date_signal(linked.date_delta_days, settings),
        reference_score=reference_score,
    )
    return MatchSignals(
        documents=(linked,),
        amount_score=amount_score,
        currency_score=currency_score,
        merchant_score=linked.merchant_similarity,
        date_score=date_signal(linked.date_delta_days, settings),
        reference_score=reference_score,
        group_amount_exact=False,
        total=total,
    )


def score_combination(
    transaction: Transaction,
    documents: tuple[Document, ...],
    settings: MatchingSettings,
) -> MatchSignals | None:
    """Score documents whose amounts sum to ``transaction`` in one currency."""
    if len(documents) < 2:
        return None
    total_amount = Decimal("0")
    for document in documents:
        amount = document.amount
        if document.currency != transaction.currency or amount is None:
            return None
        total_amount += amount
    exact = currency_safe_amount_equal(
        total_amount,
        transaction.currency,
        transaction.amount,
        transaction.currency,
        tolerance=settings.amount_tolerance,
    )
    if exact is not True:
        return None
    linked = tuple(_document_signals(transaction, document, settings) for document in documents)
    merchant_score = _group_merchant(linked)
    date_delta = _group_date_delta(linked)
    reference_score = _max_present(
        reference_signal(transaction, document, settings) for document in documents
    )
    amount_score = 1.0
    currency_score = 1.0
    date_value = date_signal(date_delta, settings)
    total = _weighted(
        settings,
        amount_score=amount_score,
        currency_score=currency_score,
        merchant_score=merchant_score,
        date_score=date_value,
        reference_score=reference_score,
    )
    return MatchSignals(
        documents=linked,
        amount_score=amount_score,
        currency_score=currency_score,
        merchant_score=merchant_score,
        date_score=date_value,
        reference_score=reference_score,
        group_amount_exact=True,
        total=total,
    )


def date_signal(delta_days: int | None, settings: MatchingSettings) -> float | None:
    """Return the configured date score for a non-negative day gap."""
    if delta_days is None:
        return None
    bands = settings.date_bands
    if delta_days <= bands.strong_days:
        return bands.same_day_score
    if delta_days <= bands.close_days:
        return bands.close_score
    if delta_days <= bands.near_days:
        return bands.near_score
    if delta_days <= settings.date_tolerance_days:
        return bands.outer_score
    return 0.0


def merchant_signal(
    left: str | None,
    right: str | None,
    settings: MatchingSettings,
) -> float | None:
    """Compare two merchant names.

    The result uses ``merchant_similarity``. A single brand token of at least
    ``minimum_length`` that appears in the other name is raised to
    ``token_score``, which is how ``AMAZON* NV3LD00P4`` meets ``Amazon`` and
    ``BOLT.EU/...`` meets ``Bolt``. A name shorter than ``minimum_length`` is
    capped so it cannot become strong evidence.
    """
    if left is None or right is None or not left.strip() or not right.strip():
        return None
    left_name = normalize_merchant(left)
    right_name = normalize_merchant(right)
    if not left_name or not right_name:
        return None
    score = merchant_similarity(left, right)
    if _brand_token_matches(left_name, right_name, settings.merchant_bands.minimum_length):
        score = max(score, settings.merchant_bands.token_score)
    shorter = min(len(left_name), len(right_name))
    if shorter < settings.merchant_bands.minimum_length:
        score = min(score, settings.merchant_bands.short_cap)
    return _unit(score)


def reference_signal(
    transaction: Transaction,
    document: Document,
    settings: MatchingSettings,
) -> float | None:
    """Return 1 when an invoice number or reference token is shared.

    The document containing its own invoice number is not evidence. The number
    has to appear in the transaction text, or a long transaction token has to
    appear in the document text.
    """
    minimum = settings.reference_minimum_length
    invoice = _compact(document.invoice_number)
    transaction_text = _compact(transaction.description)
    document_text = _compact(
        " ".join(part for part in (document.invoice_number, document.extracted_text) if part)
    )
    if invoice and _useful_token(invoice, minimum) and invoice in transaction_text:
        return 1.0
    if not document_text:
        return None
    for token in _reference_tokens(transaction.description, minimum):
        if token in document_text:
            return 1.0
    if invoice or document.extracted_text:
        return 0.0
    return None


def explain(
    signals: MatchSignals,
    status_label: str,
    settings: MatchingSettings,
    posted_date: date,
) -> str:
    """Build a deterministic explanation from the signals that were present."""
    parts: list[str] = []
    if signals.amount_score == 1.0 and signals.currency_score == 1.0:
        if signals.group_amount_exact:
            parts.append("Documents in the same currency sum to the transaction amount")
        else:
            parts.append("Exact amount and currency")
    elif signals.currency_score == 0.0:
        parts.append("Currency differs")
    elif signals.amount_score == 0.0:
        parts.append("Amount differs")
    elif signals.amount_score is None or signals.currency_score is None:
        parts.append("Amount or currency is missing")
    parts.append(_merchant_phrase(signals.merchant_score, settings))
    parts.append(_date_phrase(signals, posted_date))
    if signals.reference_score == 1.0:
        parts.append("invoice or reference text matches")
    sentence = "; ".join(parts)
    sentence = sentence[0].upper() + sentence[1:]
    return f"{sentence}. Classified as {status_label}."


def _document_signals(
    transaction: Transaction,
    document: Document,
    settings: MatchingSettings,
) -> DocumentSignals:
    amount_exact = currency_safe_amount_equal(
        transaction.amount,
        transaction.currency,
        document.amount,
        document.currency,
        tolerance=settings.amount_tolerance,
    )
    merchant = _best_merchant(transaction, document, settings)
    return DocumentSignals(
        document=document,
        amount_exact=amount_exact,
        merchant_similarity=merchant,
        date_delta_days=_date_delta(transaction.posted_date, document.issued_date),
    )


def _best_merchant(
    transaction: Transaction,
    document: Document,
    settings: MatchingSettings,
) -> float | None:
    pairs = (
        (transaction.merchant_raw, document.merchant_raw),
        (transaction.merchant_normalized, document.merchant_normalized),
        (transaction.description, document.merchant_raw),
    )
    scores = [
        merchant_signal(left, right, settings)
        for left, right in pairs
        if left and right
    ]
    present = [score for score in scores if score is not None]
    if not present:
        return None
    return max(present)


def _brand_token_matches(left: str, right: str, minimum_length: int) -> bool:
    left_tokens = _distinctive(left, minimum_length)
    right_tokens = _distinctive(right, minimum_length)
    if len(left_tokens) == 1 and _token_in(left_tokens[0], right_tokens):
        return True
    if len(right_tokens) == 1 and _token_in(right_tokens[0], left_tokens):
        return True
    if left_tokens and right_tokens and _token_in(left_tokens[0], right_tokens):
        return True
    if left_tokens and right_tokens and _token_in(right_tokens[0], left_tokens):
        return True
    return False


def _distinctive(name: str, minimum_length: int) -> tuple[str, ...]:
    return tuple(token for token in name.split(" ") if len(token) >= minimum_length)


def _token_in(token: str, others: tuple[str, ...]) -> bool:
    return any(
        other == token or other.startswith(token) or token.startswith(other) for other in others
    )


def _date_delta(posted: date, issued: date | None) -> int | None:
    if issued is None:
        return None
    return abs((issued - posted).days)


def _currency_score(left: str | None, right: str | None) -> float | None:
    if left is None or right is None:
        return None
    if left == right:
        return 1.0
    return 0.0


def _flag_score(flag: bool | None) -> float | None:
    if flag is None:
        return None
    if flag:
        return 1.0
    return 0.0


def _weighted(
    settings: MatchingSettings,
    *,
    amount_score: float | None,
    currency_score: float | None,
    merchant_score: float | None,
    date_score: float | None,
    reference_score: float | None,
) -> float:
    weights = settings.weights
    total = (
        weights.amount * _or_zero(amount_score)
        + weights.currency * _or_zero(currency_score)
        + weights.merchant * _or_zero(merchant_score)
        + weights.date * _or_zero(date_score)
        + weights.reference * _or_zero(reference_score)
    )
    return _unit(total)


def _or_zero(value: float | None) -> float:
    if value is None:
        return 0.0
    return value


def _unit(value: float) -> float:
    rounded = round(value, 6)
    if rounded < 0:
        return 0.0
    if rounded > 1:
        return 1.0
    return rounded


def _group_merchant(linked: tuple[DocumentSignals, ...]) -> float | None:
    scores = [item.merchant_similarity for item in linked]
    if any(score is None for score in scores):
        return None
    present = [score for score in scores if score is not None]
    return min(present)


def _group_date_delta(linked: tuple[DocumentSignals, ...]) -> int | None:
    deltas = [item.date_delta_days for item in linked]
    if any(delta is None for delta in deltas):
        return None
    present = [delta for delta in deltas if delta is not None]
    return max(present)


def _max_present(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(present)


def _merchant_phrase(score: float | None, settings: MatchingSettings) -> str:
    if score is None:
        return "merchant was not available"
    if score >= settings.merchant_bands.strong:
        return "strong merchant match"
    if score >= settings.merchant_bands.moderate:
        return "merchant similarity is moderate"
    return "merchant similarity is weak"


def _date_phrase(signals: MatchSignals, posted_date: date) -> str:
    dated = [
        item
        for item in signals.documents
        if item.document.issued_date is not None and item.date_delta_days is not None
    ]
    if len(dated) != len(signals.documents) or not dated:
        return "document date is missing"
    delta = max(item.date_delta_days or 0 for item in dated)
    if delta == 0:
        return "dates are the same day"
    unit = "day" if delta == 1 else "days"
    if len(dated) == 1:
        issued = dated[0].document.issued_date
        if issued is not None and issued < posted_date:
            return f"document date is {delta} {unit} before the transaction"
        return f"document date is {delta} {unit} after the transaction"
    return f"dates differ by up to {delta} {unit}"


def _compact(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(character for character in value.upper() if character.isalnum())


def _reference_tokens(description: str, minimum: int) -> tuple[str, ...]:
    tokens: list[str] = []
    current: list[str] = []
    for character in description.upper():
        if character.isalnum():
            current.append(character)
            continue
        _keep_token(tokens, "".join(current), minimum)
        current = []
    _keep_token(tokens, "".join(current), minimum)
    return tuple(dict.fromkeys(tokens))


def _keep_token(tokens: list[str], token: str, minimum: int) -> None:
    if _useful_token(token, minimum):
        tokens.append(token)


def _useful_token(token: str, minimum: int) -> bool:
    if len(token) < minimum:
        return False
    if token.isdigit():
        return len(token) >= 8
    return any(character.isalpha() for character in token)
