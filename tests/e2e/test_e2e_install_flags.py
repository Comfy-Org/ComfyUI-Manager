"""GOAL #60 — Real-server E2E for the dedicated install flags (worktree-mounted Manager).

Boots a REAL ComfyUI server from a disposable test root
(`E2E_COMFYUI_ROOT`, built by tests/e2e/scripts/setup_e2e_env.sh) with
the Manager mounted via `git worktree add --detach` (NEVER pip-installed
— [D2]) and exercises both dedicated-flag surfaces over live HTTP.

Usage:
    bash tests/e2e/scripts/setup_e2e_env.sh            # once (E2E-SC-01)
    E2E_COMFYUI_ROOT=/path/to/root pytest tests/e2e/test_e2e_install_flags.py -v

Per-row map (goal60-scenarios.md, 24 rows — spec §3 BINDING):
  SC-01  setup_e2e_env.sh (pre-suite script; idempotent build + marker — not a pytest test)
  SC-02  mount_worktree fixture create path (SHA pin, .git-file, no-pip, printed SHA)
  SC-03  mount_worktree fixture reuse path + path-prefix scoping invariant
  SC-04  _start_server via start_comfyui.sh (readiness poll, restart tolerance,
         per-launch log comfyui.<port>.<launch-id>.log)
  SC-05  test_00_smoke_manager_version in EVERY server-up class (+abort guard)
  SC-06  _stage via stage_flags.sh (backup-if-absent; restart-only by construction)
  SC-07  class fixture finalizers (stop + port-free + config restore + backup DELETE)
         + mount_worktree finalizer (unmount + prune + absence assert)
  SC-10  TestDenyArms.test_01_sa_deny           SC-11  TestDenyArms.test_02_sb_deny
  SC-12  TestAllowArms.test_01_git_url_allow
  SC-13  TestAllowArms.test_02_pip_allow_reserved      (anti-false-PASS — VERBATIM)
  SC-14  TestAllowArms.test_03_restart_consumes_reservation (R-A through the holder)
  SC-20  _pre_guards in both class fixtures (before any request)
  SC-21  TestAllowArms.test_04_clone_residual_cleanup (+ installed-index cross-check)
  SC-22  TestAllowArms.test_05_pip_residual_uninstall
  SC-23  _reservation_guard — UNCONDITIONAL fixture-teardown guard (failure path)
  SC-24  TestZeroResidual.test_99_zero_residual_sweep (unmount half lives in the
         mount_worktree finalizer — it cannot be asserted from inside the session)
  SC-30  module-level pytestmark (env unset -> all SKIP; unit suite unaffected)
  SC-31  module-level pytestmark (marker absent -> all SKIP)
  SC-32  needs_network marker on fixture-dependent (allow-arm / public) rows
  SC-33  collection safety by construction: stdlib + pytest + requests
         (via pytest.importorskip) ONLY — no glob/ imports, no server imports,
         HTTP only at test time
  SC-40  TestPublicListener (opt-in E2E_PUBLIC_LISTEN=1; L-P @ 0.0.0.0)
  SC-41  batch S-C/S-C' E2E — DEFERRED (Q-5; spec FREEZE item 3; recorded here)
  SC-42  TestAllowArms.test_06_requirements_watchdog (L-A launch log)

Fixture-lifecycle ownership (spec §3 BINDING block):
  - every class server fixture DECLARES mount_worktree (mount-before-launch);
  - process handle lives in a MUTABLE ServerHolder owned by the fixture;
    teardown stops the CURRENT holder content (whatever launch identity is live);
  - SC-14 restarts THROUGH the holder (stop L-A -> launch R-A -> replace handle);
  - stop-before-next-class is structural (pytest class-fixture scoping);
  - `requests` is imported via pytest.importorskip (absence degrades to SKIP).

T6 note: no tests/e2e/conftest.py — all fixtures are single-module, so the
optional T6 file is not demanded (spec §2 T6 condition not met).
"""
from __future__ import annotations

import configparser
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Skip gates (E2E-SC-30/31) — BEFORE anything env-dependent
# ---------------------------------------------------------------------------

E2E_ROOT = os.environ.get("E2E_COMFYUI_ROOT", "")
_MARKER_OK = bool(E2E_ROOT) and os.path.isfile(os.path.join(E2E_ROOT, ".e2e_setup_complete"))

