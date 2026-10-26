from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_application_starts_without_uploaded_pdf_or_saved_candidates():
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "Annual Report Figure Review"
    assert app.info[0].value == "Upload a PDF to begin."
