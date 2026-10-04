"""Plain-text extraction from receipt and invoice PDFs.

This parser reads the PDF text layer with PyMuPDF. It does not perform OCR
and it does not interpret bank-statement layouts.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, Self

import pymupdf
from pydantic import model_validator

from expense_auditor.models.base import DomainModel
from expense_auditor.models.fields import RequiredPath


class PdfTextError(Exception):
    """The file could not be read as a PDF."""


class _PdfPage(Protocol):
    def get_text(self, option: str) -> object: ...


class _PdfDocument(Protocol):
    needs_pass: int

    def __iter__(self) -> Iterator[_PdfPage]: ...


class PdfPageText(DomainModel):
    """Clean text from one PDF page. ``number`` starts at 1."""

    number: int
    text: str


class PdfText(DomainModel):
    """Text layer of a PDF, one entry per page, in page order."""

    path: RequiredPath
    pages: tuple[PdfPageText, ...]

    @model_validator(mode="after")
    def pages_are_ordered(self) -> Self:
        numbers = [page.number for page in self.pages]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("PDF pages must stay in order and start at 1")
        return self

    @property
    def text(self) -> str:
        """Clean text of every non-empty page, in page order."""
        return "\n\n".join(page.text for page in self.pages if page.text)


def extract_pdf_text(path: Path) -> PdfText:
    """Extract the text layer from ``path``.

    Pages stay in document order. Whitespace-only pages are kept and stored
    as empty strings, so a scanned or blank PDF returns empty text instead of
    raising. The source file is not modified.
    """
    if not path.exists():
        raise FileNotFoundError(f"PDF does not exist: {path}")
    if not path.is_file():
        raise IsADirectoryError(f"PDF path is not a file: {path}")

    try:
        with pymupdf.open(path) as document:  # type: ignore[no-untyped-call]
            if document.needs_pass:
                raise PdfTextError(f"PDF is encrypted: {path}")
            pages = _extract_pages(document)
    except PdfTextError:
        raise
    except pymupdf.FileDataError as exc:
        raise PdfTextError(f"cannot read PDF: {path}") from exc
    except pymupdf.FileNotFoundError as exc:
        raise FileNotFoundError(f"PDF does not exist: {path}") from exc

    return PdfText(path=path, pages=pages)


def _extract_pages(document: _PdfDocument) -> tuple[PdfPageText, ...]:
    pages: list[PdfPageText] = []
    for index, page in enumerate(document):
        raw = page.get_text("text")
        if not isinstance(raw, str):
            raise PdfTextError(f"PDF page {index + 1} did not yield text")
        pages.append(PdfPageText(number=index + 1, text=_clean_page_text(raw)))
    return tuple(pages)


def _clean_page_text(raw: str) -> str:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()
