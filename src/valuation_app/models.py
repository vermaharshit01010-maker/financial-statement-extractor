"""Data records used by extraction, review, and export."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from valuation_app.numeric import as_decimal


@dataclass
class Candidate:
    candidate_id: str
    metric: str
    original_label: str
    value: Decimal | None
    unit: str | None
    currency: str | None
    reporting_period: str | None
    statement_type: str | None
    source_page: int
    source_text: str
    statement_scope: str | None = None
    warnings: list[str] = field(default_factory=list)
    unit_scale: str | None = None
    per_share_unit: str | None = None
    unit_exception: str | None = None
    source_statement: str | None = None
    printed_page: int | None = None
    source_row: str | None = None
    source_bbox: tuple[float, float, float, float] | None = None
    source_identity: str | None = None
    source_value: Decimal | None = None
    positive_magnitude: Decimal | None = None
    source_document_id: str | None = None
    source_pdf_filename: str | None = None
    source_column_header: str | None = None
    extraction_version: int = 1
    extraction_status: str = "pending"
    source_verification_status: str = "unverified"

    def __post_init__(self) -> None:
        self.value = as_decimal(self.value)
        self.source_value = as_decimal(self.source_value)
        self.positive_magnitude = as_decimal(self.positive_magnitude)
        if self.unit_scale is None and self.unit:
            self.unit_scale = None if self.unit.lower() == "rupees" else self.unit
        if self.unit_scale is not None:
            self.unit = self.unit_scale
        if self.unit == "rupees":
            self.unit = None
            warning = (
                "Legacy unit metadata 'rupees' does not identify a numeric scale; "
                "verify the source heading before approval."
            )
            if warning not in self.warnings:
                self.warnings.append(warning)
        if self.extraction_status == "pending":
            required_context = (
                self.value,
                self.unit_scale,
                self.currency,
                self.reporting_period,
                self.statement_type,
                self.statement_scope,
            )
            self.extraction_status = (
                "extracted" if all(item not in (None, "") for item in required_context) else "needs_review"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Candidate":
        values = dict(data)
        if values.get("unit") == "rupees" and "unit_scale" not in values:
            values["unit"] = None
            warning = (
                "Legacy unit metadata 'rupees' does not identify a numeric scale; "
                "verify the source heading before approval."
            )
            values["warnings"] = list(values.get("warnings", []))
            if warning not in values["warnings"]:
                values["warnings"].append(warning)
        if values.get("source_bbox") is not None:
            values["source_bbox"] = tuple(values["source_bbox"])
        return cls(**values)


@dataclass
class ReviewedFigure:
    candidate_id: str
    metric: str
    original_label: str
    value: Decimal | None
    unit: str
    currency: str
    reporting_period: str
    statement_type: str
    source_page: int
    source_text: str
    statement_scope: str
    review_status: str = "approved"
    warnings: list[str] = field(default_factory=list)
    unit_scale: str | None = None
    per_share_unit: str | None = None
    unit_exception: str | None = None
    source_statement: str | None = None
    printed_page: int | None = None
    source_row: str | None = None
    source_bbox: tuple[float, float, float, float] | None = None
    source_identity: str | None = None
    source_value: Decimal | None = None
    positive_magnitude: Decimal | None = None
    source_document_id: str | None = None
    source_pdf_filename: str | None = None
    source_column_header: str | None = None
    extraction_version: int = 1
    source_verification_status: str = "unverified"
    extraction_status: str = "extracted"

    def __post_init__(self) -> None:
        self.value = as_decimal(self.value)
        self.source_value = as_decimal(self.source_value)
        self.positive_magnitude = as_decimal(self.positive_magnitude)
        if self.unit_scale is None and self.unit:
            self.unit_scale = None if self.unit.lower() == "rupees" else self.unit
        if self.unit_scale is not None:
            self.unit = self.unit_scale
        if self.unit == "rupees":
            self.unit = None
            warning = (
                "Legacy unit metadata 'rupees' does not identify a numeric scale; "
                "verify the source heading before approval."
            )
            if warning not in self.warnings:
                self.warnings.append(warning)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewedFigure":
        values = dict(data)
        if values.get("unit") == "rupees" and "unit_scale" not in values:
            values["unit"] = None
            warning = (
                "Legacy unit metadata 'rupees' does not identify a numeric scale; "
                "verify the source heading before approval."
            )
            values["warnings"] = list(values.get("warnings", []))
            if warning not in values["warnings"]:
                values["warnings"].append(warning)
        if values.get("source_bbox") is not None:
            values["source_bbox"] = tuple(values["source_bbox"])
        return cls(**values)
