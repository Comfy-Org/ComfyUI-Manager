"""E2E tests for ComfyUI Manager system information endpoints.

Tests the system-level endpoints:
- GET  /v2/manager/version             — manager version string
- GET  /v2/manager/is_legacy_manager_ui — legacy UI flag
- POST /v2/manager/reboot              — server reboot (last test)

The reboot test is intentionally placed LAST because it triggers a
server restart. After POST, the test polls until the server comes back.

Requires a pre-built E2E environment (from setup_e2e_env.sh).
Set E2E_ROOT env var to point at it, or the tests will be skipped.

Usage:
    E2E_ROOT=/tmp/e2e_full_test pytest tests/e2e/test_e2e_system_info.py -v
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest
import requests

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scripts"
)

PORT = 8199
BASE_URL = f"http://127.0.0.1:{PORT}"

# Reboot requires longer polling — server must fully restart
REBOOT_TIMEOUT = 60
REBOOT_INTERVAL = 2.0

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


def _wait_for(predicate, timeout=30, interval=0.5):
    """Poll *predicate* until it returns True or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _server_is_healthy():
    """Check if the ComfyUI server responds to a health endpoint."""
    try:
        resp = requests.get(f"{BASE_URL}/system_stats", timeout=5)
        return resp.status_code == 200
    except requests.ConnectionError:
        return False
    except requests.Timeout:
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def comfyui():
    """Start ComfyUI once for the module, stop after all tests."""
    pid = _start_comfyui()
    yield pid
    _stop_comfyui()


# ---------------------------------------------------------------------------
# Tests — version
# ---------------------------------------------------------------------------

class TestManagerVersion:
    """Test GET /v2/manager/version."""

    def test_version_returns_string(self, comfyui):
        """GET /v2/manager/version returns a non-empty version string."""
        resp = requests.get(f"{BASE_URL}/v2/manager/version", timeout=10)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}"
        )
        version = resp.text
        assert isinstance(version, str), (
            f"Expected string response, got {type(version).__name__}"
        )
        assert len(version.strip()) > 0, "Version string should not be empty"

    def test_version_is_stable(self, comfyui):
        """Consecutive calls return the same version (no mutation)."""
        resp1 = requests.get(f"{BASE_URL}/v2/manager/version", timeout=10)
        resp1.raise_for_status()
        resp2 = requests.get(f"{BASE_URL}/v2/manager/version", timeout=10)
        resp2.raise_for_status()
        assert resp1.text == resp2.text, (
            f"Version changed between calls: {resp1.text!r} vs {resp2.text!r}"
        )


# ---------------------------------------------------------------------------
# Tests — is_legacy_manager_ui
# ---------------------------------------------------------------------------

class TestIsLegacyManagerUI:
    """Test GET /v2/manager/is_legacy_manager_ui."""

    def test_returns_boolean_field(self, comfyui):
        """GET /v2/manager/is_legacy_manager_ui returns False in E2E env.

        WI-T Cluster G target 5 (research-cluster-g.md Target 2):
        Strengthened from type-only `isinstance(bool)` to exact-value `is False`.

        Launcher-deterministic: `tests/e2e/scripts/start_comfyui.sh` passes
        only `--cpu --enable-manager --port` — NO `--enable-manager-legacy-ui`.
        `action='store_true'` on that flag defaults to False, so the handler
        at `glob/manager_server.py:1500-1506` must return
        `{"is_legacy_manager_ui": False}`.

        If the E2E launcher ever starts passing `--enable-manager-legacy-ui`,
        this assertion fails loudly with a clear pointer — correct behavior.
        """
        resp = requests.get(
            f"{BASE_URL}/v2/manager/is_legacy_manager_ui", timeout=10
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}"
        )
        data = resp.json()
        assert "is_legacy_manager_ui" in data, (
            f"Response missing 'is_legacy_manager_ui' field: {data}"
        )
        assert data["is_legacy_manager_ui"] is False, (
            f"E2E launcher omits --enable-manager-legacy-ui; expected False, "
            f"got {data['is_legacy_manager_ui']!r}. "
            f"If start_comfyui.sh was changed to pass that flag, update this assertion."
        )


# ---------------------------------------------------------------------------
# Tests — reboot (MUST BE LAST — server restarts)
# ---------------------------------------------------------------------------

class TestReboot:
    """Test POST /v2/manager/reboot.

    This test MUST run last in the module because a successful reboot
    terminates or replaces the server process. The test polls until the
    server comes back (or times out).
    """

    def test_reboot_and_recovery(self, comfyui):
        """POST /v2/manager/reboot triggers restart; server comes back."""
        # Verify server is running before reboot
        assert _server_is_healthy(), "Server not healthy before reboot test"

        # Record pre-reboot version for comparison
        pre_version = requests.get(
            f"{BASE_URL}/v2/manager/version", timeout=10
        ).text

        # Trigger reboot — server may drop connection mid-response
        try:
            resp = requests.post(f"{BASE_URL}/v2/manager/reboot", timeout=10)
            if resp.status_code == 403:
                pytest.skip(
                    "Reboot denied by security policy "
                    "(security_level does not allow 'middle')"
                )
            assert resp.status_code == 200, (
                f"Expected 200 or 403 from reboot, got {resp.status_code}"
            )
        except requests.ConnectionError:
            # Server dropped connection during reboot — expected behavior
            pass

        # Give the server a moment to begin shutdown
        time.sleep(2)

        # Poll until server comes back
        recovered = _wait_for(
            _server_is_healthy,
            timeout=REBOOT_TIMEOUT,
            interval=REBOOT_INTERVAL,
        )
        assert recovered, (
            f"Server did not recover within {REBOOT_TIMEOUT}s after reboot"
        )

        # Verify server is functional after reboot
        post_version = requests.get(
            f"{BASE_URL}/v2/manager/version", timeout=10
        ).text
        assert post_version == pre_version, (
            f"Version changed after reboot: {pre_version!r} -> {post_version!r}"
        )
