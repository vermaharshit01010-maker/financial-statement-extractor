# Annual-Report Financial Statement Extraction

A local Streamlit application that extracts a limited set of historical financial-statement figures from one text-readable annual-report PDF. It uses deterministic Python rules and PyMuPDF page/layout information. Extracted values are unverified candidates: users inspect the source and explicitly approve figures before the app includes them in the reviewed-results table or Excel export.

This is an extraction and review prototype, not an investment recommendation or a complete valuation product. It does not include AI APIs, OCR, automatic report downloads, forecasts, comparable-company analysis, or DCF valuation.

## Features

- Upload one annual-report PDF through a local browser interface.
- Extract supported income statement, balance sheet, comprehensive income, changes in stockholders' equity, and cash flow statement figures.
- Preserve original labels, reporting periods, statement/scope metadata, currency and scale where identifiable, physical PDF pages, printed pages when detected, and source-row details.
- Associate comparative numeric columns with periods when the source layout provides reliable evidence; leave uncertain information unresolved for manual review.
- Review, edit, source-check, approve, or reject candidates. Extraction does not automatically approve a figure.
- Run basic field and accounting reconciliation checks. Warnings do not change values.
- Present numeric values with financial formatting and optional display-scale conversion.
- Download explicitly approved, source-verified figures as an Excel workbook.
- Persist extraction candidates and review decisions locally in JSON files under `data/`, keyed by the uploaded PDF's content hash.

## Limitations and data handling

- The extractor supports a limited set of common statement labels and layouts; it is not accurate for every annual report.
- The PDF must contain selectable text. Scanned/image-only documents are not supported because OCR is not included.
- Complex, multi-level, or unusual tables may produce unresolved or incorrect candidates. Verify every figure, year, sign, currency, unit, statement, and scope against the cited report page.
- Source verification, successful extraction, and accounting validation are separate states. A reconciliation pass does not prove that source data are accurate or complete.
- The application does not send uploaded documents to an external service. It needs no API key, paid service, database server, or other external runtime service.
- Uploaded PDFs are processed in memory and are not copied to the local data store by this app. Extracted candidates and review decisions are saved locally in `data/`; treat this directory as potentially sensitive and do not commit or share it.
- Excel numeric cells have spreadsheet precision limits. Exact decimal text is included in the export as a reference where applicable.

## Project structure

```text
.
├── app.py                         # Streamlit entry point
├── requirements.txt               # Runtime dependencies
├── requirements-dev.txt           # Runtime plus test dependencies
├── README.md
├── .gitignore
├── src/
│   └── valuation_app/
│       ├── extractor.py           # PDF extraction and candidate mapping
│       ├── models.py              # Candidate and reviewed-figure data models
│       ├── numeric.py             # Numeric parsing and presentation helpers
│       ├── presentation.py        # Results table data
│       ├── storage.py             # Local JSON persistence
│       ├── validation.py          # Field and accounting checks
│       └── excel_export.py        # Excel workbook generation
└── tests/                         # Automated tests and generated fixtures
```

`data/` is created as needed for local candidates and review decisions. It is intentionally not part of the source distribution. No sample PDF, screenshot, database, or saved session is required to start the application.

## Prerequisites and supported platforms

- Python 3.9 or newer; Python 3.10+ is recommended.
- Git to clone the repository.
- VS Code is recommended but optional. Use its integrated terminal and select the project's `.venv` interpreter if desired.
- Internet access is required to install Python packages.
- No separate system library or database service is required on platforms where the Python packages provide compatible wheels.

The code is designed to use cross-platform Python packages and should be usable on macOS, Windows, and Linux. Only the current macOS development environment was exercised for this distribution preparation; Windows and Linux installation have not been independently tested. PyMuPDF includes native components, so a platform without a compatible wheel may require its platform-specific build tools.

## Clone and install

The repository is private, so you must have GitHub access to clone it:

### macOS and Linux (VS Code terminal)

```bash
git clone https://github.com/vermaharshit01010-maker/financial-statement-extractor.git
cd financial-statement-extractor
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Open the cloned folder in VS Code if it is not already open:

```bash
code .
```

In VS Code, choose the interpreter at `.venv` if prompted.

### Windows PowerShell (VS Code terminal)

```powershell
git clone https://github.com/vermaharshit01010-maker/financial-statement-extractor.git
Set-Location financial-statement-extractor
py --version
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, either use Command Prompt and run `.venv\Scripts\activate.bat`, or adjust the execution policy for the current user according to Microsoft's guidance. Do not run an unfamiliar policy-changing command without understanding its scope.

