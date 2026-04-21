#!/usr/bin/env bash
# start_comfyui_strict.sh — Launch ComfyUI in STRICT security mode for SECGATE tests.
#
# Patches `security_level = strong` into the manager config.ini before launching
# (with backup of original value), then delegates to start_comfyui.sh. The
# corresponding stop_comfyui.sh teardown should be paired with restore_config()
# inside the pytest fixture (this script does NOT restore on its own — restore
# happens at fixture teardown to keep this wrapper symmetric with
# start_comfyui_legacy.sh).
#
# Why strict mode is needed:
# Several state-changing endpoints (snapshot/remove [middle], snapshot/restore
# [middle+], reboot [middle], queue/update_all [middle+]) check
# is_allowed_security_level(<gate>). At the default `security_level = normal`
# (and is_local_mode = True since we listen on 127.0.0.1), middle and middle+
# operations are ALLOWED — so the 403 path is unreachable. Setting
# security_level = strong puts NORMAL out of the allowed sets and makes the
# 403 contract observable.
#
# At-or-below `normal` configurations cannot test the 403 path for these gates;
# `strong` is required.
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
#
# Side effect: $E2E_ROOT/comfyui/user/__manager/config.ini gets
# `security_level = strong`. The original value is preserved at
# config.ini.before-strict for the fixture to restore on teardown.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ -n "${E2E_ROOT:-}" ]] || { echo "[start_comfyui_strict] ERROR: E2E_ROOT is not set" >&2; exit 1; }

CONFIG="$E2E_ROOT/comfyui/user/__manager/config.ini"
BACKUP="$CONFIG.before-strict"

[[ -f "$CONFIG" ]] || { echo "[start_comfyui_strict] ERROR: config not found at $CONFIG" >&2; exit 1; }

# Preserve original config so the fixture can restore it on teardown.
# If a previous run left a backup, do NOT overwrite (preserves the *true*
# pre-strict baseline across crashed test runs).
if [[ ! -f "$BACKUP" ]]; then
    cp "$CONFIG" "$BACKUP"
    echo "[start_comfyui_strict] Backed up original config to $BACKUP"
fi

# Patch security_level to strong (idempotent — works whether the line is
# already `strong`, `normal`, or any other value).
if grep -qE '^security_level\s*=' "$CONFIG"; then
    sed -i -E 's/^security_level\s*=.*/security_level = strong/' "$CONFIG"
else
    # security_level missing entirely (unusual) — append under [default]
    sed -i -E '/^\[default\]/a security_level = strong' "$CONFIG"
fi
echo "[start_comfyui_strict] Patched security_level = strong in $CONFIG"

exec bash "$SCRIPT_DIR/start_comfyui.sh" "$@"
