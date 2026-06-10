"""[goal265 step4 — RED] E2E endpoint binding for the dedicated install flags
``allow_git_url_install`` / ``allow_pip_install`` on the LEGACY server.

TARGET CONTRACT (NOT YET IMPLEMENTED — goal265-spec.md §1, LOCKED):

  S-A  POST /v2/customnode/install/git_url  gated by allow_git_url_install
  S-B  POST /v2/customnode/install/pip      gated by allow_pip_install
  S-C  batch unknown-URL install: retained middle+ entry gate AND the
       allow_git_url_install full predicate replaces the high+ risky check;
       unknown-pip 'block' branch stays UNCONDITIONAL (Q1).
  The security_level term is fully REMOVED from S-A/S-B (spec §1.1 inv. 1);
  denial logs name the responsible flag, not the security level (inv. 6).

These tests are EXPECTED TO FAIL against current code (today S-A/S-B are
``is_allowed_security_level('high+')``-gated) — RED confirmation is Step 5.
Do NOT weaken them to pass against today's code.

This module delivers the LGU2/LPP2 legacy-fixture follow-up explicitly
deferred by tests/e2e/test_e2e_secgate_default.py (its header, lines 31-34).

SC rows covered (goal265-scenarios.md), grouped by server config combination
(one legacy-server launch per combination, config.ini staged per flags):

  CFG-A (git=T, pip=T, sl=strong,  nm=public):  SC-01, SC-11, SC-08
  CFG-B (git=T, pip=F, sl=normal,  nm=public):  SC-02, SC-04, SC-10, SC-17,
                                                SC-18 (transitive-pip arm)
  CFG-C (git=F, pip=T, sl=normal,  nm=public):  SC-16
  CFG-D (git=F, pip=F, sl=weak,    nm=public):  SC-05, SC-09, SC-13,
                                                SC-23 (denial-log copy arm)
  CFG-E (git=T, pip=T, sl=weak,    nm=public):  SC-24 (Q1 unknown-pip block)
  CFG-F (git=T, pip=T, sl=normal,  nm=public):  SC-25A/B (guards, flags-on)
  CFG-G (git=F, pip=F, sl=normal,  nm=public):  SC-25A/B (guards, flags-off)
  CFG-H (git=T, pip=F, sl=normal,  nm=personal_cloud): SC-30 (note below)

SC-30 limitation (deliberate, documented): the E2E harness listens on
127.0.0.1, so the personal_cloud arm of the middle+ entry gate is satisfied
via is_local_mode as well; the public-listener arm of personal_cloud is
proven at predicate level (tests/common/test_install_flag_predicate.py
SC-03/SC-12) — this row re-proves the endpoint binding with
network_mode=personal_cloud staged.

SC-18 strategy: endpoint-level arm — git-URL install transaction completes
(200) with allow_pip_install=false and the captured log slice contains NO
allow_pip_install denial, proving the pip flag is never consulted inside a
git transaction (MM §1.4). The spec's integration-level alternative
(in-process gitclone_install with execute_install_script mocked) remains
open to Step-7 if this arm proves under-discriminating.

Side-effect control: batch rows pre-seed the target node directory so the
queue worker's gitclone_install short-circuits on "Already exists" — the
GATE decision (the contract under test) happens synchronously in
_install_custom_node BEFORE the worker runs, so the batch response's
``failed`` list is a complete gate observable without real clones.

Requires a pre-built E2E environment (setup_e2e_env.sh); skip-marked
otherwise (harness precedent: tests/e2e/test_e2e_secgate_default.py).
"""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess

import pytest
import requests

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")

PORT = 8199
BASE_URL = f"http://127.0.0.1:{PORT}"

CONFIG_PATH = os.path.join(COMFYUI_PATH, "user", "__manager", "config.ini")
CONFIG_BACKUP = CONFIG_PATH + ".before-flags"
SERVER_LOG = os.path.join(E2E_ROOT, "logs", "comfyui.log") if E2E_ROOT else ""

