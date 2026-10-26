"""Local JSON persistence for extracted candidates and reviewed figures."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from decimal import Decimal

from valuation_app.models import Candidate, ReviewedFigure


DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(value, indent=2, default=_json_default), encoding="utf-8"
        )
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def candidate_path(document_id: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / "candidates" / f"{document_id}.json"


def review_path(document_id: str, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / "reviews" / f"{document_id}.json"


def save_candidates(
    document_id: str, candidates: list[Candidate], data_dir: Path = DATA_DIR
) -> None:
    _atomic_write_json(
        candidate_path(document_id, data_dir),
        [candidate.to_dict() for candidate in candidates],
    )


def load_candidates(document_id: str, data_dir: Path = DATA_DIR) -> list[Candidate]:
    path = candidate_path(document_id, data_dir)
    if not path.exists():
        return []
    content = json.loads(path.read_text(encoding="utf-8"))
    return [Candidate.from_dict(item) for item in content]


def load_review_state(
    document_id: str, data_dir: Path = DATA_DIR
) -> tuple[list[ReviewedFigure], set[str]]:
    path = review_path(document_id, data_dir)
    if not path.exists():
        return [], set()
    content = json.loads(path.read_text(encoding="utf-8"))
    approved = [ReviewedFigure.from_dict(item) for item in content.get("approved", [])]
    rejected_ids = set(content.get("rejected_ids", []))
    return approved, rejected_ids


def save_review_state(
    document_id: str,
    approved: list[ReviewedFigure],
    rejected_ids: set[str],
    data_dir: Path = DATA_DIR,
) -> None:
    _atomic_write_json(
        review_path(document_id, data_dir),
        {
            "approved": [figure.to_dict() for figure in approved],
            "rejected_ids": sorted(rejected_ids),
        },
    )
