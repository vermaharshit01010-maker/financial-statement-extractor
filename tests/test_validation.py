from valuation_app.models import ReviewedFigure
from valuation_app.validation import validate_approved_figures, validate_fields


def make_figure(metric, value, **overrides):
    fields = {
        "candidate_id": metric,
        "metric": metric,
        "original_label": metric,
        "value": value,
        "unit": "crore",
        "currency": "INR",
        "reporting_period": "2025",
        "statement_type": "income_statement",
        "source_page": 3,
        "source_text": f"{metric} {value}",
        "statement_scope": "consolidated",
    }
    fields.update(overrides)
    return ReviewedFigure(**fields)


def test_required_metadata_and_numeric_value_are_checked():
    figure = make_figure("revenue", None, unit="")

    errors = validate_fields(figure)

    assert "Unit scale is required." in errors
    assert "Value is required." in errors


def test_reconciliation_warning_is_reported_for_same_period_and_unit():
    figures = [
        make_figure("revenue", "100"),
        make_figure("other_income", "5"),
        make_figure("total_expenses", "80"),
        make_figure("profit_before_tax", "30"),
    ]

    warnings = validate_approved_figures(figures)

    assert any("reconciliation difference" in warning for warning in warnings)


def test_matching_profit_before_tax_passes_reconciliation():
    figures = [
        make_figure("revenue", "100"),
        make_figure("other_income", "5"),
        make_figure("total_expenses", "80"),
        make_figure("profit_before_tax", "25"),
    ]

    assert validate_approved_figures(figures) == []


def test_balance_sheet_reconciliation_matches_verisk_values():
    figures = [
        make_figure(
            "total_assets",
            "6195.5",
            statement_type="balance_sheet",
            unit="million",
            currency="USD",
        ),
        make_figure(
            "total_liabilities",
            "5885.7",
            statement_type="balance_sheet",
            unit="million",
            currency="USD",
        ),
        make_figure(
            "total_stockholders_equity",
            "309.8",
            statement_type="balance_sheet",
            unit="million",
            currency="USD",
        ),
    ]

    assert validate_approved_figures(figures) == []


def test_cash_flow_reconciliation_includes_exchange_effect_once():
    figures = [
        make_figure("operating_cash_flow", "1436.0", statement_type="cash_flow", unit="million", currency="USD"),
        make_figure("investing_cash_flow", "-358.1", statement_type="cash_flow", unit="million", currency="USD"),
        make_figure("financing_cash_flow", "795.2", statement_type="cash_flow", unit="million", currency="USD"),
        make_figure("exchange_rate_effect", "13.9", statement_type="cash_flow", unit="million", currency="USD"),
        make_figure("cash_change", "1887.0", statement_type="cash_flow", unit="million", currency="USD"),
        make_figure("cash_beginning_of_period", "291.2", statement_type="cash_flow", unit="million", currency="USD"),
        make_figure("cash_end_of_period", "2178.2", statement_type="cash_flow", unit="million", currency="USD"),
    ]

    assert validate_approved_figures(figures) == []


def test_reports_balance_sheet_reconciliation_difference():
    figures = [
        make_figure("total_assets", "6195.5", statement_type="balance_sheet"),
        make_figure("total_liabilities", "5885.7", statement_type="balance_sheet"),
        make_figure("total_stockholders_equity", "300.0", statement_type="balance_sheet"),
    ]

    warnings = validate_approved_figures(figures)

    assert any("Balance-sheet reconciliation difference" in warning for warning in warnings)


def test_reports_inconsistent_currency_and_scale_within_statement():
    figures = [
        make_figure("total_assets", "100", statement_type="balance_sheet", unit="million", currency="USD"),
        make_figure("total_liabilities", "80", statement_type="balance_sheet", unit="thousand", currency="USD"),
    ]

    warnings = validate_approved_figures(figures)

    assert any("Currency or unit scale is inconsistent" in warning for warning in warnings)
