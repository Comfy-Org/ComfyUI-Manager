"""E2E tests for git-clone-based node installation via ComfyUI Manager API.

Starts a real ComfyUI instance and installs custom nodes by URL (nightly mode),
which triggers git_helper.py as a subprocess. This is the code path that crashed
on Windows with ModuleNotFoundError (Phase 1) and exit 128 (Phase 2).

Requires a pre-built E2E environment (from setup_e2e_env.py).
Set E2E_ROOT env var to point at it, or the tests will be skipped.

Supply-chain safety policy:
    Only install from verified, controllable authors (ltdrdata).

Usage:
    E2E_ROOT=/tmp/e2e_full_test pytest tests/e2e/test_e2e_git_clone.py -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

import pytest
import requests

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
CUSTOM_NODES = os.path.join(COMFYUI_PATH, "custom_nodes") if COMFYUI_PATH else ""

PORT = 8198  # Different port from endpoint tests to avoid conflicts
BASE_URL = f"http://127.0.0.1:{PORT}"

REPO_TEST1 = "https://github.com/ltdrdata/nodepack-test1-do-not-install"
PACK_TEST1 = "nodepack-test1-do-not-install"

POLL_TIMEOUT = 60
POLL_INTERVAL = 1.0

pytestmark = pytest.mark.skipif(
    not E2E_ROOT or not os.path.isfile(os.path.join(E2E_ROOT, ".e2e_setup_complete")),
    reason="E2E_ROOT not set or E2E environment not ready",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_comfyui_proc: subprocess.Popen | None = None


def _venv_python() -> str:
    if sys.platform == "win32":
        return os.path.join(E2E_ROOT, "venv", "Scripts", "python.exe")
    return os.path.join(E2E_ROOT, "venv", "bin", "python")


def _cm_cli_path() -> str:
    if sys.platform == "win32":
        return os.path.join(E2E_ROOT, "venv", "Scripts", "cm-cli.exe")
    return os.path.join(E2E_ROOT, "venv", "bin", "cm-cli")


def _ensure_cache():
    """Run cm-cli update-cache (blocking) to populate Manager cache before tests."""
    env = {**os.environ, "COMFYUI_PATH": COMFYUI_PATH}
    r = subprocess.run(
        [_cm_cli_path(), "update-cache"],
        capture_output=True, text=True, timeout=120, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"update-cache failed:\n{r.stderr}")


def _start_comfyui() -> int:
    """Start ComfyUI via Popen (cross-platform, no bash dependency)."""
    global _comfyui_proc  # noqa: PLW0603
    log_dir = os.path.join(E2E_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "comfyui.log")
    # Open the log file for the subprocess. We must keep this fd open while
    # the process runs, but MUST close it on any exit path to avoid handle
    # leaks (particularly on Windows where open handles block rmtree).
    log_file = open(log_path, "w")  # noqa: SIM115

    def _read_tail() -> str:
        with open(log_path) as f:
            return f.read()[-2000:]

    env = {
        **os.environ,
        "COMFYUI_PATH": COMFYUI_PATH,
        "PYTHONUNBUFFERED": "1",
    }
    try:
        _comfyui_proc = subprocess.Popen(
            [_venv_python(), "-u", os.path.join(COMFYUI_PATH, "main.py"),
             "--listen", "127.0.0.1", "--port", str(PORT),
             "--cpu", "--enable-manager"],
            stdout=log_file, stderr=subprocess.STDOUT,
            env=env,
        )
        # Wait for server to be ready.
        # Manager may restart ComfyUI after startup dependency install (exit 0 → re-launch).
        # If the process exits with code 0, keep polling — the restarted process will bind the port.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                r = requests.get(f"{BASE_URL}/system_stats", timeout=2)
                if r.status_code == 200:
                    return _comfyui_proc.pid
            except requests.ConnectionError:
                pass
            if _comfyui_proc.poll() is not None:
                if _comfyui_proc.returncode != 0:
                    log_file.close()
                    raise RuntimeError(
                        f"ComfyUI exited with code {_comfyui_proc.returncode}:\n{_read_tail()}"
                    )
                # exit 0 = Manager restart. Keep polling for the restarted process.
            time.sleep(1)
        raise RuntimeError(f"ComfyUI did not start within 120s. Log:\n{_read_tail()}")
    except Exception:
        # Ensure log_file handle is released on any failure
        try:
            log_file.close()
        except Exception:  # noqa: BLE001
            pass
        raise


def _stop_comfyui():
    """Stop ComfyUI process."""
    global _comfyui_proc  # noqa: PLW0603
    if _comfyui_proc is None:
        return
    _comfyui_proc.terminate()
    try:
        _comfyui_proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _comfyui_proc.kill()
    _comfyui_proc = None


def _queue_task(task: dict) -> None:
    """Queue a Manager task and start the worker."""
    resp = requests.post(f"{BASE_URL}/v2/manager/queue/task", json=task, timeout=10)
    resp.raise_for_status()
    requests.post(f"{BASE_URL}/v2/manager/queue/start", timeout=10)


def _remove_pack(name: str) -> None:
    """Remove a node pack from custom_nodes.

    On Windows, file locks (antivirus, git handles) can prevent immediate
    deletion. Strategy: retry rmtree, then fall back to rename (moves the
    directory out of the resolver's scan path so stale deps don't leak).
    """
    path = os.path.join(CUSTOM_NODES, name)
    if os.path.islink(path):
        os.unlink(path)
        return
    if not os.path.isdir(path):
        return
    for attempt in range(3):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            if attempt < 2:
                time.sleep(1)
    # Fallback: rename out of custom_nodes so resolver won't scan it
    import uuid
    trash = os.path.join(CUSTOM_NODES, f".trash_{uuid.uuid4().hex[:8]}")
    try:
        os.rename(path, trash)
        shutil.rmtree(trash, ignore_errors=True)
    except OSError:
        shutil.rmtree(path, ignore_errors=True)


def _pack_exists(name: str) -> bool:
    return os.path.isdir(os.path.join(CUSTOM_NODES, name))


def _wait_for(predicate, timeout=POLL_TIMEOUT, interval=POLL_INTERVAL):
    """Poll predicate until True or timeout."""
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
    """Populate cache, start ComfyUI, stop after all tests."""
    _remove_pack(PACK_TEST1)
    _ensure_cache()
    pid = _start_comfyui()
    yield pid
    _stop_comfyui()
    _remove_pack(PACK_TEST1)


# ---------------------------------------------------------------------------
# Tests: nightly (URL) install via Manager API → git_helper.py subprocess
#
# Single sequential test to avoid autouse cleanup races. The task queue
# is async so we poll for completion between steps.
# ---------------------------------------------------------------------------

_INSTALL_PARAMS = {
    "id": PACK_TEST1,
    "selected_version": "nightly",
    "mode": "remote",
    "channel": "default",
    "repository": REPO_TEST1,
    "version": "1.0.0",
}


class TestNightlyInstallCycle:
    """Full nightly install/verify/uninstall cycle in one test class.

    Tests MUST run in order (install → verify → uninstall). pytest preserves
    method definition order within a class.
    """

    def test_01_nightly_install(self, comfyui):
        """Nightly install should git-clone the requested repo AND .git/config remote.origin.url matches.

        WI-N strengthening: previously only `pack_exists + .git/ dir`. The
        `.git/` directory alone proves *some* git artifact exists but NOT
        that the clone targeted the requested URL — a regression where the
        manager clones the wrong repo (or a cached stale one) would still
        pass the old test. We now parse `.git/config` and assert the
        `[remote "origin"] url = ...` line matches REPO_TEST1 (with or
        without `.git` suffix — git accepts both forms).
        """
        _remove_pack(PACK_TEST1)
        assert not _pack_exists(PACK_TEST1), (
            f"Failed to clean {PACK_TEST1} — file locks may be holding the directory"
        )

        _queue_task({
            "ui_id": "e2e-nightly-install",
            "client_id": "e2e-nightly",
            "kind": "install",
            "params": _INSTALL_PARAMS,
        })

        assert _wait_for(lambda: _pack_exists(PACK_TEST1)), (
            f"{PACK_TEST1} not cloned within {POLL_TIMEOUT}s"
        )

        # Verify .git directory exists (git clone, not zip download)
        pack_dir = os.path.join(CUSTOM_NODES, PACK_TEST1)
        git_dir = os.path.join(pack_dir, ".git")
        assert os.path.isdir(git_dir), "No .git directory — not a git clone"

        # Parse .git/config for [remote "origin"] url and cross-check against
        # the requested repo URL. Git stores either `REPO` or `REPO.git`.
        git_config = os.path.join(git_dir, "config")
        assert os.path.isfile(git_config), (
            f".git/config missing at {git_config} — corrupted clone?"
        )
        import configparser
        cp = configparser.ConfigParser()
        cp.read(git_config)
        origin_section = 'remote "origin"'
        assert origin_section in cp, (
            f"[{origin_section}] section missing from .git/config: sections={cp.sections()!r}"
        )
        remote_url = cp[origin_section].get("url", "").rstrip("/")
        acceptable = {REPO_TEST1, REPO_TEST1 + ".git", REPO_TEST1.rstrip("/"), REPO_TEST1.rstrip("/") + ".git"}
        assert remote_url in acceptable or remote_url.rstrip(".git") == REPO_TEST1.rstrip(".git"), (
            f".git/config remote.origin.url mismatch — expected one of "
            f"{sorted(acceptable)}, got {remote_url!r}. The clone targeted "
            f"the wrong repository!"
        )

    def test_02_no_module_error(self, comfyui):
        """Server log must not contain ModuleNotFoundError (Phase 1 regression)."""
        log_path = os.path.join(E2E_ROOT, "logs", "comfyui.log")
        if not os.path.isfile(log_path):
            pytest.skip("Log file not found (server may use different log path)")

        with open(log_path) as f:
            log = f.read()
        assert "ModuleNotFoundError" not in log, (
            "ModuleNotFoundError in server log — git_helper.py import isolation broken"
        )

    def test_03_nightly_uninstall(self, comfyui):
        """Uninstall the nightly-installed pack from disk AND from API installed-index.

        WI-N strengthening: previously FS-only. The installed-index API is the
        authoritative Manager contract; FS-deletion alone is insufficient to
        call the operation "uninstalled". Cross-check that the pack key is
        absent from `/v2/customnode/installed` response.
        """
        if not _pack_exists(PACK_TEST1):
            pytest.skip("Pack not installed (previous test may have failed)")

        _queue_task({
            "ui_id": "e2e-nightly-uninst",
            "client_id": "e2e-nightly",
            "kind": "uninstall",
            "params": {
                "node_name": PACK_TEST1,
            },
        })
        assert _wait_for(lambda: not _pack_exists(PACK_TEST1)), (
            f"{PACK_TEST1} still exists after uninstall ({POLL_TIMEOUT}s timeout)"
        )

        # API cross-check: pack must be absent from /v2/customnode/installed.
        # Nightly packs appear keyed by directory name (no cnr_id for git-URL installs),
        # so membership check uses the pack's dir name.
        resp = requests.get(f"{BASE_URL}/v2/customnode/installed", timeout=10)
        resp.raise_for_status()
        installed = resp.json()
        assert PACK_TEST1 not in installed, (
            f"FS delete succeeded but {PACK_TEST1!r} still present in "
            f"/v2/customnode/installed — cache-invalidation regression. "
            f"Keys: {list(installed.keys())}"
        )
        # Defensive: also check by aux_id / cnr_id in case of schema variation.
        for pkg_key, pkg in installed.items():
            if isinstance(pkg, dict):
                assert (
                    pkg.get("cnr_id") != PACK_TEST1
                    and pkg.get("aux_id") != PACK_TEST1
                ), (
                    f"Installed entry {pkg_key!r} still references {PACK_TEST1!r} "
                    f"via cnr_id/aux_id: {pkg!r}"
                )