pytestmark = pytest.mark.skipif(
    not _MARKER_OK,
    reason="E2E_COMFYUI_ROOT not set or E2E environment not ready (.e2e_setup_complete missing)",
)

# requests: test-extra — absence degrades to SKIP, never a collection error
# (spec §3 binding block item 5; [D4]).
requests = pytest.importorskip("requests")

# ---------------------------------------------------------------------------
# Constants / paths
# ---------------------------------------------------------------------------

PORT = int(os.environ.get("PORT", "8189"))
TIMEOUT = int(os.environ.get("TIMEOUT", "120"))
BASE_URL = f"http://127.0.0.1:{PORT}"

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR / "scripts"
MANAGER_REPO = THIS_DIR.parents[1]  # repo root of the checkout running the suite

ROOT = Path(E2E_ROOT) if E2E_ROOT else Path(".")
COMFY_DIR = ROOT / "comfyui"
CN_DIR = COMFY_DIR / "custom_nodes"
MOUNT = CN_DIR / "comfyui-manager"
CFG = COMFY_DIR / "user" / "__manager" / "config.ini"
CFG_BACKUP = Path(str(CFG) + ".before-flags")
SCRIPTS_FILE = COMFY_DIR / "user" / "__manager" / "startup-scripts" / "install-scripts.txt"
LOGS_DIR = ROOT / "logs"
VENV_PY = ROOT / "venv" / "bin" / "python"

# Owned fixtures ONLY (goal60-scenarios.md Conventions; [D3])
NODEPACK_URL = "https://github.com/ltdrdata/nodepack-test1-do-not-install"
PACK_NAME = "nodepack-test1-do-not-install"
# pip stimulus uses the git+ scheme: pip/uv require it for VCS URLs — a
# plain GitHub repo URL serves HTML and cannot install (verified by probe;
# spec amendment requested via leader pushback 2026-06-08; the SC-13/14
# oracle itself is encoded VERBATIM).
PIP_URL = "git+https://github.com/ltdrdata/pip-test1-do-not-install"
PIP_PKG = "pip-test1-do-not-install"
PIP_IMPORT = "pip_test1_do_not_install"
PIP_MARKER = "pip-test1-do-not-install:ok"
# Amendment A2 (live-run finding, leader-approved): the S-A nodepack fixture
# is deliberately NOT zero-dep — it pins python-slugify==8.0.4 in its
# requirements as the invariant-4 ride-along proof vehicle. The SC-42
# watchdog therefore allowlists exactly that requirement, and the
# transitive-dep residual class is swept at allow-class teardown + SC-24.
# (The S-B pip fixture IS zero-dep as documented.)
NODEPACK_PINNED_REQ = "python-slugify==8.0.4"
TRANSITIVE_DEPS = ("python-slugify", "text-unidecode")

POLL_TIMEOUT = 60
POLL_INTERVAL = 1.0

# Distinctive substrings of the flag-naming denial constants @ d45c8e6b
DENY_COPY_GIT = "'allow_git_url_install = true' in config.ini"
DENY_COPY_PIP = "'allow_pip_install = true' in config.ini"
# Old security_level-attributing copy (must NOT appear on flag denials)
OLD_COPY_GENERAL = "is not allowed in this security_level"
OLD_COPY_NORMAL_MINUS = "set the security level to"


# ---------------------------------------------------------------------------
# Network probe (E2E-SC-32) — evaluated ONLY when the env gate is open, so
# collection without the env performs no network IO (SC-33).
# ---------------------------------------------------------------------------

def _network_available() -> bool:
    try:
        with socket.create_connection(("github.com", 443), timeout=5):
            return True
    except OSError:
        return False


_NETWORK = _network_available() if _MARKER_OK else False
needs_network = pytest.mark.skipif(
    not _NETWORK,
    reason="github.com unreachable — network-dependent fixture row skipped (E2E-SC-32)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd, check=False, timeout=180, env=None, cwd=None):
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=check,
        env=env, cwd=cwd,
    )


def _script(name: str) -> str:
    return str(SCRIPTS_DIR / name)


def _script_env(**extra) -> dict:
    env = {**os.environ, "E2E_COMFYUI_ROOT": str(ROOT), "PORT": str(PORT),
           "TIMEOUT": str(TIMEOUT)}
    env.update({k: str(v) for k, v in extra.items()})
    return env


