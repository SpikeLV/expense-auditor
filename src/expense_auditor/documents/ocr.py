"""Local Tesseract OCR for photographed receipts.

The module returns raw text. It does not interpret merchants, amounts, or dates.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Self

import cv2
import numpy as np
import pytesseract
import yaml
from numpy.typing import NDArray
from PIL import Image
from pydantic import ValidationError, model_validator

from expense_auditor.models.base import DomainModel
from expense_auditor.models.document import DocumentType

logger = logging.getLogger(__name__)

_LANGUAGE_CODE = re.compile(r"^[a-z]{3}$")
_UPSCALE_LIMIT = 1600
_UPSCALE_FACTOR = 2
_THRESHOLD_BLOCK = 31
_OCR_TIMEOUT_SECONDS = 30

_SUPPORTED_SUFFIXES = frozenset(
    {
        f".{DocumentType.JPG.value}",
        f".{DocumentType.JPEG.value}",
        f".{DocumentType.PNG.value}",
    }
)

GrayImage = NDArray[np.uint8]


class OcrError(Exception):
    """The image could not be read as text."""


class OcrSettings(DomainModel):
    """Tesseract language settings loaded from config.yaml."""

    language: str
    supported_languages: tuple[str, ...]

    @model_validator(mode="before")
    @classmethod
    def normalize_codes(cls, data: object) -> object:
        if not isinstance(data, dict):
            raise ValueError("OCR settings must be a mapping")
        raw_language = data.get("language")
        raw_supported = data.get("supported_languages")
        if not isinstance(raw_language, str) or not isinstance(raw_supported, list | tuple):
            raise ValueError("OCR settings require language and supported_languages")
        if not raw_supported:
            raise ValueError("supported_languages must not be empty")
        supported = tuple(_required_code(item) for item in raw_supported)
        language = "+".join(_language_codes(raw_language))
        return {"language": language, "supported_languages": supported}

    @model_validator(mode="after")
    def language_is_enabled(self) -> Self:
        allowed = set(self.supported_languages)
        missing = [code for code in self.language.split("+") if code not in allowed]
        if missing:
            raise ValueError("OCR language is not enabled in config")
        return self


def extract_image_text(path: Path, *, config_path: Path | None = None) -> str:
    """Return raw Tesseract text for a JPG, JPEG, or PNG file.

    The language comes from ``config.yaml``. Blank and image-only results are
    returned as raw text, including an empty string. The source file is not
    modified.
    """
    if not path.exists():
        raise FileNotFoundError(f"image does not exist: {path}")
    if not path.is_file():
        raise IsADirectoryError(f"image path is not a file: {path}")
    suffix = path.suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        logger.warning("unsupported image suffix=%s", suffix or "(none)")
        raise OcrError(f"unsupported image type: {suffix or '(none)'}")

    image = _open_image(path)
    settings = _load_ocr_settings(config_path or _default_config_path())
    try:
        prepared = _preprocess(image)
    except OcrError:
        raise
    except Exception as exc:
        _log_failure("preprocessing failed", path, exc)
        raise OcrError(f"could not preprocess image: {path.name}") from exc

    executable = _tesseract_executable()
    tessdata_dir = _prepare_languages(executable, settings.language)
    previous_tessdata = os.environ.get("TESSDATA_PREFIX")
    if tessdata_dir is not None:
        os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
    try:
        raw = pytesseract.image_to_string(
            prepared,
            lang=settings.language,
            timeout=_OCR_TIMEOUT_SECONDS,
        )
    except pytesseract.TesseractNotFoundError as exc:
        _log_failure("Tesseract is not available", path, exc)
        raise OcrError("Tesseract OCR is not available") from exc
    except Exception as exc:
        _log_failure("Tesseract failed", path, exc)
        raise OcrError(f"OCR failed: {path.name}") from exc
    finally:
        if tessdata_dir is not None:
            if previous_tessdata is None:
                os.environ.pop("TESSDATA_PREFIX", None)
            else:
                os.environ["TESSDATA_PREFIX"] = previous_tessdata
    if not isinstance(raw, str):
        _log_failure("Tesseract returned an unexpected result", path, TypeError(type(raw).__name__))
        raise OcrError(f"OCR failed: {path.name}")
    return raw


def _required_code(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("supported language codes must be three letters")
    return _one_code(value)


def _one_code(value: str) -> str:
    code = value.strip().lower()
    if _LANGUAGE_CODE.fullmatch(code) is None:
        raise ValueError("OCR language codes must be three letters")
    return code


def _language_codes(language: str) -> tuple[str, ...]:
    parts = tuple(part.strip().lower() for part in language.split("+"))
    if not parts or any(_LANGUAGE_CODE.fullmatch(part) is None for part in parts):
        raise ValueError("OCR language must be three-letter codes joined by +")
    return parts


def _default_config_path() -> Path:
    cwd_config = Path.cwd() / "config" / "config.yaml"
    if cwd_config.is_file():
        return cwd_config
    project_config = Path(__file__).resolve().parents[3] / "config" / "config.yaml"
    if project_config.is_file():
        return project_config
    raise OcrError("OCR config file was not found")


def _load_ocr_settings(config_path: Path) -> OcrSettings:
    if not config_path.is_file():
        raise OcrError("OCR config file was not found")
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        _log_failure("OCR config could not be read", config_path, exc)
        raise OcrError("OCR config could not be read") from exc
    if not isinstance(loaded, dict):
        raise OcrError("OCR config must be a mapping")
    section = loaded.get("ocr")
    if not isinstance(section, dict):
        raise OcrError("OCR config is missing the ocr section")
    try:
        return OcrSettings.model_validate(section)
    except ValidationError as exc:
        _log_failure("OCR config is invalid", config_path, exc)
        raise OcrError("OCR config is invalid") from exc


def _open_image(path: Path) -> Image.Image:
    try:
        with Image.open(path) as image:
            image.load()
            return image.copy()
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        _log_failure("image could not be opened", path, exc)
        raise OcrError(f"image could not be opened: {path.name}") from exc


def _preprocess(image: Image.Image) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    gray = _as_gray(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
    gray = _upscale(gray)
    gray = _denoise(gray)
    return Image.fromarray(_threshold(gray))


def _upscale(gray: GrayImage) -> GrayImage:
    height, width = gray.shape[:2]
    if max(height, width) >= _UPSCALE_LIMIT:
        return gray
    resized = cv2.resize(
        gray,
        None,
        fx=_UPSCALE_FACTOR,
        fy=_UPSCALE_FACTOR,
        interpolation=cv2.INTER_CUBIC,
    )
    return _as_gray(resized)


def _denoise(gray: GrayImage) -> GrayImage:
    if min(gray.shape[:2]) < 3:
        return gray
    return _as_gray(cv2.medianBlur(gray, 3))


def _threshold(gray: GrayImage) -> GrayImage:
    short_side = min(int(gray.shape[0]), int(gray.shape[1]))
    if short_side <= _THRESHOLD_BLOCK:
        _ignored, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return _as_gray(binary)
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        _THRESHOLD_BLOCK,
        11,
    )
    return _as_gray(binary)


def _as_gray(value: object) -> GrayImage:
    array = np.asarray(value, dtype=np.uint8)
    if array.ndim != 2:
        raise OcrError("preprocessed image was not grayscale")
    return array


def _tesseract_executable() -> Path | None:
    configured = os.environ.get("TESSERACT_CMD", "").strip()
    if configured:
        pytesseract.pytesseract.tesseract_cmd = configured
        path = Path(configured)
        return path if path.is_file() else None
    found = shutil.which("tesseract")
    if found:
        pytesseract.pytesseract.tesseract_cmd = found
        return Path(found)
    for candidate in _tesseract_candidates():
        if candidate.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return candidate
    return None


def _prepare_languages(executable: Path | None, language: str) -> Path | None:
    """Return a tessdata directory when the Tesseract install lacks a language.

    ``None`` means the install already contains every requested language.
    """
    if executable is None:
        return None
    codes = tuple(language.split("+"))
    system_dir = executable.parent / "tessdata"
    if all((system_dir / f"{code}.traineddata").is_file() for code in codes):
        return None
    runtime_dir = _runtime_tessdata_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for code in codes:
        filename = f"{code}.traineddata"
        source = _find_traineddata(filename, system_dir)
        if source is None:
            raise OcrError(f"Tesseract language data is not installed: {code}")
        target = runtime_dir / filename
        if not target.is_file() or source.stat().st_mtime_ns > target.stat().st_mtime_ns:
            shutil.copyfile(source, target)
    return runtime_dir


def _find_traineddata(filename: str, system_dir: Path) -> Path | None:
    for directory in (system_dir, *_extra_tessdata_dirs()):
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


def _extra_tessdata_dirs() -> tuple[Path, ...]:
    found: list[Path] = []
    env_dir = os.environ.get("EXPENSE_AUDITOR_TESSDATA", "").strip()
    if env_dir:
        found.append(Path(env_dir))
    found.append(Path.cwd() / "tessdata")
    found.append(Path(__file__).resolve().parents[3] / "tessdata")
    unique: list[Path] = []
    for directory in found:
        resolved = directory.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return tuple(unique)


def _runtime_tessdata_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home()
    return base / "expense-auditor" / "tessdata"


def _tesseract_candidates() -> tuple[Path, ...]:
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(program_files) / "Tesseract-OCR" / "tesseract.exe",
        Path(program_files_x86) / "Tesseract-OCR" / "tesseract.exe",
    ]
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    return tuple(candidates)


def _log_failure(action: str, path: Path, exc: BaseException) -> None:
    logger.error(
        "%s suffix=%s error=%s",
        action,
        path.suffix.lower() or "(none)",
        type(exc).__name__,
    )
