from decimal import Decimal

from valuation_app.models import ReviewedFigure
from valuation_app.numeric import (
    convert_display_scale,
    format_display_number,
    format_financial_number,
    preserve_unedited_decimal,
    sort_numeric,
)
from valuation_app.presentation import financial_results_frame


def make_figure(value, scale="thousand", **overrides):
    fields = {
        "candidate_id": str(value),
        "metric": "revenue",
        "original_label": "Revenue",
        "value": value,
        "unit": scale,
        "currency": "USD",
        "reporting_period": "2025",
        "statement_type": "income_statement",
        "source_page": 1,
        "source_text": f"Revenue {value}",
        "statement_scope": "consolidated",
        "unit_scale": scale,
    }
    fields.update(overrides)
    return ReviewedFigure(**fields)


def test_formatting_groups_and_parenthesizes_without_changing_decimal():
    value = Decimal("-108381.2500")

    assert format_financial_number(value) == "(108,381.2500)"
    assert value == Decimal("-108381.2500")


def test_display_conversion_keeps_source_scale_and_precision_unchanged():
    source_value = Decimal("1234.500")

    displayed = convert_display_scale(source_value, "thousand", "million")

    assert displayed == Decimal("1.234500")
    assert source_value == Decimal("1234.500")
    assert format_display_number(source_value, "thousand", "million") == "1.234500"


def test_unresolved_scale_does_not_guess_conversion():
    assert convert_display_scale(Decimal("1503149"), None, "million") is None
    assert (
        format_display_number(Decimal("1503149"), None, "million")
        == "1,503,149 (source scale unresolved)"
    )


def test_sorting_and_result_frame_use_numeric_decimal_values():
    values = [
        Decimal("100"),
        Decimal("20"),
        None,
        Decimal("-5"),
    ]
    assert sort_numeric(values) == [
        Decimal("-5"),
        Decimal("20"),
        Decimal("100"),
        None,
    ]
    assert sort_numeric(values, reverse=True) == [
        Decimal("100"),
        Decimal("20"),
        Decimal("-5"),
        None,
    ]

    frame = financial_results_frame(
        [
            make_figure(Decimal("20")),
            make_figure(Decimal("100")),
            make_figure(Decimal("5")),
        ]
    )
    sorted_frame = frame.sort_values("value")

    assert list(sorted_frame["value"]) == [
        Decimal("5"),
        Decimal("20"),
        Decimal("100"),
    ]
    assert all(isinstance(value, Decimal) for value in frame["value"])


def test_results_frame_labels_unresolved_source_scale_without_rescaling():
    figure = make_figure(
        Decimal("1500"),
        unit=None,
        unit_scale=None,
    )

    frame = financial_results_frame([figure])

    assert frame.loc[0, "value"] == Decimal("1500")
    assert frame.loc[0, "unit_scale"] == "unresolved source scale"


def test_thousand_and_million_views_are_consistent():
    value = Decimal("1500")
    assert convert_display_scale(value, "thousand", "million") == Decimal("1.500")
    assert convert_display_scale(value, "thousand", "thousand") == Decimal("1500")
    assert convert_display_scale(value, "million", "thousand") == Decimal("1500000")


def test_review_editor_round_trip_preserves_source_precision():
    source = Decimal("123456789012.3400")

    assert preserve_unedited_decimal(source, 123456789012.34) == source
    assert preserve_unedited_decimal(source, "123456789012.35") == Decimal(
        "123456789012.35"
    )
    assert preserve_unedited_decimal(None, "") is None


def test_numeric_sort_accepts_iterators():
    values = iter([Decimal("100"), None, Decimal("20")])

    assert sort_numeric(values) == [Decimal("20"), Decimal("100"), None]
