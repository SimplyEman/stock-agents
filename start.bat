@echo off
REM ===========================================================================
REM stock_agents - one-click launcher for Windows.
REM Double-click this file in Explorer, or run `start.bat` from a terminal.
REM Starts the FastAPI backend (:8001) + Next.js frontend (:3000) and opens
REM the browser. Close this window to stop both servers.
REM ===========================================================================

REM --- config ---------------------------------------------------------------
REM USE_MAX=1 -> drive the Claude Max subscription (no metered API $; needs the
REM             `claude` CLI logged into your subscription).
REM USE_MAX=0 -> use the metered Anthropic API key from stock_agents\.env.
set USE_MAX=1

setlocal enabledelayedexpansion
set "DIR=%~dp0"
set "BACKEND_DIR=%DIR%stock_agents"
set "FRONTEND_DIR=%DIR%stock_agents_ui"

REM --- tool checks ----------------------------------------------------------
where uv >nul 2>nul || (echo ERROR: 'uv' not found. Install: https://docs.astral.sh/uv/ && pause && exit /b 1)
where npm >nul 2>nul || (echo ERROR: 'npm' not found. Install Node.js: https://nodejs.org && pause && exit /b 1)

echo stock_agents launcher
echo   backend : %BACKEND_DIR%  (:8001)
echo   frontend: %FRONTEND_DIR% (:3000)
if "%USE_MAX%"=="1" (echo   backend mode: Claude Max subscription) else (echo   backend mode: metered Anthropic API)
echo.

REM --- free the ports first (in case a previous launch left them bound) ------
for %%P in (8001 3000) do (
  for /f "tokens=5" %%I in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
    echo freeing port %%P (was %%I)
    taskkill /F /PID %%I >nul 2>nul
  )
)

REM --- first-run frontend dependency install --------------------------------
if not exist "%FRONTEND_DIR%\node_modules" (
  echo First run: installing frontend dependencies (one-time)...
  pushd "%FRONTEND_DIR%" && call npm install && popd
)

REM --- backend --------------------------------------------------------------
if "%USE_MAX%"=="1" (
  start "stock_agents backend" cmd /c "cd /d "%BACKEND_DIR%" && set "ANTHROPIC_API_KEY=" && set "LLM_BACKEND=claude_code" && uv run stockagents serve-api --port 8001"
) else (
  start "stock_agents backend" cmd /c "cd /d "%BACKEND_DIR%" && uv run stockagents serve-api --port 8001"
)

REM --- frontend -------------------------------------------------------------
start "stock_agents frontend" cmd /c "cd /d "%FRONTEND_DIR%" && npm run dev"

REM --- wait for the frontend, then open the browser -------------------------
echo Starting servers (this can take ~10-20s on first run)...
set "UP="
for /l %%N in (1,1,60) do (
  if not defined UP (
    curl -s -o nul http://localhost:3000 && set "UP=1"
    if not defined UP ping -n 2 127.0.0.1 >nul
  )
)
echo Opening http://localhost:3000
start "" "http://localhost:3000"

echo.
echo Running. The backend and frontend each opened their own window.
echo Close those two windows (or this one) to stop the servers.
echo.
pause
endlocal
