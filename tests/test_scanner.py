"""Unit tests for recursive document discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from expense_auditor.documents.scanner import ScannedDocument, scan_documents
from expense_auditor.models import DocumentType


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("receipt.pdf", DocumentType.PDF),
        ("receipt.jpg", DocumentType.JPG),
        ("receipt.jpeg", DocumentType.JPEG),
        ("receipt.png", DocumentType.PNG),
    ],
)
def test_supported_extensions(tmp_path: Path, name: str, kind: DocumentType) -> None:
    path = tmp_path / name
    _touch(path)

    assert scan_documents(tmp_path) == (ScannedDocument(filepath=path, document_type=kind),)


def test_unsupported_extensions_are_ignored(tmp_path: Path) -> None:
    kept = tmp_path / "kept.png"
    _touch(kept)
    for name in ("notes.txt", "table.csv", "sheet.xlsx", "image.gif", "README", "scan.pdf.txt"):
        _touch(tmp_path / name)
    (tmp_path / "folder.pdf").mkdir()

    found = scan_documents(tmp_path)

    assert [item.filepath for item in found] == [kept]
    assert found[0].document_type is DocumentType.PNG


def test_nested_directories(tmp_path: Path) -> None:
    for name in ("outer.pdf", "sub/inner.jpg", "sub/deeper/leaf.png", "sub/deeper/skip.txt"):
        _touch(tmp_path / name)

    found = scan_documents(tmp_path)

    assert [item.filepath.relative_to(tmp_path).as_posix() for item in found] == [
        "outer.pdf",
        "sub/deeper/leaf.png",
        "sub/inner.jpg",
    ]


def test_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "empty-nested").mkdir()

    assert scan_documents(tmp_path) == ()


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Invoice.PDF", DocumentType.PDF),
        ("photo.Jpg", DocumentType.JPG),
        ("scan.JPEG", DocumentType.JPEG),
        ("image.PnG", DocumentType.PNG),
    ],
)
def test_case_insensitive_extensions(tmp_path: Path, name: str, kind: DocumentType) -> None:
    path = tmp_path / name
    _touch(path)

    assert scan_documents(tmp_path) == (ScannedDocument(filepath=path, document_type=kind),)


def test_deterministic_ordering(tmp_path: Path) -> None:
    for name in ("nested/c.png", "B.pdf", "a.jpg", "nested/A.jpeg"):
        _touch(tmp_path / name)

    expected = [
        "B.pdf",
        "a.jpg",
        "nested/A.jpeg",
        "nested/c.png",
    ]
    first = scan_documents(tmp_path)
    second = scan_documents(tmp_path)

    assert [item.filepath.relative_to(tmp_path).as_posix() for item in first] == expected
    assert second == first


def test_scan_does_not_change_file_contents(tmp_path: Path) -> None:
    path = tmp_path / "receipt.pdf"
    payload = b"%PDF-1.4 untouched"
    path.write_bytes(payload)
    modified_at = path.stat().st_mtime_ns

    found = scan_documents(tmp_path)

    assert [item.filepath for item in found] == [path]
    assert path.read_bytes() == payload
    assert path.stat().st_mtime_ns == modified_at


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        scan_documents(tmp_path / "missing")


def test_file_path_raises(tmp_path: Path) -> None:
    path = tmp_path / "receipt.pdf"
    _touch(path)

    with pytest.raises(NotADirectoryError):
        scan_documents(path)
