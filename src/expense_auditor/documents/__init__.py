"""Supporting-document discovery and text extraction."""

from expense_auditor.documents.ocr import OcrError, extract_image_text
from expense_auditor.documents.pdf_parser import (
    PdfPageText,
    PdfText,
    PdfTextError,
    extract_pdf_text,
)
from expense_auditor.documents.scanner import SUPPORTED_SUFFIXES, ScannedDocument, scan_documents

__all__ = [
    "SUPPORTED_SUFFIXES",
    "OcrError",
    "PdfPageText",
    "PdfText",
    "PdfTextError",
    "ScannedDocument",
    "extract_image_text",
    "extract_pdf_text",
    "scan_documents",
]
