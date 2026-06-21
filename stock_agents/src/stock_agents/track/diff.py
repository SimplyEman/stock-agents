"""Material-change detection between two thesis snapshots.

A change is *material* (alert-worthy) if any of (per the v2 spec):
- composite conviction moved >= 15 points either direction
- any component score moved >= 3 (1-10 scale)
- a new red flag appeared in any agent's report (only checkable when both
  snapshots carry analyst reports; otherwise this dimension is skipped)
- an entry-thesis falsifier ("what would change my mind") is referenced by the
  new bear case (substring match — imperfect but useful)
- status is cannot_evaluate (the fresh inspect could not produce a thesis)

Everything else is a quiet diff: recorded for history, not alerted.
"""

from __future__ import annotations

import re

from stock_agents.track.models import Diff, ThesisSnapshot

CONVICTION_THRESHOLD = 15.0
COMPONENT_THRESHOLD = 3
_COMPONENTS = ("fundamentals", "balance_sheet", "management", "stress_test")

# Stopwords so falsifier substring matching keys on meaningful phrases.
_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "and", "or", "if", "is", "are", "be",
    "would", "could", "my", "mind", "change", "this", "that", "for", "with", "as",
    "it", "its", "their", "than", "from", "by", "at", "we", "i",
}


def cannot_evaluate(ticker: str, from_id: str | None, reason: str) -> Diff:
    return Diff(
        ticker=ticker.upper(),
        from_snapshot_id=from_id,
        to_snapshot_id=None,
        status="cannot_evaluate",
        material_reasons=[f"cannot_evaluate: {reason}"],
    )


def _phrases(text: str, min_words: int = 3) -> list[str]:
    """Extract candidate falsifier phrases (clauses) from free text."""
    out: list[str] = []
    for clause in re.split(r"[.;:\n]| - |—|–", text):
        words = [w for w in re.findall(r"[a-zA-Z0-9%$]+", clause.lower())]
        content = [w for w in words if w not in _STOP]
        if len(content) >= min_words:
            out.append(" ".join(words))
    return out


def _falsifier_hits(entry: ThesisSnapshot, new: ThesisSnapshot) -> list[str]:
    """Entry falsifier phrases whose key terms now show up in the new bear case."""
    falsifier_text = entry.thesis.what_would_change_my_mind or ""
    bear_blob = " ".join(new.thesis.bear_case).lower()
    if not falsifier_text or not bear_blob:
        return []
    hits: list[str] = []
    for phrase in _phrases(falsifier_text):
        key_terms = [w for w in phrase.split() if w not in _STOP and len(w) > 3]
        if not key_terms:
            continue
        matched = sum(1 for w in key_terms if w in bear_blob)
        # Treat a falsifier as "referenced" when a majority of its key terms
        # (and at least two) appear in the new bear case.
        if matched >= 2 and matched >= len(key_terms) / 2:
            hits.append(phrase)
    return hits


def compute_diff(entry: ThesisSnapshot, new: ThesisSnapshot) -> Diff:
    et, nt = entry.thesis, new.thesis
    reasons: list[str] = []

    conviction_delta = round(nt.conviction_score - et.conviction_score, 1)
    if abs(conviction_delta) >= CONVICTION_THRESHOLD:
        reasons.append(
            f"conviction moved {conviction_delta:+.1f} ({et.conviction_score:.1f} -> {nt.conviction_score:.1f})"
        )

    component_deltas: dict[str, int] = {}
    for comp in _COMPONENTS:
        delta = getattr(nt, f"{comp}_score") - getattr(et, f"{comp}_score")
        component_deltas[comp] = delta
        if abs(delta) >= COMPONENT_THRESHOLD:
            reasons.append(f"{comp} score moved {delta:+d}")

    # Red flags only when both snapshots carry analyst reports.
    red_flags_available = entry.has_analyst_reports and new.has_analyst_reports
    new_red_flags: list[str] = []
    if red_flags_available:
        old = {f.strip().lower() for f in entry.red_flags()}
        for flag in new.red_flags():
            if flag.strip().lower() not in old:
                new_red_flags.append(flag)
        if new_red_flags:
            reasons.append(f"{len(new_red_flags)} new red flag(s)")

    falsifiers = _falsifier_hits(entry, new)
    if falsifiers:
        reasons.append("entry falsifier referenced by new bear case")

    return Diff(
        ticker=nt.ticker.upper(),
        from_snapshot_id=entry.id,
        to_snapshot_id=new.id,
        status="ok",
        conviction_from=et.conviction_score,
        conviction_to=nt.conviction_score,
        conviction_delta=conviction_delta,
        component_deltas=component_deltas,
        red_flags_available=red_flags_available,
        new_red_flags=new_red_flags,
        falsifiers_referenced=falsifiers,
        material_reasons=reasons,
    )
