#!/usr/bin/env bash
# setup_e2e_env.sh — Automated E2E environment setup for ComfyUI + Manager
#
# Creates an isolated ComfyUI installation with ComfyUI-Manager for E2E testing.
# Idempotent: skips setup if marker file and key artifacts already exist.
#
# Input env vars:
#   E2E_ROOT       — target directory (default: auto-generated via mktemp)
#   MANAGER_ROOT   — manager repo root (default: auto-detected from script location)
#   COMFYUI_BRANCH — ComfyUI branch to clone (default: master)
#   PYTHON         — Python executable (default: python3)
#
# Output (last line of stdout):
#   E2E_ROOT=/path/to/environment
#
# Exit: 0=success, 1=failure

set -euo pipefail

# --- Constants ---
COMFYUI_REPO="https://github.com/comfyanonymous/ComfyUI.git"
PYTORCH_CPU_INDEX="https://download.pytorch.org/whl/cpu"
CONFIG_INI_CONTENT="[default]
use_uv = true
use_unified_resolver = true
file_logging = false"

# --- Logging helpers ---
log()  { echo "[setup_e2e] $*"; }
err()  { echo "[setup_e2e] ERROR: $*" >&2; }
die()  { err "$@"; exit 1; }

# --- Detect manager root by walking up from script dir to find pyproject.toml ---
detect_manager_root() {
    local dir
    dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    while [[ "$dir" != "/" ]]; do
        if [[ -f "$dir/pyproject.toml" ]]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

# --- Validate prerequisites ---
validate_prerequisites() {
    local py="${PYTHON:-python3}"
    local missing=()

    command -v git   >/dev/null 2>&1 || missing+=("git")
    command -v uv    >/dev/null 2>&1 || missing+=("uv")
    command -v "$py" >/dev/null 2>&1 || missing+=("$py")

    if [[ ${#missing[@]} -gt 0 ]]; then
        die "Missing prerequisites: ${missing[*]}"
    fi

    # Verify Python version >= 3.9
    local py_version
    py_version=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    local major minor
    major="${py_version%%.*}"
    minor="${py_version##*.}"
    if [[ "$major" -lt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -lt 9 ]]; }; then
        die "Python 3.9+ required, found $py_version"
    fi
    log "Prerequisites OK (python=$py_version, git=$(git --version | awk '{print $3}'), uv=$(uv --version 2>&1 | awk '{print $2}'))"
}

# --- Check idempotency: skip if already set up ---
check_already_setup() {
    local root="$1"
    if [[ -f "$root/.e2e_setup_complete" ]] \
        && [[ -d "$root/comfyui" ]] \
        && [[ -d "$root/venv" ]] \
        && [[ -f "$root/comfyui/user/__manager/config.ini" ]] \
        && [[ -L "$root/comfyui/custom_nodes/ComfyUI-Manager" ]]; then
        log "Environment already set up at $root (marker file exists). Skipping."
        echo "E2E_ROOT=$root"
        exit 0
    fi
}

# --- Verify the setup ---
verify_setup() {
    local root="$1"
    local manager_root="$2"
    local venv_py="$root/venv/bin/python"
    local errors=0

    log "Running verification checks..."

    # Check ComfyUI directory
    if [[ ! -f "$root/comfyui/main.py" ]]; then
        err "Verification FAIL: comfyui/main.py not found"
        ((errors++))
    fi

    # Check venv python
    if [[ ! -x "$venv_py" ]]; then
        err "Verification FAIL: venv python not executable"
        ((errors++))
    fi

    # Check symlink
    local link_target="$root/comfyui/custom_nodes/ComfyUI-Manager"
    if [[ ! -L "$link_target" ]]; then
        err "Verification FAIL: symlink $link_target does not exist"
        ((errors++))
    elif [[ "$(readlink -f "$link_target")" != "$(readlink -f "$manager_root")" ]]; then
        err "Verification FAIL: symlink target mismatch"
        ((errors++))
    fi

    # Check config.ini
    if [[ ! -f "$root/comfyui/user/__manager/config.ini" ]]; then
        err "Verification FAIL: config.ini not found"
        ((errors++))
    fi

    # Check Python imports
    # comfy is a local package inside ComfyUI (not pip-installed), and
    # comfyui_manager.__init__ imports from comfy — both need PYTHONPATH
    if ! PYTHONPATH="$root/comfyui" "$venv_py" -c "import comfy" 2>/dev/null; then
        err "Verification FAIL: 'import comfy' failed"
        ((errors++))
    fi

    if ! PYTHONPATH="$root/comfyui" "$venv_py" -c "import comfyui_manager" 2>/dev/null; then
        err "Verification FAIL: 'import comfyui_manager' failed"
        ((errors++))
    fi

    if [[ "$errors" -gt 0 ]]; then
        die "Verification failed with $errors error(s)"
    fi
    log "Verification OK: all checks passed"
}

# ===== Main =====

# Resolve MANAGER_ROOT
if [[ -z "${MANAGER_ROOT:-}" ]]; then
    MANAGER_ROOT="$(detect_manager_root)" || die "Cannot detect MANAGER_ROOT. Set it explicitly."
fi
MANAGER_ROOT="$(cd "$MANAGER_ROOT" && pwd)"
log "MANAGER_ROOT=$MANAGER_ROOT"

# Validate prerequisites
validate_prerequisites

PYTHON="${PYTHON:-python3}"
COMFYUI_BRANCH="${COMFYUI_BRANCH:-master}"

# Create or use E2E_ROOT
CREATED_BY_US=false
if [[ -z "${E2E_ROOT:-}" ]]; then
    E2E_ROOT="$(mktemp -d -t e2e_comfyui_XXXXXX)"
    CREATED_BY_US=true
    log "Created E2E_ROOT=$E2E_ROOT"
else
    mkdir -p "$E2E_ROOT"
    log "Using E2E_ROOT=$E2E_ROOT"
fi

# Idempotency check
check_already_setup "$E2E_ROOT"

# Cleanup trap: remove E2E_ROOT on failure only if we created it
cleanup_on_failure() {
    local exit_code=$?
    if [[ "$exit_code" -ne 0 ]] && [[ "$CREATED_BY_US" == "true" ]]; then
        err "Setup failed. Cleaning up $E2E_ROOT"
        rm -rf "$E2E_ROOT"
    fi
}
trap cleanup_on_failure EXIT

# Step 1: Clone ComfyUI
log "Step 1/8: Cloning ComfyUI (branch=$COMFYUI_BRANCH)..."
if [[ -d "$E2E_ROOT/comfyui/.git" ]]; then
    log "  ComfyUI already cloned, skipping"
else
    git clone --depth=1 --branch "$COMFYUI_BRANCH" "$COMFYUI_REPO" "$E2E_ROOT/comfyui"
fi

# Step 2: Create virtual environment
log "Step 2/8: Creating virtual environment..."
if [[ -d "$E2E_ROOT/venv" ]]; then
    log "  venv already exists, skipping"
else
    uv venv "$E2E_ROOT/venv"
fi
VENV_PY="$E2E_ROOT/venv/bin/python"

# Step 3: Install ComfyUI dependencies
log "Step 3/8: Installing ComfyUI dependencies (CPU-only)..."
uv pip install \
    --python "$VENV_PY" \
    -r "$E2E_ROOT/comfyui/requirements.txt" \
    --extra-index-url "$PYTORCH_CPU_INDEX"

# Step 4: Install ComfyUI-Manager (non-editable, production-like)
log "Step 4/8: Installing ComfyUI-Manager..."
uv pip install --python "$VENV_PY" "$MANAGER_ROOT"

# Step 5: Create symlink for custom_nodes discovery
log "Step 5/8: Creating custom_nodes symlink..."
mkdir -p "$E2E_ROOT/comfyui/custom_nodes"
local_link="$E2E_ROOT/comfyui/custom_nodes/ComfyUI-Manager"
if [[ -L "$local_link" ]]; then
    log "  Symlink already exists, updating"
    rm -f "$local_link"
fi
ln -s "$MANAGER_ROOT" "$local_link"

# Step 6: Write config.ini to correct path
log "Step 6/8: Writing config.ini..."
mkdir -p "$E2E_ROOT/comfyui/user/__manager"
echo "$CONFIG_INI_CONTENT" > "$E2E_ROOT/comfyui/user/__manager/config.ini"

# Step 7: Create HOME isolation directories
log "Step 7/8: Creating HOME isolation directories..."
mkdir -p "$E2E_ROOT/home/.config"
mkdir -p "$E2E_ROOT/home/.local/share"
mkdir -p "$E2E_ROOT/logs"

# Step 8: Verify setup
log "Step 8/8: Verifying setup..."
verify_setup "$E2E_ROOT" "$MANAGER_ROOT"

# Write marker file
date -Iseconds > "$E2E_ROOT/.e2e_setup_complete"

# Clear the EXIT trap since setup succeeded
trap - EXIT

log "Setup complete."
echo "E2E_ROOT=$E2E_ROOT"
