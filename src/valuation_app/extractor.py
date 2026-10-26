"""Deterministic, layout-aware extraction from digital annual-report PDFs."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any

import fitz

from valuation_app.models import Candidate


EXTRACTION_VERSION = 2


METRIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "revenue",
        re.compile(
            r"^(?:revenue from operations|revenue from contracts with customers|"
            r"revenue from sale of products and services|revenue from sale of products|"
            r"revenue from services|revenue from operations and other income)$",
            re.IGNORECASE,
        ),
    ),
    ("other_income", re.compile(r"^other income$", re.IGNORECASE)),
    ("total_expenses", re.compile(r"^total expenses$", re.IGNORECASE)),
    (
        "profit_before_tax",
        re.compile(r"^(?:profit|loss) before tax(?:ation)?$", re.IGNORECASE),
    ),
    ("tax_expense", re.compile(r"^tax expense(?:/(?:benefit|credit))?$", re.IGNORECASE)),
    (
        "profit_after_tax",
        re.compile(
            r"^(?:profit|loss) for the (?:year|period)|"
            r"^(?:net profit|profit after tax)(?: for the (?:year|period))?$",
            re.IGNORECASE,
        ),
    ),
    ("total_assets", re.compile(r"^total assets$", re.IGNORECASE)),
    ("total_liabilities", re.compile(r"^total liabilities$", re.IGNORECASE)),
    (
        "total_stockholders_equity",
        re.compile(r"^total stockholders['’] equity$", re.IGNORECASE),
    ),
    (
        "equity",
        re.compile(
            r"^(?:total equity|total equity and liabilities attributable to owners|"
            r"equity attributable to owners of the parent)$",
            re.IGNORECASE,
        ),
    ),
    ("borrowings", re.compile(r"^total borrowings$", re.IGNORECASE)),
    (
        "cash_and_cash_equivalents",
        re.compile(r"^(?:cash and cash equivalents|cash equivalents)$", re.IGNORECASE),
    ),
    (
        "operating_cash_flow",
        re.compile(
            r"^(?:net cash (?:provided by|generated from|from|used in) "
            r"operating activities)$",
            re.IGNORECASE,
        ),
    ),
    (
        "capital_expenditure",
        re.compile(
            r"^(?:purchase of property, plant and equipment|"
            r"purchase of property plant and equipment|"
            r"purchase of property, plant and equipment and intangible assets|"
            r"capital expenditure|capital expenditures)$",
            re.IGNORECASE,
        ),
    ),
    (
        "investing_cash_flow",
        re.compile(
            r"^net cash \(used in\) provided by investing activities$",
            re.IGNORECASE,
        ),
    ),
    (
        "financing_cash_flow",
        re.compile(
            r"^net cash provided by \(used in\) financing activities$",
            re.IGNORECASE,
        ),
    ),
    (
        "exchange_rate_effect",
        re.compile(r"^effect of exchange rate changes$", re.IGNORECASE),
    ),
    (
        "cash_change",
        re.compile(
            r"^increase \(decrease\) in cash and cash equivalents$",
            re.IGNORECASE,
        ),
    ),
    (
        "cash_beginning_of_period",
        re.compile(
            r"^cash and cash equivalents, beginning of period$", re.IGNORECASE
        ),
    ),
    (
        "cash_end_of_period",
        re.compile(
            r"^cash and cash equivalents, end of period$", re.IGNORECASE
        ),
    ),
)

NUMBER_TOKEN_RE = re.compile(r"\(?[+-]?\d[\d,]*(?:\.\d+)?\)?")
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?:\s*[-–/]\s*(\d{2,4}))?(?!\d)")
PERIOD_YEAR_RE = re.compile(
    r"(?:\b(?:financial\s+)?(?:year|period)\s+ended\b|\bas\s+at\b|\bas\s+of\b)"
    r"[^\n]{0,50}?\b((?:19|20)\d{2})\b",
    re.IGNORECASE,
)
UNIT_SCALE_PATTERNS = (
    (re.compile(r"\b(?:in\s+)?crores?\b|\bin\s+cr\.?\b", re.IGNORECASE), "crore"),
    (re.compile(r"\b(?:in\s+)?(?:lakhs?|lacs?)\b", re.IGNORECASE), "lakh"),
    (re.compile(r"\b(?:in\s+)?millions?\b|\bin\s+mn\b", re.IGNORECASE), "million"),
    (re.compile(r"\b(?:in\s+)?billions?\b|\bin\s+bn\b", re.IGNORECASE), "billion"),
    (re.compile(r"\b(?:in\s+)?thousands?\b|\bin\s+000s?\b", re.IGNORECASE), "thousand"),
    (re.compile(r"\bin\s+(?:rupees?|dollars?)\b", re.IGNORECASE), "unit"),
)


@dataclass(frozen=True)
class PDFPageText:
    """Page text with the positioned words needed for table-column matching."""

    text: str
    words: tuple[tuple[Any, ...], ...]
    page_height: float | None = None


@dataclass(frozen=True)
class _Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def x_center(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def y_center(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class _Line:
    words: tuple[_Word, ...]

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def x0(self) -> float:
        return min(word.x0 for word in self.words)

    @property
    def y0(self) -> float:
        return min(word.y0 for word in self.words)

    @property
    def y1(self) -> float:
        return max(word.y1 for word in self.words)

    @property
    def y_center(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(frozen=True)
class _PeriodAnchor:
    period: str
    x_center: float
    source_header: str


@dataclass(frozen=True)
class _NumericCell:
    value: Decimal
    x_center: float


def extract_pdf_pages(pdf_bytes: bytes) -> list[PDFPageText]:
    """Return text plus word coordinates for every page in a digital PDF."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        return [
            PDFPageText(
                text=page.get_text("text"),
                words=tuple(page.get_text("words", sort=True)),
                page_height=float(page.rect.height),
            )
            for page in document
        ]


