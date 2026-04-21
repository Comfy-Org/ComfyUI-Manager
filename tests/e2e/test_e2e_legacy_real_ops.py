"""E2E REAL-execution tests for legacy-UI state-changing endpoints (WI-YY).

SCOPE — closes 6 Playwright-mock gaps by executing the real backend
operation via HTTP:
  Default-security fixture (middle+ / no-gate endpoints):
    - wi-020 POST /v2/manager/queue/install_model (tiny TAEF1 model, <5MB)
    - wi-024 POST /v2/manager/queue/update_comfyui (safe via env var)
  Permissive-security fixture (high+ endpoints — normal- harness):
    - wi-014 POST /v2/comfyui_manager/comfyui_switch_version (no-op self-switch)
    - wi-037 POST /v2/customnode/install/git_url (nodepack-test1-do-not-install)
    - wi-038 POST /v2/customnode/install/pip (text-unidecode)
  Pre-seeded broken-pack fixture (no-gate endpoint, needs scan-time state):
    - wi-015 POST /v2/customnode/import_fail_info (pre-seeded broken pack)

Safety belt — COMFYUI_MANAGER_SKIP_MANAGER_REQUIREMENTS=1 is exported in
tests/e2e/scripts/start_comfyui.sh (WI-YY change). Any install/update path
that would normally run `pip install -r manager_requirements.txt` becomes
a no-op log line — essential for WI-YY real E2E: without this, triggering
the update_comfyui queue worker could run unbounded pip installs against
the test venv.

Permissive harness security rationale:
  wi-014/037/038 execute arbitrary remote code (version switch, git
  clone, pip install) and are gated at `high+` precisely to prevent
  such operations at default security. The permissive harness
  (start_comfyui_permissive.sh) reflects the production use case
  these endpoints exist to serve — operators in a trusted environment
  lower security_level to normal-/weak to enable these features. The
  200 path IS a supported feature, and testing it requires exactly
  this configuration. Permissive harness uses HARDCODED trusted inputs:
    - wi-014: the CURRENT ComfyUI version (self-switch no-op)
    - wi-037: https://github.com/ltdrdata/nodepack-test1-do-not-install
             (project's test-fixture repo, also used by tests/cli/test_uv_compile.py)
    - wi-038: text-unidecode (pure-Python, ~8KB, idempotent)
  User-input-derived values MUST NEVER be substituted. The 403 contract
  at default security remains the positive-path security behavior in
  production — verified by test_e2e_csrf_legacy.py and
  test_e2e_secgate_default.py.

WI-YY.3 (wi-015) real-E2E strategy:
  The import_fail_info endpoint returns info for packs that failed to
  import during the ComfyUI custom_nodes/ startup scan. To exercise
  the 200 path with real state, we pre-seed a known-broken pack via
  git clone (skip pip install). On server start, the scan attempts
  to import the pack, it fails, prestartup_script.py L302-305
  captures the stderr traceback into
  cm_global.error_dict[<module_name>], and the pack is registered
  in core.unified_manager (manager_core.py:541-561).

  Pack selection: ComfyUI-YoloWorld-EfficientSAM — user-suggested.
  Its production failure mode is that requirements.txt pins
  UNINSTALLABLE packages (unresolvable versions / removed-from-index
  / etc), so even the normal install flow
  (`/v2/customnode/install/git_url` → gitclone_install → pip install
  -r requirements.txt) leaves the pack dir present but dependencies
  unsatisfied → scan import fails → the exact state this endpoint
  is meant to report on. The pre-seed fixture (git clone, skip pip)
  reproduces the END STATE that the production install path reaches
  after pip-failure, without the cost and non-determinism of running
  the failing pip. This is NOT "missing deps we chose not to
  install" — it is the genuine production failure mode packaged as
  a deterministic fixture. Tiny clone (few KB of Python).

Requires a pre-built E2E environment (from setup_e2e_env.sh).
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

# Small, well-known VAE-approx model from the whitelist (verified via
# GET /v2/externalmodel/getlist?mode=cache — 4.71MB, public raw URL).
# Selected for minimal download time + deterministic whitelist membership.
TAEF1_MODEL_SPEC = {
    "name": "TAEF1 Decoder",
    "type": "TAESD",
    "base": "FLUX.1",
    "save_path": "vae_approx",
    "description": "WI-YY real-E2E install — TAEF1 decoder",
    "reference": "https://github.com/madebyollin/taesd",
    "filename": "taef1_decoder.pth",
    "url": "https://github.com/madebyollin/taesd/raw/main/taef1_decoder.pth",
}

# HARDCODED TRUSTED INPUTS for the permissive-harness suite.
# Never substitute user-derived values — these constants exist to test
# the supported 200-path of features the operator explicitly enables by
# lowering security_level to normal-.
# TRUSTED_GIT_URL: same purpose-built test fixture used by
# tests/cli/test_uv_compile.py (REPO_TEST1 at L41). The 'do-not-install'
# suffix in the repo name is the project's convention for
# test-fixture-only packs — safe to install and delete repeatedly in E2E.
TRUSTED_GIT_URL = "https://github.com/ltdrdata/nodepack-test1-do-not-install"
TRUSTED_GIT_DIRNAME = "nodepack-test1-do-not-install"
TRUSTED_PIP_PKG = "text-unidecode"  # pure-Python, ~8KB, idempotent

# Broken-pack pre-seed target for wi-015 real E2E.
# User-suggested: ZHO-ZHO-ZHO/ComfyUI-YoloWorld-EfficientSAM. In
# production, this pack's requirements.txt pins uninstallable
# packages, so gitclone_install → pip install -r leaves the pack dir
# present but deps unsatisfied. Our pre-seed (git clone, skip pip)
# reproduces that END STATE deterministically — see module docstring
# §"WI-YY.3 (wi-015) real-E2E strategy".
BROKEN_PACK_URL = "https://github.com/ZHO-ZHO-ZHO/ComfyUI-YoloWorld-EfficientSAM"
BROKEN_PACK_DIRNAME = "ComfyUI-YoloWorld-EfficientSAM"

pytestmark = pytest.mark.skipif(
    not E2E_ROOT
    or not os.path.isfile(os.path.join(E2E_ROOT, ".e2e_setup_complete")),
    reason="E2E_ROOT not set or E2E environment not ready",
)


def _start_comfyui_legacy() -> int:
    env = {**os.environ, "E2E_ROOT": E2E_ROOT, "PORT": str(PORT)}
    r = subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "start_comfyui_legacy.sh")],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Failed to start ComfyUI (legacy):\n{r.stderr}")
    for part in r.stdout.strip().split():
        if part.startswith("COMFYUI_PID="):
            return int(part.split("=")[1])
    raise RuntimeError(f"Could not parse PID:\n{r.stdout}")


def _stop_comfyui():
    env = {**os.environ, "E2E_ROOT": E2E_ROOT, "PORT": str(PORT)}
    subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "stop_comfyui.sh")],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


@pytest.fixture(scope="module")
def comfyui_legacy():
    pid = _start_comfyui_legacy()
    yield pid
    _stop_comfyui()


def _start_comfyui_permissive() -> int:
    """Launch via start_comfyui_permissive.sh — patches config.ini to
    `security_level = normal-` (backup at config.ini.before-permissive)
    then delegates to start_comfyui.sh with ENABLE_LEGACY_UI=1.
    The permissive fixture MUST restore config on teardown.
    """
    env = {**os.environ, "E2E_ROOT": E2E_ROOT, "PORT": str(PORT)}
    r = subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "start_comfyui_permissive.sh")],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Failed to start ComfyUI (permissive):\n{r.stderr}")
    for part in r.stdout.strip().split():
        if part.startswith("COMFYUI_PID="):
            return int(part.split("=")[1])
    raise RuntimeError(f"Could not parse PID:\n{r.stdout}")


def _restore_permissive_config():
    """Restore $CONFIG from $CONFIG.before-permissive. Safe to call even
    if the backup is missing (idempotent). Mirrors the pattern used by
    test_e2e_secgate_strict.py for the strict harness.
    """
    config = os.path.join(
        COMFYUI_PATH, "user", "__manager", "config.ini"
    )
    backup = config + ".before-permissive"
    if os.path.isfile(backup):
        import shutil
        shutil.move(backup, config)


@pytest.fixture(scope="module")
def comfyui_permissive():
    """Module-scoped fixture: start server with security_level=normal-,
    tear down with config restore. Use for wi-014/037/038 which require
    `high+` (security_utils.py:20-26 allows weak/normal- at is_local_mode).
    """
    pid = _start_comfyui_permissive()
    try:
        yield pid
    finally:
        _stop_comfyui()
        _restore_permissive_config()


def _seed_broken_pack() -> str:
    """Pre-seed the broken pack via git clone --depth 1. Returns the
    absolute path to the cloned directory. pip install is skipped —
    this reproduces the production end-state where gitclone_install +
    pip install -r requirements.txt leaves the pack dir in place
    despite pip failing on uninstallable package pins (see module
    docstring §"WI-YY.3 real-E2E strategy"). The ImportError at scan
    time populates cm_global.error_dict (prestartup_script.py:
    302-305) and registers the pack in unified_manager
    (manager_core.py:541-561).
    """
    target = os.path.join(COMFYUI_PATH, "custom_nodes", BROKEN_PACK_DIRNAME)
    if os.path.isdir(target):
        import shutil
        shutil.rmtree(target)
    r = subprocess.run(
        ["git", "clone", "--depth", "1", BROKEN_PACK_URL, target],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"Failed to clone broken-pack seed {BROKEN_PACK_URL!r}: "
            f"rc={r.returncode} stderr={r.stderr!r}"
        )
    assert os.path.isdir(os.path.join(target, ".git")), (
        f"Clone reported success but {target}/.git missing"
    )
    return target


def _remove_broken_pack():
    target = os.path.join(COMFYUI_PATH, "custom_nodes", BROKEN_PACK_DIRNAME)
    if os.path.isdir(target):
        import shutil
        shutil.rmtree(target, ignore_errors=True)


@pytest.fixture(scope="module")
def comfyui_with_broken_pack():
    """Module-scoped fixture: pre-seed a broken pack, start the legacy
    server so its scan captures the import failure, yield, then stop
    server + remove the pack.

    Uses the default-security legacy launcher because
    /v2/customnode/import_fail_info has no security gate
    (legacy/manager_server.py:1289-1303).
    """
    _seed_broken_pack()
    try:
        pid = _start_comfyui_legacy()
        try:
            yield pid
        finally:
            _stop_comfyui()
    finally:
        _remove_broken_pack()


def _wait_for_file(target: str, timeout: float, poll_interval: float = 1.0) -> bool:
    """Poll for target file existence up to `timeout` seconds. Returns
    True if the file appears (and has non-zero size) before timeout.
    Relying on disk artifact rather than queue/status counters because
    task_batch_queue drains to empty post-completion, so
    `queue/status.total_count` returns to 0 once the worker is idle —
    it is not a persistent completion counter.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(target) and os.path.getsize(target) > 0:
            return True
        time.sleep(poll_interval)
    return False


