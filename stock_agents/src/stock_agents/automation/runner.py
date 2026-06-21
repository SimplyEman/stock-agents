"""Job runner + scheduler (v2 Phase 4).

Two execution modes:
- **cron** (default): ``generate_cron_snippet()`` emits crontab lines that invoke
  ``stockagents run-job <name>``.
- **in-process APScheduler**: ``start_daemon()`` runs a blocking scheduler that
  fires the jobs on their cron schedules.

Every job runs through :func:`run_job`, which records a ``runs`` row before
starting and, on failure, writes an ``important`` alert and notifies. Jobs are
idempotent stubs in Phase 4; Phase 5 fills in the bodies.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from stock_agents.automation.jobs import (
    eight_k_monitor,
    post_earnings,
    quarterly_retest,
    sunday_batch,
    weekly_cache_warm,
)
from stock_agents.track import store

log = logging.getLogger("stock_agents.automation")


@dataclass
class JobSpec:
    name: str
    func: Callable[[], dict]
    cron: str  # standard 5-field crontab expression
    description: str


JOBS: dict[str, JobSpec] = {
    "post_earnings": JobSpec(
        "post_earnings", post_earnings.run, "0 6 * * *",
        "Re-analyze watchlist tickers that reported in the last 24h (daily 06:00)",
    ),
    "eight_k_monitor": JobSpec(
        "eight_k_monitor", eight_k_monitor.run, "*/30 * * * *",
        "Watch EDGAR 8-K feed for watchlist tickers (every 30 min)",
    ),
    "weekly_cache_warm": JobSpec(
        "weekly_cache_warm", weekly_cache_warm.run, "0 2 * * 0",
        "Refresh fundamentals/filings/ETF caches (Sundays 02:00)",
    ),
    "sunday_batch": JobSpec(
        "sunday_batch", sunday_batch.run, "0 4 * * 0",
        "Run the weekly batch theme analyses + digest (Sundays 04:00)",
    ),
    "quarterly_retest": JobSpec(
        "quarterly_retest", quarterly_retest.run, "0 4 1 1,4,7,10 *",
        "Retest every portfolio manifest under data/portfolios/ (Jan/Apr/Jul/Oct 1, 04:00)",
    ),
}


def run_job(name: str, **kwargs) -> dict:
    """Execute one job by name, wrapped in a runs row + failure alerting.

    ``kwargs`` are forwarded to the job body (e.g. ``summarize=True`` for the
    8-K monitor). Returns the job's result dict (with ``run_id`` and ``status``
    added). Never raises — a failure is recorded as a failed run and an
    ``important`` alert.
    """
    spec = JOBS.get(name)
    if spec is None:
        raise KeyError(f"unknown job {name!r}; known: {', '.join(JOBS)}")

    run = store.start_run(kind=name)
    log.info("job %s started (run %s)", name, run.id)
    try:
        result = spec.func(**kwargs) or {}
        store.finish_run(run.id, status="success", cost_estimate_usd=result.get("spent_usd"))
        log.info("job %s success (run %s)", name, run.id)
        return {**result, "run_id": run.id, "status": "success"}
    except Exception as exc:  # noqa: BLE001 - jobs must never crash the scheduler
        store.finish_run(run.id, status="failed", error=str(exc))
        log.exception("job %s failed (run %s)", name, run.id)
        from stock_agents import notify

        notify.emit_alert(
            kind="run_failure", severity="important",
            subject=f"[job:{name}] failed",
            short=f"Scheduled job {name} failed: {exc}"[:240],
            html=f"<h3>Job {name} failed</h3><pre>{exc}</pre>",
        )
        return {"run_id": run.id, "status": "failed", "error": str(exc)}


def generate_cron_snippet() -> str:
    """Return a crontab snippet that runs each job via the installed CLI."""
    project = Path.cwd()
    binary = Path(sys.executable).parent / "stockagents"
    lines = [
        "# stock_agents v2 — scheduled jobs.",
        "# Review paths, then install with:  crontab automation/cron.sh",
        f"# (generated for project at {project})",
        "",
    ]
    for spec in JOBS.values():
        lines.append(f"# {spec.description}")
        lines.append(
            f"{spec.cron} cd {project} && {binary} run-job {spec.name} "
            f">> {project / 'automation' / 'cron.log'} 2>&1"
        )
        lines.append("")
    return "\n".join(lines)


def write_cron_snippet(path: Path | None = None) -> Path:
    path = path or (Path.cwd() / "automation" / "cron.sh")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_cron_snippet())
    return path


def build_scheduler():
    """Build a BlockingScheduler with every job registered on its cron trigger."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler()
    for spec in JOBS.values():
        scheduler.add_job(
            run_job, CronTrigger.from_crontab(spec.cron), args=[spec.name],
            id=spec.name, name=spec.description, replace_existing=True,
        )
    return scheduler


def start_daemon() -> None:  # pragma: no cover - long-running
    scheduler = build_scheduler()
    log.info("starting scheduler with %d jobs", len(JOBS))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler stopped")
