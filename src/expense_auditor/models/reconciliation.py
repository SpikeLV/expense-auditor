"""Shared result of matching, for every report.

Excel and HTML read the documents and transactions stored here. They do not
rebuild those links from raw ids.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Self

from pydantic import model_validator

from expense_auditor.models.base import DomainModel
from expense_auditor.models.document import Document
from expense_auditor.models.match import Match, MatchStatus
from expense_auditor.models.transaction import Transaction, TransactionDirection


class ReconciledTransaction(DomainModel):
    """One outgoing transaction, its match, and the documents that match cites."""

    transaction: Transaction
    match: Match
    documents: tuple[Document, ...] = ()

    @model_validator(mode="after")
    def links_agree(self) -> Self:
        if self.transaction.direction is not TransactionDirection.OUTGOING:
            raise ValueError("reconciliation only includes outgoing transactions")
        if self.match.transaction_id != self.transaction.id:
            raise ValueError("match transaction id must equal the transaction id")
        match_ids = [item.document_id for item in self.match.documents]
        document_ids = [item.id for item in self.documents]
        if match_ids != document_ids:
            raise ValueError("documents must follow the match in the same order")
        return self


class DocumentReference(DomainModel):
    """One document and the outgoing transactions that cite it.

    ``transactions`` is empty when no match uses the document.
    """

    document: Document
    transactions: tuple[Transaction, ...] = ()


class ReconciliationSummary(DomainModel):
    """Counts taken from a reconciliation result."""

    outgoing_count: int
    confirmed_count: int
    probable_count: int
    missing_count: int
    unmatched_document_count: int


class ReconciliationResult(DomainModel):
    """Outgoing transactions, their documents, and every document that was supplied.

    ``reconciled`` points at documents. ``document_references`` points back at
    the transactions. A document with no transactions was not used by any match.
    """

    reconciled: tuple[ReconciledTransaction, ...]
    document_references: tuple[DocumentReference, ...]

    @model_validator(mode="after")
    def references_follow_matches(self) -> Self:
        if len({row.transaction.id for row in self.reconciled}) != len(self.reconciled):
            raise ValueError("transaction listed twice")
        cited: dict[str, list[Transaction]] = {}
        for row in self.reconciled:
            for document in row.documents:
                cited.setdefault(document.id, []).append(row.transaction)
        seen_documents: set[str] = set()
        for reference in self.document_references:
            if reference.document.id in seen_documents:
                raise ValueError("document listed twice")
            seen_documents.add(reference.document.id)
            expected = cited.get(reference.document.id, [])
            if [item.id for item in reference.transactions] != [item.id for item in expected]:
                raise ValueError(
                    "document references must list the transactions that cite the document"
                )
            for transaction in reference.transactions:
                owner = next(
                    row.transaction
                    for row in self.reconciled
                    if row.transaction.id == transaction.id
                )
                if transaction != owner:
                    raise ValueError(
                        "document reference transaction must be the reconciled transaction"
                    )
        if not set(cited) <= seen_documents:
            raise ValueError("every cited document must appear in document references")
        return self

    def unmatched_documents(self) -> tuple[Document, ...]:
        """Return documents that no match cites."""
        return tuple(
            reference.document
            for reference in self.document_references
            if not reference.transactions
        )

    def summary(self) -> ReconciliationSummary:
        """Return counts derived from the stored rows and document references."""
        return ReconciliationSummary(
            outgoing_count=len(self.reconciled),
            confirmed_count=_count(self, MatchStatus.CONFIRMED),
            probable_count=_count(self, MatchStatus.PROBABLE),
            missing_count=_count(self, MatchStatus.MISSING),
            unmatched_document_count=len(self.unmatched_documents()),
        )


def build_reconciliation_result(
    reconciled: Sequence[ReconciledTransaction],
    documents: Sequence[Document],
) -> ReconciliationResult:
    """Assemble a result from outgoing rows and the full document set.

    This does not search for matches. Documents that no row cites are stored
    with an empty transaction list.
    """
    cited: dict[str, list[Transaction]] = {}
    for row in reconciled:
        for document in row.documents:
            cited.setdefault(document.id, []).append(row.transaction)
    references = tuple(
        DocumentReference(
            document=document,
            transactions=tuple(cited.get(document.id, ())),
        )
        for document in documents
    )
    return ReconciliationResult(
        reconciled=tuple(reconciled),
        document_references=references,
    )


def _count(result: ReconciliationResult, status: MatchStatus) -> int:
    return sum(1 for row in result.reconciled if row.match.status is status)
