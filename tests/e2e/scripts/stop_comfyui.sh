#!/usr/bin/env bash
# stop_comfyui.sh — Graceful ComfyUI shutdown for E2E tests
#
# Stops a ComfyUI process previously started by start_comfyui.sh.
# Uses SIGTERM first, then SIGKILL after a grace period.
#
# Input env vars:
#   E2E_ROOT  — (required) path to E2E environment
#   PORT      — ComfyUI port for fallback pkill (default: 8199)
#
# Exit: 0=stopped, 1=failed

set -euo pipefail

PORT="${PORT:-8199}"
GRACE_PERIOD=10

# --- Logging helpers ---
log()  { echo "[stop_comfyui] $*"; }
err()  { echo "[stop_comfyui] ERROR: $*" >&2; }
die()  { err "$@"; exit 1; }

# --- Validate ---
[[ -n "${E2E_ROOT:-}" ]] || die "E2E_ROOT is not set"

PID_FILE="$E2E_ROOT/logs/comfyui.pid"

# --- Read PID ---
COMFYUI_PID=""
if [[ -f "$PID_FILE" ]]; then
    COMFYUI_PID="$(cat "$PID_FILE")"
    log "Read PID=$COMFYUI_PID from $PID_FILE"
fi

# --- Graceful shutdown via SIGTERM ---
if [[ -n "$COMFYUI_PID" ]] && kill -0 "$COMFYUI_PID" 2>/dev/null; then
    log "Sending SIGTERM to PID $COMFYUI_PID..."
    kill "$COMFYUI_PID" 2>/dev/null || true

    # Wait for graceful shutdown
    elapsed=0
    while kill -0 "$COMFYUI_PID" 2>/dev/null && [[ "$elapsed" -lt "$GRACE_PERIOD" ]]; do
        sleep 1
        elapsed=$((elapsed + 1))
    done

    # Force kill if still alive
    if kill -0 "$COMFYUI_PID" 2>/dev/null; then
        log "Process still alive after ${GRACE_PERIOD}s. Sending SIGKILL..."
        kill -9 "$COMFYUI_PID" 2>/dev/null || true
        sleep 1
    fi
fi

# --- Fallback: kill by port pattern ---
if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
    log "Port $PORT still in use. Attempting pkill fallback..."
    pkill -f "main\\.py.*--port $PORT" 2>/dev/null || true
    sleep 2

    if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
        pkill -9 -f "main\\.py.*--port $PORT" 2>/dev/null || true
        sleep 1
    fi
fi

# --- Cleanup PID file ---
rm -f "$PID_FILE"

# --- Verify port is free ---
if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
    die "Port $PORT is still in use after shutdown"
fi

log "ComfyUI stopped."