def _text_page_words(page_text: str) -> tuple[_Word, ...]:
    """Create approximate coordinates for text fixtures and legacy callers."""
    words: list[_Word] = []
    for line_number, line in enumerate(page_text.splitlines()):
        for match in re.finditer(r"\S+", line):
            x0 = float(match.start() * 5)
            x1 = float(match.end() * 5)
            y0 = float(line_number * 12)
            words.append(_Word(x0, y0, x1, y0 + 9, match.group(0)))
    return tuple(words)


def _make_lines(words: Iterable[tuple[Any, ...] | _Word]) -> list[_Line]:
    positioned_words: list[_Word] = []
    for item in words:
        if isinstance(item, _Word):
            positioned_words.append(item)
        else:
            x0, y0, x1, y1, text = item[:5]
            positioned_words.append(_Word(float(x0), float(y0), float(x1), float(y1), str(text)))
    positioned_words.sort(key=lambda word: (word.y_center, word.x0))

    clusters: list[list[_Word]] = []
    for word in positioned_words:
        if not clusters:
            clusters.append([word])
            continue
        current_center = median(item.y_center for item in clusters[-1])
        current_height = max(item.y1 - item.y0 for item in clusters[-1])
        tolerance = max(2.5, min(current_height, word.y1 - word.y0) * 0.35)
        if abs(word.y_center - current_center) <= tolerance:
            clusters[-1].append(word)
        else:
            clusters.append([word])

    lines = [
        _Line(tuple(sorted(cluster, key=lambda word: word.x0)))
        for cluster in clusters
    ]
    return sorted(lines, key=lambda line: (line.y_center, line.x0))


def _metric_expression(pattern: re.Pattern[str]) -> re.Pattern[str]:
    expression = pattern.pattern.removeprefix("^").removesuffix("$")
    return re.compile(rf"^(?:{expression})(?=$|\s|[:：])", re.IGNORECASE)


def _looks_like_value_tail(tail: str) -> bool:
    tokens = tail.split()
    while tokens and tokens[0].lower().rstrip(".") in {"$", "₹", "usd", "inr", "rs"}:
        tokens.pop(0)
    while tokens and tokens[0] in {"(", "-(", "−("}:
        tokens.pop(0)
    if not tokens:
        return False
    token = tokens[0].replace("−", "-").strip(",;:")
    return token in {"-", "—", "–"} or NUMBER_TOKEN_RE.fullmatch(token) is not None


