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
import sys
import time

import pytest

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
CUSTOM_NODES = os.path.join(COMFYUI_PATH, "custom_nodes") if COMFYUI_PATH else ""

# Cross-platform: resolve cm-cli executable in venv
if E2E_ROOT:
    if sys.platform == "win32":
        CM_CLI = os.path.join(E2E_ROOT, "venv", "Scripts", "cm-cli.exe")
    else:
        CM_CLI = os.path.join(E2E_ROOT, "venv", "bin", "cm-cli")
else:
    CM_CLI = ""

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
    """Run cm-cli in the E2E environment.

    Uses file-based capture instead of pipes to avoid Windows pipe buffer
    loss when the subprocess exits via typer.Exit / sys.exit.
    """
    env = {
        **os.environ,
        "COMFYUI_PATH": COMFYUI_PATH,
        "PYTHONUNBUFFERED": "1",
    }
    stdout_path = os.path.join(E2E_ROOT, f"_cm_stdout_{os.getpid()}.tmp")
    stderr_path = os.path.join(E2E_ROOT, f"_cm_stderr_{os.getpid()}.tmp")
    try:
        with open(stdout_path, "w", encoding="utf-8") as out_f, \
             open(stderr_path, "w", encoding="utf-8") as err_f:
            r = subprocess.run(
                [CM_CLI, *args],
                stdout=out_f,
                stderr=err_f,
                timeout=timeout,
                env=env,
            )
        with open(stdout_path, encoding="utf-8", errors="replace") as f:
            r.stdout = f.read()
        with open(stderr_path, encoding="utf-8", errors="replace") as f:
            r.stderr = f.read()
    finally:
        for p in (stdout_path, stderr_path):
            try:
                os.unlink(p)
            except OSError:
                pass
    return r


