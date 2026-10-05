"""Match outgoing bank transactions to supporting documents.

Candidate documents share the transaction currency, or have no currency yet.
Exact amounts and same-currency combinations are scored separately. Status
comes from the configured thresholds plus a supporting-evidence check.
One document is assigned to at most one transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from expense_auditor.config import MatchingSettings, load_matching_settings
from expense_auditor.matching.scoring import (
    MatchSignals,
    explain,
    merchant_signal,
    score_combination,
    score_document,
)
from expense_auditor.matching.validation import currency_safe_amount_equal
from expense_auditor.models.document import Document
from expense_auditor.models.match import Match, MatchedDocument, MatchStatus
from expense_auditor.models.reconciliation import (
    ReconciledTransaction,
    ReconciliationResult,
    build_reconciliation_result,
)
from expense_auditor.models.transaction import Transaction, TransactionDirection

_MISSING_REASON = "No supporting document found with sufficient evidence."


@dataclass(frozen=True)
class _Proposal:
    transaction: Transaction
    signals: MatchSignals
    status: MatchStatus


def match_transactions(
    transactions: Sequence[Transaction],
    documents: Sequence[Document],
    settings: MatchingSettings | None = None,
) -> ReconciliationResult:
    """Match outgoing transactions and return the reconciliation result.

    Incoming and unknown transactions are omitted. Every outgoing transaction
    is present, including those with status ``MISSING``. Documents that no
    match cites are available from ``unmatched_documents()``.
    """
    active = settings if settings is not None else load_matching_settings()
    outgoing = [item for item in transactions if item.direction is TransactionDirection.OUTGOING]
    _require_unique(outgoing, documents)
    proposals = _proposals(outgoing, documents, active)
    chosen, blocked = _assign(proposals)
    rows: list[ReconciledTransaction] = []
    for transaction in outgoing:
        proposal = chosen.get(transaction.id)
        if proposal is None:
            rows.append(_missing_row(transaction, blocked.get(transaction.id, _MISSING_REASON)))
            continue
        cited = tuple(item.document for item in proposal.signals.documents)
        rows.append(
            ReconciledTransaction(
                transaction=transaction,
                match=_match_from(proposal, active),
                documents=cited,
            )
        )
    return build_reconciliation_result(rows, documents)


def _proposals(
    transactions: Sequence[Transaction],
    documents: Sequence[Document],
    settings: MatchingSettings,
) -> list[_Proposal]:
    proposals: list[_Proposal] = []
    for transaction in transactions:
        proposals.extend(_single_proposals(transaction, documents, settings))
        proposals.extend(_combination_proposals(transaction, documents, settings))
    return proposals


def _single_proposals(
    transaction: Transaction,
    documents: Sequence[Document],
    settings: MatchingSettings,
) -> list[_Proposal]:
    proposals: list[_Proposal] = []
    for document in documents:
        if document.currency is not None and document.currency != transaction.currency:
            continue
        signals = score_document(transaction, document, settings)
        status = _classify(signals, settings)
        if status is MatchStatus.MISSING:
            continue
        proposals.append(_Proposal(transaction=transaction, signals=signals, status=status))
    return proposals


def _combination_proposals(
    transaction: Transaction,
    documents: Sequence[Document],
    settings: MatchingSettings,
) -> list[_Proposal]:
    if not settings.combination.enabled:
        return []
    pool = _combination_pool(transaction, documents, settings)
    proposals: list[_Proposal] = []
    for combo in _search_combinations(pool, transaction, settings):
        signals = score_combination(transaction, combo, settings)
        if signals is None:
            continue
        status = _classify(signals, settings)
        if status is MatchStatus.MISSING:
            continue
        proposals.append(_Proposal(transaction=transaction, signals=signals, status=status))
    return proposals


def _combination_pool(
    transaction: Transaction,
    documents: Sequence[Document],
    settings: MatchingSettings,
) -> tuple[Document, ...]:
    eligible: list[Document] = []
    for document in documents:
        amount = document.amount
        if document.currency != transaction.currency or amount is None:
            continue
        same_total = currency_safe_amount_equal(
            amount,
            document.currency,
            transaction.amount,
            transaction.currency,
            tolerance=settings.amount_tolerance,
        )
        if same_total is True or amount > transaction.amount:
            continue
        eligible.append(document)
    eligible.sort(key=lambda document: _pool_key(transaction, document, settings))
    return tuple(eligible[: settings.combination.pool_limit])


def _pool_key(
    transaction: Transaction,
    document: Document,
    settings: MatchingSettings,
) -> tuple[float, int, Decimal, str]:
    similarity = merchant_signal(transaction.merchant_raw, document.merchant_raw, settings)
    merchant_rank = -(similarity if similarity is not None else -1.0)
    if document.issued_date is None:
        delta = 10**9
    else:
        delta = abs((document.issued_date - transaction.posted_date).days)
    amount = document.amount if document.amount is not None else Decimal("0")
    return (merchant_rank, delta, -amount, document.id)


def _search_combinations(
    pool: Sequence[Document],
    transaction: Transaction,
    settings: MatchingSettings,
) -> tuple[tuple[Document, ...], ...]:
    """Find same-currency subsets that sum to the transaction amount.

    The pool is already capped. The search never grows past
    ``max_documents``, and a branch stops once its running total is past the
    configured tolerance.
    """
    target = transaction.amount
    tolerance = settings.amount_tolerance
    limit = settings.combination.max_documents
    found: list[tuple[Document, ...]] = []

    def walk(start: int, chosen: list[Document], running: Decimal) -> None:
        if len(chosen) >= 2 and _totals_match(running, target, tolerance):
            found.append(tuple(chosen))
        if len(chosen) >= limit:
            return
        for index in range(start, len(pool)):
            amount = pool[index].amount
            if amount is None:
                continue
            next_total = running + amount
            if next_total > target + tolerance:
                continue
            chosen.append(pool[index])
            walk(index + 1, chosen, next_total)
            chosen.pop()

    walk(0, [], Decimal("0"))
    return tuple(found)


def _totals_match(running: Decimal, target: Decimal, tolerance: Decimal) -> bool:
    return abs(running - target) <= tolerance


def _classify(signals: MatchSignals, settings: MatchingSettings) -> MatchStatus:
    if not _credible(signals, settings):
        return MatchStatus.MISSING
    if _confirmable(signals, settings):
        return MatchStatus.CONFIRMED
    return MatchStatus.PROBABLE


def _credible(signals: MatchSignals, settings: MatchingSettings) -> bool:
    if signals.total < settings.probable_threshold:
        return False
    merchant = signals.merchant_score
    if merchant is not None and merchant >= settings.merchant_bands.moderate:
        return True
    return signals.reference_score == 1.0


def _confirmable(signals: MatchSignals, settings: MatchingSettings) -> bool:
    if signals.total < settings.confirmed_threshold:
        return False
    if signals.amount_score != 1.0 or signals.currency_score != 1.0:
        return False
    merchant = signals.merchant_score
    if merchant is not None and merchant >= settings.merchant_bands.strong:
        return True
    return signals.reference_score == 1.0


def _assign(
    proposals: Sequence[_Proposal],
) -> tuple[dict[str, _Proposal], dict[str, str]]:
    chosen: dict[str, _Proposal] = {}
    blocked: dict[str, str] = {}
    used: dict[str, str] = {}
    for proposal in sorted(proposals, key=_proposal_key):
        transaction_id = proposal.transaction.id
        if transaction_id in chosen:
            continue
        conflict = _conflict_reason(proposal, used)
        if conflict is not None:
            blocked.setdefault(transaction_id, conflict)
            continue
        chosen[transaction_id] = proposal
        for item in proposal.signals.documents:
            used[item.document.id] = transaction_id
    return chosen, blocked


def _proposal_key(proposal: _Proposal) -> tuple[int, float, int, str, tuple[str, ...]]:
    rank = 0 if proposal.status is MatchStatus.CONFIRMED else 1
    document_ids = tuple(item.document.id for item in proposal.signals.documents)
    return (
        rank,
        -proposal.signals.total,
        len(document_ids),
        proposal.transaction.id,
        document_ids,
    )


def _conflict_reason(proposal: _Proposal, used: dict[str, str]) -> str | None:
    for item in proposal.signals.documents:
        owner = used.get(item.document.id)
        if owner is None:
            continue
        return (
            f"Document {item.document.id} is already used by transaction {owner}. "
            "The same document is not assigned to a second transaction."
        )
    return None


def _match_from(proposal: _Proposal, settings: MatchingSettings) -> Match:
    signals = proposal.signals
    cited = tuple(
        MatchedDocument(
            document_id=item.document.id,
            amount_exact=item.amount_exact,
            merchant_similarity=item.merchant_similarity,
            date_delta_days=item.date_delta_days,
        )
        for item in signals.documents
    )
    return Match(
        transaction_id=proposal.transaction.id,
        status=proposal.status,
        documents=cited,
        score=signals.total,
        reason=explain(signals, proposal.status.value, settings, proposal.transaction.posted_date),
        amount_score=signals.amount_score,
        currency_score=signals.currency_score,
        merchant_score=signals.merchant_score,
        date_score=signals.date_score,
        reference_score=signals.reference_score,
        group_amount_exact=signals.group_amount_exact,
    )


def _missing_row(transaction: Transaction, reason: str) -> ReconciledTransaction:
    return ReconciledTransaction(
        transaction=transaction,
        match=Match(
            transaction_id=transaction.id,
            status=MatchStatus.MISSING,
            documents=(),
            score=0,
            reason=reason,
        ),
        documents=(),
    )


def _require_unique(transactions: Sequence[Transaction], documents: Sequence[Document]) -> None:
    transaction_ids = [item.id for item in transactions]
    if len(transaction_ids) != len(set(transaction_ids)):
        raise ValueError("outgoing transaction listed twice")
    document_ids = [item.id for item in documents]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("document listed twice")
