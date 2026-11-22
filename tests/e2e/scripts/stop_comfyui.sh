#!/usr/bin/env bash
# stop_comfyui.sh — Graceful ComfyUI shutdown (T3, spec §1.3 stop contract).
#
# Donor mirror: SIGTERM -> 10s grace -> SIGKILL -> port-pattern pkill
# fallback -> port-free verify (incl. the legacy-PID-file warning from
# the donor WI-CC cross-port-kill incident).
#
# Input env vars:
#   E2E_COMFYUI_ROOT — (required) path to the E2E environment
#   PORT             — ComfyUI port (default: 8189)
#
# Exit: 0=stopped, 1=failed

set -euo pipefail

PORT="${PORT:-8189}"
GRACE_PERIOD=10

log()  { echo "[stop_comfyui] $*"; }
err()  { echo "[stop_comfyui] ERROR: $*" >&2; }
die()  { err "$@"; exit 1; }

[[ -n "${E2E_COMFYUI_ROOT:-}" ]] || die "E2E_COMFYUI_ROOT is not set"

# Ownership guard: only signal a PID whose cmdline references THIS E2E root.
# On shared runners a bare "main.py --port N" pattern (or a reused PID) could
# otherwise match an unrelated process; the launcher invokes
# "$E2E_COMFYUI_ROOT/venv/bin/python $E2E_COMFYUI_ROOT/comfyui/main.py", so the
# root path is always present in our process's cmdline.
belongs_to_root() {
    local pid="$1"
    [[ -n "$pid" && -r "/proc/$pid/cmdline" ]] || return 1
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -qF "$E2E_COMFYUI_ROOT"
}

# PIDs currently listening on PORT (deduped).
listener_pids() {
    ss -tlnp 2>/dev/null | grep ":${PORT}\b" | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u
}

PID_FILE="$E2E_COMFYUI_ROOT/logs/comfyui.${PORT}.pid"
LEGACY_PID_FILE="$E2E_COMFYUI_ROOT/logs/comfyui.pid"
if [[ -f "$LEGACY_PID_FILE" ]] && [[ ! -f "$PID_FILE" ]]; then
    log "WARN: found legacy unported PID file $LEGACY_PID_FILE but no ${PID_FILE}. Cross-port risk — ignoring legacy file."
fi

COMFYUI_PID=""
if [[ -f "$PID_FILE" ]]; then
    COMFYUI_PID="$(cat "$PID_FILE")"
    log "Read PID=$COMFYUI_PID from $PID_FILE"
fi

if [[ -n "$COMFYUI_PID" ]] && kill -0 "$COMFYUI_PID" 2>/dev/null; then
    if belongs_to_root "$COMFYUI_PID"; then
        log "Sending SIGTERM to PID $COMFYUI_PID..."
        kill "$COMFYUI_PID" 2>/dev/null || true
        elapsed=0
        while kill -0 "$COMFYUI_PID" 2>/dev/null && [[ "$elapsed" -lt "$GRACE_PERIOD" ]]; do
            sleep 1
            elapsed=$((elapsed + 1))
        done
        if kill -0 "$COMFYUI_PID" 2>/dev/null; then
            log "Process still alive after ${GRACE_PERIOD}s. Sending SIGKILL..."
            kill -9 "$COMFYUI_PID" 2>/dev/null || true
            sleep 1
        fi
    else
        log "WARN: PID $COMFYUI_PID does NOT belong to $E2E_COMFYUI_ROOT (reused/stale PID). Refusing to kill it."
    fi
fi

# Fallback: kill the port listener(s) (covers Manager-restarted processes whose
# PID differs from the recorded one) — but ONLY those verified to belong to this
# E2E root, never a broad pattern pkill that could hit unrelated CI processes.
if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
    log "Port $PORT still in use. Killing verified-own listener(s)..."
    for pid in $(listener_pids); do
        if belongs_to_root "$pid"; then
            log "Sending SIGTERM to listener PID $pid..."
            kill "$pid" 2>/dev/null || true
        else
            log "WARN: PID $pid on port $PORT is not part of $E2E_COMFYUI_ROOT — leaving it alone."
        fi
    done
    sleep 2
    for pid in $(listener_pids); do
        if belongs_to_root "$pid"; then
            log "Listener PID $pid still alive. Sending SIGKILL..."
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    sleep 1
fi

rm -f "$PID_FILE"

if ss -tlnp 2>/dev/null | grep -q ":${PORT}\b"; then
    die "Port $PORT is still in use after shutdown"
fi

log "ComfyUI stopped."
