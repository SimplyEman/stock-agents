"""Generic Claude tool-use loop shared by every agent.

:class:`AgentRunner` drives the conversation: it calls the model, executes any
client-side tools, feeds results back, then parses and validates the final
message against a Pydantic schema. It tracks token usage / cost and writes a
JSONL audit record of every tool call so each run is reproducible and
attributable.

Output is forced to JSON via the system prompt (the schema is injected) and
parsed with ``model_validate_json``. On a validation failure the runner sends
one corrective message before giving up.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from anthropic import Anthropic
from pydantic import BaseModel, ValidationError

from stock_agents.config import MODEL_PRICING, settings
from stock_agents.tools.handlers import ToolContext

TModel = TypeVar("TModel", bound=BaseModel)

Handler = Callable[[dict, ToolContext], str]


class AgentError(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    def add(self, raw: Any) -> None:
        self.input_tokens += getattr(raw, "input_tokens", 0) or 0
        self.output_tokens += getattr(raw, "output_tokens", 0) or 0
        self.cache_write_tokens += getattr(raw, "cache_creation_input_tokens", 0) or 0
        self.cache_read_tokens += getattr(raw, "cache_read_input_tokens", 0) or 0

    def cost(self, model: str) -> float:
        p = MODEL_PRICING.get(model)
        if not p:
            return 0.0
        return (
            self.input_tokens * p["input"]
            + self.output_tokens * p["output"]
            + self.cache_write_tokens * p["cache_write"]
            + self.cache_read_tokens * p["cache_read"]
        ) / 1_000_000


@dataclass
class AgentResult:
    output: BaseModel | None
    cost_usd: float
    usage: Usage
    audit_log: list[dict] = field(default_factory=list)
    raw_text: str = ""
    model: str = ""
    error: str | None = None


# Module-level ledger so the CLI cost-report can sum across runs.
def _ledger_path() -> Path:
    settings.audit_log_dir.mkdir(parents=True, exist_ok=True)
    return settings.audit_log_dir / "cost_ledger.jsonl"


def record_cost(agent: str, model: str, cost: float, ticker: str | None = None) -> None:
    with _ledger_path().open("a") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": dt.datetime.now(dt.UTC).isoformat(),
                    "agent": agent,
                    "model": model,
                    "ticker": ticker,
                    "cost_usd": round(cost, 6),
                }
            )
            + "\n"
        )


class AgentRunner:
    """Runs one agent's tool-use loop to completion and validates output."""

    def __init__(
        self,
        model: str,
        tools: list[dict],
        handlers: dict[str, Handler],
        *,
        agent_name: str = "agent",
        client: Anthropic | None = None,
        max_tokens: int = 4096,
    ):
        self.model = model
        self.tools = tools
        self.handlers = handlers
        self.agent_name = agent_name
        self.max_tokens = max_tokens
        self.client = client or Anthropic(api_key=settings.anthropic_api_key or None)

    # -- public API --------------------------------------------------------

    def run(
        self,
        system: str,
        user_message: str,
        output_schema: type[TModel],
        *,
        max_iters: int = 12,
        ctx: ToolContext | None = None,
        ticker: str | None = None,
    ) -> AgentResult:
        ctx = ctx or ToolContext()

        # Delegate to the Claude subscription backend when selected. Same inputs,
        # same AgentResult contract — only the model transport differs.
        if settings.llm_backend == "claude_code":
            from stock_agents.agents import claude_code_backend

            result = claude_code_backend.run_agent(
                model=_cc_model_alias(self.model),
                tool_defs=self.tools,
                handlers=self.handlers,
                system=self._augment_system(system, output_schema),
                user_message=user_message,
                output_schema=output_schema,
                agent_name=self.agent_name,
                ctx=ctx,
                max_iters=max_iters,
                ticker=ticker,
            )
            self._write_audit(
                uuid.uuid4().hex[:12], ticker, result.audit_log, result.cost_usd, result.usage
            )
            return result

        usage = Usage()
        audit: list[dict] = []
        run_id = uuid.uuid4().hex[:12]

        system_blocks = [
            {
                "type": "text",
                "text": self._augment_system(system, output_schema),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

        parse_retries_left = 1
        final_text = ""

        # Build kwargs so `tools` is omitted entirely when empty. Passing
        # tools=None serializes to JSON null, which the API rejects with
        # "tools: Input should be a valid array" (hit by the tool-less synthesizer).
        base_kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_blocks,
        }
        if self.tools:
            base_kwargs["tools"] = self.tools

        for _ in range(max_iters):
            resp = self.client.messages.create(messages=messages, **base_kwargs)
            usage.add(resp.usage)
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason == "tool_use":
                tool_results = self._run_tools(resp.content, ctx, audit, run_id, ticker)
                messages.append({"role": "user", "content": tool_results})
                continue

            if resp.stop_reason == "pause_turn":
                # Server-side tool (web search) still working — continue the turn.
                continue

            final_text = self._extract_text(resp.content)

            # Try to parse/validate. On failure, give the model one correction.
            try:
                output = output_schema.model_validate_json(_extract_json(final_text))
                cost = usage.cost(self.model)
                self._write_audit(run_id, ticker, audit, cost, usage)
                record_cost(self.agent_name, self.model, cost, ticker)
                return AgentResult(
                    output=output,
                    cost_usd=cost,
                    usage=usage,
                    audit_log=audit,
                    raw_text=final_text,
                    model=self.model,
                )
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                if parse_retries_left <= 0:
                    cost = usage.cost(self.model)
                    self._write_audit(run_id, ticker, audit, cost, usage)
                    record_cost(self.agent_name, self.model, cost, ticker)
                    return AgentResult(
                        output=None,
                        cost_usd=cost,
                        usage=usage,
                        audit_log=audit,
                        raw_text=final_text,
                        model=self.model,
                        error=f"schema validation failed: {exc}",
                    )
                parse_retries_left -= 1
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous message did not parse as valid JSON matching "
                            f"the required schema. Error: {exc}\n\n"
                            "Reply with ONLY the corrected JSON object — no prose, no "
                            "markdown fences."
                        ),
                    }
                )
                continue

        # Ran out of iterations.
        cost = usage.cost(self.model)
        self._write_audit(run_id, ticker, audit, cost, usage)
        record_cost(self.agent_name, self.model, cost, ticker)
        return AgentResult(
            output=None,
            cost_usd=cost,
            usage=usage,
            audit_log=audit,
            raw_text=final_text,
            model=self.model,
            error=f"max_iters ({max_iters}) reached without final output",
        )

    # -- internals ---------------------------------------------------------

    def _augment_system(self, system: str, schema: type[BaseModel]) -> str:
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        return (
            f"{system}\n\n"
            "## Output contract\n"
            "Your FINAL message must be a single JSON object — no markdown fences, no "
            "commentary before or after — conforming exactly to this JSON schema:\n\n"
            f"{schema_json}\n\n"
            "Use tools first to gather evidence, then emit the JSON. Numbers must be "
            "real figures derived from tool results, never invented."
        )

    def _run_tools(
        self,
        content: list[Any],
        ctx: ToolContext,
        audit: list[dict],
        run_id: str,
        ticker: str | None,
    ) -> list[dict]:
        results: list[dict] = []
        for block in content:
            if getattr(block, "type", None) != "tool_use":
                continue
            name = block.name
            handler = self.handlers.get(name)
            entry: dict[str, Any] = {
                "run_id": run_id,
                "agent": self.agent_name,
                "ticker": ticker,
                "tool": name,
                "input": block.input,
                "ts": dt.datetime.now(dt.UTC).isoformat(),
            }
            if handler is None:
                # Unknown / server-side tool reached the client loop — report back.
                result_text = json.dumps({"error": f"no handler for tool {name}"})
                entry["error"] = "no handler"
            else:
                try:
                    result_text = handler(block.input, ctx)
                    entry["ok"] = True
                except Exception as exc:  # surface tool errors to the model, don't crash
                    result_text = json.dumps({"error": str(exc)})
                    entry["error"] = str(exc)
            entry["result_chars"] = len(result_text)
            entry["accessions"] = extract_accessions(
                result_text, json.dumps(block.input, default=str)
            )
            audit.append(entry)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})
        return results

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        parts = [b.text for b in content if getattr(b, "type", None) == "text"]
        return "\n".join(parts).strip()

    def _write_audit(
        self, run_id: str, ticker: str | None, audit: list[dict], cost: float, usage: Usage
    ) -> None:
        settings.audit_log_dir.mkdir(parents=True, exist_ok=True)
        path = settings.audit_log_dir / "tool_calls.jsonl"
        with path.open("a") as fh:
            for entry in audit:
                fh.write(json.dumps(entry) + "\n")
            fh.write(
                json.dumps(
                    {
                        "run_id": run_id,
                        "agent": self.agent_name,
                        "ticker": ticker,
                        "summary": True,
                        "cost_usd": round(cost, 6),
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "cache_read_tokens": usage.cache_read_tokens,
                    }
                )
                + "\n"
            )


def _cc_model_alias(model: str) -> str:
    """Map a full Anthropic model id to the short alias the `claude` CLI expects."""
    m = model.lower()
    if "opus" in m:
        return "opus"
    if "haiku" in m:
        return "haiku"
    return "sonnet"


_ACCESSION_RE = re.compile(r"\d{10}-\d{2}-\d{6}")


def extract_accessions(*texts: str) -> list[str]:
    """Pull SEC accession numbers (NNNNNNNNNN-NN-NNNNNN) out of arbitrary text.

    Used to record which filings a tool call actually surfaced, so the Forensic
    agent's citations can be checked against real fetched filings (anti-hallucination).
    """
    found: set[str] = set()
    for t in texts:
        if t:
            found.update(_ACCESSION_RE.findall(t))
    return sorted(found)


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> str:
    """Pull the JSON object out of a model reply, tolerating fences/preamble."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError("no JSON object found in model output")
    return m.group(0)
