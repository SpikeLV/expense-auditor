"""Link between one bank transaction and its supporting documents."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import model_validator

from expense_auditor.models.base import DomainModel
from expense_auditor.models.fields import (
    OptionalBool,
    OptionalDayOffset,
    OptionalScore,
    OptionalSimilarity,
    RequiredText,
)


class MatchStatus(StrEnum):
    """Reconciliation outcome stored for a transaction."""

    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    MISSING = "MISSING"


class MatchedDocument(DomainModel):
    """One supporting document cited by a match, with the signals used to cite it.

    ``amount_exact``, ``merchant_similarity``, and ``date_delta_days`` stay
    ``None`` when that signal could not be evaluated. A similarity of ``0``
    means the names were compared and did not match.
    """

    document_id: RequiredText
    amount_exact: OptionalBool = None
    merchant_similarity: OptionalSimilarity = None
    date_delta_days: OptionalDayOffset = None


class Match(DomainModel):
    """Reconciliation result for a single transaction.

    ``documents`` is empty when ``status`` is ``MISSING`` and holds one or more
    documents otherwise. Several documents fit the same field, so a later
    multi-document matcher can store them without a new model.

    ``CONFIRMED`` is accepted only when ``matching.validation`` finds
    currency-safe amount evidence and a score at or above the configured
    threshold. Setting ``status`` alone does not make a match confirmed.
    """

    transaction_id: RequiredText
    status: MatchStatus
    documents: tuple[MatchedDocument, ...] = ()
    score: OptionalScore = None

    @model_validator(mode="after")
    def status_agrees_with_documents(self) -> Self:
        document_ids = [document.document_id for document in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("a match cannot cite the same document more than once")
        if self.status is MatchStatus.MISSING:
            if self.documents:
                raise ValueError("MISSING match cannot cite documents")
            return self
        if not self.documents:
            raise ValueError(f"{self.status.value} match requires at least one document")
        if self.status is MatchStatus.CONFIRMED:
            from expense_auditor.config import load_matching_settings
            from expense_auditor.matching.validation import ensure_confirmed

            ensure_confirmed(
                score=self.score,
                amount_exact=tuple(document.amount_exact for document in self.documents),
                settings=load_matching_settings(),
            )
        return self
