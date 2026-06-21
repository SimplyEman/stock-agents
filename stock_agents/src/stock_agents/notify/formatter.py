"""Render alerts into human-readable short (Pushover) + long (email) forms.

Takes a tracking :class:`Diff` or an 8-K filing and produces a ``(subject, short,
html)`` tuple. The 8-K item-code → description map is hardcoded (no LLM needed).
"""

from __future__ import annotations

from stock_agents.track.models import Diff

# SEC 8-K item codes worth alerting on (v2 Phase 5 uses the same map).
EIGHT_K_ITEMS: dict[str, str] = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.04": "Triggering Events Accelerating a Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financials",
    "5.02": "Departure/Election of Directors or Officers",
    "5.03": "Amendments to Articles or Bylaws",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
}


def describe_items(item_numbers: str | None) -> list[str]:
    if not item_numbers:
        return []
    out = []
    for code in [c.strip() for c in item_numbers.split(",") if c.strip()]:
        out.append(f"Item {code} ({EIGHT_K_ITEMS.get(code, 'Other')})")
    return out


def format_diff(diff: Diff) -> tuple[str, str, str]:
    """Render a tracking Diff. Returns (subject, short_text, html)."""
    if diff.status == "cannot_evaluate":
        subject = f"[{diff.ticker}] cannot evaluate"
        short = f"{diff.ticker}: fresh analysis could not produce a thesis. " + "; ".join(
            diff.material_reasons
        )
        html = f"<h3>{diff.ticker} — cannot evaluate</h3><ul>" + "".join(
            f"<li>{r}</li>" for r in diff.material_reasons
        ) + "</ul>"
        return subject, short, html

    tag = "MATERIAL" if diff.is_material else "quiet"
    conv = ""
    if diff.conviction_delta is not None:
        conv = f" conviction {diff.conviction_from:.0f}->{diff.conviction_to:.0f} ({diff.conviction_delta:+.0f})"
    subject = f"[{diff.ticker}] {tag} thesis change{conv}"
    short = f"{diff.ticker}: {tag}.{conv}"
    if diff.material_reasons:
        short += " " + "; ".join(diff.material_reasons)
    short = short[:240]

    rows = "".join(f"<li>{k}: {v:+d}</li>" for k, v in diff.component_deltas.items())
    flags = (
        "".join(f"<li>{f}</li>" for f in diff.new_red_flags)
        if diff.new_red_flags
        else "<li>none new</li>"
        if diff.red_flags_available
        else "<li>n/a (entry lacks per-agent reports)</li>"
    )
    html = (
        f"<h3>{diff.ticker} — {tag} thesis change</h3>"
        f"<p>{conv.strip() or 'conviction unchanged'}</p>"
        f"<p><b>Component deltas</b></p><ul>{rows}</ul>"
        f"<p><b>New red flags</b></p><ul>{flags}</ul>"
    )
    if diff.falsifiers_referenced:
        html += "<p><b>Entry falsifiers now in the bear case</b></p><ul>" + "".join(
            f"<li>{f}</li>" for f in diff.falsifiers_referenced
        ) + "</ul>"
    if diff.material_reasons:
        html += "<p><b>Material because</b></p><ul>" + "".join(
            f"<li>{r}</li>" for r in diff.material_reasons
        ) + "</ul>"
    return subject, short, html


def format_eight_k(ticker: str, item_numbers: str | None, url: str) -> tuple[str, str, str]:
    """Render an 8-K alert. Returns (subject, short_text, html)."""
    items = describe_items(item_numbers)
    primary = items[0] if items else "8-K filed"
    subject = f"[{ticker}] 8-K filed: {primary}"
    short = f"{ticker} 8-K: {primary} — {url}"[:240]
    html = (
        f"<h3>{ticker} — 8-K filed</h3><ul>"
        + "".join(f"<li>{it}</li>" for it in items or ["8-K"])
        + f"</ul><p><a href=\"{url}\">{url}</a></p>"
    )
    return subject, short, html