def _pack_dir(name: str = PACK_NAME) -> Path:
    return CN_DIR / name


def _pack_exists(name: str = PACK_NAME) -> bool:
    return _pack_dir(name).is_dir()


def _remove_pack(name: str = PACK_NAME) -> None:
    """Donor _remove_pack pattern: rmtree 3-retry + rename-to-.trash_ fallback."""
    path = _pack_dir(name)
    if path.is_symlink():
        path.unlink()
        return
    if not path.is_dir():
        return
    for attempt in range(3):
        try:
            shutil.rmtree(path)
            return
        except OSError:
            if attempt < 2:
                time.sleep(1)
    trash = CN_DIR / f".trash_{uuid.uuid4().hex[:8]}"
    try:
        os.rename(path, trash)
        shutil.rmtree(trash, ignore_errors=True)
    except OSError:
        shutil.rmtree(path, ignore_errors=True)


def _wait_for(predicate, timeout=POLL_TIMEOUT, interval=POLL_INTERVAL) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _pip_import_rc() -> int:
    return _run([str(VENV_PY), "-c", f"import {PIP_IMPORT}"]).returncode


def _pip_marker_rc() -> "subprocess.CompletedProcess":
    return _run([
        str(VENV_PY), "-c",
        f"import {PIP_IMPORT} as m; assert m.MARKER == '{PIP_MARKER}'",
    ])


def _pip_uninstall() -> "subprocess.CompletedProcess":
    return _run([str(VENV_PY), "-m", "pip", "uninstall", "-y", PIP_PKG])


def _scripts_clean() -> bool:
    """True when the reservation file is absent OR carries no pip-test1 line."""
    if not SCRIPTS_FILE.exists():
        return True
    return "pip-test1" not in SCRIPTS_FILE.read_text(errors="ignore")


def _reservation_guard() -> None:
    """E2E-SC-23 — UNCONDITIONAL teardown guard for the unconsumed-reservation
    leak class: a leaked line would pip-install on ANY next boot of this root."""
    if SCRIPTS_FILE.exists() and "pip-test1" in SCRIPTS_FILE.read_text(errors="ignore"):
        SCRIPTS_FILE.unlink()
    assert _scripts_clean(), "reservation guard failed to clear pip-test1 line (SC-23)"


def _restore_config() -> None:
    """E2E-SC-07: restore from backup, then DELETE the backup and assert absence
    (a surviving stale backup would silently restore an outdated config at a
    FUTURE run's teardown via the create-only-if-absent rule)."""
    if CFG_BACKUP.exists():
        shutil.copyfile(CFG_BACKUP, CFG)
        CFG_BACKUP.unlink()
    assert not CFG_BACKUP.exists(), "config backup must be DELETED after restore (SC-07/24)"


def _port_free() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", PORT)) != 0
    finally:
        s.close()


def _pre_guards() -> None:
    """E2E-SC-20 — before EACH arm's matrix rows; assert all three."""
    _remove_pack(PACK_NAME)
    assert not _pack_exists(PACK_NAME), (
        f"pre-guard: failed to clean {PACK_NAME} (file locks?)"
    )
    _pip_uninstall()  # ignore rc: not-installed is fine
    assert _pip_import_rc() != 0, "pre-guard: pip fixture importable before test"
    _reservation_guard()
    assert _scripts_clean(), "pre-guard: stale pip-test1 reservation present"


# ---------------------------------------------------------------------------
# Server lifecycle (E2E-SC-04 + spec §3 binding holder contract)
# ---------------------------------------------------------------------------

class ServerHolder:
    """Mutable process-handle holder owned by the class server fixture.

    The holder always points at the CURRENT launch identity; SC-14 replaces
    its content when it restarts through it, so class teardown stops
    whatever is live — no orphan."""

    def __init__(self):
        self.launch_id: str | None = None
        self.log_path: Path | None = None
        self.live = False
        self.smoke_ok = False


def _stage(mode: str) -> None:
    r = _run(["bash", _script("stage_flags.sh"), mode], env=_script_env(), check=False)
    assert r.returncode == 0, f"stage_flags.sh {mode} failed:\n{r.stdout}\n{r.stderr}"
    assert CFG_BACKUP.exists(), "backup must exist after staging (SC-06)"