def _match_label(text: str) -> tuple[str, str, str] | None:
    cleaned = re.sub(r"\s+", " ", text).strip()
    for metric, pattern in METRIC_PATTERNS:
        match = _metric_expression(pattern).match(cleaned)
        if match is None:
            continue
        tail = cleaned[match.end() :].strip(" \t:：·.")
        if tail and not _looks_like_value_tail(tail):
            continue
        label = match.group(0).strip(" :：.")
        return label, tail, metric
    return None


def _statement_type_for_heading(heading: str) -> str | None:
    text = re.sub(r"\s+", " ", heading.lower())
    company_scope = r"(?:(?:consolidated|standalone|stand[- ]alone)\s+)?"
    if re.search(
        rf"^{company_scope}statements?\s+of\s+comprehensive\s+income\b",
        text,
    ):
        return "comprehensive_income"
    if re.search(
        rf"^{company_scope}statements?\s+of\s+changes\s+in\s+"
        r"(?:stockholders['’] equity|shareholders['’] equity|equity)\b",
        text,
    ):
        return "changes_in_stockholders_equity"
    if re.search(
        rf"^{company_scope}statements?\s+of\s+cash\s+flows?\b|"
        rf"^{company_scope}cash flow statement\b",
        text,
    ):
        return "cash_flow"
    if re.search(
        rf"^{company_scope}balance sheets?\b|"
        rf"^{company_scope}statement of financial position\b",
        text,
    ):
        return "balance_sheet"
    if re.search(
        rf"^{company_scope}statements?\s+of\s+(?:profit and loss|income|operations)\b|"
        rf"^{company_scope}income statement\b",
        text,
    ):
        return "income_statement"
    return None


def _statement_heading(page_text: str) -> str | None:
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in page_text.splitlines()[:20]
        if line.strip() and "table of contents" not in line.lower()
    ]
    for line in lines:
        if _statement_type_for_heading(line):
            return line
    for first, second in zip(lines, lines[1:]):
        combined = f"{first} {second}"
        if _statement_type_for_heading(combined):
            return combined
    return None


def _classify_statement(page_text: str) -> str | None:
    heading = _statement_heading(page_text)
    return _statement_type_for_heading(heading) if heading else None


def _classify_scope(page_text: str) -> str | None:
    text = "\n".join(page_text.splitlines()[:20]).lower()
    consolidated = bool(re.search(r"\bconsolidated\b", text))
    standalone = bool(re.search(r"\bstandalone\b|\bstand[- ]alone\b", text))
    if consolidated == standalone:
        return None
    return "consolidated" if consolidated else "standalone"


def _unit_and_currency(page_text: str) -> tuple[str | None, str | None]:
    heading_text = "\n".join(page_text.splitlines()[:20])
    scale_evidence = {
        scale for pattern, scale in UNIT_SCALE_PATTERNS if pattern.search(heading_text)
    }
    unit_scale = next(iter(scale_evidence)) if len(scale_evidence) == 1 else None

    currency_evidence: set[str] = set()
    if re.search(r"\bUSD\b|\bUS dollars?\b|\$", page_text, re.IGNORECASE):
        currency_evidence.add("USD")
    if re.search(r"\bINR\b|₹|\bRs\.?\b|\brupees?\b", page_text, re.IGNORECASE):
        currency_evidence.add("INR")
    currency = next(iter(currency_evidence)) if len(currency_evidence) == 1 else None
    return unit_scale, currency


def _unit_exception(page_text: str) -> str | None:
    heading_text = " ".join(page_text.splitlines()[:20])
    match = re.search(r"\bexcept\s+([^)]*)", heading_text, re.IGNORECASE)
    return match.group(1).strip(" .") if match else None


def _per_share_unit(original_label: str, currency: str | None) -> str | None:
    if currency and re.search(r"\bper share\b|\bpar value\b", original_label, re.IGNORECASE):
        return f"{currency}/share"
    return None


