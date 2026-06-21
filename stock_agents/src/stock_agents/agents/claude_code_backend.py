"""Claude Code backend — run agents on a Claude Max subscription via the Agent SDK.

Instead of metered Anthropic API calls (``anthropic.Anthropic().messages.create``),
this backend drives the ``claude`` CLI through the Claude Agent SDK. Model usage
then counts against the user's Claude subscription rather than per-token API
dollars. The existing tool handlers are bridged into the SDK as in-process MCP
tools, so the data layer and tool logic are reused unchanged.

Auth note: a present ``ANTHROPIC_API_KEY`` makes the CLI bill the API instead of
the subscription, so it is stripped from the subprocess environment here.

The reported ``cost_usd`` is the SDK's subscription-equivalent figure
(``ResultMessage.total_cost_usd``) — useful for relative comparison, but NOT a
metered charge. The cost ledger tags these entries as ``claude_code`` so
``cost-report`` can keep them separate from real API spend.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import uuid
from typing import Any

import claude_agent_sdk as sdk
from pydantic import BaseModel, ValidationError

from stock_agents.agents.base import AgentResult, Usage, _extract_json, record_cost
from stock_agents.tools.handlers import ToolContext

_MCP_SERVER = "stockdata"


def _is_web_search(tool_def: dict) -> bool:
    return tool_def.get("type", "").startswith("web_search")


def _build_sdk_tools(
    tool_defs: list[dict],
    handlers: dict,
    ctx: ToolContext,
    audit: list[dict],
    run_id: str,
    agent_name: str,
    ticker: str | None,
) -> list:
    sdk_tools = []
    for d in tool_defs:
        name = d.get("name")
        if not name or name not in handlers:
            continue
        handler = handlers[name]

        def make(h, tool_name):
            async def fn(args: dict[str, Any]) -> dict[str, Any]:
                entry = {
                    "run_id": run_id,
                    "agent": agent_name,
                    "ticker": ticker,
                    "tool": tool_name,
                    "input": args,
                    "ts": dt.datetime.now(dt.UTC).isoformat(),
                    "backend": "claude_code",
                }
                try:
                    text = h(args, ctx)
                    entry["ok"] = True
                except Exception as exc:  # surface tool errors to the model
                    text = json.dumps({"error": str(exc)})
                    entry["error"] = str(exc)
                entry["result_chars"] = len(text)
                from stock_agents.agents.base import extract_accessions

                entry["accessions"] = extract_accessions(text, json.dumps(args, default=str))
                audit.append(entry)
                return {"content": [{"type": "text", "text": text}]}

            return fn

        sdk_tools.append(sdk.tool(name, d["description"], d["input_schema"])(make(handler, name)))
    return sdk_tools


def _subprocess_env() -> dict[str, str]:
    # Strip ANTHROPIC_API_KEY so the CLI uses the Claude subscription, not the API.
    return {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}


async def _run_async(
    *,
    system: str,
    user_message: str,
    tool_defs: list[dict],
    handlers: dict,
    model: str,
    output_schema: type[BaseModel],
    ctx: ToolContext,
    max_iters: int,
    agent_name: str,
    ticker: str | None,
) -> tuple[str, dict, float, list[dict]]:
    run_id = uuid.uuid4().hex[:12]
    audit: list[dict] = []
    sdk_tools = _build_sdk_tools(tool_defs, handlers, ctx, audit, run_id, agent_name, ticker)
    allowed = [f"mcp__{_MCP_SERVER}__{t['name']}" for t in tool_defs if t.get("name") in handlers]
    # Allow Claude Code's built-in web search where the agent declared it.
    if any(_is_web_search(t) for t in tool_defs):
        allowed.append("WebSearch")

    options = sdk.ClaudeAgentOptions(
        system_prompt=system,
        model=model,
        mcp_servers={_MCP_SERVER: sdk.create_sdk_mcp_server(_MCP_SERVER, tools=sdk_tools)},
        allowed_tools=allowed,
        max_turns=max_iters,
        permission_mode="bypassPermissions",
        setting_sources=[],  # don't load the repo's CLAUDE.md into the analyst's context
        env=_subprocess_env(),
    )

    final = ""
    usage: dict = {}
    cost = 0.0
    # The SDK RAISES (rather than returning a ResultMessage) on conditions like
    # "Reached maximum number of turns". Catch it so a single agent hitting the
    # cap degrades to an empty/partial result instead of crashing the whole run;
    # any text captured from assistant messages before the stop is preserved.
    try:
        async for msg in sdk.query(prompt=user_message, options=options):
            if isinstance(msg, sdk.AssistantMessage):
                for block in msg.content:
                    if isinstance(block, sdk.TextBlock) and block.text:
                        final = block.text
            elif isinstance(msg, sdk.ResultMessage):
                final = msg.result or final
                usage = msg.usage or {}
                cost = msg.total_cost_usd or 0.0
    except Exception as exc:  # SDK signals max-turns / transport issues by raising
        audit.append(
            {
                "run_id": run_id,
                "agent": agent_name,
                "ticker": ticker,
                "backend": "claude_code",
                "error": str(exc),
                "ts": dt.datetime.now(dt.UTC).isoformat(),
            }
        )
    return final, usage, cost, audit


def run_agent(
    *,
    model: str,
    tool_defs: list[dict],
    handlers: dict,
    system: str,
    user_message: str,
    output_schema: type[BaseModel],
    agent_name: str,
    ctx: ToolContext | None = None,
    max_iters: int = 12,
    ticker: str | None = None,
) -> AgentResult:
    """Run one agent on the Claude subscription and validate its JSON output."""
    ctx = ctx or ToolContext()

    def _go(extra: str = "") -> tuple[str, dict, float, list[dict]]:
        return asyncio.run(
            _run_async(
                system=system + extra,
                user_message=user_message,
                tool_defs=tool_defs,
                handlers=handlers,
                model=model,
                output_schema=output_schema,
                ctx=ctx,
                max_iters=max_iters,
                agent_name=agent_name,
                ticker=ticker,
            )
        )

    final, raw_usage, cost, audit = _go()
    usage = Usage(
        input_tokens=raw_usage.get("input_tokens", 0) or 0,
        output_tokens=raw_usage.get("output_tokens", 0) or 0,
        cache_write_tokens=raw_usage.get("cache_creation_input_tokens", 0) or 0,
        cache_read_tokens=raw_usage.get("cache_read_input_tokens", 0) or 0,
    )

    def _finish(output, error=None):
        record_cost(agent_name, f"{model}@claude_code", cost, ticker)
        return AgentResult(
            output=output,
            cost_usd=cost,
            usage=usage,
            audit_log=audit,
            raw_text=final,
            model=f"{model}@claude_code",
            error=error,
        )

    try:
        return _finish(output_schema.model_validate_json(_extract_json(final)))
    except (ValidationError, ValueError, json.JSONDecodeError):
        # One correction attempt, same as the API backend.
        final2, u2, c2, a2 = _go(
            "\n\nIMPORTANT: respond with ONLY a single valid JSON object matching the "
            "schema — no prose, no markdown fences."
        )
        audit.extend(a2)
        nonlocal_cost = cost + c2
        try:
            output = output_schema.model_validate_json(_extract_json(final2))
            record_cost(agent_name, f"{model}@claude_code", nonlocal_cost, ticker)
            return AgentResult(
                output=output,
                cost_usd=nonlocal_cost,
                usage=usage,
                audit_log=audit,
                raw_text=final2,
                model=f"{model}@claude_code",
            )
        except (ValidationError, ValueError, json.JSONDecodeError) as exc2:
            record_cost(agent_name, f"{model}@claude_code", nonlocal_cost, ticker)
            return AgentResult(
                output=None,
                cost_usd=nonlocal_cost,
                usage=usage,
                audit_log=audit,
                raw_text=final2,
                model=f"{model}@claude_code",
                error=f"schema validation failed: {exc2}",
            )
