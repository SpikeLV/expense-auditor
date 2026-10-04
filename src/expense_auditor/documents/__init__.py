"""Supporting-document discovery and text extraction."""

from expense_auditor.documents.pdf_parser import (
    PdfPageText,
    PdfText,
    PdfTextError,
    extract_pdf_text,
)
from expense_auditor.documents.scanner import SUPPORTED_SUFFIXES, ScannedDocument, scan_documents

__all__ = [
    "SUPPORTED_SUFFIXES",
    "PdfPageText",
    "PdfText",
    "PdfTextError",
    "ScannedDocument",
    "extract_pdf_text",
    "scan_documents",
]