def _parse_number(token: str) -> Decimal | None:
    value = token.replace(",", "").replace("−", "-").strip()
    negative_parentheses = value.startswith("(") and value.endswith(")")
    value = value.strip("()")
    if negative_parentheses:
        value = f"-{value.lstrip('+-')}"
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _period_for_line(line: str, page_text: str) -> str | None:
    years = PERIOD_YEAR_RE.findall(line)
    if not years:
        years = PERIOD_YEAR_RE.findall(page_text)
    if not years or len(set(years)) != 1:
        return None
    return years[0]


def _periods_on_line(line: _Line) -> list[_PeriodAnchor]:
    result: list[_PeriodAnchor] = []
    for word in line.words:
        for match in YEAR_RE.finditer(word.text):
            start_year, end_year = match.groups()
            period = f"{start_year}-{end_year}" if end_year else start_year
            result.append(
                _PeriodAnchor(
                    period=period,
                    x_center=word.x_center,
                    source_header=word.text,
                )
            )
    return result


def _period_anchors(lines: list[_Line], row_index: int) -> list[_PeriodAnchor]:
    row = lines[row_index]
    for header in reversed(lines[:row_index]):
        distance = row.y_center - header.y_center
        if distance > 550:
            break
        anchors = _periods_on_line(header)
        header_text = header.text.lower()
        has_date_context = bool(
            re.search(r"\b(?:year|period)\s+ended\b|\bas\s+at\b|\bas\s+of\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", header_text)
        )
        is_year_only_row = bool(re.fullmatch(r"\s*(?:20\d{2}(?:\s*[-–/]\s*\d{2,4})?\s*)+", header.text))
        if (
            anchors
            and _match_label(header.text) is None
            and (has_date_context or len(anchors) > 1 or is_year_only_row)
        ):
            return anchors
    return []


def _numeric_cells(words: Iterable[_Word]) -> list[_NumericCell]:
    cells: list[_NumericCell] = []
    for index, word in enumerate(words):
        token = word.text.replace("−", "-").strip(",;:")
        match = NUMBER_TOKEN_RE.fullmatch(token)
        if match is None:
            continue
        value = _parse_number(token)
        if value is None:
            continue
        if token in {"-", "—", "–"}:
            continue

        if index > 0 and words[index - 1].text in {"(", "−(", "-", "−"}:
            value = value.lstrip("-")
            value = f"-{value}"
        if index + 1 < len(words) and words[index + 1].text == ")":
            value = value.lstrip("-")
            value = f"-{value}"
        cells.append(_NumericCell(value=value, x_center=word.x_center))
    return cells


def _candidate_label_lines(lines: list[_Line]) -> list[tuple[int, str, str, tuple[_Word, ...]]]:
    rows: list[tuple[int, str, str, tuple[_Word, ...]]] = []
    for index, line in enumerate(lines):
        direct = _match_label(line.text)
        if direct is not None:
            label, _tail, metric = direct
            rows.append((index, label, metric, line.words))
            continue

        if index + 1 >= len(lines):
            continue
        next_line = lines[index + 1]
        gap = next_line.y0 - line.y1
        same_label_column = abs(line.x0 - next_line.x0) <= 12
        max_gap = max(8.0, (line.y1 - line.y0) * 1.5)
        if not same_label_column or gap < -2 or gap > max_gap:
            continue
        combined_words = tuple(
            sorted(line.words + next_line.words, key=lambda word: (word.y_center, word.x0))
        )
        combined = _match_label(f"{line.text} {next_line.text}")
        if combined is None:
            continue
        label, _tail, metric = combined
        rows.append((index, label, metric, combined_words))
    return rows