def _remove_pack(name: str) -> None:
    """Remove a node pack from custom_nodes (if it exists).

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
    # Try direct removal first
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _clean_trash() -> None:
    """Remove .trash_* directories left by rename-then-delete fallback."""
    if not CUSTOM_NODES or not os.path.isdir(CUSTOM_NODES):
        return
    for name in os.listdir(CUSTOM_NODES):
        if name.startswith(".trash_"):
            shutil.rmtree(os.path.join(CUSTOM_NODES, name), ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_test_packs():
    """Ensure test node packs are removed before and after each test."""
    _remove_pack(PACK_TEST1)
    _remove_pack(PACK_TEST2)
    _clean_trash()
    yield
    _remove_pack(PACK_TEST1)
    _remove_pack(PACK_TEST2)
    _clean_trash()


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
        assert _pack_exists(PACK_TEST1), f"test1 not installed (rc={r1.returncode})"
        assert r1.returncode == 0, f"test1 install failed (rc={r1.returncode})"

        # Install second → uv-compile detects conflict between
        # python-slugify==8.0.4 (test1) and text-unidecode==1.2 (test2)
        r2 = _run_cm_cli("install", "--uv-compile", REPO_TEST2)
        combined = r2.stdout + r2.stderr

        assert _pack_exists(PACK_TEST2), f"test2 not cloned (rc={r2.returncode})"
        assert r2.returncode != 0, f"Expected non-zero exit (conflict). rc={r2.returncode}"
        assert "Resolution failed" in combined, (
            f"Missing 'Resolution failed'. stdout={r2.stdout[:500]!r}"
        )
        assert "Conflicting packages (by node pack):" in combined


class TestReinstall:
    """cm-cli reinstall --uv-compile"""

    def test_reinstall_with_uv_compile(self):
        """Reinstall an existing pack with --uv-compile — resolver MUST run."""
        _run_cm_cli("install", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)

        r = _run_cm_cli("reinstall", "--uv-compile", REPO_TEST1)
        combined = r.stdout + r.stderr

        assert _pack_exists(PACK_TEST1)
        assert "Resolving dependencies" in combined, (
            f"Expected resolver to run on reinstall but output had: {combined[:500]!r}"
        )


class TestUvCompileVerbs:
    """cm-cli verbs that support --uv-compile.

    WI-NN Cluster 5 (bloat-sweep dev:ci-004/005/006/007/011 B9 copy-paste):
    consolidates 5 previously-separate test functions that all assert the same
    "Resolving dependencies" emission after install+verb. Parametrized across
    the 5 supported verb/target combinations.
    """

    @pytest.mark.parametrize(
        "cm_args",
        [
            pytest.param(("update", "--uv-compile", REPO_TEST1), id="update-single"),
            pytest.param(("update", "--uv-compile", "all"), id="update-all"),
            pytest.param(("fix", "--uv-compile", REPO_TEST1), id="fix-single"),
            pytest.param(("fix", "--uv-compile", "all"), id="fix-all"),
            pytest.param(("restore-dependencies", "--uv-compile"), id="restore-dependencies"),
        ],
    )
    def test_verb_with_uv_compile_runs_resolver(self, cm_args):
        """Every --uv-compile-aware verb triggers dependency resolution."""
        _run_cm_cli("install", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)

        r = _run_cm_cli(*cm_args)
        combined = r.stdout + r.stderr

        assert "Resolving dependencies" in combined


class TestUvCompileStandalone:
    """cm-cli uv-sync (standalone command, formerly uv-compile)"""

    def test_uv_compile_no_test_packs_exits_zero(self):
        """uv-sync without test packs must exit rc==0 (clean success).

        WI-OO Item 2 (bloat dev:ci-008 B5): split from the previous OR-fallback
        test. This half pins the exit-code contract.
        """
        r = _run_cm_cli("uv-sync")
        assert r.returncode == 0, (
            f"uv-sync should exit 0 when no test packs are installed; "
            f"got rc={r.returncode}. Output: {(r.stdout + r.stderr)[:500]!r}"
        )

    def test_uv_compile_no_test_packs_emits_signal(self):
        """uv-sync emits a definitive signal — never silent success.

        WI-OO Item 2 (bloat dev:ci-008 B5): split from the previous OR-fallback
        test. This half pins the output-signal contract. The emitted marker
        depends on what's installed in the E2E sandbox at the moment — either
        'No custom node packs' (empty tree with no resolvable requirements) or
        'Resolved' (non-empty tree with successful resolution). Asserting the
        disjunction here is narrower than the original OR (which also accepted
        rc==0 with completely silent output); this test requires an actual
        human-readable marker in the output stream.
        """
        r = _run_cm_cli("uv-sync")
        combined = r.stdout + r.stderr
        # Precondition: exit success is verified by the sibling test above.
        assert r.returncode == 0, f"Precondition failed: uv-sync rc={r.returncode}"
        empty_marker = "No custom node packs" in combined
        resolved_marker = "Resolved" in combined
        assert empty_marker or resolved_marker, (
            f"Expected 'No custom node packs' (empty tree) or 'Resolved' "
            f"(non-empty tree) marker; output was silent or unrecognized: "
            f"{combined[:500]!r}"
        )

    def test_uv_compile_with_packs(self):
        """uv-compile after installing test pack → resolves."""
        _run_cm_cli("install", REPO_TEST1)
        assert _pack_exists(PACK_TEST1)

        r = _run_cm_cli("uv-sync")
        combined = r.stdout + r.stderr

        assert "Resolving dependencies" in combined
        assert "Resolved" in combined


class TestConflictAttributionDetail:
    """Verify conflict attribution output details."""

    def test_both_packs_and_specs_shown(self):
        """Conflict output shows pack names AND version specs."""
        _run_cm_cli("install", REPO_TEST1)
        _run_cm_cli("install", REPO_TEST2)

        r = _run_cm_cli("uv-sync")
        combined = r.stdout + r.stderr

        # Processed attribution must show exact version specs (not raw uv error)
        assert r.returncode != 0
        assert "Conflicting packages (by node pack):" in combined
        assert "python-slugify==8.0.4" in combined
        assert "text-unidecode==1.2" in combined
        # Both pack names present in attribution block
        assert PACK_TEST1 in combined
        assert PACK_TEST2 in combined