class TestUpdateComfyuiQueued:
    """Real E2E for wi-024 POST /v2/manager/queue/update_comfyui.

    At default `security_level = normal` the handler has no security
    gate (legacy/manager_server.py:1572-1576 — unlike install/git_url
    and install/pip which require `high+`). The handler appends an
    ("update-comfyui", (...)) entry to temp_queue_batch and returns 200.
    It does NOT start the worker — that is triggered separately by
    POST /v2/manager/queue/batch at handler L797-799 (the UI batches
    update_comfyui:true via queue/batch in production, per
    comfyui-manager.js:478-480).

    Therefore the real-E2E contract for this endpoint is:
    (a) HTTP 200 return,
    (b) temp_queue_batch mutation observable via subsequent queue/status
        delta once the worker processes (when batch is called later).

    We verify (a) — the direct endpoint's immediate contract. Triggering
    the worker with a real git pull would risk advancing the test-env
    ComfyUI git state; the env var only protects against pip install
    runaway, not against HEAD advancing.
    """

    def test_direct_endpoint_returns_200(self, comfyui_legacy):
        resp = requests.post(
            f"{BASE_URL}/v2/manager/queue/update_comfyui", timeout=15
        )
        assert resp.status_code == 200, (
            f"update_comfyui should return 200 at default security_level, "
            f"got {resp.status_code}: {resp.text[:200]}"
        )


