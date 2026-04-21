"""E2E tests for ComfyUI Manager HTTP API endpoints (install/uninstall).

Starts a real ComfyUI instance, exercises the task-queue-based install
and uninstall endpoints, then verifies the results via the installed-list
endpoint and filesystem checks.

Requires a pre-built E2E environment (from setup_e2e_env.sh).
Set E2E_ROOT env var to point at it, or the tests will be skipped.

Install test methodology follows the main comfyui-manager test suite
(tests/glob/test_queue_task_api.py):
    - Uses a CNR-registered package with proper version-based install
    - Verifies .tracking file for CNR installs
    - Checks installed-list API with cnr_id matching
    - Cleans up .disabled/ directory entries

Usage:
    E2E_ROOT=/tmp/e2e_full_test pytest tests/e2e/test_e2e_endpoint.py -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest
import requests

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
CUSTOM_NODES = os.path.join(COMFYUI_PATH, "custom_nodes") if COMFYUI_PATH else ""
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scripts"
)

PORT = 8199
BASE_URL = f"http://127.0.0.1:{PORT}"

# CNR-registered package with multiple versions, no heavy dependencies.
# Same test package used by the main comfyui-manager test suite.
PACK_ID = "ComfyUI_SigmoidOffsetScheduler"
PACK_DIR_NAME = "ComfyUI_SigmoidOffsetScheduler"
PACK_CNR_ID = "comfyui_sigmoidoffsetscheduler"
PACK_VERSION = "1.0.1"

# Polling configuration for async task completion
POLL_TIMEOUT = 30       # max seconds to wait for an operation
POLL_INTERVAL = 0.5     # seconds between polls

pytestmark = pytest.mark.skipif(
    not E2E_ROOT
    or not os.path.isfile(os.path.join(E2E_ROOT, ".e2e_setup_complete")),
    reason="E2E_ROOT not set or E2E environment not ready (run setup_e2e_env.sh first)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_comfyui() -> int:
    """Start ComfyUI and return its PID."""
    env = {**os.environ, "E2E_ROOT": E2E_ROOT, "PORT": str(PORT)}
    r = subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "start_comfyui.sh")],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Failed to start ComfyUI:\n{r.stderr}")
    for part in r.stdout.strip().split():
        if part.startswith("COMFYUI_PID="):
            return int(part.split("=")[1])
    raise RuntimeError(f"Could not parse PID from start_comfyui output:\n{r.stdout}")


def _stop_comfyui():
    """Stop ComfyUI."""
    env = {**os.environ, "E2E_ROOT": E2E_ROOT, "PORT": str(PORT)}
    subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "stop_comfyui.sh")],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def _queue_task(task: dict) -> None:
    """Queue a task and start the worker."""
    resp = requests.post(
        f"{BASE_URL}/v2/manager/queue/task",
        json=task,
        timeout=10,
    )
    resp.raise_for_status()
    requests.post(f"{BASE_URL}/v2/manager/queue/start", timeout=10)


def _remove_pack(name: str) -> None:
    """Remove a node pack directory and any .disabled/ entries."""
    # Active directory
    path = os.path.join(CUSTOM_NODES, name)
    if os.path.islink(path):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    # .disabled/ entries (CNR versioned + nightly)
    disabled_dir = os.path.join(CUSTOM_NODES, ".disabled")
    if os.path.isdir(disabled_dir):
        cnr_lower = name.lower().replace("_", "").replace("-", "")
        for entry in os.listdir(disabled_dir):
            entry_lower = entry.lower().replace("_", "").replace("-", "")
            if entry_lower.startswith(cnr_lower):
                entry_path = os.path.join(disabled_dir, entry)
                if os.path.isdir(entry_path):
                    shutil.rmtree(entry_path, ignore_errors=True)


def _pack_exists(name: str) -> bool:
    return os.path.isdir(os.path.join(CUSTOM_NODES, name))


def _has_tracking(name: str) -> bool:
    """Check if the pack has a .tracking file (CNR install marker)."""
    return os.path.isfile(os.path.join(CUSTOM_NODES, name, ".tracking"))


def _wait_for(predicate, timeout=POLL_TIMEOUT, interval=POLL_INTERVAL):
    """Poll *predicate* until it returns True or *timeout* seconds elapse.

    Returns True if predicate was satisfied, False on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def comfyui():
    """Start ComfyUI once for the module, stop after all tests."""
    _remove_pack(PACK_DIR_NAME)
    pid = _start_comfyui()
    yield pid
    _stop_comfyui()
    _remove_pack(PACK_DIR_NAME)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEndpointInstallUninstall:
    """Install and uninstall via HTTP endpoints on a running ComfyUI.

    Follows the same methodology as tests/glob/test_queue_task_api.py in
    the main comfyui-manager repo: CNR version-based install, .tracking
    verification, installed-list API check.
    """

    def test_install_via_endpoint(self, comfyui):
        """POST /v2/manager/queue/task (install) -> pack appears on disk with .tracking."""
        _remove_pack(PACK_DIR_NAME)

        _queue_task({
            "ui_id": "e2e-install",
            "client_id": "e2e-install",
            "kind": "install",
            "params": {
                "id": PACK_ID,
                "version": PACK_VERSION,
                "selected_version": "latest",
                "mode": "remote",
                "channel": "default",
            },
        })
        assert _wait_for(
            lambda: _pack_exists(PACK_DIR_NAME),
        ), f"{PACK_DIR_NAME} not found in custom_nodes within {POLL_TIMEOUT}s"
        assert _has_tracking(PACK_DIR_NAME), f"{PACK_DIR_NAME} missing .tracking (not a CNR install?)"

    def test_installed_list_shows_pack(self, comfyui):
        """GET /v2/customnode/installed includes the installed pack."""
        # Self-contained precondition: ensure pack installed (don't rely on prior test)
        if not _pack_exists(PACK_DIR_NAME):
            _queue_task({
                "ui_id": "e2e-setup",
                "client_id": "e2e-setup",
                "kind": "install",
                "params": {
                    "id": PACK_ID,
                    "version": PACK_VERSION,
                    "selected_version": "latest",
                    "mode": "remote",
                    "channel": "default",
                },
            })
            assert _wait_for(lambda: _pack_exists(PACK_DIR_NAME)), (
                "Setup failed: pack not installed"
            )

        resp = requests.get(f"{BASE_URL}/v2/customnode/installed", timeout=10)
        resp.raise_for_status()
        installed = resp.json()

        package_found = any(
            pkg.get("cnr_id", "").lower() == PACK_CNR_ID.lower()
            for pkg in installed.values()
            if isinstance(pkg, dict) and pkg.get("cnr_id")
        )
        assert package_found, (
            f"{PACK_CNR_ID} not found in installed list: {list(installed.keys())}"
        )

    def test_uninstall_via_endpoint(self, comfyui):
        """POST /v2/manager/queue/task (uninstall) -> pack removed from disk AND absent from API.

        WI-N strengthening: previously FS-only (`not _pack_exists`). The API
        `installed` endpoint is the authoritative contract surface: a pack is
        "uninstalled" only when both the filesystem entry is gone AND the
        Manager's in-memory installed-index no longer lists its cnr_id.
        Defeats a regression where the FS delete succeeds but the installed
        cache still reports the pack (e.g. cache-invalidation bug).
        """
        # Self-contained: ensure pack is installed before testing uninstall
        if not _pack_exists(PACK_DIR_NAME):
            _queue_task({
                "ui_id": "e2e-uninstall-setup",
                "client_id": "e2e-uninstall-setup",
                "kind": "install",
                "params": {
                    "id": PACK_ID,
                    "version": PACK_VERSION,
                    "selected_version": "latest",
                    "mode": "remote",
                    "channel": "default",
                },
            })
            assert _wait_for(lambda: _pack_exists(PACK_DIR_NAME)), (
                "Setup failed: cannot install pack for uninstall test"
            )

        _queue_task({
            "ui_id": "e2e-uninstall",
            "client_id": "e2e-uninstall",
            "kind": "uninstall",
            "params": {
                "node_name": PACK_CNR_ID,
            },
        })
        assert _wait_for(
            lambda: not _pack_exists(PACK_DIR_NAME),
        ), f"{PACK_DIR_NAME} still exists after uninstall ({POLL_TIMEOUT}s timeout)"

        # API cross-check: cnr_id must be absent from /v2/customnode/installed.
        resp = requests.get(f"{BASE_URL}/v2/customnode/installed", timeout=10)
        resp.raise_for_status()
        installed = resp.json()
        package_found = any(
            pkg.get("cnr_id", "").lower() == PACK_CNR_ID.lower()
            for pkg in installed.values()
            if isinstance(pkg, dict) and pkg.get("cnr_id")
        )
        assert not package_found, (
            f"FS delete succeeded but {PACK_CNR_ID} still present in "
            f"/v2/customnode/installed — cache-invalidation regression. "
            f"Keys: {list(installed.keys())}"
        )


class TestEndpointStartup:
    """Verify ComfyUI startup with unified resolver."""

    def test_startup_resolver_ran(self, comfyui):
        """Startup log contains unified resolver output."""
        log_path = os.path.join(E2E_ROOT, "logs", "comfyui.log")
        with open(log_path) as f:
            log = f.read()
        assert "[UnifiedDepResolver]" in log
        assert "startup batch resolution succeeded" in log
