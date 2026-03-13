"""E2E tests for cm-cli --uv-compile across all supported commands.

Requires a pre-built E2E environment (from setup_e2e_env.sh).
Set E2E_ROOT env var to point at it, or the tests will be skipped.

Supply-chain safety policy:
    To prevent supply-chain attacks, E2E tests MUST only install node packs
    from verified, controllable authors (ltdrdata, comfyanonymous, etc.).
    Currently this suite uses only ltdrdata's dedicated test packs
    (nodepack-test1-do-not-install, nodepack-test2-do-not-install) which
    are intentionally designed for conflict testing and contain no
    executable code.  Adding packs from unverified sources is prohibited.

Usage:
    E2E_ROOT=/tmp/e2e_full_test pytest tests/e2e/test_e2e_uv_compile.py -v
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
CM_CLI = os.path.join(E2E_ROOT, "venv", "bin", "cm-cli") if E2E_ROOT else ""
CUSTOM_NODES = os.path.join(COMFYUI_PATH, "custom_nodes") if COMFYUI_PATH else ""

REPO_TEST1 = "https://github.com/ltdrdata/nodepack-test1-do-not-install"
REPO_TEST2 = "https://github.com/ltdrdata/nodepack-test2-do-not-install"
PACK_TEST1 = "nodepack-test1-do-not-install"
PACK_TEST2 = "nodepack-test2-do-not-install"

pytestmark = pytest.mark.skipif(
    not E2E_ROOT or not os.path.isfile(os.path.join(E2E_ROOT, ".e2e_setup_complete")),
    reason="E2E_ROOT not set or E2E environment not ready (run setup_e2e_env.sh first)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cm_cli(*args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run cm-cli in the E2E environment."""
    env = {**os.environ, "COMFYUI_PATH": COMFYUI_PATH}
    return subprocess.run(
        [CM_CLI, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _remove_pack(name: str) -> None:
    """Remove a node pack from custom_nodes (if it exists)."""
    path = os.path.join(CUSTOM_NODES, name)
    if os.path.islink(path):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _pack_exists(name: str) -> bool:
    return os.path.isdir(os.path.join(CUSTOM_NODES, name))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_test_packs():
    """Ensure test node packs are removed before and after each test."""
    _remove_pack(PACK_TEST1)
    _remove_pack(PACK_TEST2)
    yield
    _remove_pack(PACK_TEST1)
    _remove_pack(PACK_TEST2)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInstall:
    """cm-cli install --uv-compile"""

    def test_install_single_pack_resolves(self):
        """Install one test pack with --uv-compile → resolve succeeds."""
        r = _run_cm_cli("install", "--uv-compile", REPO_TEST1)
        combined = r.stdout + r.stderr

        assert _pack_exists(PACK_TEST1)
        assert "Installation was successful" in combined
        assert "Resolved" in combined

    def test_install_conflicting_packs_shows_attribution(self):
        """Install two conflicting packs → conflict attribution output."""
        # Install first (no conflict yet)
        r1 = _run_cm_cli("install", "--uv-compile", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)
        assert "Resolved" in r1.stdout + r1.stderr

        # Install second → conflict
        r2 = _run_cm_cli("install", "--uv-compile", REPO_TEST2)
        combined = r2.stdout + r2.stderr

        assert _pack_exists(PACK_TEST2)
        assert "Installation was successful" in combined
        assert "Resolution failed" in combined
        assert "Conflicting packages (by node pack):" in combined
        assert PACK_TEST1 in combined
        assert PACK_TEST2 in combined
        assert "ansible" in combined.lower()


class TestReinstall:
    """cm-cli reinstall --uv-compile"""

    def test_reinstall_with_uv_compile(self):
        """Reinstall an existing pack with --uv-compile."""
        # Install first
        _run_cm_cli("install", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)

        # Reinstall with --uv-compile
        r = _run_cm_cli("reinstall", "--uv-compile", REPO_TEST1)
        combined = r.stdout + r.stderr

        # uv-compile should run (resolve output present)
        assert "Resolving dependencies" in combined


class TestUpdate:
    """cm-cli update --uv-compile"""

    def test_update_single_with_uv_compile(self):
        """Update an installed pack with --uv-compile."""
        _run_cm_cli("install", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)

        r = _run_cm_cli("update", "--uv-compile", REPO_TEST1)
        combined = r.stdout + r.stderr

        assert "Resolving dependencies" in combined

    def test_update_all_with_uv_compile(self):
        """update all --uv-compile runs uv-compile after updating."""
        _run_cm_cli("install", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)

        r = _run_cm_cli("update", "--uv-compile", "all")
        combined = r.stdout + r.stderr

        assert "Resolving dependencies" in combined


class TestFix:
    """cm-cli fix --uv-compile"""

    def test_fix_single_with_uv_compile(self):
        """Fix an installed pack with --uv-compile."""
        _run_cm_cli("install", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)

        r = _run_cm_cli("fix", "--uv-compile", REPO_TEST1)
        combined = r.stdout + r.stderr

        assert "Resolving dependencies" in combined

    def test_fix_all_with_uv_compile(self):
        """fix all --uv-compile runs uv-compile after fixing."""
        _run_cm_cli("install", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)

        r = _run_cm_cli("fix", "--uv-compile", "all")
        combined = r.stdout + r.stderr

        assert "Resolving dependencies" in combined


class TestUvCompileStandalone:
    """cm-cli uv-compile (standalone command)"""

    def test_uv_compile_no_packs(self):
        """uv-compile with no node packs → 'No custom node packs found'."""
        r = _run_cm_cli("uv-compile")
        combined = r.stdout + r.stderr

        # Only ComfyUI-Manager exists (no requirements.txt in it normally)
        # so either "No custom node packs found" or resolves 0
        assert r.returncode == 0 or "No custom node packs" in combined

    def test_uv_compile_with_packs(self):
        """uv-compile after installing test pack → resolves."""
        _run_cm_cli("install", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)

        r = _run_cm_cli("uv-compile")
        combined = r.stdout + r.stderr

        assert "Resolving dependencies" in combined
        assert "Resolved" in combined

    def test_uv_compile_conflict_attribution(self):
        """uv-compile with conflicting packs → shows attribution."""
        _run_cm_cli("install", REPO_TEST1)
        _run_cm_cli("install", REPO_TEST2)

        r = _run_cm_cli("uv-compile")
        combined = r.stdout + r.stderr

        assert r.returncode != 0
        assert "Conflicting packages (by node pack):" in combined
        assert PACK_TEST1 in combined
        assert PACK_TEST2 in combined


class TestRestoreDependencies:
    """cm-cli restore-dependencies --uv-compile"""

    def test_restore_dependencies_with_uv_compile(self):
        """restore-dependencies --uv-compile runs resolver after restore."""
        _run_cm_cli("install", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)

        r = _run_cm_cli("restore-dependencies", "--uv-compile")
        combined = r.stdout + r.stderr

        assert "Resolving dependencies" in combined


class TestConflictAttributionDetail:
    """Verify conflict attribution output details."""

    def test_both_packs_and_specs_shown(self):
        """Conflict output shows pack names AND version specs."""
        _run_cm_cli("install", REPO_TEST1)
        _run_cm_cli("install", REPO_TEST2)

        r = _run_cm_cli("uv-compile")
        combined = r.stdout + r.stderr

        # Processed attribution must show exact version specs (not raw uv error)
        assert "Conflicting packages (by node pack):" in combined
        assert "ansible==9.13.0" in combined
        assert "ansible-core==2.14.0" in combined
        # Both pack names present in attribution block
        assert PACK_TEST1 in combined
        assert PACK_TEST2 in combined
