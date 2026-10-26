"""Basic review and consistency checks for historical financial figures."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from valuation_app.models import Candidate, ReviewedFigure
from valuation_app.numeric import as_decimal


REQUIRED_FIELDS = (
    "unit_scale",
    "currency",
    "reporting_period",
    "statement_type",
    "statement_scope",
)
ALLOWED_STATEMENTS = {
    "income_statement",
    "balance_sheet",
    "comprehensive_income",
    "changes_in_stockholders_equity",
    "cash_flow",
}
ALLOWED_SCOPES = {"consolidated", "standalone"}


def validate_fields(figure: Candidate | ReviewedFigure) -> list[str]:
    """Return blocking issues for required metadata and numeric values."""
    issues: list[str] = []
    for field_name in REQUIRED_FIELDS:
        if not str(getattr(figure, field_name, "") or "").strip():
            issues.append(f"{field_name.replace('_', ' ').capitalize()} is required.")
    raw_value = getattr(figure, "value", None)
    parsed_value = as_decimal(raw_value)
    if raw_value is None or raw_value == "":
        issues.append("Value is required.")
    elif parsed_value is None:
        issues.append("Value must be a valid number.")

    period = str(getattr(figure, "reporting_period", "") or "")
    if period and not any(character.isdigit() for character in period):
        issues.append("Reporting period must identify a year or date.")
    statement_type = getattr(figure, "statement_type", None)
    if statement_type and statement_type not in ALLOWED_STATEMENTS:
        issues.append("Statement type must be one of the supported financial statements.")
    statement_scope = getattr(figure, "statement_scope", None)
    if statement_scope and statement_scope not in ALLOWED_SCOPES:
        issues.append("Statement scope must be consolidated or standalone.")
    if getattr(figure, "source_page", 0) < 1:
        issues.append("Source page must be a positive page number.")
    return issues


def _decimal_value(figure: ReviewedFigure) -> Decimal | None:
    return as_decimal(figure.value)


def validate_approved_figures(figures: Iterable[ReviewedFigure]) -> list[str]:
    """Return visible, non-blocking cross-figure checks for approved records."""
    items = list(figures)
    warnings: list[str] = []
    duplicates: set[tuple[str, str, str, str]] = set()
    metadata_by_statement: dict[
        tuple[str, str, str], set[tuple[str | None, str]]
    ] = defaultdict(set)
    for figure in items:
        key = (
            figure.metric,
            figure.reporting_period,
            figure.statement_type,
            figure.statement_scope,
        )
        if key in duplicates:
            warnings.append(
                f"More than one approved {figure.metric} figure exists for "
                f"{figure.reporting_period} ({figure.statement_type}, "
                f"{figure.statement_scope}); review duplicates."
            )
        duplicates.add(key)

        value = _decimal_value(figure)
        if figure.metric == "total_assets" and value is not None and value < 0:
            warnings.append(
                f"Total assets on page {figure.source_page} are negative; verify the source."
            )
        metadata_by_statement[
            (figure.statement_type, figure.statement_scope, figure.reporting_period)
        ].add((figure.currency, figure.unit_scale or figure.unit))

    for (statement_type, scope, period), metadata in metadata_by_statement.items():
        currencies = {currency for currency, _scale in metadata}
        scales = {scale for _currency, scale in metadata}
        if len(currencies) > 1 or len(scales) > 1:
            warnings.append(
                f"Currency or unit scale is inconsistent within the {statement_type} "
                f"for {period} ({scope}); verify the source headings."
            )

    balance_sheet_groups: dict[
        tuple[str, str, str, str | None, str | None], dict[str, ReviewedFigure]
    ] = defaultdict(dict)
    cash_flow_groups: dict[
        tuple[str, str, str, str | None, str | None], dict[str, ReviewedFigure]
    ] = defaultdict(dict)
    for figure in items:
        group_key = (
            figure.reporting_period,
            figure.statement_scope,
            figure.statement_type,
            figure.currency,
            figure.unit_scale or figure.unit,
        )
        if figure.statement_type == "balance_sheet":
            balance_sheet_groups[group_key][figure.metric] = figure
        if figure.statement_type == "cash_flow":
            cash_flow_groups[group_key][figure.metric] = figure

    for key, matched in balance_sheet_groups.items():
        total_equity = matched.get("total_stockholders_equity") or matched.get("equity")
        if not total_equity or "total_assets" not in matched or "total_liabilities" not in matched:
            continue
        assets = _decimal_value(matched["total_assets"])
        liabilities = _decimal_value(matched["total_liabilities"])
        equity = _decimal_value(total_equity)
        if assets is None or liabilities is None or equity is None:
            continue
        if abs(assets - liabilities - equity) > Decimal("0.2"):
            warnings.append(
                f"Balance-sheet reconciliation difference for {key[0]} "
                f"({key[1]}): total assets do not equal total liabilities plus "
                "total stockholders' equity (tolerance: 0.2 unit)."
            )

    for key, matched in cash_flow_groups.items():
        components = (
            "operating_cash_flow",
            "investing_cash_flow",
            "financing_cash_flow",
            "exchange_rate_effect",
        )
        if all(metric in matched for metric in components + ("cash_change",)):
            component_values = [_decimal_value(matched[metric]) for metric in components]
            change = _decimal_value(matched["cash_change"])
            if change is not None and all(value is not None for value in component_values):
                component_total = sum(
                    value for value in component_values if value is not None
                )
                if abs(component_total - change) > Decimal("0.2"):
                    warnings.append(
                        f"Cash-flow component reconciliation difference for {key[0]} "
                        f"({key[1]}): operating, investing, financing, and FX flows "
                        "do not equal the reported cash change (tolerance: 0.2 unit)."
                    )

        roll_forward = (
            "cash_beginning_of_period",
            "cash_change",
            "cash_end_of_period",
        )
        if all(metric in matched for metric in roll_forward):
            beginning = _decimal_value(matched["cash_beginning_of_period"])
            change = _decimal_value(matched["cash_change"])
            ending = _decimal_value(matched["cash_end_of_period"])
            if beginning is None or change is None or ending is None:
                continue
            if abs(beginning + change - ending) > Decimal("0.2"):
                warnings.append(
                    f"Cash roll-forward difference for {key[0]} ({key[1]}): "
                    "beginning cash plus reported net change does not equal ending "
                    "cash (tolerance: 0.2 unit). FX is already included in net change."
                )

    by_key = {
        (
            figure.reporting_period,
            figure.unit_scale or figure.unit,
            figure.currency,
            figure.statement_scope,
        ): figure
        for figure in items
        if figure.statement_type == "income_statement"
    }
    required_metrics = ("revenue", "other_income", "total_expenses", "profit_before_tax")
    for key in by_key:
        matched: dict[str, ReviewedFigure] = {}
        for figure in items:
            if (
                figure.statement_type == "income_statement"
                and (
                    figure.reporting_period,
                    figure.unit_scale or figure.unit,
                    figure.currency,
                    figure.statement_scope,
                ) == key
                and figure.metric in required_metrics
            ):
                matched[figure.metric] = figure
        if all(metric in matched for metric in required_metrics):
            values = {
                metric: _decimal_value(matched[metric])
                for metric in required_metrics
            }
            revenue = values["revenue"]
            other_income = values["other_income"]
            total_expenses = values["total_expenses"]
            actual_pbt = values["profit_before_tax"]
            if (
                revenue is None
                or other_income is None
                or total_expenses is None
                or actual_pbt is None
            ):
                continue
            expected_pbt = revenue + other_income - total_expenses
            if abs(expected_pbt - actual_pbt) > Decimal("1"):
                warnings.append(
                    "Possible income-statement reconciliation difference for "
                    f"{key[0]}: revenue + other income - total expenses does not "
                    "match profit before tax (tolerance: 1 unit). Check the report's definitions."
                )
    return warnings
