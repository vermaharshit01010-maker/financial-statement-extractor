"""Financial number parsing, display, and presentation-scale conversion."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from collections.abc import Iterable


SCALE_FACTORS = {
    "unit": Decimal("1"),
    "thousand": Decimal("1000"),
    "lakh": Decimal("100000"),
    "million": Decimal("1000000"),
    "crore": Decimal("10000000"),
    "billion": Decimal("1000000000"),
}


def as_decimal(value: object) -> Decimal | None:
    """Convert a numeric value to Decimal without reducing source precision."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    text = str(value).replace(",", "").replace("−", "-").strip()
    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = f"-{text[1:-1].strip()}"
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def preserve_unedited_decimal(
    original: Decimal | None, edited_value: object
) -> Decimal | None:
    """Keep source precision when the UI returns an unchanged numeric cell."""
    edited = as_decimal(edited_value)
    if original is None or edited is None:
        return edited
    if edited == original:
        return original
    try:
        if float(edited) == float(original):
            return original
    except (OverflowError, ValueError):
        pass
    return edited


def convert_display_scale(
    value: Decimal | None,
    source_scale: str | None,
    display_scale: str,
) -> Decimal | None:
    """Convert a source-unit Decimal for presentation without mutating it."""
    if value is None:
        return None
    if display_scale == "source":
        return value
    source_factor = SCALE_FACTORS.get(source_scale or "")
    target_factor = SCALE_FACTORS.get(display_scale)
    if source_factor is None or target_factor is None:
        return None
    return value * (source_factor / target_factor)


def decimal_places(value: Decimal) -> int:
    """Return the non-negative source precision represented by a Decimal."""
    return max(0, -value.as_tuple().exponent)


def format_financial_number(value: Decimal | None) -> str:
    """Render a number with grouping, source precision, and accounting negatives."""
    if value is None:
        return "—"
    places = decimal_places(value)
    rendered = f"{abs(value):,.{places}f}"
    if value.is_zero():
        return rendered
    return f"({rendered})" if value.is_signed() else rendered


def format_display_number(
    value: Decimal | None,
    source_scale: str | None,
    display_scale: str,
) -> str:
    converted = convert_display_scale(value, source_scale, display_scale)
    if converted is None and value is not None:
        return f"{format_financial_number(value)} (source scale unresolved)"
    return format_financial_number(converted)


def sort_numeric(
    values: Iterable[Decimal | None], reverse: bool = False
) -> list[Decimal | None]:
    """Sort numeric values numerically, keeping missing values at the end."""
    items = list(values)
    present = [value for value in items if value is not None]
    missing_count = len(items) - len(present)
    return sorted(present, reverse=reverse) + [None] * missing_count
