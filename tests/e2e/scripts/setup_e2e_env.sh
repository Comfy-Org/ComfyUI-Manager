#!/usr/bin/env bash
# setup_e2e_env.sh — E2E environment builder for GOAL #60 (T1, spec §2).
#
# Builds the DISPOSABLE test ComfyUI root used by
# tests/e2e/test_e2e_install_flags.py. ENV BUILD ONLY: donor steps 4-5
# (editable pip install of the Manager + custom_nodes symlink) are
# deliberately DROPPED — the Manager is mounted via `git worktree add`
# by the `mount_worktree` session fixture in the test module, which is
# the SOLE owner of mount create/reuse/teardown (spec §2 T1
# single-ownership rule). This script never touches the Manager repo.
#
# Idempotent: re-run is a no-op when the marker + key artifacts exist
# (E2E-SC-01).
#
# Input env vars:
#   E2E_COMFYUI_ROOT — target directory (default: mktemp -d)
#   COMFYUI_BRANCH   — ComfyUI clone ref (default: master; Q-2)
#   PYTHON           — python executable for version probe (default: python3)
#
# Output (last line of stdout):
#   E2E_COMFYUI_ROOT=/path/to/environment
#
# Exit: 0=success, 1=failure

set -euo pipefail

COMFYUI_REPO="https://github.com/comfyanonymous/ComfyUI.git"
PYTORCH_CPU_INDEX="https://download.pytorch.org/whl/cpu"
# Minimal seed config. use_uv=false: the venv is seeded with pip
# (`uv venv --seed`), so the Manager's make_pip_cmd resolves to
# `<venv-python> -m pip` and the suite's pip-uninstall hygiene helpers
# work without uv on PATH at server runtime. The install flags are NOT
# seeded here — stage_flags.sh stages them per launch identity (SC-06).
CONFIG_INI_CONTENT="[default]
file_logging = false
use_uv = false"

log()  { echo "[setup_e2e] $*"; }
err()  { echo "[setup_e2e] ERROR: $*" >&2; }
die()  { err "$@"; exit 1; }

