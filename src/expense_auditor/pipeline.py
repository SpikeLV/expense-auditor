"""V0.1 pipeline boundaries.

The stages name the order of work. Stages that belong to a later phase are
marked unimplemented and are not run.
"""

from __future__ import annotations

from expense_auditor.models.base import DomainModel


class PipelineStage(DomainModel):
    """One named boundary in the V0.1 flow."""

    order: int
    name: str
    owner: str
    implemented: bool


_V01_PIPELINE: tuple[PipelineStage, ...] = (
    PipelineStage(
        order=1,
        name="scan_documents",
        owner="documents.scanner",
        implemented=True,
    ),
    PipelineStage(
        order=2,
        name="extract_document_content",
        owner="documents.pdf_parser, documents.ocr",
        implemented=True,
    ),
    PipelineStage(
        order=3,
        name="extract_document_fields",
        owner="documents.fields",
        implemented=True,
    ),
    PipelineStage(
        order=4,
        name="normalize_document_fields",
        owner="models.document",
        implemented=True,
    ),
    PipelineStage(
        order=5,
        name="parse_bank_statement",
        owner="bank",
        implemented=True,
    ),
    PipelineStage(
        order=6,
        name="normalize_transactions",
        owner="models.transaction",
        implemented=True,
    ),
    PipelineStage(
        order=7,
        name="match_transactions",
        owner="matching",
        implemented=True,
    ),
    PipelineStage(
        order=8,
        name="build_reconciliation_result",
        owner="models.reconciliation",
        implemented=True,
    ),
    PipelineStage(
        order=9,
        name="render_reports",
        owner="reporting",
        implemented=True,
    ),
)


def v01_pipeline() -> tuple[PipelineStage, ...]:
    """Return the V0.1 stages in order.

    Parsing a bank statement, matching, and rendering reports are listed so
    later phases have a place to land. This function does not run them.
    """
    return _V01_PIPELINE
