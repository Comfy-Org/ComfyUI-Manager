"""[goal299 step3] E2E: URL-form pip install through the S-B endpoint.

CONTRACT UNDER TEST (SHIPPED — goal265; this module adds tests only):
the ``allow_pip_install`` gate on POST /v2/customnode/install/pip is
**argument-content-agnostic** (goal299-mm-addendum.md §1): a URL-form
argument (``git+https://github.com/...``) exercises the SAME
dedicated-flag gate as a bare package name — no code path inspects
the argument before the gate decision (legacy/manager_server.py:1574).

FIXTURE NOTE (goal329 — WHY the owned fixture): the install arm
originally exercised ``git+https://github.com/facebookresearch/sam2``;
that external, unpinned, heavy dependency (torch-ecosystem build at
restart time) made the test hostage to upstream maintainer drift
(maintainer-fragility decision, goal329). It is replaced by the OWNED,
purpose-built fixture ``git+https://github.com/ltdrdata/pip-test1-do-not-install``
(PUBLIC; package ``pip-test1-do-not-install``, module
``pip_test1_do_not_install``, ``MARKER = "pip-test1-do-not-install:ok"``,
zero deps, pure Python, no import side effects). The gate contract is
argument-content-agnostic, so the URL swap changes NOTHING about what
is being proven — only the install payload shrinks to a harmless,
owned package.

Two arms (goal299-spec.md §1.1, LOCKED):

  DENY arm    flag=false at security_level=weak -> 403, NO reservation
              entry appended, denial log names allow_pip_install
              (weak proves the FLAG, not the security_level, decides).
  INSTALL arm flag=true at security_level=strong, loopback -> 200 =
              gate-pass + RESERVATION (deferred-execution semantics,
              addendum §1: '#FORCE' reserves into install-scripts.txt;
              the real `uv pip install` runs at the NEXT server start)
              -> restart -> fixture module REALLY importable (MARKER
              verified) in the isolated E2E venv -> self-clean ->
              absent again.

Placement: NEW SIBLING of tests/e2e/test_e2e_secgate_legacy_flags.py
(spec §1.2) — that module carries an engineered zero-install guarantee
(its header :96-100), so the real-install arm must NOT live there.
Helper reuse contract (spec §1.2, LOCKED): import-reuse is limited to
``_stage_flags_config`` / ``_stop_legacy`` / ``_make_flags_server_fixture``
/ ``_post_pip`` / ``_log_offset``; everything else needed here is a
sibling-local definition (provenance-commented copies where applicable).

Self-cleaning + idempotent (spec §1.3 install-arm steps 1/6): pre-guard
uninstall, teardown uninstall (runs even on failure), reservation-file
hygiene on both ends. The venv is uv-managed and has NO pip module
(addendum R4) — all (un)installs go through ``<venv>/bin/uv``.

Requires a pre-built E2E environment (setup_e2e_env.sh); skip-marked
otherwise. The install arm additionally requires github.com reachability
(addendum R5) and is skip-marked offline; the deny arm always runs.
"""

from __future__ import annotations

import ast
import os
import socket
import subprocess

import pytest

# Import-reuse: the LOCKED helper subset only (goal299-spec.md §1.2).
from test_e2e_secgate_legacy_flags import (
    _log_offset,
    _make_flags_server_fixture,
    _post_pip,
    _stop_legacy,
)

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
SERVER_LOG = os.path.join(E2E_ROOT, "logs", "comfyui.log") if E2E_ROOT else ""

# Same port as the flags module (its module constant is not in the locked
# import set; the value is part of the shared legacy-fixture contract).
PORT = 8199

# Owned fixture (goal329 — see FIXTURE NOTE in the module docstring).
# Dist name uses hyphens, import name uses underscores; MARKER gives a
# stronger installed-for-real check than a bare import.
FIXTURE_URL = "git+https://github.com/ltdrdata/pip-test1-do-not-install"
FIXTURE_DIST = "pip-test1-do-not-install"
FIXTURE_MODULE = "pip_test1_do_not_install"
FIXTURE_MARKER = "pip-test1-do-not-install:ok"
VENV_PY = os.path.join(E2E_ROOT, "venv", "bin", "python") if E2E_ROOT else ""
VENV_UV = os.path.join(E2E_ROOT, "venv", "bin", "uv") if E2E_ROOT else ""
# Reservation file (path shape per tests/e2e/test_e2e_legacy_real_ops.py:538;
# producer: reserve_script, legacy/manager_core.py:1836-1843; consumer:
# comfyui_manager/prestartup_script.py:485 at next server start).
SCRIPTS_PATH = (
    os.path.join(
        COMFYUI_PATH, "user", "__manager", "startup-scripts", "install-scripts.txt"
    )
    if E2E_ROOT
    else ""
)

