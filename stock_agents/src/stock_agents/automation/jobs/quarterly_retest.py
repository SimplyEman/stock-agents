"""quarterly_retest job.

Quarterly (Jan/Apr/Jul/Oct 1, 04:00). For each position in the Lidia I portfolio
manifest, runs the full analyst pipeline (forensic on), diffs conviction +
component scores + forensic risk against the manifest baseline, and emits a
``portfolio_drift`` alert per position whose conviction shifts >=5 points or
whose forensic risk increases >=2 levels. Writes a digest JSON under
``data/reports/quarterly/{YYYY-MM-DD}.json`` for human review.

Manifest path: ``data/portfolios/lidia_i.json``. Multiple manifests can coexist;
the job iterates every ``*.json`` file in ``data/portfolios/``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from stock_agents import notify
from stock_agents.agents import orchestrator
from stock_agents.config import settings

log = logging.getLogger("stock_agents.automation")

CONVICTION_TRIGGER = 5.0
FORENSIC_TRIGGER = 2
STRESS_TRIGGER = 2


def _load_portfolios() -> list[dict]:
    pdir = settings.data_dir / "portfolios"
    if not pdir.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(pdir.glob("*.json"))]


def _retest_position(pos: dict) -> dict:
    ticker = pos["ticker"]
    log.info("retest %s", ticker)
    try:
        result = orchestrator.analyze_ticker_detailed(ticker, forensic=True)
    except Exception as exc:  # noqa: BLE001 - per-ticker resilience
        return {"ticker": ticker, "error": str(exc)}

    thesis = result.thesis
    if thesis is None:
        return {"ticker": ticker, "error": "no thesis (synthesizer failure)"}

    current = {
        "conviction": thesis.conviction_score,
        "forensic_risk": thesis.forensic_risk_score,
        "fundamentals": result.fundamentals.score_1_to_10 if result.fundamentals else None,
        "balance_sheet": result.balance_sheet.score_1_to_10 if result.balance_sheet else None,
        "management": result.management.score_1_to_10 if result.management else None,
        "stress_test": (
            result.stress_test.survivability_score_1_to_10 if result.stress_test else None
        ),
    }
    baseline_conv = pos.get("baseline_conviction")
    baseline_for = pos.get("baseline_forensic")

    triggers: list[str] = []
    delta_conv = (
        None if baseline_conv is None else round(current["conviction"] - baseline_conv, 1)
    )
    if delta_conv is not None and abs(delta_conv) >= CONVICTION_TRIGGER:
        triggers.append(f"conviction shifted {delta_conv:+.1f} (baseline {baseline_conv})")
    if (
        baseline_for is not None
        and current["forensic_risk"] is not None
        and (current["forensic_risk"] - baseline_for) >= FORENSIC_TRIGGER
    ):
        triggers.append(
            f"forensic risk increased {baseline_for} -> {current['forensic_risk']}"
        )

    return {
        "ticker": ticker,
        "sleeve": pos.get("sleeve"),
        "weight_pct": pos.get("weight_pct"),
        "baseline_conviction": baseline_conv,
        "baseline_forensic": baseline_for,
        "current": current,
        "delta_conviction": delta_conv,
        "triggers": triggers,
        "kill_criteria": pos.get("kill_criteria"),
        "cost_usd": result.cost_usd,
    }


def run(**_kwargs) -> dict:
    portfolios = _load_portfolios()
    if not portfolios:
        log.warning("quarterly_retest: no portfolio manifests under data/portfolios/")
        return {"portfolios": 0, "positions": 0, "alerts": 0, "spent_usd": 0.0}

    today = datetime.now(timezone.utc).date().isoformat()
    out_dir = settings.data_dir / "reports" / "quarterly"
    out_dir.mkdir(parents=True, exist_ok=True)

    spent = 0.0
    total_positions = 0
    total_alerts = 0
    digest = {"date": today, "portfolios": []}

    for portfolio in portfolios:
        rows: list[dict] = []
        for pos in portfolio["positions"]:
            row = _retest_position(pos)
            spent += float(row.get("cost_usd") or 0)
            total_positions += 1
            rows.append(row)
            if row.get("triggers"):
                total_alerts += 1
                notify.emit_alert(
                    kind="portfolio_drift", severity="important",
                    subject=f"[{portfolio['name']}] {row['ticker']} drift",
                    short=" | ".join(row["triggers"])[:240],
                    html=(
                        f"<h3>{portfolio['name']} / {row['ticker']}</h3>"
                        f"<p>{' | '.join(row['triggers'])}</p>"
                        f"<p>Kill criteria: {row.get('kill_criteria','')}</p>"
                    ),
                )
        digest["portfolios"].append({"name": portfolio["name"], "rows": rows})

    digest_path = out_dir / f"{today}.json"
    digest_path.write_text(json.dumps(digest, indent=2, default=str))
    log.info(
        "quarterly_retest: %d positions across %d portfolios, %d alerts, $%.2f equiv, digest -> %s",
        total_positions, len(portfolios), total_alerts, spent, digest_path,
    )

    return {
        "portfolios": len(portfolios),
        "positions": total_positions,
        "alerts": total_alerts,
        "digest_path": str(digest_path.relative_to(settings.data_dir)),
        "spent_usd": spent,
    }
