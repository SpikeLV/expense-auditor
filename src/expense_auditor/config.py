"""Load the local V0.1 configuration.

OCR-only files remain valid for the OCR loader. This module reads the
application sections: paths, matching, and OCR.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import BeforeValidator, Field, ValidationError, model_validator

from expense_auditor.documents.ocr import OcrSettings
from expense_auditor.models.base import DomainModel


class ConfigError(ValueError):
    """The application config could not be read."""


def _unit_threshold(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("threshold must be between 0 and 1")
    if isinstance(value, float) and math.isnan(value):
        raise ValueError("threshold must be between 0 and 1")
    threshold = float(value)
    if threshold < 0 or threshold > 1:
        raise ValueError("threshold must be between 0 and 1")
    return threshold


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("date tolerance must be a non-negative number of days")
    if value < 0:
        raise ValueError("date tolerance must be a non-negative number of days")
    return value


def _non_negative_decimal(value: object) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("amount tolerance must be Decimal, int, or str")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, str):
        try:
            amount = Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError("invalid amount tolerance") from exc
    elif isinstance(value, int):
        amount = Decimal(value)
    else:
        raise ValueError("amount tolerance must be Decimal, int, or str")
    if not amount.is_finite() or amount < 0:
        raise ValueError("amount tolerance must be a finite value of at least zero")
    return amount


def _config_path(value: object) -> Path:
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError("path must not be empty")
        return Path(raw)
    if isinstance(value, Path):
        return value
    raise ValueError("expected a filesystem path")


UnitThreshold = Annotated[float, BeforeValidator(_unit_threshold)]
NonNegativeInt = Annotated[int, BeforeValidator(_non_negative_int)]
NonNegativeDecimal = Annotated[Decimal, BeforeValidator(_non_negative_decimal)]
ConfigPath = Annotated[Path, BeforeValidator(_config_path)]


class PathSettings(DomainModel):
    """Directories used by the local pipeline."""

    data_root: ConfigPath
    reports_root: ConfigPath


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("expected a positive integer")
    return value


PositiveInt = Annotated[int, BeforeValidator(_positive_int)]


class ScoreWeights(DomainModel):
    """Fractions of the 0–1 match score. They must sum to 1."""

    amount: UnitThreshold
    currency: UnitThreshold
    merchant: UnitThreshold
    date: UnitThreshold
    reference: UnitThreshold

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> Self:
        total = self.amount + self.currency + self.merchant + self.date + self.reference
        if abs(total - 1.0) > 0.000001:
            raise ValueError("matching weights must sum to 1")
        return self


class DateBandSettings(DomainModel):
    """Date-distance bands inside ``date_tolerance_days``.

    A missing document date contributes no date evidence. A gap larger than
    ``date_tolerance_days`` is compared and then scores nothing.
    """

    strong_days: NonNegativeInt = 0
    close_days: NonNegativeInt = 1
    near_days: NonNegativeInt = 3
    same_day_score: UnitThreshold = 1.0
    close_score: UnitThreshold = 0.90
    near_score: UnitThreshold = 0.45
    outer_score: UnitThreshold = 0.20

    @model_validator(mode="after")
    def bands_are_ordered(self) -> Self:
        if not self.strong_days <= self.close_days <= self.near_days:
            raise ValueError("date bands must increase")
        return self


class MerchantBandSettings(DomainModel):
    """Merchant similarity bands and the cap for very short names."""

    strong: UnitThreshold = 0.90
    moderate: UnitThreshold = 0.70
    minimum_length: PositiveInt = 4
    short_cap: UnitThreshold = 0.35
    token_score: UnitThreshold = 0.95

    @model_validator(mode="after")
    def bands_are_ordered(self) -> Self:
        if self.moderate > self.strong:
            raise ValueError("moderate merchant band cannot exceed the strong band")
        if self.short_cap > self.moderate:
            raise ValueError("short merchant cap cannot exceed the moderate band")
        return self


class CombinationSettings(DomainModel):
    """Limits for documents that sum to one transaction."""

    enabled: bool = True
    max_documents: PositiveInt = 3
    pool_limit: PositiveInt = 12

    @model_validator(mode="after")
    def limits_are_safe(self) -> Self:
        if self.max_documents < 2 or self.max_documents > 5:
            raise ValueError("combination size must be from 2 to 5 documents")
        if self.pool_limit < self.max_documents:
            raise ValueError("combination pool must hold at least one full combination")
        return self


class MatchingSettings(DomainModel):
    """Thresholds and tolerances used by matching.

    Scoring code reads these values. It does not keep its own copies.
    ``amount_tolerance`` of zero means amounts must be equal.
    """

    confirmed_threshold: UnitThreshold
    probable_threshold: UnitThreshold
    date_tolerance_days: NonNegativeInt
    amount_tolerance: NonNegativeDecimal
    weights: ScoreWeights = Field(
        default_factory=lambda: ScoreWeights(
            amount=0.40,
            currency=0.15,
            merchant=0.25,
            date=0.10,
            reference=0.10,
        )
    )
    date_bands: DateBandSettings = Field(default_factory=DateBandSettings)
    merchant_bands: MerchantBandSettings = Field(default_factory=MerchantBandSettings)
    combination: CombinationSettings = Field(default_factory=CombinationSettings)
    reference_minimum_length: PositiveInt = 5

    @model_validator(mode="after")
    def thresholds_are_ordered(self) -> Self:
        if self.probable_threshold > self.confirmed_threshold:
            raise ValueError("probable threshold cannot exceed confirmed threshold")
        if self.date_bands.near_days > self.date_tolerance_days:
            raise ValueError("date bands must stay inside date_tolerance_days")
        amount_and_currency = self.weights.amount + self.weights.currency
        if amount_and_currency >= self.probable_threshold:
            raise ValueError("amount and currency alone must stay below the probable threshold")
        return self


class AppConfig(DomainModel):
    """The sections of config.yaml that V0.1 reads."""

    paths: PathSettings
    matching: MatchingSettings
    ocr: OcrSettings


def default_config_path() -> Path:
    """Return ``config/config.yaml`` from the working directory or the project."""
    cwd_config = Path.cwd() / "config" / "config.yaml"
    if cwd_config.is_file():
        return cwd_config
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "config.yaml"
        if candidate.is_file():
            return candidate
    raise ConfigError("config file was not found")


def load_matching_settings(config_path: Path | None = None) -> MatchingSettings:
    """Load the ``matching`` section."""
    loaded = _read_mapping(config_path or default_config_path())
    section = loaded.get("matching")
    if not isinstance(section, dict):
        raise ConfigError("matching config must be a mapping")
    try:
        return MatchingSettings.model_validate(section)
    except ValidationError as exc:
        raise ConfigError("matching config is invalid") from exc


def load_app_config(config_path: Path | None = None) -> AppConfig:
    """Load paths, matching, and OCR settings."""
    path = config_path or default_config_path()
    loaded = _read_mapping(path)
    try:
        return AppConfig.model_validate(
            {
                "paths": loaded.get("paths"),
                "matching": loaded.get("matching"),
                "ocr": OcrSettings.model_validate(loaded.get("ocr")),
            }
        )
    except (ValidationError, ValueError) as exc:
        raise ConfigError("application config is invalid") from exc


def _read_mapping(config_path: Path) -> dict[str, object]:
    if not config_path.is_file():
        raise ConfigError("config file was not found")
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError("config file could not be read") from exc
    if not isinstance(loaded, dict):
        raise ConfigError("config file must be a mapping")
    return loaded