def _start_server(holder: ServerHolder, launch_id: str, listen: str = "127.0.0.1") -> None:
    r = _run(
        ["bash", _script("start_comfyui.sh")],
        env=_script_env(LISTEN=listen, LAUNCH_ID=launch_id),
        timeout=TIMEOUT + 90,
    )
    assert r.returncode == 0, (
        f"start_comfyui.sh failed for launch {launch_id}:\n{r.stdout}\n{r.stderr}"
    )
    holder.launch_id = launch_id
    holder.log_path = LOGS_DIR / f"comfyui.{PORT}.{launch_id}.log"
    holder.live = True
    assert holder.log_path.is_file(), "per-launch log file missing (SC-04)"


def _stop_server(holder: ServerHolder) -> None:
    if not holder.live:
        return
    r = _run(["bash", _script("stop_comfyui.sh")], env=_script_env(), timeout=120)
    assert r.returncode == 0, f"stop_comfyui.sh failed:\n{r.stdout}\n{r.stderr}"
    holder.live = False
    assert _port_free(), "port still bound after stop (SC-07)"


def _launch_log(holder: ServerHolder) -> str:
    assert holder.log_path is not None and holder.log_path.is_file()
    return holder.log_path.read_text(errors="ignore")


def _named_log(launch_id: str) -> str:
    p = LOGS_DIR / f"comfyui.{PORT}.{launch_id}.log"
    assert p.is_file(), f"launch log for {launch_id} missing"
    return p.read_text(errors="ignore")


def _require_smoke(holder: ServerHolder) -> None:
    """SC-05 abort semantics: matrix rows refuse to run after a smoke failure
    so a mount/activation problem cannot produce misleading 404 results."""
    if not holder.smoke_ok:
        pytest.fail(
            "aborting matrix row: smoke (GET /manager/version) has not passed "
            "for this launch — mount/activation problem or Q-2 bundled-manager "
            "collision (E2E-SC-05)"
        )


def _smoke(holder: ServerHolder) -> None:
    r = requests.get(f"{BASE_URL}/manager/version", timeout=10)
    assert r.status_code == 200, (
        f"smoke FAILED: GET /manager/version -> {r.status_code}; the "
        f"worktree-mounted plugin did not register its routes (E2E-SC-05). "
        f"Log tail:\n{_launch_log(holder)[-2000:]}"
    )
    assert r.text.strip(), "smoke: /manager/version body empty"
    holder.smoke_ok = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mount_worktree():
    """E2E-SC-02/03 — SOLE owner of mount create / reuse-verify / teardown."""
    ref = os.environ.get("E2E_MANAGER_REF", "HEAD")
    r = _run(["git", "-C", str(MANAGER_REPO), "rev-parse", f"{ref}^{{commit}}"], check=True)
    sha = r.stdout.strip()

    # Scoping invariant (SC-03): the mount path is {ROOT}-prefixed and is
    # NEVER under the members' .claude/worktrees tree. Every mount/teardown
    # command below references ONLY this path.
    mount = MOUNT.resolve()
    assert ".claude/worktrees" not in str(mount).replace(os.sep, "/"), (
        "mount path must never live under member worktrees (SC-03 scoping)"
    )
    assert str(mount).startswith(str(ROOT.resolve())), (
        "mount path must be {ROOT}-prefixed (SC-03 scoping)"
    )

    porcelain = _run(["git", "-C", str(MANAGER_REPO), "worktree", "list", "--porcelain"]).stdout
    if f"worktree {mount}" in porcelain:
        # Reuse path (SC-03)
        head = _run(["git", "-C", str(mount), "rev-parse", "HEAD"]).stdout.strip()
        if head != sha:
            _run(["git", "-C", str(mount), "checkout", "--detach", sha], check=True)
    else:
        # Create path (SC-02)
        _run(["git", "-C", str(MANAGER_REPO), "worktree", "add", "--detach",
              str(mount), sha], check=True)

    # From here a worktree exists at `mount`. Any failure between now and the
    # yield (the verify asserts below) must STILL run teardown — otherwise a
    # failed setup leaks an orphaned worktree into the next session (review
    # follow-up). Hence the try/finally wraps verify + yield, not just yield.
    try:
        # Verify (every session)
        head = _run(["git", "-C", str(mount), "rev-parse", "HEAD"]).stdout.strip()
        assert head == sha, f"mount HEAD {head} != expected {sha} (SC-02)"
        print(f"[mount_worktree] Manager mounted at {mount} @ SHA {sha}")  # [D2] traceability
        assert (mount / ".git").is_file(), (
            ".git in the mount must be a FILE (gitdir pointer) — worktree layout (SC-02)"
        )
        # [D2] other half: no pip-installed Manager in the venv; per MM §2.2 no
        # assertion anywhere relies on the mounted Manager's OWN version/remote
        # self-report (.git-file degradation accepted by design — spec R5).
        for dist in ("comfyui-manager", "ComfyUI-Manager"):
            rc = _run([str(VENV_PY), "-m", "pip", "show", dist]).returncode
            assert rc != 0, f"pip-installed Manager '{dist}' found in venv — violates [D2]"

        yield {"path": mount, "sha": sha}
    finally:
        if os.environ.get("E2E_KEEP_MOUNT"):
            print(f"[mount_worktree] E2E_KEEP_MOUNT set — keeping {mount}")
        else:
            # Exception-safe: prune + absence asserts run even when remove fails
            # (review iter-2 — crash residue must still be surfaced honestly).
            try:
                _run(["git", "-C", str(MANAGER_REPO), "worktree", "remove", "--force", str(mount)],
                     check=True)
            finally:
                _run(["git", "-C", str(MANAGER_REPO), "worktree", "prune"])
                porcelain = _run(["git", "-C", str(MANAGER_REPO), "worktree", "list", "--porcelain"]).stdout
                assert f"worktree {mount}" not in porcelain, "mount still listed after remove (SC-07)"
                assert not mount.exists(), "mount dir still present after remove (SC-07)"