# Purpose-built test-fixture repo (same constant as
# tests/e2e/test_e2e_legacy_real_ops.py TRUSTED_GIT_URL) — the DESIGNATED
# do-not-install sample for every S-A surface test that performs a REAL
# clone (direct /v2/customnode/install/git_url).
UNKNOWN_GIT_URL = "https://github.com/ltdrdata/nodepack-test1-do-not-install"
UNKNOWN_GIT_DIRNAME = "nodepack-test1-do-not-install"

# Batch S-C "unknown-URL" rows need a files URL genuinely NOT in the
# custom-node DB (scenario preconditions SC-04/08/09/30: "file URL NOT in
# node DB" -> get_risky_level returns 'high+' -> the dedicated-flag gate
# engages). DISCOVERY (task #297 real-server run): the do-not-install
# sample above IS registered in the Comfy-Org main-channel
# custom-node-list (served from the manager cache), so get_risky_level
# returns 'middle+' for it and the flag gate is bypassed — using it for
# batch rows silently tests the wrong path (observed as an SC-09
# false-FAIL: flag=false yet the item queued via middle+ at sl=weak).
# The batch rows therefore use a SYNTHETIC nonexistent URL. ZERO-INSTALL
# guarantee holds by construction: deny rows (SC-08/09) never reach the
# worker, and allow rows (SC-04/30) pre-seed the matching placeholder dir
# so the worker's gitclone_install short-circuits on "Already exists" —
# the URL is never cloned (and could not be: the repo does not exist).
BATCH_UNKNOWN_GIT_URL = "https://github.com/ltdrdata/goal265-nonexistent-unknown-node"
BATCH_UNKNOWN_DIRNAME = "goal265-nonexistent-unknown-node"

# Long-standing custom-node-list.json entry — used by SC-24/SC-25B rows that
# need a files URL the DB KNOWS (get_risky_level must not short-circuit at
# high+ on the URL check).
KNOWN_GIT_URL = "https://github.com/ltdrdata/ComfyUI-Impact-Pack"
KNOWN_GIT_DIRNAME = "ComfyUI-Impact-Pack"

UNKNOWN_PIP_PKG = "cm-goal265-nonexistent-pip-pkg-xyz"

pytestmark = pytest.mark.skipif(
    not E2E_ROOT
    or not os.path.isfile(os.path.join(E2E_ROOT, ".e2e_setup_complete")),
    reason="E2E_ROOT not set or E2E environment not ready",
)


# ---------------------------------------------------------------------------
# Config staging + server lifecycle helpers
# ---------------------------------------------------------------------------

def _stage_flags_config(git: bool, pip: bool, security_level: str,
                        network_mode: str) -> None:
    """Patch config.ini with the row preconditions (backup-once pattern,
    mirrors start_comfyui_strict.sh)."""
    if not os.path.isfile(CONFIG_BACKUP):
        shutil.copy(CONFIG_PATH, CONFIG_BACKUP)

    cfg = configparser.ConfigParser(strict=False)
    cfg.read(CONFIG_PATH)
    if "default" not in cfg:
        cfg["default"] = {}
    cfg["default"]["allow_git_url_install"] = "true" if git else "false"
    cfg["default"]["allow_pip_install"] = "true" if pip else "false"
    cfg["default"]["security_level"] = security_level
    cfg["default"]["network_mode"] = network_mode
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)


def _restore_config() -> None:
    if os.path.isfile(CONFIG_BACKUP):
        shutil.move(CONFIG_BACKUP, CONFIG_PATH)


def _start_legacy() -> int:
    env = {**os.environ, "E2E_ROOT": E2E_ROOT, "PORT": str(PORT)}
    r = subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "start_comfyui_legacy.sh")],
        capture_output=True, text=True, timeout=180, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Failed to start ComfyUI (legacy):\n{r.stderr}")
    for part in r.stdout.strip().split():
        if part.startswith("COMFYUI_PID="):
            return int(part.split("=")[1])
    raise RuntimeError(f"Could not parse PID:\n{r.stdout}")


def _stop_legacy() -> None:
    env = {**os.environ, "E2E_ROOT": E2E_ROOT, "PORT": str(PORT)}
    subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "stop_comfyui.sh")],
        capture_output=True, text=True, timeout=30, env=env,
    )