def _map_cells_to_periods(
    cells: list[_NumericCell],
    anchors: list[_PeriodAnchor],
    fallback_period: str | None,
) -> tuple[list[tuple[_NumericCell, str | None]], str | None]:
    if not cells:
        return [], "No numeric value was found in the matched statement row."
    if not anchors:
        if len(cells) == 1 and fallback_period:
            return [(cells[0], fallback_period)], None
        if len(cells) == 1:
            return [(cells[0], None)], "Reporting period could not be determined unambiguously."
        return [], (
            "Multiple numeric cells were found but no reporting-period column headers "
            "could be mapped to them."
        )

    mapped: list[tuple[_NumericCell, str | None]] = []
    used_periods: set[str] = set()
    for cell in cells:
        distances = sorted(
            ((abs(cell.x_center - anchor.x_center), anchor) for anchor in anchors),
            key=lambda item: item[0],
        )
        if distances[0][0] > 90:
            mapped.append((cell, None))
            continue
        if len(distances) > 1 and abs(distances[0][0] - distances[1][0]) < 3:
            mapped.append((cell, None))
            continue
        period = distances[0][1].period
        if period in used_periods:
            return [], (
                "Numeric cells do not map one-to-one to distinct reporting-period columns."
            )
        used_periods.add(period)
        mapped.append((cell, period))

    if len(cells) > 1 and len(anchors) < len(cells):
        return [], (
            "More numeric cells were found than identifiable reporting-period columns."
        )
    return mapped, None


def _candidate_warning(
    unit: str | None,
    currency: str | None,
    period: str | None,
    statement_type: str | None,
    statement_scope: str | None,
) -> list[str]:
    warnings: list[str] = []
    if unit is None:
        warnings.append("Unit scale could not be determined unambiguously from this statement.")
    if currency is None:
        warnings.append("Currency could not be determined unambiguously from this statement.")
    if period is None:
        warnings.append("Reporting period could not be determined unambiguously.")
    if statement_type is None:
        warnings.append("Statement type could not be determined from this page.")
    if statement_scope is None:
        warnings.append("Consolidated or standalone scope could not be determined unambiguously.")
    return warnings


def _printed_page(lines: list[_Line]) -> int | None:
    for line in reversed(lines):
        if not re.fullmatch(r"\s*\d{1,3}\s*", line.text):
            continue
        return int(line.text.strip())
    return None


def _row_bbox(words: tuple[_Word, ...]) -> tuple[float, float, float, float] | None:
    if not words:
        return None
    return (
        round(min(word.x0 for word in words), 2),
        round(min(word.y0 for word in words), 2),
        round(max(word.x1 for word in words), 2),
        round(max(word.y1 for word in words), 2),
    )


def _extract_page_candidates(page: PDFPageText | str, page_number: int) -> list[Candidate]:
    if isinstance(page, str):
        page_text = page
        words = _text_page_words(page)
    else:
        page_text = page.text
        words = page.words
    lines = _make_lines(words)
    source_statement = _statement_heading(page_text)
    statement_type = _classify_statement(page_text)
    if source_statement is None or statement_type is None:
        return []
    statement_scope = _classify_scope(page_text)
    unit, currency = _unit_and_currency(page_text)
    unit_exception = _unit_exception(page_text)
    page_period = _period_for_line("", page_text)
    printed_page = _printed_page(lines)
    candidates: list[Candidate] = []

    for row_index, label, metric, row_words in _candidate_label_lines(lines):
        cells = _numeric_cells(row_words)
        anchors = _period_anchors(lines, row_index)
        mapped_cells, mapping_warning = _map_cells_to_periods(cells, anchors, page_period)
        if mapping_warning and mapping_warning.startswith("No numeric"):
            known_periods = {anchor.period for anchor in anchors}
            unresolved_period = (
                next(iter(known_periods))
                if len(known_periods) == 1
                else page_period
            )
            mapped_cells = [(None, unresolved_period)]
        elif mapping_warning:
            mapped_cells = [(None, None)]

        source_text = " ".join(word.text for word in row_words).strip()
        per_share_unit = _per_share_unit(label, currency)
        source_bbox = _row_bbox(row_words)
        for cell, period in mapped_cells:
            warnings = _candidate_warning(
                unit, currency, period, statement_type, statement_scope
            )
            if mapping_warning:
                warnings.append(mapping_warning)
            if cell is None:
                value = None
            else:
                value = cell.value
            if period is None and not any("Reporting period" in item for item in warnings):
                warnings.append("Reporting period could not be matched to a numeric column.")

            identity = "|".join(
                (
                    metric,
                    statement_type or "",
                    statement_scope or "",
                    period or "",
                    str(page_number),
                    str(source_bbox),
                )
            )
            source_identity = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            candidate_id = source_identity[:16]
            source_value = cell.value if cell is not None else None
            positive_magnitude = None
            if metric == "capital_expenditure" and source_value is not None:
                positive_magnitude = abs(source_value)
            candidates.append(
                Candidate(
                    candidate_id=candidate_id,
                    metric=metric,
                    original_label=label,
                    value=value,
                    unit=unit,
                    currency=currency,
                    reporting_period=period,
                    statement_type=statement_type,
                    source_page=page_number,
                    source_text=source_text,
                    statement_scope=statement_scope,
                    warnings=warnings,
                    unit_scale=unit,
                    per_share_unit=per_share_unit,
                    unit_exception=unit_exception,
                    source_statement=source_statement,
                    printed_page=printed_page,
                    source_row=source_text,
                    source_bbox=source_bbox,
                    source_identity=source_identity,
                    source_value=source_value,
                    positive_magnitude=positive_magnitude,
                    extraction_version=EXTRACTION_VERSION,
                    source_column_header=next(
                        (
                            anchor.source_header
                            for anchor in anchors
                            if anchor.period == period
                        ),
                        None,
                    ),
                )
            )
    return candidates


