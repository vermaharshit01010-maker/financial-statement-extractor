import fitz
from decimal import Decimal

from valuation_app.extractor import _classify_statement, extract_candidates, extract_pdf_pages


def test_extracts_candidates_with_source_page_and_metadata():
    text = """Statement of Profit and Loss
Consolidated Statement
(₹ in lakhs)
For the year ended 31 March 2025
Revenue from operations        1,250.50
Other income                    30.00
Total expenses                 900.00
Profit before tax              380.50"""

    candidates = extract_candidates([text])

    assert [candidate.metric for candidate in candidates] == [
        "revenue",
        "other_income",
        "total_expenses",
        "profit_before_tax",
    ]
    assert candidates[0].value == Decimal("1250.50")
    assert candidates[0].source_page == 1
    assert candidates[0].unit == "lakh"
    assert candidates[0].currency == "INR"
    assert candidates[0].reporting_period == "2025"
    assert candidates[0].statement_type == "income_statement"
    assert candidates[0].statement_scope == "consolidated"


def test_keeps_parentheses_sign_and_flags_ambiguous_columns():
    page = """Consolidated Statement of Cash Flows
INR in crores
For the year ended 31 March 2025
Net cash from operating activities      (120)     95"""

    candidate = extract_candidates([page])[0]

    assert candidate.metric == "operating_cash_flow"
    assert candidate.value is None
    assert candidate.source_page == 1
    assert candidate.statement_type == "cash_flow"
    assert any("one-to-one" in warning or "More numeric cells" in warning for warning in candidate.warnings)


def test_does_not_guess_period_from_unrelated_year_on_page():
    page = """Consolidated Statement of Profit and Loss
2025 Annual Report
Revenue from operations 100"""

    candidate = extract_candidates([page])[0]

    assert candidate.reporting_period is None
    assert any("Reporting period" in warning for warning in candidate.warnings)


def test_ambiguous_page_units_are_left_for_manual_review():
    page = """Standalone Statement of Profit and Loss
₹ in lakhs
Some note: amounts in ₹ in crores
For the year ended 31 March 2025
Revenue from operations 100"""

    candidate = extract_candidates([page])[0]

    assert candidate.unit is None
    assert candidate.currency == "INR"
    assert candidate.unit_scale is None
    assert any("Unit scale could not be determined" in warning for warning in candidate.warnings)


def test_pdf_text_extraction_preserves_one_based_pages():
    document = fitz.open()
    page_one = document.new_page()
    page_one.insert_text((72, 72), "Page one")
    page_two = document.new_page()
    page_two.insert_text((72, 72), "Page two")
    pdf_bytes = document.tobytes()
    document.close()

    pages = extract_pdf_pages(pdf_bytes)

    assert len(pages) == 2
    assert "Page one" in pages[0].text
    assert "Page two" in pages[1].text
    assert pages[0].words
    assert pages[1].words


def _make_positioned_pdf(page_lines):
    document = fitz.open()
    for lines in page_lines:
        page = document.new_page(width=612, height=792)
        for x, y, text in lines:
            page.insert_text((x, y), text, fontsize=10)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def test_associates_separate_text_blocks_on_the_same_statement_row():
    pdf_bytes = _make_positioned_pdf(
        [
            [
                (50, 35, "Consolidated Statement of Profit and Loss"),
                (50, 55, "INR in crores"),
                (300, 75, "2025"),
                (50, 95, "Revenue from operations"),
                (300, 95, "1,23,456.78"),
            ]
        ]
    )

    candidates = extract_candidates(extract_pdf_pages(pdf_bytes))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.value == Decimal("123456.78")
    assert candidate.unit == "crore"
    assert candidate.currency == "INR"
    assert candidate.reporting_period == "2025"
    assert candidate.statement_type == "income_statement"
    assert candidate.statement_scope == "consolidated"
    assert candidate.source_page == 1
    assert not any("Reporting period" in warning for warning in candidate.warnings)


def test_joins_a_wrapped_statement_label_to_its_value_column():
    pdf_bytes = _make_positioned_pdf(
        [
            [
                (50, 35, "Consolidated Balance Sheet"),
                (50, 55, "INR in crores"),
                (300, 75, "2025"),
                (50, 95, "Cash and cash"),
                (50, 107, "equivalents"),
                (300, 107, "50"),
            ]
        ]
    )

    candidates = extract_candidates(extract_pdf_pages(pdf_bytes))

    assert len(candidates) == 1
    assert candidates[0].metric == "cash_and_cash_equivalents"
    assert candidates[0].value == Decimal("50")
    assert candidates[0].reporting_period == "2025"
    assert candidates[0].source_page == 1


