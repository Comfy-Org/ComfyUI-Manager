# Test Environment Setup

Procedures for setting up a ComfyUI environment with ComfyUI-Manager installed for functional testing.

## Automated Setup (Recommended)

Three shell scripts in `tests/e2e/scripts/` automate the entire lifecycle:

```bash
# 1. Setup: clone ComfyUI, create venv, install deps, symlink Manager
E2E_ROOT=/tmp/e2e_test MANAGER_ROOT=/path/to/comfyui-manager-draft4 \
    bash tests/e2e/scripts/setup_e2e_env.sh

# 2. Start: launches ComfyUI in background, blocks until ready
E2E_ROOT=/tmp/e2e_test bash tests/e2e/scripts/start_comfyui.sh

# 3. Stop: graceful SIGTERM → SIGKILL shutdown
E2E_ROOT=/tmp/e2e_test bash tests/e2e/scripts/stop_comfyui.sh

# 4. Cleanup
rm -rf /tmp/e2e_test
```

### Script Details

| Script | Purpose | Input | Output |
|--------|---------|-------|--------|
| `setup_e2e_env.sh` | Full environment setup (8 steps) | `E2E_ROOT`, `MANAGER_ROOT`, `COMFYUI_BRANCH` (default: master), `PYTHON` (default: python3) | `E2E_ROOT=<path>` on last line |
| `start_comfyui.sh` | Foreground-blocking launcher | `E2E_ROOT`, `PORT` (default: 8199), `TIMEOUT` (default: 120s) | `COMFYUI_PID=<pid> PORT=<port>` |
| `stop_comfyui.sh` | Graceful shutdown | `E2E_ROOT`, `PORT` (default: 8199) | — |

**Idempotent**: `setup_e2e_env.sh` checks for a `.e2e_setup_complete` marker file and skips setup if the environment already exists.

**Blocking mechanism**: `start_comfyui.sh` uses `tail -n +1 -f | grep -q -m1 'To see the GUI'` to block until ComfyUI is ready. No polling loop needed.

---

## Prerequisites

- Python 3.9+
- Git
- `uv` (install via `pip install uv` or [standalone](https://docs.astral.sh/uv/getting-started/installation/))

## Manual Setup (Reference)

For understanding or debugging, the manual steps are documented below. The automated scripts execute these same steps.

### 1. ComfyUI Clone

```bash
COMFY_ROOT=$(mktemp -d)/ComfyUI
git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFY_ROOT"
cd "$COMFY_ROOT"
```

### 2. Virtual Environment

```bash
cd "$COMFY_ROOT"
uv venv .venv
source .venv/bin/activate    # Linux/macOS
# .venv\Scripts\activate     # Windows
```

### 3. ComfyUI Dependencies

```bash
# GPU (CUDA)
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu121

# CPU only (lightweight, for functional testing)
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
```

### 4. ComfyUI-Manager Install (Development)

```bash
# MANAGER_ROOT = comfyui-manager-draft4 repository root
MANAGER_ROOT=/path/to/comfyui-manager-draft4

# Editable install from current source
uv pip install -e "$MANAGER_ROOT"
```

> **Note**: Editable mode (`-e`) reflects code changes without reinstalling.
> For production-like testing, use `uv pip install "$MANAGER_ROOT"` (non-editable).

### 5. Symlink Manager into custom_nodes

```bash
ln -s "$MANAGER_ROOT" "$COMFY_ROOT/custom_nodes/ComfyUI-Manager"
```

### 6. Write config.ini

```bash
mkdir -p "$COMFY_ROOT/user/__manager"
cat > "$COMFY_ROOT/user/__manager/config.ini" << 'EOF'
[default]
use_uv = true
use_unified_resolver = true
EOF
```

> **IMPORTANT**: The config path is `$COMFY_ROOT/user/__manager/config.ini`, resolved by `folder_paths.get_system_user_directory("manager")`. It is NOT inside the symlinked Manager directory.

### 7. HOME Isolation

```bash
export HOME=/tmp/e2e_home
mkdir -p "$HOME/.config" "$HOME/.local/share"
```

### 8. ComfyUI Launch

```bash
cd "$COMFY_ROOT"
PYTHONUNBUFFERED=1 python main.py --enable-manager --cpu --port 8199
```

| Flag | Purpose |
|------|---------|
| `--enable-manager` | Enable ComfyUI-Manager (disabled by default) |
| `--cpu` | Run without GPU (for functional testing) |
| `--port 8199` | Use non-default port to avoid conflicts |
| `--enable-manager-legacy-ui` | Enable legacy UI (optional) |
| `--listen` | Allow remote connections (optional) |

### Key Directories

| Directory | Path | Description |
|-----------|------|-------------|
| ComfyUI root | `$COMFY_ROOT/` | ComfyUI installation root |
| Manager data | `$COMFY_ROOT/user/__manager/` | Manager config, startup scripts, snapshots |
| Config file | `$COMFY_ROOT/user/__manager/config.ini` | Manager settings (`use_uv`, `use_unified_resolver`, etc.) |
| custom_nodes | `$COMFY_ROOT/custom_nodes/` | Installed node packs |

> The Manager data path is resolved via `folder_paths.get_system_user_directory("manager")`.
> Printed at startup: `** ComfyUI-Manager config path: <path>/config.ini`

### Startup Sequence

When Manager loads successfully, the following log lines appear:

```
[PRE] ComfyUI-Manager          # prestartup_script.py executed
[START] ComfyUI-Manager         # manager_server.py loaded
```

The `Blocked by policy` message for Manager in custom_nodes is **expected** — `should_be_disabled()` in `comfyui_manager/__init__.py` prevents legacy double-loading when Manager is already pip-installed.

---

## Caveats & Known Issues

### PYTHONPATH for `comfy` imports

ComfyUI's `comfy` package is a **local package** inside the ComfyUI directory — it is NOT pip-installed. Any code that imports from `comfy` (including `comfyui_manager.__init__`) requires `PYTHONPATH` to include the ComfyUI directory:

```bash
PYTHONPATH="$COMFY_ROOT" python -c "import comfy"
PYTHONPATH="$COMFY_ROOT" python -c "import comfyui_manager"
```

The automated scripts handle this via `PYTHONPATH` in verification checks and the ComfyUI process inherits it implicitly by running from the ComfyUI directory.

### config.ini path

The config file must be at `$COMFY_ROOT/user/__manager/config.ini`, **NOT** inside the Manager symlink directory. This is resolved by `folder_paths.get_system_user_directory("manager")` at `prestartup_script.py:65-73`.

### Manager v4 endpoint prefix

All Manager endpoints use the `/v2/` prefix (e.g., `/v2/manager/queue/status`, `/v2/snapshot/get_current`). Paths without the prefix will return 404.

### `Blocked by policy` is expected

When Manager detects that it's loaded as a custom_node but is already pip-installed, it prints `Blocked by policy` and skips legacy loading. This is intentional behavior in `comfyui_manager/__init__.py:39-51`.

### Bash `((var++))` trap

Under `set -e`, `((0++))` evaluates the pre-increment value (0), and `(( 0 ))` returns exit code 1, killing the script. Use `var=$((var + 1))` instead.

### `git+https://` URLs in requirements.txt

Some node packs (e.g., Impact Pack's SAM2 dependency) use `git+https://github.com/...` URLs. The unified resolver correctly rejects these with "rejected path separator" — they must be installed separately.

---

## Cleanup

```bash
deactivate
rm -rf "$COMFY_ROOT"
```
