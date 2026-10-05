"""Typed access to the PyMuPDF operations the SEB parser uses.

The installed PyMuPDF annotations do not cover every call this parser needs.
Those calls stay in this module.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

import pymupdf


class _Rect(Protocol):
    width: float
    height: float


class _Pixmap(Protocol):
    samples: bytes
    width: int
    height: int
    n: int


class PdfPage(Protocol):
    """One PDF page."""

    rect: _Rect

    def get_fonts(self) -> Sequence[Sequence[object]]: ...

    def get_texttrace(self) -> Sequence[Mapping[str, object]]: ...

    def get_pixmap(self, *, alpha: bool = False) -> _Pixmap: ...

    def insert_text(
        self,
        point: tuple[int, int],
        text: str,
        *,
        fontname: str,
        fontsize: int,
        color: tuple[int, int, int],
    ) -> object: ...

    def insert_font(
        self,
        *,
        fontname: str,
        fontbuffer: bytes | None = None,
        fontfile: str | None = None,
    ) -> object: ...

    def get_contents(self) -> Sequence[int]: ...


class PdfDocument(Protocol):
    """An open PDF."""

    needs_pass: int
    page_count: int

    def __iter__(self) -> Iterator[PdfPage]: ...

    def close(self) -> None: ...

    def extract_font(self, xref: int) -> tuple[object, object, object, object]: ...

    def xref_stream(self, xref: int) -> bytes: ...

    def update_stream(self, xref: int, data: bytes) -> None: ...

    def new_page(self, *, width: float, height: float) -> PdfPage: ...


class PdfFace(Protocol):
    """A decoded font face."""

    glyph_count: int

    def has_glyph(self, codepoint: int) -> int: ...


def open_document(path: Path) -> PdfDocument:
    """Open ``path`` for reading."""
    document = pymupdf.open(path)  # type: ignore[no-untyped-call]
    return cast(PdfDocument, document)


def blank_document() -> PdfDocument:
    """Open an empty in-memory PDF used to draw comparison glyphs."""
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    return cast(PdfDocument, document)


def face_from_buffer(font_bytes: bytes) -> PdfFace:
    """Load an embedded font."""
    face = pymupdf.Font(fontbuffer=font_bytes)  # type: ignore[no-untyped-call]
    return cast(PdfFace, face)


def face_from_file(path: str) -> PdfFace:
    """Load an installed font file."""
    face = pymupdf.Font(fontfile=path)  # type: ignore[no-untyped-call]
    return cast(PdfFace, face)
