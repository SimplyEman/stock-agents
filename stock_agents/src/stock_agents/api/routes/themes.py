"""Theme endpoints (v2 Phase 6)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks

from stock_agents.api.schemas import RunIdResponse, ThemeView
from stock_agents.config import settings
from stock_agents.data.etf import THEME_REGISTRY
from stock_agents.track import store

router = APIRouter(prefix="/api/themes", tags=["themes"])


def _latest_analyze(theme: str):
    for r in store.list_runs(limit=200):
        if r.kind == "analyze" and r.theme == theme and r.status == "success" and r.report_path:
            return r
    return None


@router.get("")
def list_themes() -> list[ThemeView]:
    out = []
    for theme, etfs in THEME_REGISTRY.items():
        run = _latest_analyze(theme)
        top5: list[str] = []
        if run:
            path = settings.data_dir / run.report_path
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    top5 = [t["ticker"] for t in data.get("top_picks", [])][:5]
                except Exception:  # noqa: BLE001
                    pass
        out.append(ThemeView(theme=theme, etfs=etfs,
                             last_analyzed=run.finished_at if run else None, top5=top5))
    return out


@router.post("/{theme}/analyze")
def analyze_theme_endpoint(
    theme: str,
    background: BackgroundTasks,
    max_candidates: int = 5,
    forensic: bool = False,
    min_market_cap_gbp: float | None = None,
    max_market_cap_gbp: float | None = None,
    max_price_gbp: float | None = None,
    max_12m_return_pct: float | None = None,
    currency: str = "gbp",
) -> RunIdResponse:
    from stock_agents.data import etf as _etf

    asym = _etf.build_filter(
        min_market_cap_gbp=min_market_cap_gbp, max_market_cap_gbp=max_market_cap_gbp,
        max_price_gbp=max_price_gbp, max_12m_return_pct=max_12m_return_pct,
        currency=currency,
    )
    run = store.start_run(kind="analyze", theme=theme)

    def _job():
        from stock_agents.agents import orchestrator

        try:
            report = orchestrator.analyze_theme(
                theme, max_candidates=max_candidates, asym=asym, forensic=forensic,
            )
            rel = Path("reports/api") / f"{run.id}.json"
            abs_path = settings.data_dir / rel
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(report.model_dump_json(indent=2))
            store.finish_run(run.id, status="success",
                             cost_estimate_usd=report.api_cost_usd, report_path=str(rel))
        except Exception as exc:  # noqa: BLE001
            store.finish_run(run.id, status="failed", error=str(exc))

    background.add_task(_job)
    return RunIdResponse(run_id=run.id, status="running")
