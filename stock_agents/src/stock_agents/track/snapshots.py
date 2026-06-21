"""Read/write thesis snapshot JSON on disk.

Snapshots live under ``settings.snapshots_dir/{TICKER}/{snapshot_id}.json``. Each
file is a :class:`ThesisSnapshot` (the synthesized thesis plus, when available,
the four analyst reports). This module also resolves a user-supplied ``--thesis``
file into an ``InvestmentThesis`` for a given ticker, accepting three shapes:
a v1 ``FinalReport``, a bare ``InvestmentThesis``, or a saved ``ThesisSnapshot``.
"""

from __future__ import annotations

import json
from pathlib import Path

from stock_agents.config import settings
from stock_agents.models.thesis import FinalReport, InvestmentThesis
from stock_agents.track.models import ThesisSnapshot, new_ulid
from stock_agents.track.store import now_iso


class ThesisFileError(ValueError):
    pass


def _snapshot_path(ticker: str, snapshot_id: str) -> Path:
    return settings.snapshots_dir / ticker.upper() / f"{snapshot_id}.json"


def write_snapshot(snapshot: ThesisSnapshot) -> str:
    """Persist a snapshot to disk; return its path relative to data_dir."""
    path = _snapshot_path(snapshot.ticker, snapshot.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(snapshot.model_dump_json(indent=2))
    try:
        return str(path.relative_to(settings.data_dir))
    except ValueError:
        return str(path)


def read_snapshot(rel_or_abs_path: str) -> ThesisSnapshot:
    path = Path(rel_or_abs_path)
    if not path.is_absolute():
        path = settings.data_dir / path
    return ThesisSnapshot.model_validate_json(path.read_text())


def build_snapshot(
    ticker: str,
    run_id: str,
    thesis: InvestmentThesis,
    *,
    fundamentals=None,
    balance_sheet=None,
    management=None,
    stress_test=None,
) -> ThesisSnapshot:
    return ThesisSnapshot(
        id=new_ulid(),
        ticker=ticker.upper(),
        run_id=run_id,
        taken_at=now_iso(),
        thesis=thesis,
        fundamentals=fundamentals,
        balance_sheet=balance_sheet,
        management=management,
        stress_test=stress_test,
    )


def load_entry_thesis(thesis_path: str, ticker: str) -> InvestmentThesis:
    """Resolve a --thesis file to the InvestmentThesis for ``ticker``.

    Accepts a v1 FinalReport (extract the matching ticker from full_results /
    top_picks), a bare InvestmentThesis, or a saved ThesisSnapshot.
    """
    ticker = ticker.upper()
    raw = Path(thesis_path).read_text()
    data = json.loads(raw)

    # ThesisSnapshot
    if isinstance(data, dict) and "thesis" in data and "taken_at" in data:
        return ThesisSnapshot.model_validate(data).thesis

    # FinalReport
    if isinstance(data, dict) and ("full_results" in data or "top_picks" in data):
        report = FinalReport.model_validate(data)
        for t in [*report.full_results, *report.top_picks]:
            if t.ticker.upper() == ticker:
                return t
        raise ThesisFileError(
            f"{ticker} not found in report {thesis_path} "
            f"(has: {', '.join(sorted({t.ticker for t in report.full_results}))})"
        )

    # Bare InvestmentThesis
    if isinstance(data, dict) and "conviction_score" in data:
        thesis = InvestmentThesis.model_validate(data)
        if thesis.ticker.upper() != ticker:
            raise ThesisFileError(f"thesis file is for {thesis.ticker}, not {ticker}")
        return thesis

    raise ThesisFileError(f"unrecognized thesis file format: {thesis_path}")
