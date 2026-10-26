import os
import hashlib
from pathlib import Path
from decimal import Decimal

import pytest

from valuation_app.extractor import extract_candidates_from_pdf
from valuation_app.models import ReviewedFigure
from valuation_app.validation import validate_approved_figures


@pytest.fixture(scope="module")
def verisk_candidates():
    source_path = os.environ.get("VERISK_10K_PDF")
    if not source_path:
        pytest.skip("Set VERISK_10K_PDF to run the source-document regression.")
    source = Path(source_path)
    source_bytes = source.read_bytes()
    return extract_candidates_from_pdf(
        source_bytes,
        source_document_id=hashlib.sha256(source_bytes).hexdigest(),
        source_pdf_filename=source.name,
    )


def _period_values(candidates, metric, source_page):
    return {
        candidate.reporting_period: candidate
        for candidate in candidates
        if candidate.metric == metric and candidate.source_page == source_page
    }


def test_verisk_cash_flow_values_metadata_and_source_pages(verisk_candidates):
    operating = _period_values(verisk_candidates, "operating_cash_flow", 66)
    assert {period: item.value for period, item in operating.items()} == {
        "2025": Decimal("1436.0"),
        "2024": Decimal("1144.0"),
        "2023": Decimal("1060.7"),
    }

    capex = _period_values(verisk_candidates, "capital_expenditure", 66)
    assert {period: item.value for period, item in capex.items()} == {
        "2025": Decimal("-244.1"),
        "2024": Decimal("-223.9"),
        "2023": Decimal("-230.0"),
    }
    assert {period: item.positive_magnitude for period, item in capex.items()} == {
        "2025": Decimal("244.1"),
        "2024": Decimal("223.9"),
        "2023": Decimal("230.0"),
    }

    ending_cash = _period_values(verisk_candidates, "cash_end_of_period", 67)
    assert {period: item.value for period, item in ending_cash.items()} == {
        "2025": Decimal("2178.2"),
        "2024": Decimal("291.2"),
        "2023": Decimal("302.7"),
    }

    for candidates in (operating.values(), capex.values(), ending_cash.values()):
        assert len(candidates) == 3
        for candidate in candidates:
            assert candidate.printed_page == candidate.source_page - 11
            assert candidate.statement_type == "cash_flow"
            assert candidate.statement_scope == "consolidated"
            assert candidate.currency == "USD"
            assert candidate.unit_scale == "million"
            assert candidate.source_statement.startswith(
                "CONSOLIDATED STATEMENTS OF CASH FLOWS"
            )
            assert candidate.source_row == candidate.source_text
            assert candidate.source_bbox is not None
            assert candidate.source_identity
            assert candidate.source_document_id
            assert candidate.source_pdf_filename
            assert candidate.source_column_header == candidate.reporting_period
            assert not candidate.warnings


def test_verisk_balance_sheet_metadata_and_reconciliation_rows(verisk_candidates):
    expected = {
        "total_assets": {"2025": Decimal("6195.5"), "2024": Decimal("4264.7")},
        "total_liabilities": {"2025": Decimal("5885.7"), "2024": Decimal("4159.7")},
        "total_stockholders_equity": {"2025": Decimal("309.8"), "2024": Decimal("105.0")},
    }
    for metric, expected_values in expected.items():
        actual = _period_values(verisk_candidates, metric, 62)
        assert {period: item.value for period, item in actual.items()} == expected_values
        for candidate in actual.values():
            assert candidate.printed_page == 51
            assert candidate.statement_type == "balance_sheet"
            assert candidate.statement_scope == "consolidated"
            assert candidate.currency == "USD"
            assert candidate.unit_scale == "million"
            assert candidate.unit_exception == "par value and number of shares"
            assert candidate.per_share_unit is None
            assert candidate.source_bbox is not None
            assert candidate.source_identity
            assert candidate.source_document_id
            assert candidate.source_pdf_filename
            assert candidate.source_column_header == candidate.reporting_period
            assert not candidate.warnings


def test_verisk_investment_income_is_not_misclassified_as_other_income(verisk_candidates):
    assert not any(
        candidate.metric == "other_income"
        and "investment income and others" in candidate.original_label.lower()
        for candidate in verisk_candidates
    )


def test_verisk_statement_reconciliations_pass_without_double_counting_fx(
    verisk_candidates,
):
    required_metrics = {
        "total_assets",
        "total_liabilities",
        "total_stockholders_equity",
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "exchange_rate_effect",
        "cash_change",
        "cash_beginning_of_period",
        "cash_end_of_period",
    }
    figures = [
        ReviewedFigure(
            candidate_id=item.candidate_id,
            metric=item.metric,
            original_label=item.original_label,
            value=item.value,
            unit=item.unit,
            currency=item.currency,
            reporting_period=item.reporting_period,
            statement_type=item.statement_type,
            source_page=item.source_page,
            source_text=item.source_text,
            statement_scope=item.statement_scope,
            unit_scale=item.unit_scale,
        )
        for item in verisk_candidates
        if item.metric in required_metrics and item.value is not None
    ]

    assert validate_approved_figures(figures) == []