@pytest.fixture(scope="class")
def deny_server(mount_worktree):
    """L-D: both flags ABSENT (live 'missing key reads false'), loopback."""
    _pre_guards()                # SC-20
    _stage("deny")               # SC-06
    holder = ServerHolder()
    _start_server(holder, "L-D")  # SC-04
    yield holder
    # Exception-safe teardown chain (review iter-2 must-fix): a failing
    # stop is exactly the crashed-run shape SC-23 exists for — the guard
    # and the config restore MUST run regardless.
    try:
        _stop_server(holder)     # SC-07 (current handle, whatever is live)
    finally:
        try:
            _reservation_guard()  # SC-23 — UNCONDITIONAL
        finally:
            _restore_config()     # SC-07: restore + DELETE backup


@pytest.fixture(scope="class")
def allow_server(mount_worktree):
    """L-A: both flags true, loopback. SC-14 mutates the holder to R-A."""
    _pre_guards()                # SC-20 (re-guards before the allow arm)
    _stage("allow")              # SC-06
    holder = ServerHolder()
    _start_server(holder, "L-A")
    yield holder
    # Exception-safe teardown chain (review iter-2 must-fix): every
    # residual guard runs even when the stop (or an earlier sweep step)
    # raises — SC-23 is contractually UNCONDITIONAL (R3 leak class).
    try:
        _stop_server(holder)     # stops the CURRENT identity (L-A or R-A)
    finally:
        try:
            _remove_pack(PACK_NAME)  # defensive re-sweep (primary assert is SC-21)
            _pip_uninstall()         # defensive (primary assert is SC-22)
            # Amendment A2: sweep the S-A fixture's transitive-dep residual
            # class (python-slugify + text-unidecode ride the git
            # transaction; verified NOT in ComfyUI's own requirements).
            _run([str(VENV_PY), "-m", "pip", "uninstall", "-y", *TRANSITIVE_DEPS])
        finally:
            try:
                _reservation_guard()  # SC-23 — UNCONDITIONAL (failure path cover)
            finally:
                _restore_config()


@pytest.fixture(scope="class")
def public_server(mount_worktree):
    """L-P (opt-in, Q-7): both flags true, 0.0.0.0 listener."""
    _pre_guards()
    _stage("allow")
    holder = ServerHolder()
    _start_server(holder, "L-P", listen="0.0.0.0")
    yield holder
    # Exception-safe teardown chain (review iter-2 must-fix).
    try:
        _stop_server(holder)
    finally:
        try:
            _reservation_guard()
        finally:
            _restore_config()