validate_prerequisites() {
    local py="${PYTHON:-python3}"
    local missing=()
    command -v git   >/dev/null 2>&1 || missing+=("git")
    command -v uv    >/dev/null 2>&1 || missing+=("uv")
    command -v "$py" >/dev/null 2>&1 || missing+=("$py")
    if [[ ${#missing[@]} -gt 0 ]]; then
        die "Missing prerequisites: ${missing[*]}"
    fi
    local py_version major minor
    py_version=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    major="${py_version%%.*}"
    minor="${py_version##*.}"
    if [[ "$major" -lt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -lt 9 ]]; }; then
        die "Python 3.9+ required, found $py_version"
    fi
    log "Prerequisites OK (python=$py_version)"
}

check_already_setup() {
    local root="$1"
    if [[ -f "$root/.e2e_setup_complete" ]] \
        && [[ -d "$root/comfyui" ]] \
        && [[ -d "$root/venv" ]] \
        && [[ -f "$root/comfyui/user/__manager/config.ini" ]]; then
        log "Environment already set up at $root (marker exists). Skipping. (E2E-SC-01 idempotence)"
        echo "E2E_COMFYUI_ROOT=$root"
        exit 0
    fi
}

verify_setup() {
    local root="$1"
    local venv_py="$root/venv/bin/python"
    local errors=0
    log "Running verification checks..."
    [[ -f "$root/comfyui/main.py" ]] || { err "Verification FAIL: comfyui/main.py not found"; ((errors+=1)); }
    [[ -x "$venv_py" ]] || { err "Verification FAIL: venv python not executable"; ((errors+=1)); }
    [[ -f "$root/comfyui/user/__manager/config.ini" ]] || { err "Verification FAIL: config.ini not found"; ((errors+=1)); }
    # venv must carry pip (uv venv --seed) — the suite's hygiene helpers
    # and the Manager's reservation-consuming boot both call `-m pip`.
    if ! "$venv_py" -m pip --version >/dev/null 2>&1; then
        err "Verification FAIL: venv pip not available"
        ((errors+=1))
    fi
    # comfy is a local package inside the ComfyUI checkout
    if ! PYTHONPATH="$root/comfyui" "$venv_py" -c "import comfy" 2>/dev/null; then
        err "Verification FAIL: 'import comfy' failed"
        ((errors+=1))
    fi
    # [D2] half-check at setup time: the Manager must NOT be pip-installed
    # into this venv (the worktree mount is the only delivery mechanism).
    if "$venv_py" -m pip show comfyui-manager >/dev/null 2>&1 \
        || "$venv_py" -m pip show ComfyUI-Manager >/dev/null 2>&1; then
        err "Verification FAIL: a pip-installed Manager exists in the venv (wrong layout for [D2])"
        ((errors+=1))
    fi
    if [[ "$errors" -gt 0 ]]; then
        die "Verification failed with $errors error(s)"
    fi
    log "Verification OK: all checks passed"
}

# ===== Main =====
validate_prerequisites

PYTHON="${PYTHON:-python3}"
COMFYUI_BRANCH="${COMFYUI_BRANCH:-master}"

CREATED_BY_US=false
if [[ -z "${E2E_COMFYUI_ROOT:-}" ]]; then
    E2E_COMFYUI_ROOT="$(mktemp -d -t e2e_comfyui_XXXXXX)"
    CREATED_BY_US=true
    log "Created E2E_COMFYUI_ROOT=$E2E_COMFYUI_ROOT"
else
    mkdir -p "$E2E_COMFYUI_ROOT"
    log "Using E2E_COMFYUI_ROOT=$E2E_COMFYUI_ROOT"
fi

check_already_setup "$E2E_COMFYUI_ROOT"

cleanup_on_failure() {
    local exit_code=$?
    if [[ "$exit_code" -ne 0 ]] && [[ "$CREATED_BY_US" == "true" ]]; then
        err "Setup failed. Cleaning up $E2E_COMFYUI_ROOT"
        rm -rf "$E2E_COMFYUI_ROOT"
    fi
}
trap cleanup_on_failure EXIT

log "Step 1/5: Cloning ComfyUI (branch=$COMFYUI_BRANCH)..."
if [[ -d "$E2E_COMFYUI_ROOT/comfyui/.git" ]]; then
    log "  ComfyUI already cloned, skipping"
else
    git clone --depth=1 --branch "$COMFYUI_BRANCH" "$COMFYUI_REPO" "$E2E_COMFYUI_ROOT/comfyui"
fi

log "Step 2/5: Creating virtual environment (seeded with pip)..."
if [[ -d "$E2E_COMFYUI_ROOT/venv" ]]; then
    log "  venv already exists, skipping"
else
    uv venv --seed "$E2E_COMFYUI_ROOT/venv"
fi
VENV_PY="$E2E_COMFYUI_ROOT/venv/bin/python"

log "Step 3/5: Installing ComfyUI dependencies (CPU-only torch index)..."
uv pip install \
    --python "$VENV_PY" \
    -r "$E2E_COMFYUI_ROOT/comfyui/requirements.txt" \
    --extra-index-url "$PYTORCH_CPU_INDEX"

log "Step 4/5: Writing seed config.ini + HOME isolation dirs..."
mkdir -p "$E2E_COMFYUI_ROOT/comfyui/user/__manager"
echo "$CONFIG_INI_CONTENT" > "$E2E_COMFYUI_ROOT/comfyui/user/__manager/config.ini"
mkdir -p "$E2E_COMFYUI_ROOT/home/.config"
mkdir -p "$E2E_COMFYUI_ROOT/home/.local/share"
mkdir -p "$E2E_COMFYUI_ROOT/logs"
mkdir -p "$E2E_COMFYUI_ROOT/comfyui/custom_nodes"

log "Step 5/5: Verifying setup..."
verify_setup "$E2E_COMFYUI_ROOT"

# Marker written ONLY after verification passes (E2E-SC-01)
date -Iseconds > "$E2E_COMFYUI_ROOT/.e2e_setup_complete"

trap - EXIT
log "Setup complete."
echo "E2E_COMFYUI_ROOT=$E2E_COMFYUI_ROOT"