class TestInstallModelRealDownload:
    """Real E2E for wi-020 POST /v2/manager/queue/install_model.

    Flow:
      1. Clean any pre-existing target file (test isolation).
      2. POST install_model with the TAEF1 Decoder spec (whitelisted,
         ~4.71MB from github.com/madebyollin/taesd raw).
      3. POST /v2/manager/queue/batch with empty body — this nudges
         _queue_start() (handler L797-799) to drain temp_queue_batch.
      4. Poll for the .pth file to land at models/vae_approx/ with
         non-zero size (primary completion signal — task_batch_queue
         drains to empty post-completion so total_count returns to 0,
         making queue/status an unreliable completion proxy).
      5. Verify the downloaded file size matches expected ~4.7MB.
      6. Teardown deletes the file.

    Handler security: middle+ at local_mode (is_loopback 127.0.0.1) allows
    `normal` → request accepted. Whitelist check at L1649 passes because
    the model entry IS in model-list.json (verified via
    GET /v2/externalmodel/getlist). Non-safetensors check at L1653 is
    bypassed because is_allowed_security_level('high+') is false — falls
    into the whitelist-url branch which DOES find a match.

    Safety belt: COMFYUI_MANAGER_SKIP_MANAGER_REQUIREMENTS=1 is exported
    at server startup. Download itself is direct HTTP (no pip run), so
    the env var is a belt+suspenders for any transitive install that
    might trigger.
    """

    def _target_path(self) -> str:
        return os.path.join(
            COMFYUI_PATH, "models", "vae_approx", TAEF1_MODEL_SPEC["filename"]
        )

    def test_install_model_downloads_file(self, comfyui_legacy):
        target = self._target_path()
        # (1) Pre-clean — idempotent test setup.
        if os.path.exists(target):
            os.remove(target)
        assert not os.path.exists(target), (
            f"Pre-condition: {target} should not exist before install"
        )

        try:
            # (2) Queue the install.
            post_resp = requests.post(
                f"{BASE_URL}/v2/manager/queue/install_model",
                json=TAEF1_MODEL_SPEC,
                timeout=15,
            )
            assert post_resp.status_code == 200, (
                f"install_model should return 200 for whitelisted model, "
                f"got {post_resp.status_code}: {post_resp.text[:300]}"
            )

            # (3) Nudge the worker via an empty batch call. This triggers
            # _queue_start() at L797-799 which drains temp_queue_batch.
            batch_resp = requests.post(
                f"{BASE_URL}/v2/manager/queue/batch",
                json={},
                timeout=15,
            )
            assert batch_resp.status_code == 200, (
                f"queue/batch nudge should return 200, "
                f"got {batch_resp.status_code}"
            )

            # (4) Poll for the target file to appear. Primary completion
            # signal — disk artifact is the durable proof of a real
            # download (HTTP body was written to the expected location).
            appeared = _wait_for_file(target, timeout=120.0, poll_interval=2.0)
            assert appeared, (
                f"Install task did not produce {target} within 120s; "
                f"last queue status: "
                f"{requests.get(f'{BASE_URL}/v2/manager/queue/status', timeout=5).json()!r}"
            )

            # (5) Verify the file is the real model (not a placeholder /
            # error HTML).
            size = os.path.getsize(target)
            assert size > 1_000_000, (
                f"Downloaded file {target} is suspiciously small ({size} bytes); "
                f"expected ~4.7MB for TAEF1 decoder"
            )
        finally:
            # (6) Teardown — delete the downloaded file regardless of
            # assertion outcome, so re-runs start clean.
            if os.path.exists(target):
                os.remove(target)


