#!/bin/bash
# stock_agents — one-click launcher (double-click in Finder, or run ./start.command).
# Starts the FastAPI backend (:8001) + Next.js frontend (:3000) and opens the browser.
# Ctrl-C, or closing this window, stops both.

# --- config ---------------------------------------------------------------
# USE_MAX=1 -> drive the Claude Max subscription (no metered API $; needs the
#             `claude` CLI logged into your subscription).
# USE_MAX=0 -> use the metered Anthropic API key from stock_agents/.env.
USE_MAX=1

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$DIR/stock_agents"
FRONTEND_DIR="$DIR/stock_agents_ui"

# Make sure uv (~/.local/bin) and Homebrew node (/opt/homebrew/bin) are on PATH,
# since a freshly double-clicked Terminal may not have them.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

command -v uv  >/dev/null || { echo "ERROR: 'uv' not found. Install: https://docs.astral.sh/uv/"; read -r; exit 1; }
command -v npm >/dev/null || { echo "ERROR: 'npm' not found. Install Node.js (https://nodejs.org)."; read -r; exit 1; }

echo "stock_agents launcher"
echo "  backend : $BACKEND_DIR  (:8001)"
echo "  frontend: $FRONTEND_DIR (:3000)"
echo "  backend mode: $([ "$USE_MAX" = 1 ] && echo 'Claude Max subscription' || echo 'metered Anthropic API')"
echo ""

# Free the ports first, in case a previous launch left a server bound.
for port in 8001 3000; do
  pids=$(lsof -ti tcp:$port 2>/dev/null || true)
  [ -n "$pids" ] && echo "freeing port $port (was $pids)" && kill -9 $pids 2>/dev/null || true
done

# --- backend --------------------------------------------------------------
if [ "$USE_MAX" = 1 ]; then
  ( cd "$BACKEND_DIR" && env -u ANTHROPIC_API_KEY LLM_BACKEND=claude_code \
      uv run stockagents serve-api --port 8001 ) &
else
  ( cd "$BACKEND_DIR" && uv run stockagents serve-api --port 8001 ) &
fi
BACKEND_PID=$!

# --- frontend -------------------------------------------------------------
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "First run: installing frontend dependencies (one-time)…"
  ( cd "$FRONTEND_DIR" && npm install )
fi
( cd "$FRONTEND_DIR" && npm run dev ) &
FRONTEND_PID=$!

# --- stop both on exit ----------------------------------------------------
cleanup() {
  echo ""
  echo "Shutting down…"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  # `uv run` / `npm` spawn child processes that outlive their launchers, so kill
  # by port to be certain both servers actually stop.
  for port in 8001 3000; do
    pids=$(lsof -ti tcp:$port 2>/dev/null || true)
    [ -n "$pids" ] && kill -9 $pids 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM HUP   # HUP = the Terminal window was closed

# --- wait for the frontend, then open the browser -------------------------
echo "Starting servers (this can take ~10-20s on first run)…"
for _ in $(seq 1 60); do
  if curl -s -o /dev/null "http://localhost:3000"; then break; fi
  sleep 1
done
echo "Opening http://localhost:3000"
open "http://localhost:3000" 2>/dev/null || true

echo ""
echo "Running. Press Ctrl-C (or close this window) to stop both servers."
wait