def _make_flags_server_fixture(git: bool, pip: bool, security_level: str,
                               network_mode: str = "public"):
    """Class-scoped fixture factory: stage config -> start legacy server ->
    yield -> stop server -> restore config."""

    @pytest.fixture(scope="class")
    def _server():
        _stage_flags_config(git, pip, security_level, network_mode)
        try:
            pid = _start_legacy()
            try:
                yield pid
            finally:
                _stop_legacy()
        finally:
            _restore_config()

    return _server


comfyui_flags_a = _make_flags_server_fixture(True, True, "strong")
comfyui_flags_b = _make_flags_server_fixture(True, False, "normal")
comfyui_flags_c = _make_flags_server_fixture(False, True, "normal")
comfyui_flags_d = _make_flags_server_fixture(False, False, "weak")
comfyui_flags_e = _make_flags_server_fixture(True, True, "weak")
comfyui_flags_f = _make_flags_server_fixture(True, True, "normal")
comfyui_flags_g = _make_flags_server_fixture(False, False, "normal")
comfyui_flags_h = _make_flags_server_fixture(
    True, False, "normal", network_mode="personal_cloud")


# ---------------------------------------------------------------------------
# Request / observation helpers
# ---------------------------------------------------------------------------

def _post_git_url(url: str) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/v2/customnode/install/git_url", data=url, timeout=120,
    )


def _post_pip(packages: str) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/v2/customnode/install/pip", data=packages, timeout=60,
    )


def _batch_install_item(ui_id: str, files: list[str],
                        pip: list[str] | None = None) -> dict:
    """Unknown-version batch install item shape consumed by
    legacy _install_custom_node (version='unknown' -> files URL path)."""
    return {
        "id": ui_id,
        "ui_id": ui_id,
        "version": "unknown",
        "files": files,
        "pip": pip or [],
        "channel": "default",
        "mode": "cache",
    }


def _post_batch(payload: dict) -> requests.Response:
    return requests.post(
        f"{BASE_URL}/v2/manager/queue/batch", json=payload, timeout=120,
    )


def _log_offset() -> int:
    return os.path.getsize(SERVER_LOG) if os.path.isfile(SERVER_LOG) else 0


