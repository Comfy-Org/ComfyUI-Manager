"""Cross-platform E2E environment setup for ComfyUI + Manager.

Creates an isolated ComfyUI installation with ComfyUI-Manager for E2E testing.
Idempotent: skips setup if marker file and key artifacts already exist.

Input env vars:
    E2E_ROOT       — target directory (required)
    MANAGER_ROOT   — manager repo root (default: auto-detected)
    COMFYUI_BRANCH — ComfyUI branch to clone (default: master)

Output (last line of stdout):
    E2E_ROOT=/path/to/environment

Usage:
    python tests/e2e/scripts/setup_e2e_env.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

COMFYUI_REPO = "https://github.com/comfyanonymous/ComfyUI.git"
PYTORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
CONFIG_INI_CONTENT = """\
[default]
use_uv = true
use_unified_resolver = true
file_logging = false
"""


def log(msg: str) -> None:
    print(f"[setup_e2e] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[setup_e2e] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    log(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def detect_manager_root() -> Path:
    """Walk up from this script to find pyproject.toml."""
    d = Path(__file__).resolve().parent
    while d != d.parent:
        if (d / "pyproject.toml").exists():
            return d
        d = d.parent
    die("Cannot detect MANAGER_ROOT (no pyproject.toml found)")
    raise SystemExit(1)  # unreachable, for type checker


def venv_python(root: Path) -> str:
    if sys.platform == "win32":
        return str(root / "venv" / "Scripts" / "python.exe")
    return str(root / "venv" / "bin" / "python")


def venv_bin(root: Path, name: str) -> str:
    if sys.platform == "win32":
        return str(root / "venv" / "Scripts" / f"{name}.exe")
    return str(root / "venv" / "bin" / name)


def is_already_setup(root: Path, manager_root: Path) -> bool:
    marker = root / ".e2e_setup_complete"
    comfyui = root / "comfyui"
    venv = root / "venv"
    config = root / "comfyui" / "user" / "__manager" / "config.ini"
    manager_link = root / "comfyui" / "custom_nodes" / "ComfyUI-Manager"
    return (
        marker.exists()
        and comfyui.is_dir()
        and venv.is_dir()
        and config.exists()
        and (manager_link.exists() or manager_link.is_symlink())
    )


def link_manager(custom_nodes: Path, manager_root: Path) -> None:
    """Create symlink or junction to manager source."""
    link = custom_nodes / "ComfyUI-Manager"
    if link.exists() or link.is_symlink():
        if link.is_symlink():
            link.unlink()
        elif link.is_dir():
            import shutil
            shutil.rmtree(link)

    if sys.platform == "win32":
        # Windows: use directory junction (no admin privileges needed)
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(manager_root)],
            check=True,
        )
    else:
        link.symlink_to(manager_root)


def main() -> None:
    manager_root = Path(os.environ.get("MANAGER_ROOT", "")) or detect_manager_root()
    manager_root = manager_root.resolve()
    log(f"MANAGER_ROOT={manager_root}")

    e2e_root_str = os.environ.get("E2E_ROOT", "")
    if not e2e_root_str:
        die("E2E_ROOT environment variable is required")
    root = Path(e2e_root_str).resolve()
    root.mkdir(parents=True, exist_ok=True)
    log(f"E2E_ROOT={root}")

    branch = os.environ.get("COMFYUI_BRANCH", "master")

    # Idempotency
    if is_already_setup(root, manager_root):
        log("Environment already set up (marker file exists). Skipping.")
        print(f"E2E_ROOT={root}")
        return

    # Step 1: Clone ComfyUI
    comfyui_dir = root / "comfyui"
    if (comfyui_dir / ".git").is_dir():
        log("Step 1/7: ComfyUI already cloned, skipping")
    else:
        log(f"Step 1/7: Cloning ComfyUI (branch={branch})...")
        run(["git", "clone", "--depth=1", "--branch", branch, COMFYUI_REPO, str(comfyui_dir)])

    # Step 2: Create venv
    venv_dir = root / "venv"
    if venv_dir.is_dir():
        log("Step 2/7: venv already exists, skipping")
    else:
        log("Step 2/7: Creating virtual environment...")
        run(["uv", "venv", str(venv_dir)])

    py = venv_python(root)

    # Step 3: Install ComfyUI dependencies (CPU-only)
    log("Step 3/7: Installing ComfyUI dependencies (CPU-only)...")
    run([
        "uv", "pip", "install",
        "--python", py,
        "-r", str(comfyui_dir / "requirements.txt"),
        "--extra-index-url", PYTORCH_CPU_INDEX,
    ])

    # Step 3.5: Ensure pip is available in the venv (Manager needs it for per-pack installs)
    log("Step 3.5: Ensuring pip is available...")
    run(["uv", "pip", "install", "--python", py, "pip"])

    # Step 4: Install Manager
    log("Step 4/7: Installing ComfyUI-Manager...")
    run(["uv", "pip", "install", "--python", py, str(manager_root)])

    # Step 5: Link manager into custom_nodes
    log("Step 5/7: Linking Manager into custom_nodes...")
    custom_nodes = comfyui_dir / "custom_nodes"
    custom_nodes.mkdir(parents=True, exist_ok=True)
    link_manager(custom_nodes, manager_root)

    # Step 6: Write config.ini
    log("Step 6/7: Writing config.ini...")
    config_dir = comfyui_dir / "user" / "__manager"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.ini").write_text(CONFIG_INI_CONTENT)

    # Step 7: Verify
    log("Step 7/7: Verifying setup...")
    errors = 0

    if not (comfyui_dir / "main.py").exists():
        log("  FAIL: comfyui/main.py not found")
        errors += 1

    if not os.path.isfile(py):
        log(f"  FAIL: venv python not found at {py}")
        errors += 1

    link = custom_nodes / "ComfyUI-Manager"
    if not link.exists():
        log(f"  FAIL: Manager link not found at {link}")
        errors += 1

    # Check cm-cli is installed
    cm_cli = venv_bin(root, "cm-cli")
    if not os.path.isfile(cm_cli):
        log(f"  FAIL: cm-cli not found at {cm_cli}")
        errors += 1

    if errors:
        die(f"Verification failed with {errors} error(s)")

    log("Verification OK")

    # Write marker
    from datetime import datetime
    (root / ".e2e_setup_complete").write_text(datetime.now().isoformat())

    log("Setup complete.")
    print(f"E2E_ROOT={root}")


if __name__ == "__main__":
    main()