# ---------------------------------------------------------------------------
# Classes — definition order IS execution order (deny first on the fresh env)
# ---------------------------------------------------------------------------

class TestDenyArms:
    """L-D launch: SC-05 smoke, SC-10, SC-11 (deny rows are offline-safe —
    denial happens before any network access)."""

    def test_00_smoke_manager_version(self, deny_server):
        _smoke(deny_server)  # SC-05

    def test_01_sa_deny(self, deny_server):
        """E2E-SC-10: S-A deny — 403 + exact flag token + no artifact + honest log."""
        _require_smoke(deny_server)
        r = requests.post(f"{BASE_URL}/customnode/install/git_url",
                          json={"url": NODEPACK_URL}, timeout=30)
        assert r.status_code == 403
        assert r.json() == {"error": "allow_git_url_install"}, (
            f"deny body must carry the flag token, got {r.text!r}"
        )
        assert not _pack_exists(PACK_NAME), "clone artifact created on DENY (SC-10)"
        log = _launch_log(deny_server)
        assert DENY_COPY_GIT in log, "flag-naming denial copy missing from L-D log"
        assert OLD_COPY_GENERAL not in log and OLD_COPY_NORMAL_MINUS not in log, (
            "denial attributed to security_level — honest-copy violation (SC-10)"
        )

    def test_02_sb_deny(self, deny_server):
        """E2E-SC-11: S-B deny — 403 + flag token + no reservation + not importable."""
        _require_smoke(deny_server)
        r = requests.post(f"{BASE_URL}/customnode/install/pip",
                          json={"packages": PIP_URL}, timeout=30)
        assert r.status_code == 403
        assert r.json() == {"error": "allow_pip_install"}
        assert _scripts_clean(), "reservation recorded on DENY (SC-11)"
        assert _pip_import_rc() != 0, "pip fixture importable after DENY (SC-11)"
        log = _launch_log(deny_server)
        assert DENY_COPY_PIP in log, "flag-naming denial copy missing from L-D log"


