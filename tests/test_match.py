"""Unit tests for reconciliation match models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from expense_auditor.models import Match, MatchedDocument, MatchStatus


def _link(document_id: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"document_id": document_id}
    payload.update(overrides)
    return payload


def test_missing_match_has_no_documents() -> None:
    match = Match(transaction_id="txn-1", status=MatchStatus.MISSING)

    assert match.documents == ()
    assert match.status is MatchStatus.MISSING


@pytest.mark.parametrize("status", [MatchStatus.CONFIRMED, MatchStatus.PROBABLE])
def test_linked_status_requires_a_document(status: MatchStatus) -> None:
    with pytest.raises(ValidationError, match="requires at least one document"):
        Match(transaction_id="txn-1", status=status)


def test_missing_match_rejects_documents() -> None:
    with pytest.raises(ValidationError, match="cannot cite documents"):
        Match.model_validate(
            {
                "transaction_id": "txn-1",
                "status": MatchStatus.MISSING,
                "documents": [_link("doc-1")],
            }
        )


def test_probable_match_records_partial_signals() -> None:
    match = Match.model_validate(
        {
            "transaction_id": "txn-1",
            "status": "PROBABLE",
            "documents": [
                _link(
                    "doc-1",
                    amount_exact=False,
                    merchant_similarity=0,
                    date_delta_days=3,
                )
            ],
        }
    )

    linked = match.documents[0]
    assert match.status is MatchStatus.PROBABLE
    assert isinstance(match.documents, tuple)
    assert linked.amount_exact is False
    assert linked.merchant_similarity == 0.0
    assert linked.date_delta_days == 3


def test_confirmed_match_can_cite_several_documents() -> None:
    match = Match.model_validate(
        {
            "transaction_id": "txn-1",
            "status": MatchStatus.CONFIRMED,
            "documents": [
                _link("doc-1", amount_exact=True, merchant_similarity=1, date_delta_days=0),
                _link("doc-2", amount_exact=True, merchant_similarity=0.8, date_delta_days=1),
            ],
        }
    )

    assert [document.document_id for document in match.documents] == ["doc-1", "doc-2"]


def test_unevaluated_signals_stay_missing() -> None:
    linked = MatchedDocument(document_id="doc-1")

    assert linked.amount_exact is None
    assert linked.merchant_similarity is None
    assert linked.date_delta_days is None


def test_duplicate_document_is_rejected() -> None:
    with pytest.raises(ValidationError, match="same document"):
        Match.model_validate(
            {
                "transaction_id": "txn-1",
                "status": MatchStatus.PROBABLE,
                "documents": [_link("doc-1"), _link("doc-1")],
            }
        )


@pytest.mark.parametrize("similarity", [-0.01, 1.01, True, float("nan")])
def test_merchant_similarity_must_be_a_unit_interval(similarity: object) -> None:
    with pytest.raises(ValidationError):
        MatchedDocument.model_validate(_link("doc-1", merchant_similarity=similarity))


@pytest.mark.parametrize("days", [-1, True, 1.5])
def test_date_proximity_must_be_a_non_negative_integer(days: object) -> None:
    with pytest.raises(ValidationError):
        MatchedDocument.model_validate(_link("doc-1", date_delta_days=days))


def test_amount_exact_must_be_boolean_when_present() -> None:
    with pytest.raises(ValidationError):
        MatchedDocument.model_validate(_link("doc-1", amount_exact=1))


def test_json_round_trip() -> None:
    match = Match(
        transaction_id="txn-1",
        status=MatchStatus.PROBABLE,
        documents=(
            MatchedDocument(
                document_id="doc-1",
                amount_exact=False,
                merchant_similarity=0.75,
                date_delta_days=2,
            ),
        ),
    )

    assert Match.model_validate(match.model_dump(mode="json")) == match


def test_models_are_exported_from_the_package() -> None:
    from expense_auditor.models import (
        Document,
        DocumentKind,
        Match,
        MatchedDocument,
        MatchStatus,
        Transaction,
        TransactionDirection,
    )

    assert Document.__name__ == "Document"
    assert DocumentKind.PDF.value == "pdf"
    assert Match.__name__ == "Match"
    assert MatchStatus.CONFIRMED.value == "CONFIRMED"
    assert MatchedDocument.__name__ == "MatchedDocument"
    assert Transaction.__name__ == "Transaction"
    assert TransactionDirection.OUTGOING.value == "outgoing"
