#!/usr/bin/env bash
# start_comfyui.sh — Foreground-blocking ComfyUI launcher for E2E tests
#
# Starts ComfyUI in the background, then blocks the foreground until the server
# is ready (or timeout). This makes it safe to call from subprocess.run() or
# Claude's Bash tool — the call returns only when ComfyUI is accepting requests.
#
# Input env vars:
#   E2E_ROOT  — (required) path to E2E environment from setup_e2e_env.sh
#   PORT      — ComfyUI listen port (default: 8199)
#   TIMEOUT   — max seconds to wait for readiness (default: 120)
#
# Output (last line on success):
#   COMFYUI_PID=<pid> PORT=<port>
#
# Exit: 0=ready, 1=timeout/failure

set -euo pipefail

# --- Defaults ---
PORT="${PORT:-8199}"
TIMEOUT="${TIMEOUT:-120}"

# --- Logging helpers ---
log()  { echo "[start_comfyui] $*"; }
err()  { echo "[start_comfyui] ERROR: $*" >&2; }
die()  { err "$@"; exit 1; }

# --- Validate environment ---
[[ -n "${E2E_ROOT:-}" ]]              || die "E2E_ROOT is not set"
[[ -d "$E2E_ROOT/comfyui" ]]         || die "ComfyUI not found at $E2E_ROOT/comfyui"
[[ -x "$E2E_ROOT/venv/bin/python" ]] || die "venv python not found at $E2E_ROOT/venv/bin/python"
[[ -f "$E2E_ROOT/.e2e_setup_complete" ]] || die "Setup marker not found. Run setup_e2e_env.sh first."

PY="$E2E_ROOT/venv/bin/python"
COMFY_DIR="$E2E_ROOT/comfyui"
LOG_DIR="$E2E_ROOT/logs"
LOG_FILE="$LOG_DIR/comfyui.log"
PID_FILE="$LOG_DIR/comfyui.pid"

mkdir -p "$LOG_DIR"

# --- Check/clear port ---
if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
    log "Port $PORT is in use. Attempting to stop existing process..."
    # Try to read existing PID file
    if [[ -f "$PID_FILE" ]]; then
        OLD_PID="$(cat "$PID_FILE")"
        if kill -0 "$OLD_PID" 2>/dev/null; then
            kill "$OLD_PID" 2>/dev/null || true
            sleep 2
        fi
    fi
    # Fallback: kill by port pattern
    if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
        pkill -f "main\\.py.*--port $PORT" 2>/dev/null || true
        sleep 2
    fi
    # Final check
    if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
        die "Port $PORT is still in use after cleanup attempt"
    fi
    log "Port $PORT cleared."
fi

# --- Start ComfyUI ---
log "Starting ComfyUI on port $PORT..."

# Create empty log file (ensures tail -f works from the start)
: > "$LOG_FILE"

# Launch with unbuffered Python output so log lines appear immediately
PYTHONUNBUFFERED=1 \
HOME="$E2E_ROOT/home" \
    nohup "$PY" "$COMFY_DIR/main.py" \
        --cpu \
        --enable-manager \
        --port "$PORT" \
    > "$LOG_FILE" 2>&1 &
COMFYUI_PID=$!

echo "$COMFYUI_PID" > "$PID_FILE"
log "ComfyUI PID=$COMFYUI_PID, log=$LOG_FILE"

# Verify process didn't crash immediately
sleep 1
if ! kill -0 "$COMFYUI_PID" 2>/dev/null; then
    err "ComfyUI process died immediately. Last 30 lines of log:"
    tail -n 30 "$LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
fi

# --- Block until ready ---
# tail -n +1 -f: read from file start AND follow new content (no race condition)
# grep -q -m1: exit on first match → tail gets SIGPIPE → pipeline ends
# timeout: kill the pipeline after TIMEOUT seconds
log "Waiting up to ${TIMEOUT}s for ComfyUI to become ready..."

if timeout "$TIMEOUT" bash -c \
    "tail -n +1 -f '$LOG_FILE' 2>/dev/null | grep -q -m1 'To see the GUI'"; then
    log "ComfyUI startup message detected."
else
    err "Timeout (${TIMEOUT}s) waiting for ComfyUI. Last 30 lines of log:"
    tail -n 30 "$LOG_FILE" >&2
    kill "$COMFYUI_PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 1
fi

# Verify process is still alive after readiness detected
if ! kill -0 "$COMFYUI_PID" 2>/dev/null; then
    err "ComfyUI process died after readiness signal. Last 30 lines:"
    tail -n 30 "$LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
fi

# Optional HTTP health check
if command -v curl >/dev/null 2>&1; then
    if curl -sf "http://127.0.0.1:${PORT}/system_stats" >/dev/null 2>&1; then
        log "HTTP health check passed (/system_stats)"
    else
        log "HTTP health check skipped (endpoint not yet available, but startup message detected)"
    fi
fi

log "ComfyUI is ready."
echo "COMFYUI_PID=$COMFYUI_PID PORT=$PORT"