def _deduplicate_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    deduplicated: list[Candidate] = []
    seen: dict[str, Candidate] = {}
    by_context: dict[tuple[str, str | None, str | None, str | None], list[Candidate]] = {}
    for candidate in candidates:
        context = (
            candidate.metric,
            candidate.reporting_period,
            candidate.statement_type,
            candidate.statement_scope,
        )
        key = candidate.source_identity or "|".join(
            (
                candidate.metric,
                candidate.reporting_period or "",
                candidate.statement_type or "",
                candidate.statement_scope or "",
                str(candidate.source_page),
                candidate.source_text,
            )
        )
        existing = seen.get(key)
        if existing is None:
            seen[key] = candidate
            deduplicated.append(candidate)
            prior_context = by_context.setdefault(context, [])
            if prior_context:
                repeat_warning = (
                    "Another candidate for the same metric, period, statement, and scope "
                    "was found at a different source location; compare the cited rows."
                )
                for prior in prior_context:
                    if repeat_warning not in prior.warnings:
                        prior.warnings.append(repeat_warning)
                candidate.warnings.append(repeat_warning)
                if any(prior.value != candidate.value for prior in prior_context):
                    conflict_warning = (
                        "Conflicting values were extracted for the same metric, period, "
                        "statement, and scope; compare the cited source rows."
                    )
                    for prior in prior_context:
                        if prior.value != candidate.value and conflict_warning not in prior.warnings:
                            prior.warnings.append(conflict_warning)
                    candidate.warnings.append(conflict_warning)
            prior_context.append(candidate)
        elif existing.value == candidate.value:
            continue
        else:
            conflict_warning = (
                "Conflicting values were extracted for the same source row; "
                "compare the source text and bounding box."
            )
            if conflict_warning not in existing.warnings:
                existing.warnings.append(conflict_warning)
            candidate.warnings.append(conflict_warning)
            deduplicated.append(candidate)
    return deduplicated


def extract_candidates(pages: Iterable[PDFPageText | str]) -> list[Candidate]:
    """Find supported figures while preserving row, column, and page context."""
    candidates: list[Candidate] = []
    for page_number, page in enumerate(pages, start=1):
        candidates.extend(_extract_page_candidates(page, page_number))
    return _deduplicate_candidates(candidates)


def extract_candidates_from_pdf(
    pdf_bytes: bytes,
    source_document_id: str | None = None,
    source_pdf_filename: str | None = None,
) -> list[Candidate]:
    """Extract page layout from a PDF, then identify deterministic candidates."""
    candidates = extract_candidates(extract_pdf_pages(pdf_bytes))
    for candidate in candidates:
        candidate.source_document_id = source_document_id
        candidate.source_pdf_filename = source_pdf_filename
        if source_document_id:
            candidate.source_identity = hashlib.sha256(
                f"{candidate.source_identity}|{source_document_id}|v{EXTRACTION_VERSION}".encode("utf-8")
            ).hexdigest()
            candidate.candidate_id = candidate.source_identity[:16]
    return candidates