class TestAllowArms:
    """L-A launch + R-A restart. ORDERED methods (donor sequential-class
    precedent): SC-12 -> SC-13 -> SC-14 -> SC-21 -> SC-22 -> SC-42."""

    def test_00_smoke_manager_version(self, allow_server):
        _smoke(allow_server)  # SC-05 (re-smoke on the new launch)

    @needs_network
    def test_01_git_url_allow(self, allow_server):
        """E2E-SC-12: S-A allow — 200 + real clone + clone-target proof."""
        _require_smoke(allow_server)
        r = requests.post(f"{BASE_URL}/customnode/install/git_url",
                          json={"url": NODEPACK_URL}, timeout=120)
        assert r.status_code == 200, f"S-A allow expected 200, got {r.status_code}: {r.text!r}"
        assert _wait_for(lambda: _pack_exists(PACK_NAME)), (
            f"{PACK_NAME} not cloned within {POLL_TIMEOUT}s (SC-12)"
        )
        git_dir = _pack_dir() / ".git"
        assert git_dir.is_dir(), "no .git DIRECTORY — not a real clone (SC-12)"
        # Donor clone-target proof: .git/config [remote "origin"] url matches
        # the requested URL modulo the .git suffix.
        cp = configparser.ConfigParser()
        cp.read(git_dir / "config")
        section = 'remote "origin"'
        assert section in cp, f'[{section}] missing from .git/config: {cp.sections()!r}'
        remote_url = cp[section].get("url", "").rstrip("/")
        expected = NODEPACK_URL.rstrip("/")
        assert remote_url in (expected, expected + ".git"), (
            f"clone targeted the WRONG repo: {remote_url!r} != {expected!r} (SC-12)"
        )

    @needs_network
    def test_02_pip_allow_reserved(self, allow_server):
        """E2E-SC-13 (VERBATIM anti-false-PASS oracle): 200 = RESERVED, NOT
        INSTALLED. Asserting import success here would be the exact false-PASS
        the MM correction exists to prevent."""
        _require_smoke(allow_server)
        r = requests.post(f"{BASE_URL}/customnode/install/pip",
                          json={"packages": PIP_URL}, timeout=30)
        assert r.status_code == 200, f"S-B allow expected 200, got {r.status_code}: {r.text!r}"
        assert SCRIPTS_FILE.is_file(), "no reservation file after S-B allow (SC-13)"
        content = SCRIPTS_FILE.read_text(errors="ignore")
        reserved_lines = [
            ln for ln in content.splitlines()
            if "'#FORCE'" in ln and PIP_PKG in ln
        ]
        assert reserved_lines, (
            f"no reservation line with '#FORCE' + {PIP_PKG!r} in {SCRIPTS_FILE}:\n{content}"
        )
        # MANDATORY: the package is NOT installed at this point.
        assert _pip_import_rc() != 0, (
            "pip fixture importable right after the 200 — reservation semantics "
            "violated, or a previous run leaked state (SC-13 anti-false-PASS)"
        )

    @needs_network
    def test_03_restart_consumes_reservation(self, allow_server):
        """E2E-SC-14: R-A restart THROUGH the holder; the consuming boot
        executes + removes the reservation; MARKER import proves field-level."""
        _require_smoke(allow_server)
        assert SCRIPTS_FILE.is_file(), "precondition: reservation must exist (SC-13 first)"
        # Restart THROUGH the holder (spec §3 binding item 3): stop the live
        # L-A process, relaunch as R-A with the SAME staged config, replace
        # the handle — class teardown then stops R-A.
        _stop_server(allow_server)
        _start_server(allow_server, "R-A")
        _smoke(allow_server)
        # Field-level positive proof (not just exit code):
        marker = _pip_marker_rc()
        assert marker.returncode == 0, (
            f"MARKER import failed after the consuming restart (SC-14):\n"
            f"{marker.stderr}\nR-A log tail:\n{_named_log('R-A')[-3000:]}"
        )
        assert not SCRIPTS_FILE.exists(), (
            "install-scripts.txt NOT removed by the consuming boot (SC-14 self-clean)"
        )
        ra_log = _named_log("R-A")
        assert "## ComfyUI-Manager: EXECUTE =>" in ra_log and PIP_PKG in ra_log, (
            "R-A log lacks the startup-script execution block (SC-14)"
        )
        assert "Startup script completed." in ra_log, (
            "R-A log lacks the startup-script completion line (SC-14)"
        )

    @needs_network
    def test_04_clone_residual_cleanup(self, allow_server):
        """E2E-SC-21: clone-dir hygiene; FS-absence primary + installed-index
        cross-check while the server is still up (defensive, donor pattern)."""
        _remove_pack(PACK_NAME)
        assert not _pack_exists(PACK_NAME), "clone dir still present (SC-21 primary)"
        try:
            r = requests.get(f"{BASE_URL}/customnode/installed", timeout=15)
            if r.status_code == 200:
                installed = r.json()
                assert PACK_NAME not in installed, (
                    f"{PACK_NAME} still in /customnode/installed after removal (SC-21)"
                )
                for key, pkg in installed.items():
                    if isinstance(pkg, dict):
                        assert pkg.get("cnr_id") != PACK_NAME and pkg.get("aux_id") != PACK_NAME, (
                            f"installed entry {key!r} still references {PACK_NAME!r} (SC-21)"
                        )
        except (ValueError, requests.RequestException):
            # Spec SC-21: if the response schema proves awkward, FS-absence
            # alone satisfies this row.
            pass

    @needs_network
    def test_05_pip_residual_uninstall(self, allow_server):
        """E2E-SC-22: S-B residual class 1 (venv package)."""
        r = _pip_uninstall()
        assert r.returncode == 0, f"pip uninstall failed (SC-22):\n{r.stdout}\n{r.stderr}"
        assert _pip_import_rc() != 0, "pip fixture importable after uninstall (SC-22)"

    @needs_network
    def test_06_requirements_watchdog(self, allow_server):
        """E2E-SC-42 (Q-6 watchdog, amendment A2): every management-script
        EXECUTE in the L-A launch log must be attributable to the owned
        fixture's OWN pinned requirements (python-slugify==8.0.4 — the
        nodepack fixture's deliberate invariant-4 ride-along requirement).
        Any other EXECUTE (e.g. a Manager-requirements install — the Q-6
        risk this row guards) FAILS the watchdog.

        The allowlisted line doubles as LIVE proof of the invariant-4
        ride-along class: a dependency pip install executed inside the
        git-URL transaction without consulting allow_pip_install."""
        la_log = _named_log("L-A")
        banner = "## ComfyUI-Manager: EXECUTE =>"
        idx = 0
        execs = []
        while True:
            idx = la_log.find(banner, idx)
            if idx < 0:
                break
            execs.append(la_log[idx: idx + 600])
            idx += len(banner)
        # Non-vacuity (review iter-2 / A2 positive half): the ride-along
        # MUST have happened — exactly ONE management-script execution,
        # the fixture's single pinned requirement.
        assert len(execs) == 1, (
            f"expected exactly 1 management-script execution during L-A "
            f"(the fixture's pinned requirement ride-along), found "
            f"{len(execs)} (SC-42 / A2)"
        )
        window = execs[0]
        assert NODEPACK_PINNED_REQ in window, (
            "unexpected management-script execution during L-A — not "
            "attributable to the fixture's pinned requirement "
            f"({NODEPACK_PINNED_REQ}) (SC-42 watchdog):\n{window}"
        )
        # Line-level shape: it must be a pip-install command, not an
        # arbitrary script that merely mentions the requirement string.
        assert "'pip'" in window and "'install'" in window, (
            f"EXECUTE block is not a pip-install command (SC-42):\n{window}"
        )