# ---------------------------------------------------------------------------
# Permissive-harness suite (high+ gated endpoints)
# ---------------------------------------------------------------------------


class TestSwitchComfyuiSelfSwitch:
    """Real E2E for wi-014 POST /v2/comfyui_manager/comfyui_switch_version.

    Strategy: GET /v2/comfyui_manager/comfyui_versions to discover the
    CURRENTLY checked-out version, then POST switch to that same version
    — a no-op self-switch that exercises the 200 branch of the handler
    (legacy/manager_server.py:1590-1604) without advancing the test-env
    ComfyUI git HEAD. core.switch_comfyui is called with the current
    version; any git checkout/fetch of the already-checked-out ref is
    idempotent.
    """

    def test_self_switch_returns_200(self, comfyui_permissive):
        versions_resp = requests.get(
            f"{BASE_URL}/v2/comfyui_manager/comfyui_versions", timeout=30
        )
        assert versions_resp.status_code == 200, (
            f"comfyui_versions GET should return 200, "
            f"got {versions_resp.status_code}: {versions_resp.text[:200]}"
        )
        current = versions_resp.json().get("current")
        assert current, (
            f"comfyui_versions response missing 'current' field: "
            f"{versions_resp.json()!r}"
        )

        # WI #258: migrated from query-string (params=) to JSON body (json=).
        # Legacy handler only reads `ver` from the body; client_id/ui_id are
        # tolerated if present but not required by legacy.
        switch_resp = requests.post(
            f"{BASE_URL}/v2/comfyui_manager/comfyui_switch_version",
            json={"ver": current},
            timeout=60,
        )
        assert switch_resp.status_code == 200, (
            f"comfyui_switch_version to current={current!r} should return "
            f"200 at security_level=normal- (high+ allowed), "
            f"got {switch_resp.status_code}: {switch_resp.text[:300]}"
        )


