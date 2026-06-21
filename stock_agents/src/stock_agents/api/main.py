"""FastAPI backend for the stock_agents web UI (v2 Phase 6).

Local-only, no auth. CORS is restricted to the Next.js dev origin
(localhost:3000). Long-running operations (analyze, inspect, refresh) return a
``run_id`` immediately and process in a background task; the UI polls
``/api/runs/{run_id}`` for status.

Run with:  uvicorn stock_agents.api.main:app --port 8001   (or `stockagents serve-api`)
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from stock_agents.api.routes import alerts, runs, settings, themes, thesis, watchlist

app = FastAPI(title="stock_agents API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(watchlist.router)
app.include_router(runs.router)
app.include_router(alerts.router)
app.include_router(themes.router)
app.include_router(thesis.router)
app.include_router(settings.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