## Launch and use

From the project directory, with the virtual environment active, launch the application with:

```bash
python -m streamlit run app.py
```

On Windows, use the same command in PowerShell after activation. Streamlit prints a local URL, usually `http://localhost:8501`; open it in a browser. Stop the application with `Ctrl+C` in the terminal.

1. Upload one text-readable annual-report PDF.
2. Select **Extract figure candidates**.
3. Check each candidate's original label, numeric value, period, sign, currency, unit, statement, scope, and physical/printed source page against the PDF. Expand source details when necessary.
4. Correct fields where the source clearly supports the correction. Leave unresolved or ambiguous candidates pending; do not guess.
5. Check **Source checked** only after comparing the candidate with the PDF, then select **Approve**. Reject irrelevant candidates or leave uncertain records pending.
6. Review validation warnings in the approved-results section.
7. Download the Excel workbook. It contains approved, source-verified figures only.

The display-scale selection is for presentation. By default, exported values remain in source scale. Review records are persisted across restarts under `data/` for that local clone.

## Run tests

Install development/test dependencies in addition to the runtime dependencies:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Most tests use generated PDFs and expected-value fixtures. An optional source-document regression suite can be run against a Verisk FY2025 10-K that you have obtained separately and are permitted to use:

macOS/Linux:

```bash
VERISK_10K_PDF="/path/to/your-verisk-10k.pdf" python -m pytest
```

PowerShell:

```powershell
$env:VERISK_10K_PDF = "C:\path\to\your-verisk-10k.pdf"
python -m pytest
Remove-Item Env:VERISK_10K_PDF
```

The Verisk PDF is not required for the app or standard tests and must not be added to the repository. Without `VERISK_10K_PDF`, source-document regression tests are skipped.

## Configuration and local files

- No runtime environment variable or external service is required.
- `VERISK_10K_PDF` is optional and used only to enable source-document regression tests.
- There is no required PDF, image, database, or prior session state. The initial screen should load from a clean clone before any PDF is uploaded.
- Persistent files are created in the repository's `data/` directory. Back up or delete local candidate/review JSON files yourself when appropriate; the app currently has no deletion screen.
- Do not commit annual reports, uploaded documents, extracted candidate JSON, review decisions, API keys, `.env` files, or other confidential data. The `.gitignore` excludes common local inputs and state, but inspect the staged changes before every commit.

## Troubleshooting

### `python3` or `py` is not found

Install Python 3.9+ and ensure the launcher is available on `PATH`. On macOS/Linux, use `python3`; on Windows, `py` is commonly available. Restart the VS Code terminal after installing Python.

### `No module named streamlit`, `fitz`, `pandas`, or `openpyxl`

Activate the project's virtual environment and install dependencies from the project root:

```bash
python -m pip install -r requirements.txt
```

The `fitz` module is provided by the **PyMuPDF** package; do not install an unrelated package named `fitz`.

### Installation fails while installing PyMuPDF

Upgrade `pip`, confirm the Python version and operating system architecture, and retry. PyMuPDF ships native code and may not have a wheel for every Python/platform combination. On unsupported combinations, use a supported Python release or follow the official PyMuPDF build instructions for your platform.

### `streamlit: command not found`

Confirm `.venv` is activated. Alternatively run the exact module command `python -m streamlit run app.py`, which uses the active interpreter.

### The app reports no supported labels or missing figures

The PDF may be scanned, have an unsupported layout, or use different line-item labels. Scanned files need OCR, which this version does not provide. Check the PDF has selectable text and manually verify the cited source; do not treat missing figures as zero.

### Candidate/review JSON cannot be saved

Confirm that the project folder is writable and that the app is running from the intended clone. The app creates `data/candidates/` and `data/reviews/` as needed.

### Verisk source tests are skipped

This is expected unless `VERISK_10K_PDF` points to a locally available PDF. The source document is intentionally not bundled.

## Distribution status

The clone instructions use the provided private repository URL. Users need permission to access that repository. Do not distribute local files ignored by `.gitignore` or reports/screenshots that are not explicitly authorized for sharing.