class TestInstallViaGitUrlRealClone:
    """Real E2E for wi-037 POST /v2/customnode/install/git_url.

    Strategy: POST with body=TRUSTED_GIT_URL (plain text). Handler
    (legacy/manager_server.py:1502-1519) runs core.gitclone_install(url)
    synchronously; 200 on success + 'After restarting ComfyUI' log;
    'skip' action on already-installed → also 200.

    Teardown: rm -rf custom_nodes/ComfyUI_examples so re-runs are clean.
    """

    def _target_dir(self) -> str:
        return os.path.join(COMFYUI_PATH, "custom_nodes", TRUSTED_GIT_DIRNAME)

    def test_install_via_git_url_clones_repo(self, comfyui_permissive):
        target = self._target_dir()
        # Pre-clean — idempotent test setup.
        if os.path.isdir(target):
            import shutil
            shutil.rmtree(target)
        assert not os.path.isdir(target), (
            f"Pre-condition: {target} should not exist before install"
        )

        try:
            resp = requests.post(
                f"{BASE_URL}/v2/customnode/install/git_url",
                data=TRUSTED_GIT_URL,
                headers={"Content-Type": "text/plain"},
                timeout=180,
            )
            assert resp.status_code == 200, (
                f"install/git_url with trusted URL {TRUSTED_GIT_URL!r} "
                f"should return 200 at security_level=normal-, got "
                f"{resp.status_code}: {resp.text[:300]}"
            )
            assert os.path.isdir(target), (
                f"Clone reported success but directory missing at {target}"
            )
            # Verify this looks like a real clone (has .git), not a stub.
            assert os.path.isdir(os.path.join(target, ".git")), (
                f"{target} exists but has no .git subdir — not a real clone"
            )
        finally:
            if os.path.isdir(target):
                import shutil
                shutil.rmtree(target, ignore_errors=True)


