"""Folder checks for invoices required by a contract."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from expense_auditor.checking.checker import check_folder, format_invoice_check
from expense_auditor.cli import main
from expense_auditor.contract.analyzer import DeterministicContractAnalyzer

_CONTRACT = """
Service agreement
Monthly service fee: EUR 500
Invoices issued monthly
Contract period: January 2026 - March 2026
"""


def _write_pdf(path: Path, text: str) -> None:
    document = pymupdf.open()
    try:
        page = document.new_page()
        y = 72
        for line in text.splitlines():
            if line:
                page.insert_text((72, y), line)
            y += 18
        document.save(path)
    finally:
        document.close()


def _invoice(month: int, amount: str = "500") -> str:
    return "\n".join(
        (
            "Invoice",
            f"Date: 15.{month:02d}.2026",
            f"Total EUR {amount}",
            "Supplier: Example Services",
        )
    )


def _folder(root: Path, contract: str, invoices: dict[str, str]) -> None:
    _write_pdf(root / "service_agreement.pdf", contract)
    for name, text in invoices.items():
        _write_pdf(root / name, text)


def test_all_required_invoices_are_present(tmp_path: Path) -> None:
    _folder(
        tmp_path,
        _CONTRACT,
        {
            "january.pdf": _invoice(1),
            "february.pdf": _invoice(2),
            "march.pdf": _invoice(3),
        },
    )

    result = check_folder(tmp_path)

    assert result.missing == ()
    assert result.found_count == 3
    assert "All expected invoices are present." in format_invoice_check(result)


def test_missing_invoice_is_listed(tmp_path: Path) -> None:
    _folder(
        tmp_path,
        _CONTRACT,
        {
            "january.pdf": _invoice(1),
            "february.pdf": _invoice(2),
        },
    )

    result = check_folder(tmp_path)
    text = format_invoice_check(result)

    assert len(result.missing) == 1
    assert result.missing[0].period == "2026-03"
    assert "Invoices missing: 1" in text
    assert "March 2026 — EUR 500" in text


def test_filename_need_not_match_the_month_name(tmp_path: Path) -> None:
    _folder(
        tmp_path,
        _CONTRACT,
        {
            "january.pdf": _invoice(1),
            "february.pdf": _invoice(2),
            "service_invoice_03_2026.pdf": _invoice(3),
        },
    )

    result = check_folder(tmp_path)

    assert result.missing == ()
    assert result.found_count == 3


def test_amount_mismatch_is_not_treated_as_found(tmp_path: Path) -> None:
    _folder(
        tmp_path,
        _CONTRACT,
        {
            "january.pdf": _invoice(1),
            "february.pdf": _invoice(2),
            "service_invoice_03_2026.pdf": _invoice(3, amount="450"),
        },
    )

    result = check_folder(tmp_path)

    assert [item.period for item in result.missing] == ["2026-03"]


def test_vague_contract_does_not_invent_invoices(tmp_path: Path) -> None:
    _write_pdf(
        tmp_path / "service_agreement.pdf",
        "This agreement sets out general terms of cooperation.",
    )
    _write_pdf(tmp_path / "note.pdf", _invoice(1))

    result = check_folder(tmp_path)
    text = format_invoice_check(result)

    assert result.unable_to_determine is True
    assert result.expected == ()
    assert result.missing == ()
    assert "I could not reliably determine the expected invoices" in text
    assert "does not clearly specify the invoice schedule/amount" in text


def test_unrelated_documents_do_not_create_missing_invoices(tmp_path: Path) -> None:
    _folder(
        tmp_path,
        _CONTRACT,
        {
            "january.pdf": _invoice(1),
            "february.pdf": _invoice(2),
            "march.pdf": _invoice(3),
            "taxi_receipt.pdf": "\n".join(
                (
                    "Taxi receipt",
                    "Date: 02.04.2026",
                    "Total EUR 18.00",
                )
            ),
        },
    )

    result = check_folder(tmp_path)

    assert result.missing == ()
    assert result.found_count == 3


def test_several_contract_files_are_not_guessed(tmp_path: Path) -> None:
    _write_pdf(tmp_path / "service_agreement.pdf", _CONTRACT)
    _write_pdf(tmp_path / "second_contract.pdf", _CONTRACT)

    result = check_folder(tmp_path)
    text = format_invoice_check(result)

    assert result.expected == ()
    assert result.ambiguous_contracts == ("second_contract.pdf", "service_agreement.pdf")
    assert "Several possible contracts were found" in text


def test_monthly_schedule_lists_every_month() -> None:
    requirements = DeterministicContractAnalyzer().analyze(
        "\n".join(
            (
                "Monthly service fee: EUR 500",
                "Invoices issued monthly",
                "Contract period: January 2026 - December 2026",
            )
        )
    )

    assert requirements.determined is True
    assert [item.period for item in requirements.invoices] == [
        f"2026-{month:02d}" for month in range(1, 13)
    ]


def test_cli_prints_the_missing_invoice(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _folder(tmp_path, _CONTRACT, {"january.pdf": _invoice(1)})

    code = main(["check-folder", str(tmp_path)])
    captured = capsys.readouterr()

    assert code == 0
    assert "Invoices expected: 3" in captured.out
    assert "Invoices found: 1" in captured.out
    assert "February 2026 — EUR 500" in captured.out
    assert "March 2026 — EUR 500" in captured.out