def test_extracts_each_comparative_period_from_its_numeric_column():
    pdf_bytes = _make_positioned_pdf(
        [
            [
                (50, 35, "Standalone Statement of Profit and Loss"),
                (50, 55, "INR in lakhs"),
                (300, 75, "2025"),
                (430, 75, "2024"),
                (50, 95, "Revenue from operations"),
                (300, 95, "(1,23,456.50)"),
                (430, 95, "98,765.25"),
            ]
        ]
    )

    candidates = extract_candidates(extract_pdf_pages(pdf_bytes))

    by_period = {candidate.reporting_period: candidate for candidate in candidates}
    assert set(by_period) == {"2025", "2024"}
    assert by_period["2025"].value == Decimal("-123456.50")
    assert by_period["2024"].value == Decimal("98765.25")
    assert all(candidate.statement_scope == "standalone" for candidate in candidates)
    assert all(candidate.unit == "lakh" for candidate in candidates)
    assert all(candidate.source_page == 1 for candidate in candidates)
    assert all(not candidate.warnings for candidate in candidates)


def test_unmatched_label_does_not_borrow_number_from_next_row():
    pdf_bytes = _make_positioned_pdf(
        [
            [
                (50, 35, "Consolidated Balance Sheet"),
                (50, 55, "INR in crores"),
                (300, 75, "2025"),
                (50, 95, "Total assets"),
                (50, 115, "Total equity"),
                (300, 115, "200"),
            ]
        ]
    )

    candidates = extract_candidates(extract_pdf_pages(pdf_bytes))

    by_metric = {candidate.metric: candidate for candidate in candidates}
    assert by_metric["total_assets"].value is None
    assert any("No numeric value" in warning for warning in by_metric["total_assets"].warnings)
    assert by_metric["equity"].value == Decimal("200")


def test_ignores_prose_prefixes_and_deduplicates_same_context():
    page = """Consolidated Balance Sheet
INR in crores
As at 31 March 2025
Total assets 500
Cash and cash equivalents 50
Total assets acquired in the business combination were 80
Cash and cash equivalents consist of cash, deposits, and other instruments."""

    candidates = extract_candidates([page, page])

    assert [candidate.metric for candidate in candidates] == [
        "total_assets",
        "cash_and_cash_equivalents",
        "total_assets",
        "cash_and_cash_equivalents",
    ]
    assert [candidate.value for candidate in candidates] == [
        Decimal("500"),
        Decimal("50"),
        Decimal("500"),
        Decimal("50"),
    ]
    assert {candidate.source_page for candidate in candidates} == {1, 2}
    assert all(
        any("different source location" in warning for warning in candidate.warnings)
        for candidate in candidates
    )


def test_retains_figures_with_distinct_statement_scope():
    consolidated = """Consolidated Balance Sheet
INR in crores
As at 31 March 2025
Total assets 500"""
    standalone = """Standalone Balance Sheet
INR in crores
As at 31 March 2025
Total assets 450"""

    candidates = extract_candidates([consolidated, standalone])

    assert len(candidates) == 2
    assert {candidate.statement_scope for candidate in candidates} == {
        "consolidated",
        "standalone",
    }
    assert {candidate.value for candidate in candidates} == {
        Decimal("500"),
        Decimal("450"),
    }


def test_flags_conflicting_same_context_values_instead_of_silently_dropping():
    first = """Consolidated Balance Sheet
INR in crores
As at 31 March 2025
Total assets 500"""
    second = """Consolidated Balance Sheet
INR in crores
As at 31 March 2025
Total assets 510"""

    candidates = extract_candidates([first, second])

    assert len(candidates) == 2
    assert {candidate.value for candidate in candidates} == {
        Decimal("500"),
        Decimal("510"),
    }
    assert all(
        any("Conflicting values" in warning for warning in candidate.warnings)
        for candidate in candidates
    )


def test_parses_explicit_minus_sign_and_decimal():
    page = """Consolidated Statement of Cash Flows
INR in thousands
For the year ended 31 March 2025
Capital expenditure -1,234.50"""

    candidate = extract_candidates([page])[0]

    assert candidate.value == Decimal("-1234.50")
    assert candidate.unit == "thousand"
    assert candidate.currency == "INR"