class TestInstallPipRealExecute:
    """Real E2E for wi-038 POST /v2/customnode/install/pip.

    Strategy: POST with body=TRUSTED_PIP_PKG. Handler
    (legacy/manager_server.py:1522-1531) runs core.pip_install(pkgs)
    which builds a `['#FORCE', 'pip', 'install', '-U', <pkg>]` command
    and calls try_install_script. The `#FORCE` prefix marks the command
    as LAZY — reserve_script appends it to
    `user/__manager/startup-scripts/install-scripts.txt`, to be
    executed by ComfyUI on the NEXT startup (legacy/manager_core.py:
    1830-1837, 1871-1876). The command does NOT run synchronously.

    Therefore the real-E2E contract here is:
    (a) POST returns 200 immediately,
    (b) install-scripts.txt contains a newly-appended line referencing
        the trusted package name AND the 'pip install' verb.

    Verifying the eventual pip install actually runs would require
    restarting ComfyUI and waiting for the startup hook — out of scope
    for this suite's module-scoped fixture. Contract (b) is the
    durable on-disk evidence that the handler correctly scheduled the
    install.

    Teardown: truncate the script file so re-runs start with a clean
    lazy-queue.
    """

    def _script_path(self) -> str:
        return os.path.join(
            COMFYUI_PATH,
            "user", "__manager", "startup-scripts", "install-scripts.txt",
        )

    def test_install_pip_schedules_lazy_install(self, comfyui_permissive):
        script_path = self._script_path()
        # Capture pre-state so we can assert a NEW line was appended.
        pre_lines: list[str] = []
        if os.path.isfile(script_path):
            with open(script_path, "r") as f:
                pre_lines = f.readlines()

        try:
            resp = requests.post(
                f"{BASE_URL}/v2/customnode/install/pip",
                data=TRUSTED_PIP_PKG,
                headers={"Content-Type": "text/plain"},
                timeout=30,
            )
            assert resp.status_code == 200, (
                f"install/pip with trusted pkg {TRUSTED_PIP_PKG!r} should "
                f"return 200 at security_level=normal-, got "
                f"{resp.status_code}: {resp.text[:300]}"
            )

            # Verify a NEW line was appended AND it references the
            # trusted package + the pip install verb.
            assert os.path.isfile(script_path), (
                f"install-scripts.txt not created at {script_path}"
            )
            with open(script_path, "r") as f:
                post_lines = f.readlines()
            new_lines = post_lines[len(pre_lines):]
            assert new_lines, (
                f"No new entry appended to {script_path} after POST"
            )
            joined = "".join(new_lines)
            assert TRUSTED_PIP_PKG in joined, (
                f"New entry does not reference {TRUSTED_PIP_PKG!r}: "
                f"{joined!r}"
            )
            assert "pip" in joined and "install" in joined, (
                f"New entry does not look like a pip install command: "
                f"{joined!r}"
            )
        finally:
            # Restore pre-state so other tests / re-runs are unaffected.
            if os.path.isfile(script_path):
                with open(script_path, "w") as f:
                    f.writelines(pre_lines)


# ---------------------------------------------------------------------------
# Broken-pack pre-seed suite (wi-015 real E2E)
# ---------------------------------------------------------------------------


