"""Check one folder for the invoices its contract requires."""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import model_validator

from expense_auditor.contract.analyzer import (
    ContractAnalyzer,
    DeterministicContractAnalyzer,
    ExpectedInvoice,
)
from expense_auditor.documents.parser import parse_invoice_file, read_document_text
from expense_auditor.documents.scanner import scan_documents
from expense_auditor.matching.invoice_matcher import match_invoices
from expense_auditor.models.base import DomainModel

_CONTRACT_NAME = re.compile(r"(?i)(contract|agreement|ligums|līgums)")
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


class CheckStatus(StrEnum):
    """How far the folder check got."""

    COMPLETE = "complete"
    UNABLE = "unable"
    AMBIGUOUS = "ambiguous"
    NO_CONTRACT = "no_contract"
    UNREADABLE = "unreadable"


class FolderCheck(DomainModel):
    """The invoices a folder's contract requires and which of them are absent."""

    status: CheckStatus
    contract_name: str | None = None
    reason: str | None = None
    expected: tuple[ExpectedInvoice, ...] = ()
    missing: tuple[ExpectedInvoice, ...] = ()
    ambiguous_contracts: tuple[str, ...] = ()

    @model_validator(mode="after")
    def counts_agree(self) -> Self:
        if self.status is not CheckStatus.COMPLETE and self.expected:
            raise ValueError("only a completed check lists expected invoices")
        if len(self.missing) > len(self.expected):
            raise ValueError("missing invoices cannot exceed expected invoices")
        return self

    @property
    def unable_to_determine(self) -> bool:
        """True when the contract was found and its invoice list could not be read."""
        return self.status is CheckStatus.UNABLE

    @property
    def found_count(self) -> int:
        """How many expected invoices were matched to a file."""
        return len(self.expected) - len(self.missing)


def check_folder(
    folder: Path,
    analyzer: ContractAnalyzer | None = None,
) -> FolderCheck:
    """Find the contract in ``folder`` and list the invoices it still lacks."""
    root = Path(folder)
    scanned = scan_documents(root)
    contracts = tuple(
        item for item in scanned if _CONTRACT_NAME.search(item.filepath.name) is not None
    )
    if not contracts:
        return FolderCheck(status=CheckStatus.NO_CONTRACT)
    if len(contracts) > 1:
        names = tuple(sorted(item.filepath.name for item in contracts))
        return FolderCheck(status=CheckStatus.AMBIGUOUS, ambiguous_contracts=names)

    contract = contracts[0]
    text = read_document_text(contract.filepath)
    if not text.strip():
        return FolderCheck(
            status=CheckStatus.UNREADABLE,
            contract_name=contract.filepath.name,
            reason="The contract file has no readable text.",
        )
    active = analyzer if analyzer is not None else DeterministicContractAnalyzer()
    requirements = active.analyze(text)
    if not requirements.determined:
        return FolderCheck(
            status=CheckStatus.UNABLE,
            contract_name=contract.filepath.name,
            reason=requirements.reason,
        )
    others = tuple(
        parse_invoice_file(item.filepath)
        for item in scanned
        if item.filepath != contract.filepath
    )
    _found, missing = match_invoices(requirements.invoices, others)
    return FolderCheck(
        status=CheckStatus.COMPLETE,
        contract_name=contract.filepath.name,
        expected=requirements.invoices,
        missing=missing,
    )


def format_invoice_check(result: FolderCheck) -> str:
    """Return the short text report for ``result``."""
    if result.status is CheckStatus.NO_CONTRACT:
        return (
            "No contract file was found in the folder.\n"
            'A contract filename should contain "contract" or "agreement".'
        )
    if result.status is CheckStatus.AMBIGUOUS:
        names = "\n".join(f"- {name}" for name in result.ambiguous_contracts)
        return (
            "Several possible contracts were found. The folder was not checked.\n\n"
            f"{names}"
        )
    if result.status is CheckStatus.UNREADABLE:
        return (
            f"Contract: {result.contract_name}\n\n"
            "I could not reliably determine the expected invoices from the contract.\n\n"
            f"Reason:\n{result.reason}"
        )
    if result.status is CheckStatus.UNABLE:
        return (
            f"Contract: {result.contract_name}\n\n"
            "I could not reliably determine the expected invoices from the contract.\n\n"
            f"Reason:\n{result.reason}"
        )
    lines = [
        f"Contract: {result.contract_name}",
        "",
        f"Invoices expected: {len(result.expected)}",
        f"Invoices found: {result.found_count}",
        f"Invoices missing: {len(result.missing)}",
        "",
    ]
    if not result.missing:
        lines.append("All expected invoices are present.")
        return "\n".join(lines)
    lines.append("Missing invoices:")
    lines.append("")
    lines.extend(f"- {_describe(invoice)}" for invoice in result.missing)
    return "\n".join(lines)


def _describe(invoice: ExpectedInvoice) -> str:
    label = _period_label(invoice.period) if invoice.period else "Invoice"
    if invoice.amount is None:
        return label
    amount = _amount_text(invoice.amount)
    if invoice.currency:
        return f"{label} — {invoice.currency} {amount}"
    return f"{label} — {amount}"


def _period_label(period: str) -> str:
    year, month = period.split("-")
    return f"{_MONTH_NAMES[int(month) - 1]} {year}"


def _amount_text(amount: Decimal) -> str:
    text = format(amount, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
