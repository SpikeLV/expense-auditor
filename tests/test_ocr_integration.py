"""Integration test for local Tesseract OCR on a generated image."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from expense_auditor.documents.ocr import extract_image_text


def test_generated_image_text_is_read(tmp_path: Path) -> None:
    path = tmp_path / "hello.png"
    image = Image.new("RGB", (900, 240), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=96)
    draw.text((40, 60), "HELLO", fill="black", font=font)
    image.save(path)
    before = path.read_bytes()
    modified_at = path.stat().st_mtime_ns

    extracted = extract_image_text(path)

    assert "HELLO" in extracted
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified_at