def test_parses_explicit_positive_sign():
    page = """Consolidated Statement of Cash Flows
INR in thousands
For the year ended 31 March 2025
Capital expenditure +1,234.50"""

    candidate = extract_candidates([page])[0]

    assert candidate.value == Decimal("1234.50")


def test_maps_fiscal_year_ranges_to_comparative_columns():
    page = """Consolidated Statement of Profit and Loss
INR in crores
Particulars          2024-25          2023-24
Revenue from operations      100.00           90.00"""

    candidates = extract_candidates([page])

    assert {candidate.reporting_period: candidate.value for candidate in candidates} == {
        "2024-25": Decimal("100.00"),
        "2023-24": Decimal("90.00"),
    }


def test_finds_all_twelve_supported_figures_across_statements():
    pages = [
        """Consolidated Statement of Profit and Loss
₹ in crores
For the year ended 31 March 2025
Revenue from operations 100
Other income 5
Total expenses 80
Profit before tax 25
Tax expense 5
Profit for the year 20""",
        """Consolidated Balance Sheet
₹ in crores
As at 31 March 2025
Total assets 500
Total equity 200
Total borrowings 100
Cash and cash equivalents 50""",
        """Consolidated Statement of Cash Flows
₹ in crores
For the year ended 31 March 2025
Net cash generated from operating activities 40
Purchase of property, plant and equipment (10)""",
    ]

    candidates = extract_candidates(pages)

    assert {candidate.metric for candidate in candidates} == {
        "revenue",
        "other_income",
        "total_expenses",
        "profit_before_tax",
        "tax_expense",
        "profit_after_tax",
        "total_assets",
        "equity",
        "borrowings",
        "cash_and_cash_equivalents",
        "operating_cash_flow",
        "capital_expenditure",
    }
    assert len(candidates) == 12
    assert all(candidate.statement_scope == "consolidated" for candidate in candidates)


def test_classifies_all_five_financial_statement_types_from_headings():
    headings = {
        "CONSOLIDATED BALANCE SHEETS": "balance_sheet",
        "CONSOLIDATED STATEMENTS OF OPERATIONS": "income_statement",
        "CONSOLIDATED STATEMENTS OF COMPREHENSIVE INCOME": "comprehensive_income",
        "CONSOLIDATED STATEMENTS OF CHANGES IN STOCKHOLDERS’ EQUITY": (
            "changes_in_stockholders_equity"
        ),
        "CONSOLIDATED STATEMENTS OF CASH FLOWS (Continued)": "cash_flow",
    }

    for heading, expected_type in headings.items():
        assert _classify_statement(f"Table of Contents\nCompany\n{heading}\n2025") == expected_type


def test_does_not_map_investment_income_and_others_to_other_income():
    candidates = extract_candidates(
        [
            """Consolidated Statements of Operations
USD in millions
For the year ended December 31, 2025
Other income (expense):
Investment income and others, net 12.4"""
        ]
    )

    assert candidates == []


def test_uses_scale_and_currency_independently_and_preserves_source_location():
    pdf_bytes = _make_positioned_pdf(
        [
            [
                (50, 35, "CONSOLIDATED STATEMENTS OF CASH FLOWS"),
                (50, 55, "For the years ended 2025 and 2024"),
                (300, 75, "2025"),
                (430, 75, "2024"),
                (50, 95, "(in millions)"),
                (50, 115, "Capital expenditures"),
                (300, 115, "(244.1)"),
                (430, 115, "(223.9)"),
                (300, 750, "55"),
            ]
        ]
    )

    candidates = extract_candidates(extract_pdf_pages(pdf_bytes))

    assert {item.reporting_period: item.value for item in candidates} == {
        "2025": Decimal("-244.1"),
        "2024": Decimal("-223.9"),
    }
    assert all(item.currency is None for item in candidates)
    assert all(item.unit_scale == "million" for item in candidates)
    assert all(
        item.positive_magnitude in {Decimal("244.1"), Decimal("223.9")}
        for item in candidates
    )
    assert all(item.printed_page == 55 for item in candidates)
    assert all(item.source_statement == "CONSOLIDATED STATEMENTS OF CASH FLOWS" for item in candidates)
    assert all(item.source_bbox is not None and item.source_identity for item in candidates)


def test_does_not_extract_supported_labels_from_notes_without_statement_heading():
    candidates = extract_candidates(
        [
            """Note 14: Assets
Total assets acquired in a transaction were 80
Cash and cash equivalents consist of cash deposits."""
        ]
    )

    assert candidates == []
