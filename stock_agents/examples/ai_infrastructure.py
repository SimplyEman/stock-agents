"""Reference end-to-end run on the 'AI infrastructure' theme.

Run with:

    uv run python examples/ai_infrastructure.py

Requires ANTHROPIC_API_KEY and FMP_API_KEY in your environment / .env. This
makes real API calls and will cost a few dollars; the budget guard caps spend
at RUN_BUDGET_USD (default $5).
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from stock_agents.agents import orchestrator

console = Console()


def main() -> None:
    def progress(event: dict) -> None:
        console.log(event)

    report = orchestrator.analyze_theme(
        "AI infrastructure",
        max_candidates=12,
        progress=progress,
    )

    out = Path("ai_infrastructure.report.json")
    out.write_text(report.model_dump_json(indent=2))
    console.rule("Top picks")
    for thesis in report.top_picks:
        console.print(
            f"[bold]{thesis.ticker}[/bold] — {thesis.name}: "
            f"{thesis.conviction_score:.1f} ({thesis.conviction_label})"
        )
        console.print(f"  {thesis.one_paragraph_summary}\n")
    console.print(f"\nMarket commentary: {report.market_commentary}")
    console.print(f"Total API cost: ${report.api_cost_usd:.2f}")
    console.print(f"Full report written to {out}")
    # Echo the structured top pick so the schema is visible in the example output.
    if report.top_picks:
        console.print_json(json.dumps(report.top_picks[0].model_dump()))


if __name__ == "__main__":
    main()
