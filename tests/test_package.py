"""Phase 1 checks that the package layout imports."""

from __future__ import annotations

import importlib

import expense_auditor

_MODULES = (
    "expense_auditor.cli",
    "expense_auditor.pipeline",
    "expense_auditor.models.transaction",
    "expense_auditor.models.document",
    "expense_auditor.models.match",
    "expense_auditor.models.reconciliation",
    "expense_auditor.bank.base",
    "expense_auditor.bank.pdf_parser",
    "expense_auditor.bank.csv_parser",
    "expense_auditor.documents.fields",
    "expense_auditor.documents.scanner",
    "expense_auditor.documents.pdf_parser",
    "expense_auditor.documents.image_parser",
    "expense_auditor.documents.ocr",
    "expense_auditor.normalization.amount",
    "expense_auditor.normalization.date",
    "expense_auditor.normalization.merchant",
    "expense_auditor.identity",
    "expense_auditor.config",
    "expense_auditor.matching.matcher",
    "expense_auditor.matching.validation",
    "expense_auditor.matching.scoring",
    "expense_auditor.reporting.excel",
    "expense_auditor.reporting.html",
)


def test_package_version() -> None:
    assert expense_auditor.__version__ == "0.1.0"


def test_package_modules_import() -> None:
    for module_name in _MODULES:
        importlib.import_module(module_name)
