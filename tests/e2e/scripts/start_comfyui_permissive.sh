#!/usr/bin/env bash
# start_comfyui_permissive.sh — Launch ComfyUI in PERMISSIVE security mode
# for WI-YY real-E2E tests of `high+` gated endpoints.
#
# Patches `security_level = normal-` into the manager config.ini before
# launching (with backup of original value), then delegates to
# start_comfyui.sh with ENABLE_LEGACY_UI=1 (wi-037 and wi-038 are
# legacy-only routes). The corresponding stop_comfyui.sh teardown should
# be paired with restore_config() inside the pytest fixture — this
# script does NOT restore on its own, so fixture teardown MUST cleanup.
#
# Why permissive mode is needed:
#   - wi-014 POST /v2/comfyui_manager/comfyui_switch_version checks
#     is_allowed_security_level('high+'): at is_local_mode=True
#     (127.0.0.1 listen) the gate requires security_level ∈ {weak,
#     normal-}. Default `security_level = normal` fails (403).
#   - wi-037 POST /v2/customnode/install/git_url and
#     wi-038 POST /v2/customnode/install/pip are gated by the dedicated
#     config.ini flags `allow_git_url_install` / `allow_pip_install`
#     (goal265 / #2962) — independent of security_level, default false
#     (403).
# Patching security_level = normal- plus both flags = true allows real
# E2E execution of these endpoints with fixed, trusted inputs (never
# test-input-derived URLs).
#
# SECURITY NOTE:
# The endpoints are gated at high+ because they execute arbitrary remote
# code (git clone / pip install / version switch). This harness opens
# the gate ONLY in the E2E sandbox with HARDCODED trusted inputs
# (ComfyUI_examples repo; text-unidecode package). Never use with
# user-input-derived inputs — the 403 contract at default security is
# the positive-path security behavior we want to preserve in production.
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
# `security_level = normal-`, `allow_git_url_install = true` and
# `allow_pip_install = true`. The original config is preserved at
# config.ini.before-permissive for the fixture to restore on teardown.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ -n "${E2E_ROOT:-}" ]] || { echo "[start_comfyui_permissive] ERROR: E2E_ROOT is not set" >&2; exit 1; }

CONFIG="$E2E_ROOT/comfyui/user/__manager/config.ini"
BACKUP="$CONFIG.before-permissive"

[[ -f "$CONFIG" ]] || { echo "[start_comfyui_permissive] ERROR: config not found at $CONFIG" >&2; exit 1; }

# Preserve original config so the fixture can restore it on teardown.
# If a previous run left a backup, do NOT overwrite.
if [[ ! -f "$BACKUP" ]]; then
    cp "$CONFIG" "$BACKUP"
    echo "[start_comfyui_permissive] Backed up original config to $BACKUP"
fi

# Patch security_level to normal- (idempotent).
if grep -qE '^security_level\s*=' "$CONFIG"; then
    sed -i -E 's/^security_level\s*=.*/security_level = normal-/' "$CONFIG"
else
    sed -i -E '/^\[default\]/a security_level = normal-' "$CONFIG"
fi
echo "[start_comfyui_permissive] Patched security_level = normal- in $CONFIG"

# Patch the dedicated install flags (goal265 / #2962): install/git_url and
# install/pip are gated by these flags instead of security_level (idempotent).
for flag in allow_git_url_install allow_pip_install; do
    if grep -qE "^${flag}\s*=" "$CONFIG"; then
        sed -i -E "s/^${flag}\s*=.*/${flag} = true/" "$CONFIG"
    else
        sed -i -E "/^\[default\]/a ${flag} = true" "$CONFIG"
    fi
done
echo "[start_comfyui_permissive] Patched allow_git_url_install/allow_pip_install = true in $CONFIG"

exec env ENABLE_LEGACY_UI=1 bash "$SCRIPT_DIR/start_comfyui.sh" "$@"
