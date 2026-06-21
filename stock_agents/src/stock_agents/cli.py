"""Command-line interface.

stockagents analyze "AI infrastructure" --max-candidates 15 --output report.json
stockagents analyze "biotech" --backtest-date 2018-01-01
stockagents inspect NVDA
stockagents cost-report
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from stock_agents.config import settings

app = typer.Typer(
    add_completion=False,
    help="Multi-agent equity research pipeline (research tool, not a trading system).",
)
console = Console()


def _progress_printer():
    """Return a progress callback that logs pipeline stages to the console."""

    def cb(event: dict) -> None:
        stage = event.get("stage")
        if stage == "macro_start":
            console.log(f"[cyan]Macro overlay:[/cyan] {event['theme']}")
        elif stage == "macro_done":
            console.log(f"[green]Regime winners:[/green] {event['winners']}")
        elif stage == "screen_start":
            console.log(f"[cyan]Screening theme:[/cyan] {event['theme']}")
        elif stage == "rescreen":
            console.log(f"[yellow]Re-screening with feedback:[/yellow] {event['feedback']}")
        elif stage == "universe_filtered":
            console.log(
                f"[yellow]Point-in-time filter ({event['as_of']}): excluded not-yet-investable[/yellow] "
                f"{', '.join(event['excluded'])}"
            )
        elif stage == "screened":
            console.log(f"[green]Candidates:[/green] {', '.join(event['tickers'])}")
        elif stage == "analyst_start":
            console.log(f"  → analyzing {event['ticker']}")
        elif stage == "analyst_done":
            console.log(f"  [green]✓[/green] {event['ticker']} conviction={event['conviction']}")
        elif stage == "analyst_failed":
            console.log(f"  [red]✗[/red] {event['ticker']} failed: {event.get('errors')}")
        elif stage == "budget_abort":
            console.log(f"[red]Budget guard tripped at ${event['spent']:.2f} — stopping.[/red]")
        elif stage == "done":
            console.log(
                f"[bold]Run complete:[/bold] {event['analyzed']} analyzed, ${event['cost']:.2f}"
            )

    return cb


def _thesis_table(theses, title: str) -> Table:
    table = Table(title=title)
    table.add_column("Ticker", style="bold")
    table.add_column("Name")
    table.add_column("Conviction", justify="right")
    table.add_column("Label")
    table.add_column("F", justify="right")
    table.add_column("B", justify="right")
    table.add_column("M", justify="right")
    table.add_column("S", justify="right")
    for t in theses:
        table.add_row(
            t.ticker,
            (t.name or "")[:28],
            f"{t.conviction_score:.1f}",
            t.conviction_label,
            str(t.fundamentals_score),
            str(t.balance_sheet_score),
            str(t.management_score),
            str(t.stress_test_score),
        )
    return table


def _build_asym_filter(min_cap, max_cap, max_price, max_12m_return, currency):
    """Thin CLI wrapper around :func:`etf.build_filter` (shared with the API)."""
    from stock_agents.data import etf

    return etf.build_filter(
        min_market_cap_gbp=min_cap,
        max_market_cap_gbp=max_cap,
        max_price_gbp=max_price,
        max_12m_return_pct=max_12m_return,
        currency=currency or "gbp",
    )


@app.command()
def analyze(
    theme: str = typer.Argument(..., help="Investment theme, e.g. 'AI infrastructure'"),
    max_candidates: int = typer.Option(15, "--max-candidates"),
    output: Path | None = typer.Option(None, "--output", help="Write FinalReport JSON here"),
    backtest_date: str | None = typer.Option(
        None, "--backtest-date", help="Run point-in-time as of YYYY-MM-DD"
    ),
    budget: float | None = typer.Option(None, "--budget", help="Override per-run USD budget"),
    forensic: bool = typer.Option(
        False, "--forensic", help="Run the Forensic agent per candidate (~+$0.4-0.8 each)"
    ),
    min_market_cap_gbp: float | None = typer.Option(None, "--min-market-cap-gbp"),
    max_market_cap_gbp: float | None = typer.Option(None, "--max-market-cap-gbp"),
    max_price_gbp: float | None = typer.Option(None, "--max-price-gbp"),
    max_12m_return_pct: float | None = typer.Option(
        None,
        "--max-12m-return-pct",
        help="Drop names whose trailing 12-month price return exceeds this %% (anti-momentum)",
    ),
    currency: str = typer.Option("gbp", "--currency", help="gbp | usd (thresholds' currency)"),
):
    """Run the full pipeline on a theme (optionally as a historical backtest)."""
    asym = _build_asym_filter(
        min_market_cap_gbp,
        max_market_cap_gbp,
        max_price_gbp,
        max_12m_return_pct,
        currency,
    )

    if backtest_date:
        from stock_agents.backtesting.harness import run_backtest

        result = run_backtest(
            theme, backtest_date, max_candidates=max_candidates, progress=_progress_printer()
        )
        _print_backtest(result)
        if output:
            output.write_text(result.report.model_dump_json(indent=2))
            console.print(f"[dim]Report written to {output}[/dim]")
        return

    from stock_agents.agents import orchestrator

    report = orchestrator.analyze_theme(
        theme,
        max_candidates=max_candidates,
        progress=_progress_printer(),
        budget_usd=budget,
        asym=asym,
        forensic=forensic,
    )
    console.print(_thesis_table(report.top_picks, f"Top picks — {theme}"))
    if report.filter_note:
        console.print(f"[dim]{report.filter_note}[/dim]")
    if report.market_commentary:
        console.print(f"\n[italic]{report.market_commentary}[/italic]\n")
    console.print(f"[bold]API cost:[/bold] ${report.api_cost_usd:.2f}")
    if output:
        output.write_text(report.model_dump_json(indent=2))
        console.print(f"[dim]Full report written to {output}[/dim]")


@app.command()
def inspect(
    ticker: str = typer.Argument(..., help="Single ticker to analyze, e.g. NVDA"),
    forensic: bool = typer.Option(False, "--forensic", help="Also run the Forensic agent"),
):
    """Run the analyst pipeline on one user-specified ticker."""
    from stock_agents.agents import orchestrator

    thesis = orchestrator.analyze_ticker(ticker, forensic=forensic, progress=_progress_printer())
    if not thesis:
        console.print(f"[red]Analysis failed for {ticker.upper()}[/red]")
        raise typer.Exit(1)
    console.print(_thesis_table([thesis], ticker.upper()))
    if thesis.forensic_risk_score is not None:
        console.print(
            f"[bold]Forensic risk:[/bold] {thesis.forensic_risk_score}/10 (higher = riskier)"
        )
    console.print(f"\n[bold]Summary:[/bold] {thesis.one_paragraph_summary}\n")
    console.print("[green]Bull case:[/green]")
    for b in thesis.bull_case:
        console.print(f"  • {b}")
    console.print("[red]Bear case:[/red]")
    for b in thesis.bear_case:
        console.print(f"  • {b}")
    console.print(f"\n[bold]What would change my mind:[/bold] {thesis.what_would_change_my_mind}")


@app.command(name="cost-report")
def cost_report():
    """Show cumulative spend, split by backend.

    The Anthropic API backend reports metered dollars. The Claude Code (Max
    subscription) backend reports a usage-equivalent estimate that is NOT billed
    per-token — it draws on the subscription. Entries are distinguished by the
    ``@claude_code`` suffix recorded on the model name.
    """
    ledger = settings.audit_log_dir / "cost_ledger.jsonl"
    if not ledger.exists():
        console.print("No spend recorded yet.")
        return
    metered = 0.0  # real Anthropic API dollars
    equiv = 0.0  # Claude subscription usage-equivalent (not billed)
    runs = 0
    for line in ledger.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if str(rec.get("model", "")).endswith("@claude_code"):
            equiv += rec["cost_usd"]
        else:
            metered += rec["cost_usd"]
        runs += 1
    table = Table(title="Cumulative spend by backend")
    table.add_column("Backend")
    table.add_column("USD", justify="right")
    table.add_row("Anthropic API (metered, billed)", f"${metered:.4f}")
    table.add_row("Claude Code / Max (equivalent, not billed)", f"${equiv:.4f}")
    table.add_row("[bold]TOTAL (metered)[/bold]", f"[bold]${metered:.4f}[/bold]")
    console.print(table)
    console.print(f"[dim]{runs} agent invocations across all runs[/dim]")


def _print_backtest(result) -> None:
    table = Table(title=f"Backtest — {result.theme} as of {result.as_of_date}")
    table.add_column("Ticker", style="bold")
    table.add_column("Conviction", justify="right")
    table.add_column("Fwd 1Y %", justify="right")
    table.add_column("Fwd 3Y %", justify="right")
    table.add_column("Fwd 5Y %", justify="right")

    def fmt(v, delisted):
        return "delisted" if delisted else (f"{v:.1f}" if v is not None else "—")

    for r in result.rows:
        table.add_row(
            r.ticker,
            f"{r.conviction_score:.1f}",
            fmt(r.fwd_1y, r.delisted),
            fmt(r.fwd_3y, r.delisted),
            fmt(r.fwd_5y, r.delisted),
        )
    console.print(table)
    b = result
    console.print(
        f"[bold]Benchmark {b.benchmark_ticker}:[/bold] "
        f"1Y={b.benchmark_fwd_1y}, 3Y={b.benchmark_fwd_3y}, 5Y={b.benchmark_fwd_5y}"
    )
    for horizon in ("fwd_1y", "fwd_3y", "fwd_5y"):
        avg = result.top5_avg(horizon)
        console.print(f"  top-5 avg {horizon}: {avg if avg is None else round(avg, 1)}")
    console.print(
        "[yellow]Caveat:[/yellow] backtest disables web search and may carry survivorship "
        "and restatement leakage. Treat as indicative."
    )


# ---------------------------------------------------------------------------
# Watchlist & tracking (v2 Phase 1)
# ---------------------------------------------------------------------------


def _conv_color(score: float) -> str:
    if score < 40:
        return "dim"
    if score < 60:
        return "blue"
    if score < 80:
        return "green"
    return "bold green"


def _render_diff(diff) -> None:
    """Render a Diff with rich (no JSON dumps)."""
    head = "[red]MATERIAL CHANGE[/red]" if diff.is_material else "[dim]no material change[/dim]"
    console.print(f"\n[bold]{diff.ticker}[/bold] — {head}")
    if diff.status == "cannot_evaluate":
        console.print(
            "[red]Status: cannot_evaluate[/red] — fresh analysis did not produce a thesis."
        )
        for r in diff.material_reasons:
            console.print(f"  • {r}")
        return

    if diff.conviction_delta is not None:
        arrow = "▲" if diff.conviction_delta > 0 else ("▼" if diff.conviction_delta < 0 else "•")
        console.print(
            f"  Conviction: {diff.conviction_from:.1f} → "
            f"[{_conv_color(diff.conviction_to)}]{diff.conviction_to:.1f}[/] "
            f"({arrow} {diff.conviction_delta:+.1f})"
        )
    deltas = " ".join(f"{k[:4]}={v:+d}" for k, v in diff.component_deltas.items())
    console.print(f"  Component Δ: {deltas}")
    if diff.red_flags_available:
        if diff.new_red_flags:
            console.print(f"  [red]New red flags ({len(diff.new_red_flags)}):[/red]")
            for f in diff.new_red_flags:
                console.print(f"    • {f}")
        else:
            console.print("  Red flags: none new")
    else:
        console.print("  [dim]Red flags: n/a (entry thesis lacks per-agent reports)[/dim]")
    if diff.falsifiers_referenced:
        console.print("  [yellow]Entry falsifier(s) referenced by new bear case:[/yellow]")
        for f in diff.falsifiers_referenced:
            console.print(f"    • {f}")
    if diff.is_material:
        console.print("  [red]Material because:[/red] " + "; ".join(diff.material_reasons))


@app.command()
def track(
    ticker: str = typer.Argument(..., help="Ticker to track, e.g. NVDA"),
    thesis: str | None = typer.Option(
        None, "--thesis", help="Path to a FinalReport / thesis / snapshot JSON"
    ),
    entry_price: float | None = typer.Option(None, "--entry-price"),
    note: str | None = typer.Option(None, "--note"),
):
    """Add a ticker to the watchlist (from a report, or run a fresh inspect)."""
    from stock_agents import track as tracking

    try:
        entry = tracking.track_add(
            ticker,
            thesis_path=thesis,
            entry_price=entry_price,
            note=note,
            progress=_progress_printer(),
        )
    except tracking.TrackError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(
        f"[green]Tracking {entry.ticker}[/green] — entry conviction "
        f"[{_conv_color(entry.entry_conviction)}]{entry.entry_conviction:.1f}[/]"
        + (f", entry price {entry.entry_price}" if entry.entry_price else "")
    )


@app.command()
def watchlist():
    """Show the watchlist with entry vs current conviction."""
    from stock_agents import track as tracking

    rows = tracking.store.list_watchlist()
    if not rows:
        console.print("Watchlist is empty. Add one with `stockagents track TICKER`.")
        return
    table = Table(title="Watchlist")
    table.add_column("Ticker", style="bold")
    table.add_column("Status")
    table.add_column("Entry", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Δ", justify="right")
    table.add_column("Added")
    for w in rows:
        cur = tracking.current_conviction(w.ticker)
        delta = (cur - w.entry_conviction) if cur is not None else None
        cur_s = f"[{_conv_color(cur)}]{cur:.1f}[/]" if cur is not None else "—"
        delta_s = f"{delta:+.1f}" if delta is not None else "—"
        table.add_row(
            w.ticker, w.status, f"{w.entry_conviction:.1f}", cur_s, delta_s, w.added_at[:10]
        )
    console.print(table)


@app.command(name="track-status")
def track_status(ticker: str = typer.Argument(..., help="Tracked ticker to re-evaluate")):
    """Run a fresh inspect against a tracked ticker, store a snapshot, diff vs entry."""
    from stock_agents import track as tracking

    try:
        diff, _ = tracking.run_track_status(ticker, progress=_progress_printer())
    except tracking.TrackError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    _render_diff(diff)


@app.command(name="track-history")
def track_history(ticker: str = typer.Argument(..., help="Tracked ticker")):
    """Show the thesis snapshot history for a ticker."""
    from stock_agents import track as tracking

    rows = tracking.store.list_snapshot_rows(ticker)
    if not rows:
        console.print(f"No snapshots for {ticker.upper()}. Is it tracked?")
        return
    table = Table(title=f"{ticker.upper()} — thesis history")
    table.add_column("Taken")
    table.add_column("Conviction", justify="right")
    table.add_column("F", justify="right")
    table.add_column("B", justify="right")
    table.add_column("M", justify="right")
    table.add_column("S", justify="right")
    table.add_column("Run")
    for r in rows:
        table.add_row(
            r.taken_at[:19].replace("T", " "),
            f"[{_conv_color(r.conviction)}]{r.conviction:.1f}[/]",
            str(r.fundamentals_score or "—"),
            str(r.balance_sheet_score or "—"),
            str(r.management_score or "—"),
            str(r.stress_test_score or "—"),
            r.run_id[:10],
        )
    console.print(table)


@app.command()
def untrack(
    ticker: str = typer.Argument(...),
    reason: str | None = typer.Option(None, "--reason", help="Why you exited (kept in notes)"),
):
    """Mark a tracked ticker as exited (history is preserved)."""
    from stock_agents import track as tracking

    row = tracking.store.set_status(ticker, "exited", note=reason)
    if not row:
        console.print(f"[red]{ticker.upper()} is not tracked.[/red]")
        raise typer.Exit(1)
    console.print(
        f"[yellow]{row.ticker} marked exited.[/yellow]" + (f" Reason: {reason}" if reason else "")
    )


@app.command(name="track-pause")
def track_pause(ticker: str = typer.Argument(...)):
    """Pause monitoring for a ticker without removing it."""
    from stock_agents import track as tracking

    row = tracking.store.set_status(ticker, "paused")
    if not row:
        console.print(f"[red]{ticker.upper()} is not tracked.[/red]")
        raise typer.Exit(1)
    console.print(f"[yellow]{row.ticker} paused.[/yellow]")


@app.command(name="track-resume")
def track_resume(ticker: str = typer.Argument(...)):
    """Resume monitoring for a paused ticker."""
    from stock_agents import track as tracking

    row = tracking.store.set_status(ticker, "active")
    if not row:
        console.print(f"[red]{ticker.upper()} is not tracked.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]{row.ticker} active.[/green]")


# ---------------------------------------------------------------------------
# Automation + notifications (v2 Phase 4)
# ---------------------------------------------------------------------------


@app.command(name="run-job")
def run_job_cmd(
    name: str = typer.Argument(..., help="Job name (see `generate-cron`)"),
    summarize: bool = typer.Option(
        False, "--summarize", help="8-K monitor: add a 1-line Haiku summary per filing"
    ),
):
    """Run a single scheduled job once (used by cron and for testing)."""
    from stock_agents.automation import JOBS, run_job

    if name not in JOBS:
        console.print(f"[red]Unknown job {name!r}.[/red] Known: {', '.join(JOBS)}")
        raise typer.Exit(1)
    kwargs = {"summarize": summarize} if name == "eight_k_monitor" else {}
    result = run_job(name, **kwargs)
    color = "green" if result.get("status") == "success" else "red"
    console.print(f"[{color}]{name}: {result.get('status')}[/] (run {result.get('run_id')})")
    if result.get("error"):
        console.print(f"  [red]{result['error']}[/red]")


@app.command(name="generate-cron")
def generate_cron_cmd(
    write: bool = typer.Option(False, "--write", help="Write to automation/cron.sh"),
):
    """Print (or write) a crontab snippet that runs the scheduled jobs."""
    from stock_agents.automation import generate_cron_snippet, write_cron_snippet

    if write:
        path = write_cron_snippet()
        console.print(f"[green]Wrote {path}[/green]\nInstall with: [bold]crontab {path}[/bold]")
    else:
        console.print(generate_cron_snippet())


@app.command()
def daemon():
    """Run the in-process APScheduler daemon (alternative to cron)."""
    from stock_agents.automation import JOBS, start_daemon

    console.print(f"[cyan]Starting scheduler[/cyan] with {len(JOBS)} jobs:")
    for spec in JOBS.values():
        console.print(f"  [bold]{spec.name}[/bold] ({spec.cron}) — {spec.description}")
    console.print("[dim]Ctrl-C to stop.[/dim]")
    start_daemon()


@app.command(name="serve-api")
def serve_api(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8001, "--port"),
):
    """Run the FastAPI backend for the web UI (localhost:8001 by default)."""
    import uvicorn

    console.print(f"[cyan]Serving stock_agents API[/cyan] on http://{host}:{port}")
    uvicorn.run("stock_agents.api.main:app", host=host, port=port)


@app.command(name="notify-test")
def notify_test(
    message: str = typer.Option("stock_agents test notification", "--message"),
):
    """Send a test notification through the configured channel(s)."""
    from stock_agents import notify

    channels = notify.get_channels()
    if not channels:
        console.print("[red]No channels selected (check ALERT_CHANNEL).[/red]")
        raise typer.Exit(1)
    configured = [c.name for c in channels if c.configured()]
    if not configured:
        console.print(
            "[yellow]Selected channels are not configured[/yellow] "
            f"({', '.join(c.name for c in channels)}). "
            "Set PUSHOVER_* / SENDGRID_* in .env to enable delivery."
        )
        raise typer.Exit(1)
    results = notify.dispatch("stock_agents test", message, f"<p>{message}</p>")
    for name, ok in results.items():
        console.print(f"  {name}: {'[green]sent[/green]' if ok else '[red]failed/skipped[/red]'}")


if __name__ == "__main__":
    app()
