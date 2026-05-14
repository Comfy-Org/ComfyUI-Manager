#!/usr/bin/env bash
# start_comfyui_legacy.sh — Thin wrapper that launches ComfyUI in LEGACY UI mode.
#
# Delegates to start_comfyui.sh with ENABLE_LEGACY_UI=1. The underlying script
# translates that into --enable-manager-legacy-ui on main.py, which registers
# the legacy Manager dialog frontend and routes POST /v2/manager/queue/* to
# the legacy handler module (legacy/manager_server.py).
#
# Use this wrapper for Playwright legacy-UI tests (tests/playwright/legacy-ui-*).
# Do NOT use for pytest suites that hit glob-only v2 endpoints (e.g.
# /v2/manager/queue/task), because glob/manager_server and legacy/manager_server
# are mutex-loaded — see comfyui_manager/__init__.py::start().
#
# Input env vars (forwarded to start_comfyui.sh):
#   E2E_ROOT  — required
#   PORT      — default 8199
#   TIMEOUT   — default 120
#
# Output (last line on success, inherited from start_comfyui.sh):
#   COMFYUI_PID=<pid> PORT=<port>
#
# Exit: 0=ready, 1=timeout/failure

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec env ENABLE_LEGACY_UI=1 bash "$SCRIPT_DIR/start_comfyui.sh" "$@"
