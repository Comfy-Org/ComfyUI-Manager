# Test Environment Setup

Procedures for setting up a ComfyUI environment with ComfyUI-Manager installed for functional testing.

## Prerequisites

- Python 3.9+
- Git
- `uv` (pip alternative, install via `pip install uv`)

## Environment Setup

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

### 5. ComfyUI Launch

```bash
cd "$COMFY_ROOT"
python main.py --enable-manager --cpu
```

| Flag | Purpose |
|------|---------|
| `--enable-manager` | Enable ComfyUI-Manager (disabled by default) |
| `--cpu` | Run without GPU (for functional testing) |
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

## Cleanup

```bash
deactivate
rm -rf "$COMFY_ROOT"
```

## Quick Reference (Copy-Paste)

```bash
# Full setup in one block
COMFY_ROOT=$(mktemp -d)/ComfyUI
MANAGER_ROOT=/path/to/comfyui-manager-draft4

git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFY_ROOT"
cd "$COMFY_ROOT"
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
uv pip install -e "$MANAGER_ROOT"
python main.py --enable-manager --cpu
```
