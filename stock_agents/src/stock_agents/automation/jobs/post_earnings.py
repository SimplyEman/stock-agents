"""post_earnings job (v2 Phase 5).

Daily 06:00. Finds watchlist tickers that reported in the last 24h (FMP earnings
calendar), re-runs track-status on each, and alerts on material diffs. Honors a
daily cost ceiling. A track-status that cannot evaluate (no data / transcript not
yet posted) logs a quiet alert; the daily cadence is itself the 24h retry.
"""

from __future__ import annotations

import datetime as dt
import logging

from stock_agents.config import settings
from stock_agents.data import fmp
from stock_agents.track import store

log = logging.getLogger("stock_agents.automation")


def _reporters_last_24h(active_tickers: set[str]) -> list[str]:
    today = dt.date.today()
    rows = fmp.get_earnings_calendar((today - dt.timedelta(days=1)).isoformat(), today.isoformat())
    reported = {str(r.get("symbol", "")).upper() for r in rows}
    return sorted(active_tickers & reported)


def run(*, budget_usd: float | None = None, **_kwargs) -> dict:
    from stock_agents import notify
    from stock_agents.notify import formatter
    from stock_agents.track import run_track_status

    budget = budget_usd if budget_usd is not None else settings.daily_post_earnings_budget_usd
    active = {w.ticker for w in store.list_watchlist(include_exited=False) if w.status == "active"}
    reporters = _reporters_last_24h(active) if active else []

    spent, processed, material, failed, aborted = 0.0, 0, 0, 0, False
    for ticker in reporters:
        if settings.llm_backend != "claude_code" and spent >= budget:
            aborted = True
            notify.emit_alert(
                kind="cost_warning", severity="notice",
                subject="[post_earnings] daily budget reached",
                short=f"post_earnings stopped after ${spent:.2f} (ceiling ${budget}).",
            )
            break
        try:
            diff, snap = run_track_status(ticker)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            store.add_alert(kind="earnings_diff", severity="info", ticker=ticker,
                            message=f"post_earnings track-status failed for {ticker}: {exc}")
            continue
        processed += 1
        # Cost: the snapshot's run row carries cost; approximate via latest run.
        latest = store.list_runs(limit=1)
        if latest and latest[0].cost_estimate_usd:
            spent += latest[0].cost_estimate_usd

        if diff.status == "cannot_evaluate":
            store.add_alert(kind="earnings_diff", severity="info", ticker=ticker,
                            message=f"{ticker}: cannot evaluate post-earnings (retry next run)")
            continue
        if diff.is_material:
            material += 1
            subject, short, html = formatter.format_diff(diff)
            notify.emit_alert(kind="earnings_diff", severity="important", ticker=ticker,
                              subject=subject, short=short, html=html)

    return {
        "active": len(active), "reporters": len(reporters), "processed": processed,
        "material_alerts": material, "failed": failed, "budget_aborted": aborted,
        "spent_usd": round(spent, 4),
    }
