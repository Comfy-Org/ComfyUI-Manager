#!/usr/bin/env bash
# stage_flags.sh — Per-launch-identity config staging (T4, spec §1.4).
#
# Analog of the donor's start_comfyui_strict.sh config patching, split
# out as a pure staging script (launch is a separate step; the pytest
# fixture owns restore+delete of the backup at teardown — donor
# symmetry, spec §1.4).
#
# Modes (arg $1):
#   deny  — REMOVE both flag keys (L-D: flags ABSENT also live-proves
#           "missing key reads false")
#   allow — set allow_git_url_install = true AND allow_pip_install = true
#           (L-A / L-P)
#
# Backup: config.ini.before-flags, created ONLY if not already present
# (crashed-run-safe — preserves the true baseline across crashed runs).
# Restore + DELETE of the backup happens in the pytest fixture teardown,
# NOT here (E2E-SC-06/07).
#
# Input env vars:
#   E2E_COMFYUI_ROOT — (required)
#
# Exit: 0=staged, 1=failure

set -euo pipefail

MODE="${1:-}"

log()  { echo "[stage_flags] $*"; }
err()  { echo "[stage_flags] ERROR: $*" >&2; }
die()  { err "$@"; exit 1; }

[[ -n "${E2E_COMFYUI_ROOT:-}" ]] || die "E2E_COMFYUI_ROOT is not set"
[[ "$MODE" == "deny" || "$MODE" == "allow" ]] || die "usage: stage_flags.sh deny|allow"

CONFIG="$E2E_COMFYUI_ROOT/comfyui/user/__manager/config.ini"
BACKUP="$CONFIG.before-flags"

[[ -f "$CONFIG" ]] || die "config not found at $CONFIG (run setup_e2e_env.sh first)"

# Backup ONLY if absent (crashed-run-safe; SC-06)
if [[ ! -f "$BACKUP" ]]; then
    cp "$CONFIG" "$BACKUP"
    log "Backed up original config to $BACKUP"
else
    log "Backup already present at $BACKUP (preserving original baseline)"
fi

stage_key() {
    local key="$1" value="$2"
    if grep -qE "^${key}\s*=" "$CONFIG"; then
        sed -i -E "s|^${key}\s*=.*|${key} = ${value}|" "$CONFIG"
    else
        # The append-after target MUST exist, otherwise the sed below is a
        # silent no-op and the flag never lands (false-PASS for the allow arm).
        grep -qE "^\[default\]" "$CONFIG" \
            || die "no [default] section in $CONFIG — cannot stage '${key}' (would silently no-op)"
        sed -i -E "/^\[default\]/a ${key} = ${value}" "$CONFIG"
    fi
}

remove_key() {
    local key="$1"
    sed -i -E "/^${key}\s*=/d" "$CONFIG"
}

case "$MODE" in
    deny)
        remove_key "allow_git_url_install"
        remove_key "allow_pip_install"
        log "Staged DENY config (both flags ABSENT — missing key reads false)"
        ;;
    allow)
        stage_key "allow_git_url_install" "true"
        stage_key "allow_pip_install" "true"
        log "Staged ALLOW config (both flags = true)"
        ;;
esac

# The staged value takes effect ONLY on the NEXT launch (restart-only
# cached_config — by construction, no hot-reload assumption; SC-06).
log "Staged config at $CONFIG (effective on next launch)"
