"""sunday_batch job (v2 Phase 5).

Sundays 04:00. Runs the configured batch themes (default 3), stores each
FinalReport under reports/batch/{YYYY-MM-DD}/{theme}.json, diffs each theme's
top-5 against last week's run, and emails a single weekly digest. Honors a
weekly cost ceiling (advisory on the Max backend).

Cost: ~$10-20 metered for 4 themes x 10 candidates; on Max it is usage-equivalent.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

from stock_agents.config import settings

log = logging.getLogger("stock_agents.automation")


def _batch_dir(date: str) -> Path:
    return Path("reports") / "batch" / date


def _slug(theme: str) -> str:
    return theme.strip().lower().replace(" ", "_").replace("/", "-")


def _previous_report(theme: str, today: str) -> dict | None:
    """Most recent prior batch report for the theme, before ``today``."""
    root = Path("reports") / "batch"
    if not root.exists():
        return None
    dates = sorted((d.name for d in root.iterdir() if d.is_dir() and d.name < today), reverse=True)
    for d in dates:
        path = root / d / f"{_slug(theme)}.json"
        if path.exists():
            return json.loads(path.read_text())
    return None


def _theme_diff(theme: str, current: dict, previous: dict | None) -> dict:
    cur = {t["ticker"]: t["conviction_score"] for t in current.get("top_picks", [])}
    if previous is None:
        return {"theme": theme, "first_run": True, "top5": list(cur),
                "new_entries": [], "dropouts": [], "conviction_shifts": []}
    prev = {t["ticker"]: t["conviction_score"] for t in previous.get("top_picks", [])}
    shifts = [
        {"ticker": k, "from": prev[k], "to": cur[k], "delta": round(cur[k] - prev[k], 1)}
        for k in set(cur) & set(prev) if abs(cur[k] - prev[k]) > 15
    ]
    return {
        "theme": theme, "first_run": False, "top5": list(cur),
        "new_entries": sorted(set(cur) - set(prev)),
        "dropouts": sorted(set(prev) - set(cur)),
        "conviction_shifts": shifts,
    }


def run(*, themes: list[str] | None = None, max_candidates: int | None = None,
        budget_usd: float | None = None, **_kwargs) -> dict:
    from stock_agents import notify
    from stock_agents.agents import orchestrator

    themes = themes or settings.batch_themes
    max_candidates = max_candidates or settings.sunday_batch_max_candidates
    budget = budget_usd if budget_usd is not None else settings.weekly_budget_usd
    today = dt.date.today().isoformat()
    out_dir = _batch_dir(today)
    out_dir.mkdir(parents=True, exist_ok=True)

    spent, diffs, completed, aborted = 0.0, [], [], False
    for theme in themes:
        if settings.llm_backend != "claude_code" and spent >= budget:
            aborted = True
            notify.emit_alert(kind="cost_warning", severity="notice",
                              subject="[sunday_batch] weekly budget reached",
                              short=f"sunday_batch stopped after ${spent:.2f} (ceiling ${budget}).")
            break
        try:
            report = orchestrator.analyze_theme(theme, max_candidates=max_candidates)
        except Exception as exc:  # noqa: BLE001
            log.warning("sunday_batch theme %s failed: %s", theme, exc)
            continue
        spent += report.api_cost_usd
        (out_dir / f"{_slug(theme)}.json").write_text(report.model_dump_json(indent=2))
        completed.append(theme)
        diffs.append(_theme_diff(theme, report.model_dump(), _previous_report(theme, today)))

    if completed:
        subject, short, html = _digest(today, diffs)
        notify.emit_alert(kind="earnings_diff", severity="info",
                          subject=subject, short=short, html=html)

    return {"themes": themes, "completed": completed, "spent_usd": round(spent, 4),
            "budget_aborted": aborted, "report_dir": str(out_dir)}


def _digest(date: str, diffs: list[dict]) -> tuple[str, str, str]:
    subject = f"Weekly research digest — {date} ({len(diffs)} themes)"
    short = subject + ": " + ", ".join(d["theme"] for d in diffs)
    parts = [f"<h2>Weekly research digest — {date}</h2>"]
    for d in diffs:
        parts.append(f"<h3>{d['theme']}</h3>")
        parts.append("<p><b>Top 5:</b> " + ", ".join(d["top5"]) + "</p>")
        if d.get("first_run"):
            parts.append("<p><i>First run for this theme.</i></p>")
        else:
            if d["new_entries"]:
                parts.append("<p><b>New entries:</b> " + ", ".join(d["new_entries"]) + "</p>")
            if d["dropouts"]:
                parts.append("<p><b>Dropped out:</b> " + ", ".join(d["dropouts"]) + "</p>")
            if d["conviction_shifts"]:
                rows = "".join(
                    f"<li>{s['ticker']}: {s['from']:.0f}->{s['to']:.0f} ({s['delta']:+.0f})</li>"
                    for s in d["conviction_shifts"]
                )
                parts.append(f"<p><b>Conviction shifts &gt;15:</b></p><ul>{rows}</ul>")
            if not (d["new_entries"] or d["dropouts"] or d["conviction_shifts"]):
                parts.append("<p>No material changes vs last week.</p>")
    return subject, short[:240], "".join(parts)