@pytest.mark.skipif(
    not os.environ.get("E2E_PUBLIC_LISTEN"),
    reason="public-listener row is opt-in (E2E_PUBLIC_LISTEN=1) — Q-7 default-off",
)
class TestPublicListener:
    """E2E-SC-40 (opt-in): flags=true + 0.0.0.0 -> still 403 on both surfaces.
    Live proof of invariant 2 (predicate = flag AND loopback at REQUEST time)."""

    def test_00_smoke_manager_version(self, public_server):
        _smoke(public_server)

    def test_01_sa_public_deny(self, public_server):
        _require_smoke(public_server)
        r = requests.post(f"{BASE_URL}/customnode/install/git_url",
                          json={"url": NODEPACK_URL}, timeout=30)
        assert r.status_code == 403
        assert r.json() == {"error": "allow_git_url_install"}
        assert not _pack_exists(PACK_NAME)

    def test_02_sb_public_deny(self, public_server):
        _require_smoke(public_server)
        r = requests.post(f"{BASE_URL}/customnode/install/pip",
                          json={"packages": PIP_URL}, timeout=30)
        assert r.status_code == 403
        assert r.json() == {"error": "allow_pip_install"}
        assert _scripts_clean()


class TestZeroResidual:
    """E2E-SC-24: the complete [D3] residual inventory in one assertion block.
    Runs AFTER the server classes (their class-scoped fixtures have finalized:
    server stopped, config restored, backup deleted). The unmount half of the
    inventory is asserted by the mount_worktree finalizer itself — it cannot
    be asserted from inside the session while the mount is still live."""

    def test_99_zero_residual_sweep(self, mount_worktree):
        # custom_nodes clean (incl. .trash_ fallback leftovers)
        assert not _pack_exists(PACK_NAME), "nodepack residue in custom_nodes (SC-24)"
        leftovers = [p.name for p in CN_DIR.iterdir()
                     if p.name.startswith((".trash_", PACK_NAME))]
        assert not leftovers, f"residual entries in custom_nodes: {leftovers} (SC-24)"
        # venv clean
        assert _pip_import_rc() != 0, "pip fixture still importable (SC-24)"
        # Amendment A2: transitive-dep residual class swept
        for dep in TRANSITIVE_DEPS:
            rc = _run([str(VENV_PY), "-m", "pip", "show", dep]).returncode
            assert rc != 0, f"transitive dep {dep!r} survived the sweep (SC-24 / A2)"
        # reservation clean
        assert _scripts_clean(), "pip-test1 reservation residue (SC-24)"
        # config restored + backup DELETED
        assert CFG.is_file(), "config.ini missing after restore (SC-24)"
        cfg_text = CFG.read_text(errors="ignore")
        assert "allow_git_url_install" not in cfg_text, "staged flag leaked into restored config (SC-24)"
        assert "allow_pip_install" not in cfg_text, "staged flag leaked into restored config (SC-24)"
        assert not CFG_BACKUP.exists(), "stale config backup survived (SC-24 / peer R2)"
        # port free
        assert _port_free(), f"port {PORT} still bound (SC-24)"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