# Post-reservation restart budget (goal329): the owned fixture is pure
# Python with zero deps — its `uv pip install` completes in seconds, so
# the restart wall time is dominated by the plain server boot
# (+prestartup resolver), observed well under 60s in this harness. 180s
# equals the proven readiness budget the flags module's _start_legacy
# uses for a plain legacy start (>=3x headroom over observed boot); the
# python-side timeout is shell+60 per the helper invariant.
RESTART_BUDGET_S = 180

pytestmark = pytest.mark.skipif(
    not E2E_ROOT
    or not os.path.isfile(os.path.join(E2E_ROOT, ".e2e_setup_complete")),
    reason="E2E_ROOT not set or E2E environment not ready",
)


# ---------------------------------------------------------------------------
# Sibling-local helpers (spec §1.2 — outside the locked import set)
# ---------------------------------------------------------------------------

def _start_legacy_install(extra_env: dict, shell_timeout: int = RESTART_BUDGET_S) -> int:
    """Parameterized variant of test_e2e_secgate_legacy_flags._start_legacy
    (:147-158) — provenance copy per goal299-spec.md §1.2. The flags
    module's helper hardcodes its env dict and python-side timeout, which
    can neither inject per-restart env nor take a per-call readiness
    budget. TIMEOUT is forwarded to start_comfyui_legacy.sh as the shell
    readiness budget; the python-side subprocess timeout MUST exceed it
    (+60s) so the start script, not python, owns the timeout."""
    env = {
        **os.environ,
        "E2E_ROOT": E2E_ROOT,
        "PORT": str(PORT),
        "TIMEOUT": str(shell_timeout),
        **extra_env,
    }
    r = subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "start_comfyui_legacy.sh")],
        capture_output=True, text=True, timeout=shell_timeout + 60, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"Failed to start ComfyUI (legacy, install restart):\n{r.stderr}"
        )
    for part in r.stdout.strip().split():
        if part.startswith("COMFYUI_PID="):
            return int(part.split("=")[1])
    raise RuntimeError(f"Could not parse PID:\n{r.stdout}")