class TestImportFailInfoReal:
    """Real E2E for wi-015 POST /v2/customnode/import_fail_info (WI-YY.3).

    See module docstring for strategy. Two assertions:
      1. POST with `{cnr_id: BROKEN_PACK_DIRNAME}` returns 200 + dict
         body containing the captured error info (at minimum a `msg`
         field per prestartup_script.py:303; the handler forwards the
         full `{name, path, msg}` record).
      2. POST with an unrelated cnr_id returns 400 (control — verifies
         the handler doesn't leak info for packs that never failed).

    Identifier discovery (empirical — verified via import_fail_info_bulk
    probe during implementation): for a non-CNR git-cloned pack, the
    lookup key is the DIRECTORY BASENAME as `cnr_id`. The repo URL and
    the aux_id form (`author/repo`) both return 400 because
    get_module_name (manager_core.py:398-407) does NOT match on URL
    for active_nodes entries; URL matching only happens via
    unknown_active_nodes which requires a different registration path
    than what a plain `git clone` produces (non-CNR packs without aux_id
    metadata land in active_nodes keyed by directory basename). The
    cnr_id=basename route is the supported single-endpoint lookup for
    this class of pack.
    """

    def test_import_fail_info_returns_error(self, comfyui_with_broken_pack):
        # Warm-up: /v2/customnode/import_fail_info (single) does NOT call
        # unified_manager.reload — it assumes state is already loaded.
        # The paired BULK endpoint at manager_server.py:1320-1321 calls
        # `reload('cache')` + `get_custom_nodes('default', 'cache')`
        # which runs update_cache_at_path (manager_core.py:742) per
        # directory — this is what registers our broken pack in
        # unified_manager via its directory-basename cnr_id
        # (manager_core.py:557-561; aux_id form = author/repo,
        # cnr_id form = directory basename). Without this warmup, the
        # single-endpoint POST sees an empty active_nodes/
        # unknown_active_nodes and returns 400.
        warm_resp = requests.post(
            f"{BASE_URL}/v2/customnode/import_fail_info_bulk",
            json={"cnr_ids": ["__warmup__"]},
            timeout=60,
        )
        assert warm_resp.status_code == 200, (
            f"warmup bulk failed: {warm_resp.status_code} "
            f"{warm_resp.text[:200]}"
        )

        # Identifier discovery (per dispatch): the key that unlocks the
        # error_dict lookup for a non-CNR git-cloned pack is the
        # DIRECTORY BASENAME, NOT the repo URL and NOT the aux_id.
        # Verified empirically via the bulk probe — full-URL and
        # author/repo both returned null, only the basename cnr_id key
        # returned the captured error info. Route: handler calls
        # unified_manager.get_module_name(cnr_id) which reads
        # active_nodes[cnr_id] → (version, fullpath), returning
        # basename(fullpath) == BROKEN_PACK_DIRNAME.
        resp = requests.post(
            f"{BASE_URL}/v2/customnode/import_fail_info",
            json={"cnr_id": BROKEN_PACK_DIRNAME},
            timeout=15,
        )
        assert resp.status_code == 200, (
            f"import_fail_info should return 200 for pre-seeded broken "
            f"pack cnr_id={BROKEN_PACK_DIRNAME!r}; got {resp.status_code}: "
            f"{resp.text[:300]}"
        )
        data = resp.json()
        assert isinstance(data, dict), (
            f"Response body should be a dict, got {type(data).__name__}"
        )
        # prestartup_script.py:303 stores {'name', 'path', 'msg'} — `msg`
        # accumulates the captured stderr output from the failing import.
        assert "msg" in data, (
            f"Response dict missing 'msg' field — import error info not "
            f"captured. keys={list(data)}"
        )
        assert data["msg"], (
            f"'msg' field is empty — expected captured stderr from the "
            f"failing import. Full response: {data!r}"
        )

    def test_import_fail_info_unknown_cnr_id_returns_400(self, comfyui_with_broken_pack):
        # Control: for a cnr_id NOT in active_nodes/unknown_active_nodes,
        # get_module_name returns None and the handler returns 400
        # (manager_server.py:1303). Distinguishes "info available" from
        # "no matching pack registered".
        resp = requests.post(
            f"{BASE_URL}/v2/customnode/import_fail_info",
            json={"cnr_id": "nonexistent_pack_xyz_123"},
            timeout=15,
        )
        assert resp.status_code == 400, (
            f"import_fail_info for unknown cnr_id should return 400; got "
            f"{resp.status_code}: {resp.text[:200]}"
        )
