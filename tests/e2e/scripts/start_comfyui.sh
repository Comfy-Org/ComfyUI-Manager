#!/usr/bin/env bash
# start_comfyui.sh — Foreground-blocking ComfyUI launcher (T2, spec §1.3).
#
# Starts ComfyUI in the background and blocks until the server answers
# GET /system_stats (or timeout). Deltas vs the donor script (binding,
# spec §1.3):
#   - NO --enable-manager: the Manager is a custom-node-style plugin
#     activated by ComfyUI's custom_nodes scan of the worktree mount.
#   - NO COMFYUI_MANAGER_SKIP_MANAGER_REQUIREMENTS: that belt does not
#     exist in this repo (Q-6 verified); watchdog row E2E-SC-42 covers
#     the residual.
#   - --listen is ALWAYS passed explicitly (LISTEN env): the predicate
#     under test is request-time `flag AND is_loopback(args.listen)` —
#     the listener value is LOAD-BEARING.
#   - Per-launch log isolation (E2E-SC-04, MANDATORY): each launch
#     identity writes a FRESH log file comfyui.<port>.<launch-id>.log,
#     so a deny-copy substring from L-D is unfindable by L-A/R-A log
#     assertions (stale-substring false-PASS class).
#   - Readiness = poll GET /system_stats == 200; child exit code 0
#     during the wait = Manager-triggered restart -> KEEP polling;
#     non-zero exit -> fail fast with log tail.
#
# Input env vars:
#   E2E_COMFYUI_ROOT — (required) root from setup_e2e_env.sh
#   PORT             — listen port (default: 8189)
#   TIMEOUT          — max seconds to readiness (default: 120)
#   LISTEN           — listener address (default: 127.0.0.1)
#   LAUNCH_ID        — launch identity tag for the log file (default: default)
#
# Output (last line on success):
#   COMFYUI_PID=<pid> PORT=<port> LOG_FILE=<path>
#
# Exit: 0=ready, 1=timeout/failure

set -euo pipefail

PORT="${PORT:-8189}"
TIMEOUT="${TIMEOUT:-120}"
LISTEN="${LISTEN:-127.0.0.1}"
LAUNCH_ID="${LAUNCH_ID:-default}"

log()  { echo "[start_comfyui] $*"; }
err()  { echo "[start_comfyui] ERROR: $*" >&2; }
die()  { err "$@"; exit 1; }

[[ -n "${E2E_COMFYUI_ROOT:-}" ]]                  || die "E2E_COMFYUI_ROOT is not set"
[[ -d "$E2E_COMFYUI_ROOT/comfyui" ]]              || die "ComfyUI not found at $E2E_COMFYUI_ROOT/comfyui"
[[ -x "$E2E_COMFYUI_ROOT/venv/bin/python" ]]      || die "venv python not found"
[[ -f "$E2E_COMFYUI_ROOT/.e2e_setup_complete" ]]  || die "Setup marker not found. Run setup_e2e_env.sh first."

PY="$E2E_COMFYUI_ROOT/venv/bin/python"
COMFY_DIR="$E2E_COMFYUI_ROOT/comfyui"
LOG_DIR="$E2E_COMFYUI_ROOT/logs"
LOG_FILE="$LOG_DIR/comfyui.${PORT}.${LAUNCH_ID}.log"
# Port-namespaced PID file (donor WI-CC incident: shared PID file caused
# a cross-port kill).
PID_FILE="$LOG_DIR/comfyui.${PORT}.pid"

mkdir -p "$LOG_DIR"

# --- Pre-launch port clear ---
if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
    log "Port $PORT is in use. Attempting to stop existing process..."
    if [[ -f "$PID_FILE" ]]; then
        OLD_PID="$(cat "$PID_FILE")"
        if kill -0 "$OLD_PID" 2>/dev/null; then
            kill "$OLD_PID" 2>/dev/null || true
            sleep 2
        fi
    fi
    if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
        pkill -f "main\\.py.*--port $PORT" 2>/dev/null || true
        sleep 2
    fi
    if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
        die "Port $PORT is still in use after cleanup attempt"
    fi
    log "Port $PORT cleared."
fi

# --- Launch (FRESH per-launch log file) ---
log "Starting ComfyUI on port $PORT (listen=$LISTEN, launch_id=$LAUNCH_ID)..."
: > "$LOG_FILE"

PYTHONUNBUFFERED=1 \
HOME="$E2E_COMFYUI_ROOT/home" \
    nohup "$PY" -u "$COMFY_DIR/main.py" \
        --cpu \
        --port "$PORT" \
        --listen "$LISTEN" \
    > "$LOG_FILE" 2>&1 &
COMFYUI_PID=$!

echo "$COMFYUI_PID" > "$PID_FILE"
log "ComfyUI PID=$COMFYUI_PID, log=$LOG_FILE"

# --- Block until ready: poll /system_stats (restart-tolerant) ---
log "Waiting up to ${TIMEOUT}s for ComfyUI readiness (GET /system_stats)..."
DEADLINE=$(( $(date +%s) + TIMEOUT ))
READY=0
while [[ "$(date +%s)" -lt "$DEADLINE" ]]; do
    if curl -sf --max-time 2 "http://127.0.0.1:${PORT}/system_stats" >/dev/null 2>&1; then
        READY=1
        break
    fi
    # Child exit handling: exit 0 = Manager-triggered restart -> keep
    # polling (a restarted process will bind the port); non-zero -> fail fast.
    if ! kill -0 "$COMFYUI_PID" 2>/dev/null; then
        if wait "$COMFYUI_PID" 2>/dev/null; then
            : # exit 0 — restart class, keep polling
        else
            RC=$?
            err "ComfyUI exited with code $RC. Last 30 lines of log:"
            tail -n 30 "$LOG_FILE" >&2
            rm -f "$PID_FILE"
            exit 1
        fi
    fi
    sleep 1
done

if [[ "$READY" -ne 1 ]]; then
    err "Timeout (${TIMEOUT}s) waiting for ComfyUI. Last 30 lines of log:"
    tail -n 30 "$LOG_FILE" >&2
    kill "$COMFYUI_PID" 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 1
fi

# A Manager-triggered restart (child exit 0 above) leaves COMFYUI_PID pointing
# at the dead original child while a FRESH process now owns the port. Re-resolve
# the live listener PID so PID_FILE (consumed by stop_comfyui.sh) targets the
# process that must actually be killed at teardown.
LISTENER_PID="$(ss -tlnp 2>/dev/null | grep ":${PORT}\b" | grep -oE 'pid=[0-9]+' | head -n1 | cut -d= -f2)"
if [[ -n "$LISTENER_PID" && "$LISTENER_PID" != "$COMFYUI_PID" ]]; then
    log "Listener PID $LISTENER_PID differs from launched PID $COMFYUI_PID (restart). Updating PID file."
    COMFYUI_PID="$LISTENER_PID"
    echo "$COMFYUI_PID" > "$PID_FILE"
fi

log "ComfyUI is ready."
echo "COMFYUI_PID=$COMFYUI_PID PORT=$PORT LOG_FILE=$LOG_FILE"