def _log_slice(offset: int) -> str:
    """Provenance copy of test_e2e_secgate_legacy_flags._log_slice
    (:241-246) — not in the locked import set (spec §1.2 fallback clause:
    fixture semantics are the lock, import path is not)."""
    if not os.path.isfile(SERVER_LOG):
        return ""
    with open(SERVER_LOG, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        return f.read()


def _scripts_state() -> str:
    """Current install-scripts.txt content, or the sentinel 'ABSENT' —
    the file may legitimately not exist (spec §1.3 deny step 2: it is
    created lazily by reserve_script on first reservation)."""
    if not os.path.isfile(SCRIPTS_PATH):
        return "ABSENT"
    with open(SCRIPTS_PATH, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _venv_fixture_probe() -> subprocess.CompletedProcess:
    """Import the fixture module in the isolated E2E venv and print its
    MARKER (subprocess — the observable for really-installed /
    really-absent). rc != 0 means absent; rc == 0 AND the MARKER value in
    stdout means installed for real (stronger than a bare import)."""
    return subprocess.run(
        [VENV_PY, "-c", f"import {FIXTURE_MODULE} as m; print(m.MARKER)"],
        capture_output=True, text=True, timeout=60,
    )


def _uninstall_fixture() -> None:
    """Uninstall the fixture distribution from the E2E venv via uv.

    The venv has NO pip module (`python -m pip` fails — addendum R4);
    `<venv>/bin/uv pip uninstall --python <venv-python>` is the working
    path. A no-op when the dist is absent (uv warns, exits 0)."""
    subprocess.run(
        [VENV_UV, "pip", "uninstall", FIXTURE_DIST, "--python", VENV_PY],
        capture_output=True, text=True, timeout=180,
    )


def _strip_fixture_reservation() -> None:
    """Remove any fixture residual line from install-scripts.txt
    (addendum R8: a leftover reservation would silently mutate the venv
    on the NEXT restart, possibly a different test's). Matches both the
    hyphenated dist/URL form and the underscored module form."""
    if not os.path.isfile(SCRIPTS_PATH):
        return
    with open(SCRIPTS_PATH, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    kept = [
        ln for ln in lines
        if FIXTURE_DIST not in ln.lower() and FIXTURE_MODULE not in ln.lower()
    ]
    if kept != lines:
        with open(SCRIPTS_PATH, "w", encoding="utf-8") as f:
            f.writelines(kept)


def _github_reachable() -> bool:
    """Runtime network probe for the install arm (addendum R5)."""
    try:
        socket.create_connection(("github.com", 443), timeout=10).close()
        return True
    except OSError:
        return False


# ===========================================================================
# DENY arm — flag=false, security_level=weak (weak proves flag-not-level
# decides; goal299-spec.md §1.3 TestPipUrlFormDeny)
# ===========================================================================

comfyui_pip_url_deny = _make_flags_server_fixture(False, False, "weak")


class TestPipUrlFormDeny:
    """URL-form POST is denied by the allow_pip_install flag gate exactly
    like a bare package name (argument-content-agnostic, addendum §1):
    403, no install-side-effect (no reservation entry), denial log names
    the flag. Shared-POST shape (spec §1.3, LOCKED): exactly ONE POST via
    a class-scoped record fixture; the three tests assert exclusively
    against the record — independent of execution order, no re-reads of
    live state."""

    @pytest.fixture(scope="class")
    def deny_post_record(self, comfyui_pip_url_deny):
        offset = _log_offset()
        snapshot_before = _scripts_state()
        resp = _post_pip(FIXTURE_URL)
        return {
            "log_offset_before": offset,
            "scripts_snapshot_before": snapshot_before,
            "status_code": resp.status_code,
            "log_slice_after": _log_slice(offset),
            "scripts_state_after": _scripts_state(),
        }

    def test_url_form_denied_403(self, deny_post_record):
        """403 from the dedicated-flag gate despite security_level=weak
        (deny-direction decoupling, mm §2 row 'deny arm, after POST')."""
        assert deny_post_record["status_code"] == 403, (
            f"URL-form pip POST: expected 403 (allow_pip_install=false "
            f"overrides sl=weak), got {deny_post_record['status_code']} — "
            f"the gate must be argument-content-agnostic."
        )

    def test_url_form_deny_no_reservation(self, deny_post_record):
        """No reservation entry appended on deny (mm §2: install-scripts.txt
        'no entry written'; HTTP 200 would have meant reservation, so the
        durable on-disk state is the decisive side-effect observable)."""
        before = deny_post_record["scripts_snapshot_before"]
        after = deny_post_record["scripts_state_after"]
        assert after == before, (
            f"deny arm: install-scripts.txt changed across the denied POST "
            f"— a reservation leaked past the gate.\nbefore:\n{before}\n"
            f"after:\n{after}"
        )
        if after != "ABSENT":
            assert FIXTURE_DIST not in after.lower(), (
                f"deny arm: a fixture line is present in install-scripts.txt "
                f"after a denied POST:\n{after}"
            )

    def test_url_form_deny_log_names_flag(self, deny_post_record):
        """Denial log names allow_pip_install (SECURITY_MESSAGE_FLAG_PIP,
        legacy/manager_server.py:47) and carries no security-level framing
        for this denial (goal265 spec §1.1 invariant 6 — same assertion
        shape as the flags module's SC-23)."""
        log = deny_post_record["log_slice_after"]
        assert "allow_pip_install" in log, (
            "deny arm: denial log does not name allow_pip_install "
            f"(SECURITY_MESSAGE_FLAG_PIP). Slice:\n{log[-1500:]}"
        )
        assert "security level to 'normal-'" not in log, (
            "deny arm: denial log still carries the misleading "
            "security-level copy (SECURITY_MESSAGE_NORMAL_MINUS)."
        )


# ===========================================================================
# INSTALL arm — flag=true, security_level=strong (strong proves allow-side
# decoupling; goal299-spec.md §1.3 TestPipUrlFormInstall)
# ===========================================================================

comfyui_pip_url_install = _make_flags_server_fixture(False, True, "strong")


@pytest.mark.network
class TestPipUrlFormInstall:
    """Full deferred-install round trip (mm §2 observable-outcome table):
    POST 200 = gate-pass + reservation (NOT installation) -> restart
    executes the reserved `uv pip install -U git+...` at prestartup
    -> fixture module imports with the expected MARKER in the isolated
    venv -> self-clean -> absent.

    Asserting importability right after the 200 would be a guaranteed
    false-FAIL (mm §2 note) — the restart between POST and the import
    assertion is the production execution path (addendum §4.1)."""

    @pytest.fixture(scope="class", autouse=True)
    def _network_guard(self):
        if not _github_reachable():
            pytest.skip("offline: github.com unreachable — install arm "
                        "requires network (deny arm unaffected)")

    @pytest.fixture(autouse=True)
    def _self_clean(self):
        """Teardown runs even on failure (spec §1.3 step 6): uninstall the
        dist, strip any residual reservation line (addendum R8), and prove
        the venv is back to baseline (import fails again)."""
        yield
        _uninstall_fixture()
        _strip_fixture_reservation()
        assert _venv_fixture_probe().returncode != 0, (
            f"self-clean: {FIXTURE_MODULE} is still importable in the E2E "
            f"venv after `uv pip uninstall {FIXTURE_DIST}` — venv NOT "
            f"restored to baseline."
        )

    def test_url_form_install_end_to_end(self, comfyui_pip_url_install):
        # Step 1 — pre-guard (idempotency, spec §1.3 step 1): a previous
        # aborted run must not turn this into a false-PASS.
        _uninstall_fixture()
        _strip_fixture_reservation()
        assert _venv_fixture_probe().returncode != 0, (
            f"pre-guard: {FIXTURE_MODULE} already importable before the "
            f"test — uninstall guard failed; venv not at baseline."
        )

        # Step 2 — POST the URL-form argument; 200 = gate-pass +
        # reservation under the deferred-execution semantics (mm §1).
        resp = _post_pip(FIXTURE_URL)
        assert resp.status_code == 200, (
            f"install arm: expected 200 (allow_pip_install=true overrides "
            f"sl=strong), got {resp.status_code} — allow-side decoupling "
            f"broken for the URL-form argument."
        )

        # Step 3 — reservation entry: a Python-list-repr line containing
        # the fixture URL substring (producer reserve_script,
        # legacy/manager_core.py:1836-1843; precedent assertion shape
        # test_e2e_legacy_real_ops.py:516-538). NOT a shell-string match.
        state = _scripts_state()
        assert state != "ABSENT", (
            "install arm: install-scripts.txt missing after 200 — "
            "no reservation was written."
        )
        fixture_lines = [ln for ln in state.splitlines() if FIXTURE_URL in ln]
        assert fixture_lines, (
            f"install arm: no reservation line contains {FIXTURE_URL!r}.\n"
            f"file content:\n{state}"
        )
        reserved = ast.literal_eval(fixture_lines[0])
        assert isinstance(reserved, list) and "#FORCE" in reserved, (
            f"install arm: reservation line is not the expected "
            f"['..', '#FORCE', <pip cmd>...] list-repr shape: {reserved!r}"
        )

        # Step 4 — restart: the production execution path for the
        # reservation (prestartup_script.py:485 consumes the file at
        # server start). Budget rationale at RESTART_BUDGET_S — the
        # owned zero-dep fixture installs in seconds; the budget covers
        # the plain server boot, no build env vars needed (goal329
        # retired the CUDA-build determinism knob with the heavy
        # upstream package).
        _stop_legacy()
        _start_legacy_install({}, shell_timeout=RESTART_BUDGET_S)

        # Step 5 — post-restart: reservation CONSUMED (prestartup removes
        # the processed file) and the fixture REALLY importable in the
        # venv, proven by its MARKER value (stronger than bare import:
        # the marker ties the import to the owned fixture's content).
        post_state = _scripts_state()
        assert post_state == "ABSENT" or FIXTURE_URL not in post_state, (
            f"install arm: reservation NOT consumed by the restart — "
            f"install-scripts.txt still references the fixture:\n{post_state}"
        )
        probe = _venv_fixture_probe()
        assert probe.returncode == 0, (
            f"install arm: `import {FIXTURE_MODULE}` still fails in the "
            f"E2E venv after the reservation-executing restart — install "
            f"did not happen or did not target the venv.\n"
            f"stderr:\n{probe.stderr[-500:]}"
        )
        assert FIXTURE_MARKER in probe.stdout, (
            f"install arm: fixture imported but MARKER mismatch — "
            f"expected {FIXTURE_MARKER!r} in stdout, got: {probe.stdout!r}"
        )
        # Version breadcrumb for triage (owned repo, so drift risk is
        # retired — the breadcrumb now just documents what was installed).
        show = subprocess.run(
            [VENV_UV, "pip", "show", FIXTURE_DIST, "--python", VENV_PY],
            capture_output=True, text=True, timeout=60,
        )
        print(f"\n[goal329 install-evidence] uv pip show {FIXTURE_DIST}:\n"
              f"{show.stdout}")
