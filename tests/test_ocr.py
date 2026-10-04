"""Unit tests for local image OCR."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml
from PIL import Image, ImageDraw

from expense_auditor.documents.ocr import OcrError, extract_image_text

_SECRET = "SECRET-AMOUNT"


def _config(path: Path, language: str, supported: tuple[str, ...]) -> Path:
    languages = "\n".join(f"    - {code}" for code in supported)
    path.write_text(
        f"ocr:\n  language: {language}\n  supported_languages:\n{languages}\n",
        encoding="utf-8",
    )
    return path


def _write_image(path: Path, text: str | None = None) -> Path:
    image = Image.new("RGB", (80, 40), "white")
    if text is not None:
        ImageDraw.Draw(image).text((4, 8), text, fill="black")
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        image.save(path, format="JPEG")
    else:
        image.save(path, format="PNG")
    return path


@pytest.mark.parametrize("name", ["receipt.png", "receipt.jpg", "receipt.jpeg"])
def test_valid_image_returns_raw_ocr_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    path = _write_image(tmp_path / name, _SECRET)
    before = path.read_bytes()
    modified_at = path.stat().st_mtime_ns
    config_path = _config(tmp_path / "config.yaml", "eng", ("eng",))
    seen: dict[str, object] = {}

    def fake_ocr(image: Image.Image, lang: str = "", timeout: int = 0) -> str:
        seen["lang"] = lang
        seen["timeout"] = timeout
        seen["width"] = image.size[0]
        return "RAW TEXT\n"

    monkeypatch.setattr("expense_auditor.documents.ocr.pytesseract.image_to_string", fake_ocr)

    assert extract_image_text(path, config_path=config_path) == "RAW TEXT\n"
    assert seen == {"lang": "eng", "timeout": 30, "width": 160}
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified_at


def test_language_is_taken_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_image(tmp_path / "receipt.png")
    config_path = _config(tmp_path / "config.yaml", "deu", ("deu", "eng"))
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    (pack_dir / "deu.traineddata").write_bytes(b"traineddata")
    monkeypatch.setenv("EXPENSE_AUDITOR_TESSDATA", str(pack_dir))
    seen: dict[str, str] = {}

    def fake_ocr(image: Image.Image, lang: str = "", timeout: int = 0) -> str:
        del image, timeout
        seen["lang"] = lang
        return "OK"

    monkeypatch.setattr("expense_auditor.documents.ocr.pytesseract.image_to_string", fake_ocr)

    assert extract_image_text(path, config_path=config_path) == "OK"
    assert seen["lang"] == "deu"


def test_project_config_enables_latvian() -> None:
    config_path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    ocr = loaded["ocr"]
    assert isinstance(ocr, dict)
    assert "lav" in ocr["supported_languages"]
    assert "lav" in str(ocr["language"]).split("+")
    assert (config_path.parent.parent / "tessdata" / "lav.traineddata").is_file()


def test_language_outside_the_config_list_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_image(tmp_path / "receipt.png")
    config_path = _config(tmp_path / "config.yaml", "deu", ("eng",))

    def fake_ocr(image: Image.Image, lang: str = "", timeout: int = 0) -> str:
        del image, lang, timeout
        raise AssertionError("OCR should not run when the language is disabled")

    monkeypatch.setattr("expense_auditor.documents.ocr.pytesseract.image_to_string", fake_ocr)

    with pytest.raises(OcrError, match="OCR config is invalid"):
        extract_image_text(path, config_path=config_path)


def test_invalid_image_raises_without_logging_contents(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "broken.png"
    payload = b"SECRET-PIXELS-NOT-A-PNG"
    path.write_bytes(payload)
    modified_at = path.stat().st_mtime_ns

    with caplog.at_level(logging.ERROR), pytest.raises(OcrError, match="could not be opened"):
        extract_image_text(path, config_path=tmp_path / "missing-config.yaml")

    assert path.read_bytes() == payload
    assert path.stat().st_mtime_ns == modified_at
    assert "UnidentifiedImageError" in caplog.text
    assert "SECRET-PIXELS-NOT-A-PNG" not in caplog.text


@pytest.mark.parametrize("name", ["notes.txt", "scan.gif", "invoice.pdf"])
def test_unsupported_file_raises(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text("not an image", encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(OcrError, match="unsupported image type"):
        extract_image_text(path)

    assert path.read_bytes() == before


def test_empty_ocr_result_is_returned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_image(tmp_path / "blank.png")
    config_path = _config(tmp_path / "config.yaml", "eng", ("eng",))

    def fake_ocr(image: Image.Image, lang: str = "", timeout: int = 0) -> str:
        del image, lang, timeout
        return ""

    monkeypatch.setattr("expense_auditor.documents.ocr.pytesseract.image_to_string", fake_ocr)

    assert extract_image_text(path, config_path=config_path) == ""


def test_preprocessing_failure_is_logged_without_document_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = _write_image(tmp_path / "receipt.png", _SECRET)
    before = path.read_bytes()
    config_path = _config(tmp_path / "config.yaml", "eng", ("eng",))

    def fail_threshold(gray: object) -> object:
        del gray
        raise RuntimeError("threshold failed")

    monkeypatch.setattr("expense_auditor.documents.ocr._threshold", fail_threshold)

    with caplog.at_level(logging.ERROR), pytest.raises(OcrError, match="could not preprocess"):
        extract_image_text(path, config_path=config_path)

    assert path.read_bytes() == before
    assert "preprocessing failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert _SECRET not in caplog.text
    assert "threshold failed" not in caplog.text
