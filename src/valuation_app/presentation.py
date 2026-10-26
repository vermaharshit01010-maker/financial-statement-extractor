"""Read-only financial result-table data with display-only unit conversion."""

from __future__ import annotations

import pandas as pd

from valuation_app.models import Candidate, ReviewedFigure
from valuation_app.numeric import SCALE_FACTORS, convert_display_scale


def financial_results_frame(
    figures: list[Candidate] | list[ReviewedFigure],
    display_scale: str = "source",
) -> pd.DataFrame:
    """Build a numerically typed table; formatting is applied only by the UI."""
    rows = []
    for figure in figures:
        scale = figure.unit_scale or figure.unit
        converted_value = convert_display_scale(
            figure.value,
            scale,
            display_scale,
        )
        scale_was_converted = (
            display_scale == "source"
            or (scale in SCALE_FACTORS and display_scale in SCALE_FACTORS)
        )
        rows.append(
            {
                "metric": figure.metric,
                "original_label": figure.original_label,
                "value": converted_value if scale_was_converted else figure.value,
                "currency": figure.currency,
                "unit_scale": (
                    scale or "unresolved source scale"
                    if display_scale == "source"
                    else display_scale if scale_was_converted else "unresolved source scale"
                ),
                "source_column_header": figure.source_column_header,
                "reporting_period": figure.reporting_period,
                "statement_type": figure.statement_type,
                "statement_scope": figure.statement_scope,
                "physical_pdf_page": figure.source_page,
                "printed_page": figure.printed_page,
                "extraction_status": getattr(
                    figure, "extraction_status", "extracted"
                ),
                "source_verification_status": getattr(
                    figure, "source_verification_status", "unverified"
                ),
            }
        )
    return pd.DataFrame(rows)
