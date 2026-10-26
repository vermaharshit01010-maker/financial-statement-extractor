"""Streamlit interface for extracting and reviewing annual-report figures."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import fitz
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from valuation_app.excel_export import create_excel_workbook
from valuation_app.extractor import EXTRACTION_VERSION, extract_candidates_from_pdf
from valuation_app.models import Candidate, ReviewedFigure
from valuation_app.numeric import (
    format_financial_number,
    preserve_unedited_decimal,
)
from valuation_app.presentation import financial_results_frame
from valuation_app.storage import load_candidates, load_review_state, save_candidates, save_review_state
from valuation_app.validation import validate_approved_figures, validate_fields


METRIC_LABELS = {
    "revenue": "Revenue",
    "other_income": "Other income",
    "total_expenses": "Total expenses",
    "profit_before_tax": "Profit before tax",
    "tax_expense": "Tax expense",
    "profit_after_tax": "Profit after tax",
    "total_assets": "Total assets",
    "total_liabilities": "Total liabilities",
    "total_stockholders_equity": "Total stockholders' equity",
    "equity": "Equity",
    "borrowings": "Borrowings",
    "cash_and_cash_equivalents": "Cash and cash equivalents",
    "operating_cash_flow": "Operating cash flow",
    "capital_expenditure": "Capital expenditure",
    "investing_cash_flow": "Investing cash flow",
    "financing_cash_flow": "Financing cash flow",
    "exchange_rate_effect": "Effect of exchange rate changes",
    "cash_change": "Net change in cash",
    "cash_beginning_of_period": "Cash, beginning of period",
    "cash_end_of_period": "Cash, end of period",
}


def _candidate_table(candidates: list[Candidate]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "candidate_id": item.candidate_id,
                "metric": METRIC_LABELS.get(item.metric, item.metric),
                "original_label": item.original_label,
                "value": item.value,
                "unit_scale": item.unit_scale or item.unit or "",
                "currency": item.currency or "",
                "reporting_period": item.reporting_period or "",
                "statement_type": item.statement_type or "",
                "statement_scope": item.statement_scope or "",
                "physical_pdf_page": item.source_page,
                "printed_page": item.printed_page,
                "positive_magnitude": item.positive_magnitude or "",
                "extraction_status": item.extraction_status,
                "source_verification_status": item.source_verification_status,
                "source_verified": False,
                "decision": "Pending",
            }
            for item in candidates
        ]
    )


def _figure_from_review(
    candidate: Candidate, row: pd.Series
) -> ReviewedFigure:
    value = preserve_unedited_decimal(candidate.value, row["value"])
    return ReviewedFigure(
        candidate_id=candidate.candidate_id,
        metric=candidate.metric,
        original_label=candidate.original_label,
        value=value,
        unit=str(row["unit_scale"]).strip(),
        currency=str(row["currency"]).strip(),
        reporting_period=str(row["reporting_period"]).strip(),
        statement_type=str(row["statement_type"]).strip(),
        source_page=int(row["physical_pdf_page"]),
        source_text=candidate.source_text,
        statement_scope=str(row["statement_scope"]).strip(),
        warnings=list(candidate.warnings),
        unit_scale=str(row["unit_scale"]).strip(),
        per_share_unit=candidate.per_share_unit,
        unit_exception=candidate.unit_exception,
        source_statement=candidate.source_statement,
        printed_page=candidate.printed_page,
        source_row=candidate.source_row,
        source_bbox=candidate.source_bbox,
        source_identity=candidate.source_identity,
        source_value=candidate.source_value,
        positive_magnitude=candidate.positive_magnitude,
        source_document_id=candidate.source_document_id,
        source_pdf_filename=candidate.source_pdf_filename,
        source_column_header=candidate.source_column_header,
        extraction_version=candidate.extraction_version,
        extraction_status=candidate.extraction_status,
        source_verification_status=(
            "verified" if bool(row["source_verified"]) else "unverified"
        ),
    )


st.set_page_config(page_title="Annual Report Figure Review", layout="wide")
st.title("Annual Report Figure Review")
st.write(
    "Upload one digital annual-report PDF. Extraction results are candidates only: "
    "check each cited page and approve figures explicitly before export."
)
st.warning(
    "This prototype uses deterministic text rules, not AI or OCR. It may miss or "
    "misread complex tables. Never use a candidate in analysis without checking the source."
)

uploaded_pdf = st.file_uploader("Choose an annual-report PDF", type=["pdf"])
if uploaded_pdf is None:
    st.info("Upload a PDF to begin.")
    st.stop()

pdf_bytes = uploaded_pdf.getvalue()
document_id = hashlib.sha256(pdf_bytes).hexdigest()
st.caption(f"Document: {uploaded_pdf.name} · ID: {document_id[:12]}")

if st.button("Extract figure candidates", type="primary"):
    try:
        extracted = extract_candidates_from_pdf(
            pdf_bytes,
            source_document_id=document_id,
            source_pdf_filename=uploaded_pdf.name,
        )
        save_candidates(document_id, extracted)
        st.session_state["active_document_id"] = document_id
        st.success(f"Saved {len(extracted)} candidate(s) for review.")
    except (fitz.FileDataError, ValueError, RuntimeError) as error:
        st.error(f"Could not read this PDF: {error}")
        st.stop()
    except OSError as error:
        st.error(f"Could not save extracted candidates locally: {error}")
        st.stop()

if st.session_state.get("active_document_id") != document_id:
    try:
        saved_candidates = load_candidates(document_id)
    except (OSError, ValueError) as error:
        st.error(f"Could not load saved candidates: {error}")
        st.stop()
    if saved_candidates:
        st.session_state["active_document_id"] = document_id
    else:
        st.info("Select **Extract figure candidates** to process this document.")
        st.stop()

try:
    candidates = load_candidates(document_id)
    approved_figures, rejected_ids = load_review_state(document_id)
except (OSError, ValueError, TypeError) as error:
    st.error(f"Could not load local review data: {error}")
    st.stop()

stale_candidates = [
    item for item in candidates if item.extraction_version < EXTRACTION_VERSION
]
if stale_candidates:
    st.warning(
        f"{len(stale_candidates)} cached candidate(s) were created by an older "
        "extractor. Re-extract this PDF before reviewing those figures; old approvals "
        "are retained but will not be exported as current."
    )
    if st.button("Refresh outdated candidates"):
        try:
            refreshed = extract_candidates_from_pdf(
                pdf_bytes,
                source_document_id=document_id,
                source_pdf_filename=uploaded_pdf.name,
            )
            save_candidates(document_id, refreshed)
        except (fitz.FileDataError, ValueError, RuntimeError, OSError) as error:
            st.error(f"Could not refresh candidates: {error}")
        else:
            st.rerun()

current_approved_figures = [
    figure
    for figure in approved_figures
    if figure.extraction_version >= EXTRACTION_VERSION
    and figure.source_verification_status == "verified"
]
reviewed_ids = {figure.candidate_id for figure in approved_figures} | rejected_ids
pending_candidates = (
    []
    if stale_candidates
    else [item for item in candidates if item.candidate_id not in reviewed_ids]
)

st.subheader("Extracted candidates")
if not candidates:
    st.info(
        "No supported labels were found. This may be a scanned PDF or a report layout "
        "the current rules do not recognize."
    )
elif pending_candidates:
    for candidate in pending_candidates:
        if candidate.warnings:
            st.warning(
                f"Page {candidate.source_page} · {candidate.original_label}: "
                + " ".join(candidate.warnings)
            )

    edited = st.data_editor(
        _candidate_table(pending_candidates),
        hide_index=True,
        width="stretch",
        num_rows="fixed",
        column_config={
            "candidate_id": None,
            "metric": st.column_config.TextColumn(disabled=True, width="medium"),
            "original_label": st.column_config.TextColumn(disabled=True, width="large"),
            "value": st.column_config.NumberColumn(
                label="Value (source units)",
                format="localized",
                width="medium",
            ),
            "physical_pdf_page": st.column_config.NumberColumn(
                disabled=True, width="small"
            ),
            "printed_page": st.column_config.NumberColumn(disabled=True),
            "positive_magnitude": st.column_config.NumberColumn(
                disabled=True, format="accounting"
            ),
            "extraction_status": st.column_config.TextColumn(disabled=True),
            "source_verification_status": st.column_config.TextColumn(disabled=True),
            "source_verified": st.column_config.CheckboxColumn(
                label="Source checked",
                help="Check only after confirming the value, period, sign, unit, and scope in the PDF.",
            ),
            "decision": st.column_config.SelectboxColumn(
                options=["Pending", "Approve", "Reject"],
                required=True,
            ),
            "statement_type": st.column_config.SelectboxColumn(
                options=[
                    "",
                    "income_statement",
                    "balance_sheet",
                    "comprehensive_income",
                    "changes_in_stockholders_equity",
                    "cash_flow",
                ]
            ),
            "statement_scope": st.column_config.SelectboxColumn(
                options=["", "consolidated", "standalone"]
            ),
        },
        key=f"review_{document_id}",
    )

    for candidate in pending_candidates:
        with st.expander(
            f"Source detail — {candidate.original_label} "
            f"(PDF page {candidate.source_page}"
            + (
                f", printed page {candidate.printed_page}"
                if candidate.printed_page is not None
                else ""
            )
            + ")"
        ):
            st.write(f"**Statement:** {candidate.source_statement or 'Unresolved'}")
            st.write(f"**Original label:** {candidate.original_label}")
            st.write(f"**Source row:** {candidate.source_row or candidate.source_text}")
            st.write(f"**Period column header:** {candidate.source_column_header or 'Unresolved'}")
            st.write(f"**Full source text:** {candidate.source_text}")
            st.write(f"**Source bounding box:** {candidate.source_bbox or 'Unavailable'}")
            st.write(f"**Document:** {candidate.source_pdf_filename or 'Unknown'}")
            st.write(f"**Document ID:** {candidate.source_document_id or 'Unknown'}")
            st.write(
                f"**Full-precision source value:** "
                f"{format_financial_number(candidate.source_value)}"
            )

    if st.button("Save review decisions"):
        candidates_by_id = {item.candidate_id: item for item in pending_candidates}
        errors: list[str] = []
        new_approvals: list[ReviewedFigure] = []
        new_rejections: set[str] = set()
        for _, row in edited.iterrows():
            candidate = candidates_by_id[str(row["candidate_id"])]
            decision = str(row["decision"])
            if decision == "Reject":
                new_rejections.add(candidate.candidate_id)
            elif decision == "Approve":
                if not bool(row["source_verified"]):
                    errors.append(
                        f"{candidate.original_label} (PDF page {candidate.source_page}): "
                        "confirm source verification before approval."
                    )
                    continue
                figure = _figure_from_review(candidate, row)
                field_errors = validate_fields(figure)
                if field_errors:
                    errors.append(
                        f"{candidate.original_label} (page {candidate.source_page}): "
                        + " ".join(field_errors)
                    )
                else:
                    new_approvals.append(figure)

        if errors:
            st.error("Some approval(s) were not saved:\n\n" + "\n".join(errors))
        else:
            try:
                save_review_state(
                    document_id,
                    approved_figures + new_approvals,
                    rejected_ids | new_rejections,
                )
            except OSError as error:
                st.error(f"Could not save review decisions: {error}")
            else:
                st.success(
                    f"Saved {len(new_approvals)} approval(s) and "
                    f"{len(new_rejections)} rejection(s)."
                )
                st.rerun()
else:
    st.success("All extracted candidates have been approved or rejected.")

st.subheader("Approved historical figures")
if stale_approved := [
    figure for figure in approved_figures
    if figure.extraction_version < EXTRACTION_VERSION
]:
    st.info(
        f"{len(stale_approved)} prior approval(s) are retained for history but excluded "
        "from current results/export until re-extracted and reviewed again."
    )

if current_approved_figures:
    display_scale = st.selectbox(
        "Display scale",
        options=["source", "thousand", "million"],
        index=0,
        help="Presentation-only conversion. Stored and exported figures remain in source scale.",
    )
    validation_warnings = validate_approved_figures(current_approved_figures)
    if validation_warnings:
        for warning in validation_warnings:
            st.warning(warning)
    else:
        st.success(
            "No reconciliation warnings were found in checks with sufficient inputs. "
            "This does not establish source accuracy or prove every possible check ran."
        )

    metric_options = sorted({figure.metric for figure in current_approved_figures})
    selected_metrics = st.multiselect(
        "Filter metrics",
        options=metric_options,
        default=metric_options,
        format_func=lambda metric: METRIC_LABELS.get(metric, metric),
    )
    approved_frame = financial_results_frame(
        [
            figure
            for figure in current_approved_figures
            if figure.metric in selected_metrics
        ],
        display_scale=display_scale,
    )
    if not approved_frame.empty:
        approved_frame["metric"] = approved_frame["metric"].map(
            lambda metric: METRIC_LABELS.get(metric, metric)
        )
        approved_frame["currency_and_scale"] = approved_frame.apply(
            lambda row: " ".join(
                item for item in (row["currency"], row["unit_scale"]) if item
            )
            or "Unresolved",
            axis=1,
        )
        approved_frame["validation_status"] = (
            "Warnings present" if validation_warnings else "No warnings; coverage may be incomplete"
        )
        approved_frame = approved_frame[
            [
                "metric",
                "original_label",
                "value",
                "currency_and_scale",
                "reporting_period",
                "source_column_header",
                "statement_type",
                "statement_scope",
                "physical_pdf_page",
                "printed_page",
                "extraction_status",
                "source_verification_status",
                "validation_status",
            ]
        ]
        styled_frame = (
            approved_frame.style.format(
                {"value": format_financial_number},
                na_rep="—",
            ).set_properties(
                subset=["value", "physical_pdf_page", "printed_page"],
                **{"text-align": "right"},
            )
        )
        st.dataframe(
            styled_frame,
            hide_index=True,
            width="stretch",
            height=480,
        )

    for figure in current_approved_figures:
        with st.expander(f"Verified detail — {figure.original_label}"):
            st.write(f"**Full-precision source value:** {figure.value!s}")
            st.write(f"**Currency and scale:** {figure.currency} / {figure.unit_scale or figure.unit}")
            st.write(f"**Reporting period / source column:** {figure.reporting_period} / {figure.source_column_header or 'Not recorded'}")
            st.write(f"**Physical PDF page:** {figure.source_page}")
            st.write(f"**Printed page:** {figure.printed_page or 'Not detected'}")
            st.write(f"**Source statement:** {figure.source_statement or 'Not recorded'}")
            st.write(f"**Source row:** {figure.source_row or figure.source_text}")
            st.write(f"**Document:** {figure.source_pdf_filename or 'Unknown'}")
            st.write(f"**Document ID:** {figure.source_document_id or 'Unknown'}")
            st.write(f"**Bounding box:** {figure.source_bbox or 'Unavailable'}")
            st.write(f"**Source verification:** {figure.source_verification_status}")
            st.write(f"**Extraction status:** {figure.extraction_status}")
    try:
        workbook = create_excel_workbook(current_approved_figures)
    except (ValueError, OSError) as error:
        st.error(f"Could not create the Excel workbook: {error}")
    else:
        st.download_button(
            "Download approved figures as Excel",
            data=workbook,
            file_name="reviewed_historical_figures.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
else:
    st.info(
        "No current, source-verified figures are approved yet. Unverified or outdated "
        "candidates are never included in the current export."
    )