def _log_slice(offset: int) -> str:
    if not os.path.isfile(SERVER_LOG):
        return ""
    with open(SERVER_LOG, "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        return f.read()


def _custom_nodes_dir() -> str:
    return os.path.join(COMFYUI_PATH, "custom_nodes")


def _preseed_node_dir(dirname: str) -> str:
    """Create a placeholder node dir so the queue worker's gitclone_install
    short-circuits on 'Already exists' (no real clone; the gate decision
    under test already happened synchronously)."""
    target = os.path.join(_custom_nodes_dir(), dirname)
    os.makedirs(target, exist_ok=True)
    marker = os.path.join(target, ".goal265-preseed")
    with open(marker, "w", encoding="utf-8") as f:
        f.write("goal265 step4 gate-test placeholder\n")
    return target


def _remove_node_dir(dirname: str) -> None:
    for candidate in (
        os.path.join(_custom_nodes_dir(), dirname),
        os.path.join(_custom_nodes_dir(), ".disabled", dirname),
        os.path.join(_custom_nodes_dir(), dirname + ".disabled"),
    ):
        if os.path.isdir(candidate):
            shutil.rmtree(candidate, ignore_errors=True)


# ===========================================================================
# CFG-A: git=T, pip=T, sl=strong, nm=public
# ===========================================================================

class TestFlagsOnStrongLevel:
    """Allow-direction decoupling: flags=true must allow S-A/S-B even at
    security_level=strong (today: 403). Batch entry gate stays
    security_level-coupled (middle+ fails at strong)."""

    def test_sc01_git_url_allowed_at_strong_when_flag_true(
            self, comfyui_flags_a):
        """SC-01: git=true, sl=strong, loopback -> POST git_url returns 200
        (today 403 — proves security_level irrelevance, allow direction).
        Pre-removes the fixture node so a real (tiny) clone proceeds; a
        200 via res.action=='skip' is equally a gate-pass observable."""
        _remove_node_dir(UNKNOWN_GIT_DIRNAME)
        try:
            resp = _post_git_url(UNKNOWN_GIT_URL)
            assert resp.status_code == 200, (
                f"SC-01: expected 200 (flag=true overrides sl=strong), got "
                f"{resp.status_code} — security_level still gates S-A. "
                f"Body: {resp.text[:200]}"
            )
        finally:
            _remove_node_dir(UNKNOWN_GIT_DIRNAME)

    def test_sc11_pip_allowed_at_strong_when_flag_true(self, comfyui_flags_a):
        """SC-11: pip=true, sl=strong, loopback -> POST pip returns 200
        (today 403). text-unidecode: pure-Python, tiny, idempotent — same
        trusted constant as test_e2e_legacy_real_ops.py."""
        resp = _post_pip("text-unidecode")
        assert resp.status_code == 200, (
            f"SC-11: expected 200 (flag=true overrides sl=strong), got "
            f"{resp.status_code} — security_level still gates S-B."
        )

    def test_sc08_batch_unknown_url_denied_at_strong(self, comfyui_flags_a):
        """SC-08: git=true, sl=strong -> batch unknown-URL install DENIED —
        the retained middle+ entry gate fails first (composite gate:
        middle+ AND flag; spec §1.2 S-C row, ':1427' gate UNCHANGED)."""
        item = _batch_install_item("sc08-unknown", [BATCH_UNKNOWN_GIT_URL])
        resp = _post_batch({"install": [item]})
        assert resp.status_code == 200, resp.text[:200]
        failed = resp.json().get("failed", [])
        assert "sc08-unknown" in failed, (
            "SC-08: batch unknown-URL install must stay denied at "
            "sl=strong (middle+ entry gate) even with "
            f"allow_git_url_install=true — failed={failed!r}"
        )


# ===========================================================================
# CFG-B: git=T, pip=F, sl=normal, nm=public
# ===========================================================================

class TestGitFlagOnDefaultLevel:
    """Default security_level: git flag alone opens S-A; pip stays closed."""

    def test_sc02_git_url_allowed_at_default_level(self, comfyui_flags_b):
        """SC-02: git=true, sl=normal (default), loopback -> 200
        (today 403). Self-cleaning (pre+post remove): a leftover clone
        would turn the NEXT install of the same repo into an
        'Already exists' 400 (gitclone_install unknown-repo path has no
        skip arm — observed as an SC-17 false-FAIL in the first #297 run)."""
        _remove_node_dir(UNKNOWN_GIT_DIRNAME)
        try:
            resp = _post_git_url(UNKNOWN_GIT_URL)
            assert resp.status_code == 200, (
                f"SC-02: expected 200 at sl=normal with flag=true, got "
                f"{resp.status_code}. Body: {resp.text[:200]}"
            )
        finally:
            _remove_node_dir(UNKNOWN_GIT_DIRNAME)

    def test_sc10_invalid_url_reaches_validation_400(self, comfyui_flags_b):
        """SC-10: git=true, sl=normal -> POST an INVALID url -> 400 from
        installer validation, NOT 403 from the gate. Distinguishes gate-403
        from install-400 (today the gate 403s before URL validation)."""
        resp = _post_git_url("not-a-url")
        assert resp.status_code == 400, (
            f"SC-10: expected 400 (installer validation), got "
            f"{resp.status_code} — a 403 means the flag gate did not open."
        )

    def test_sc17_git_open_pip_closed_independent(self, comfyui_flags_b):
        """SC-17: git=true, pip=false, sl=normal -> git_url 200, pip 403
        (flags fully independent, [D1][D2]). Self-cleaning like SC-02 —
        a stale clone from an earlier S-A test would 400 the git arm."""
        _remove_node_dir(UNKNOWN_GIT_DIRNAME)
        try:
            git_resp = _post_git_url(UNKNOWN_GIT_URL)
            pip_resp = _post_pip("text-unidecode")
            assert git_resp.status_code == 200, (
                f"SC-17 git arm: expected 200, got {git_resp.status_code}"
            )
            assert pip_resp.status_code == 403, (
                f"SC-17 pip arm: expected 403, got {pip_resp.status_code}"
            )
        finally:
            _remove_node_dir(UNKNOWN_GIT_DIRNAME)

    def test_sc18_git_transaction_never_consults_pip_flag(
            self, comfyui_flags_b):
        """SC-18: git=true, pip=false -> a git-URL install transaction
        (clone + execute_install_script dependency step) COMPLETES, and the
        captured log slice contains no allow_pip_install denial — the pip
        flag governs ONLY the standalone S-B surface (MM §1.4 transaction
        scope; spec §1.1 invariant 4).

        Fresh install forced (pre-remove) so execute_install_script actually
        runs inside the transaction window."""
        _remove_node_dir(UNKNOWN_GIT_DIRNAME)
        offset = _log_offset()
        try:
            resp = _post_git_url(UNKNOWN_GIT_URL)
            log = _log_slice(offset)
            assert resp.status_code == 200, (
                f"SC-18: git transaction failed ({resp.status_code}) with "
                "pip=false — transitive scope broken? Body: "
                f"{resp.text[:200]}"
            )
            assert "allow_pip_install" not in log, (
                "SC-18: the git-URL install transaction consulted/logged "
                "allow_pip_install — per-surface scope violated (MM §1.4):\n"
                + log[-2000:]
            )
        finally:
            _remove_node_dir(UNKNOWN_GIT_DIRNAME)

    def test_sc04_batch_unknown_url_queued_at_default_level(
            self, comfyui_flags_b):
        """SC-04: git=true, sl=normal -> batch unknown-URL install is
        QUEUED (failed list empty): middle+ entry passes at normal local
        AND the flag replaces the high+ risky check (today 403: risky
        high+ fails at normal). Target dir pre-seeded — see module
        docstring 'Side-effect control'."""
        _preseed_node_dir(BATCH_UNKNOWN_DIRNAME)
        try:
            item = _batch_install_item("sc04-unknown", [BATCH_UNKNOWN_GIT_URL])
            resp = _post_batch({"install": [item]})
            assert resp.status_code == 200, resp.text[:200]
            failed = resp.json().get("failed", [])
            assert "sc04-unknown" not in failed, (
                "SC-04: batch unknown-URL install still denied at "
                "sl=normal with allow_git_url_install=true — the risky "
                f"high+ check was not replaced by the flag. failed={failed!r}"
            )
        finally:
            _remove_node_dir(BATCH_UNKNOWN_DIRNAME)


# ===========================================================================
# CFG-C: git=F, pip=T, sl=normal, nm=public
# ===========================================================================

class TestPipFlagOnDefaultLevel:
    def test_sc16_git_closed_pip_open_independent(self, comfyui_flags_c):
        """SC-16: git=false, pip=true, sl=normal -> git_url 403, pip 200
        (flags fully independent, [D1][D2])."""
        git_resp = _post_git_url(UNKNOWN_GIT_URL)
        pip_resp = _post_pip("text-unidecode")
        assert git_resp.status_code == 403, (
            f"SC-16 git arm: expected 403, got {git_resp.status_code}"
        )
        assert pip_resp.status_code == 200, (
            f"SC-16 pip arm: expected 200, got {pip_resp.status_code}"
        )


# ===========================================================================
# CFG-D: git=F, pip=F, sl=weak, nm=public
# ===========================================================================

class TestFlagsOffWeakLevel:
    """Deny-direction decoupling: flags=false must deny S-A/S-B even at
    security_level=weak (today: 200) — and the denial log must name the
    responsible flag (SC-23 log arm, spec §1.3)."""

    def test_sc05_sc23_git_url_denied_at_weak_log_names_flag(
            self, comfyui_flags_d):
        """SC-05: git=false, sl=weak, loopback -> 403 (today 200 — deny
        direction of security_level irrelevance).
        SC-23 (log arm): the denial log names allow_git_url_install and
        drops the security-level framing (SECURITY_MESSAGE_NORMAL_MINUS)."""
        offset = _log_offset()
        resp = _post_git_url(UNKNOWN_GIT_URL)
        log = _log_slice(offset)

        assert resp.status_code == 403, (
            f"SC-05: expected 403 (flag=false overrides sl=weak), got "
            f"{resp.status_code} — security_level still opens S-A."
        )
        assert "allow_git_url_install" in log, (
            "SC-23: denial log does not name allow_git_url_install "
            f"(spec §1.3 SECURITY_MESSAGE_FLAG_GIT_URL). Slice:\n{log[-1500:]}"
        )
        assert "security level to 'normal-'" not in log, (
            "SC-23: denial log still carries the misleading "
            "security-level copy (SECURITY_MESSAGE_NORMAL_MINUS)."
        )

    def test_sc13_sc23_pip_denied_at_weak_log_names_flag(
            self, comfyui_flags_d):
        """SC-13: pip=false, sl=weak, loopback -> 403 (today 200).
        SC-23 (log arm): denial log names allow_pip_install
        (spec §1.3 SECURITY_MESSAGE_FLAG_PIP)."""
        offset = _log_offset()
        resp = _post_pip("text-unidecode")
        log = _log_slice(offset)

        assert resp.status_code == 403, (
            f"SC-13: expected 403 (flag=false overrides sl=weak), got "
            f"{resp.status_code} — security_level still opens S-B."
        )
        assert "allow_pip_install" in log, (
            "SC-23: denial log does not name allow_pip_install "
            f"(spec §1.3 SECURITY_MESSAGE_FLAG_PIP). Slice:\n{log[-1500:]}"
        )

    def test_sc09_batch_unknown_url_denied_when_flag_false(
            self, comfyui_flags_d):
        """SC-09: git=false, sl=weak -> batch unknown-URL install denied —
        the flag gate fails despite weak (today: allowed). Composite gate's
        flag term is the decider here (middle+ passes at weak local)."""
        item = _batch_install_item("sc09-unknown", [BATCH_UNKNOWN_GIT_URL])
        resp = _post_batch({"install": [item]})
        assert resp.status_code == 200, resp.text[:200]
        failed = resp.json().get("failed", [])
        assert "sc09-unknown" in failed, (
            "SC-09: batch unknown-URL install must be denied with "
            f"allow_git_url_install=false even at sl=weak. failed={failed!r}"
        )


# ===========================================================================
# CFG-E: git=T, pip=T, sl=weak, nm=public — Q1 guard
# ===========================================================================

class TestUnknownPipStaysBlocked:
    def test_sc24_batch_unknown_pip_block_is_unconditional(
            self, comfyui_flags_e):
        """SC-24 (Q1 guard): batch item whose files are ALL DB-known (no
        high+ short-circuit on the URL check) but whose pip list names an
        UNKNOWN package -> still denied. get_risky_level's 'block' branch
        stays UNCONDITIONAL — the flags do NOT open it (spec §5 freeze
        item 7), even with both flags true at sl=weak."""
        item = _batch_install_item(
            "sc24-known-url-unknown-pip",
            [KNOWN_GIT_URL],
            pip=[UNKNOWN_PIP_PKG],
        )
        resp = _post_batch({"install": [item]})
        assert resp.status_code == 200, resp.text[:200]
        failed = resp.json().get("failed", [])
        assert "sc24-known-url-unknown-pip" in failed, (
            "SC-24: unknown-pip 'block' branch opened — it must remain "
            f"unconditional regardless of the new flags. failed={failed!r}"
        )


# ===========================================================================
# CFG-F / CFG-G: out-of-scope legacy guards (SC-25A/B) — flags have NO effect
# ===========================================================================

def _batch_op_item(ui_id: str) -> dict:
    """Item for middle-gated batch ops (fix/uninstall/update). The GATE
    check precedes node resolution, so a placeholder spec is sufficient:
    the queue worker's later failure on the nonexistent node is irrelevant
    to the synchronous gate observable (the response's failed list)."""
    return {
        "id": ui_id,
        "ui_id": ui_id,
        "version": "unknown",
        "files": [f"https://example.com/{ui_id}"],
    }


class _LegacyGuardRows:
    """Shared assertions for SC-25A/B — executed under BOTH flag combos
    ((t,t) via CFG-F and (f,f) via CFG-G); outcomes must be IDENTICAL,
    proving the flags have zero effect on middle/middle+ surfaces."""

    flags_label = ""

    def _assert_sc25a(self):
        """SC-25A: legacy middle-gated ops (fix/uninstall/update) stay
        allowed at sl=normal local for this flag combination."""
        payload = {
            "fix": [_batch_op_item(f"sc25a-fix-{self.flags_label}")],
            "uninstall": [_batch_op_item(f"sc25a-unin-{self.flags_label}")],
            "update": [_batch_op_item(f"sc25a-upd-{self.flags_label}")],
        }
        resp = _post_batch(payload)
        assert resp.status_code == 200, resp.text[:200]
        failed = resp.json().get("failed", [])
        gate_denied = [x for x in failed if x.startswith("sc25a-")]
        assert gate_denied == [], (
            f"SC-25A({self.flags_label}): middle-gated batch ops were "
            f"gate-denied at sl=normal — flags must have ZERO effect on "
            f"out-of-scope surfaces. failed={failed!r}"
        )

    def _assert_sc25b(self):
        """SC-25B: batch KNOWN-node install (middle+ path, DB-resolved
        files URL) stays allowed at sl=normal local for this flag
        combination. Known-node dir pre-seeded — no real install."""
        _preseed_node_dir(KNOWN_GIT_DIRNAME)
        try:
            item = _batch_install_item(
                f"sc25b-known-{self.flags_label}", [KNOWN_GIT_URL])
            resp = _post_batch({"install": [item]})
            assert resp.status_code == 200, resp.text[:200]
            failed = resp.json().get("failed", [])
            assert f"sc25b-known-{self.flags_label}" not in failed, (
                f"SC-25B({self.flags_label}): KNOWN-node batch install was "
                f"denied at sl=normal — middle+ path must be unaffected by "
                f"the flags. failed={failed!r}"
            )
        finally:
            _remove_node_dir(KNOWN_GIT_DIRNAME)


class TestGuardsFlagsOn(_LegacyGuardRows):
    flags_label = "flags-on"

    def test_sc25a_middle_ops_allowed_with_flags_on(self, comfyui_flags_f):
        self._assert_sc25a()

    def test_sc25b_known_install_allowed_with_flags_on(self, comfyui_flags_f):
        self._assert_sc25b()


class TestGuardsFlagsOff(_LegacyGuardRows):
    flags_label = "flags-off"

    def test_sc25a_middle_ops_allowed_with_flags_off(self, comfyui_flags_g):
        self._assert_sc25a()

    def test_sc25b_known_install_allowed_with_flags_off(self, comfyui_flags_g):
        self._assert_sc25b()


# ===========================================================================
# CFG-H: git=T, pip=F, sl=normal, nm=personal_cloud
# ===========================================================================

class TestPersonalCloudBatch:
    def test_sc30_batch_unknown_url_queued_under_personal_cloud(
            self, comfyui_flags_h):
        """SC-30: git=true, sl=normal, nm=personal_cloud -> batch
        unknown-URL install queued: the S-C composite gate's middle+ arm
        passes (is_local_mode OR is_personal_cloud) AND the flag is true.
        See module docstring for the loopback-harness limitation; the
        public-listener personal_cloud arm is proven at predicate level."""
        _preseed_node_dir(BATCH_UNKNOWN_DIRNAME)
        try:
            item = _batch_install_item("sc30-unknown", [BATCH_UNKNOWN_GIT_URL])
            resp = _post_batch({"install": [item]})
            assert resp.status_code == 200, resp.text[:200]
            failed = resp.json().get("failed", [])
            assert "sc30-unknown" not in failed, (
                "SC-30: batch unknown-URL install denied under "
                f"network_mode=personal_cloud with flag=true. "
                f"failed={failed!r}"
            )
        finally:
            _remove_node_dir(BATCH_UNKNOWN_DIRNAME)
