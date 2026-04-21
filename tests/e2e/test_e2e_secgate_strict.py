"""E2E PoC for the strict-mode security gate (T2 SECGATE-PENDING harness).

SCOPE — important clarification:
This suite is the PoC for the security_level=strong harness needed to verify
the 403 contract on middle/middle+ gates. The default E2E config
(security_level=normal, is_local_mode=True) puts NORMAL inside the allowed
set for both middle and middle+ checks (see comfyui_manager/glob/utils/
security_utils.py:32-38), so the 403 path on these gates is unreachable
without elevating the security_level to STRONG.

The 4 T2 SECGATE-PENDING Goals at middle/middle+ that depend on this harness:
  - SR4 (snapshot/remove, gate=middle)        ← THIS PoC
  - SR6 (snapshot/restore, gate=middle+)      ← follow-up
  - V5  (manager/reboot, gate=middle)         ← follow-up
  - UA2 (manager/queue/update_all, gate=middle+) ← follow-up

WI-KK established the harness pattern (start_comfyui_strict.sh + a fixture
that backs up + restores config.ini). Once this PoC lands, the remaining
3 strict-mode tests are mechanical additions to this file.

Why a separate file (not test_e2e_csrf*.py-style mixed):
The strict-mode server lifecycle is heavyweight (config patch + restart). It
must NOT contaminate normal-mode test suites where security_level=normal is
expected. By keeping strict tests in their own module with their own fixture,
we keep the cost contained and the contracts unambiguous.

Negative-check coverage (per verification_design.md §7.3 Security Boundary
Template):
  - 403 status
  - target snapshot file UNCHANGED on disk
  - (log substring check is OPTIONAL and not asserted here — observable in
    server logs but cumbersome to scrape from pytest)

Requires a pre-built E2E environment (from setup_e2e_env.sh).
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest
import requests

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scripts"
)
MANAGER_CONFIG = (
    os.path.join(COMFYUI_PATH, "user", "__manager", "config.ini")
    if COMFYUI_PATH else ""
)
SNAPSHOT_DIR = (
    os.path.join(COMFYUI_PATH, "user", "__manager", "snapshots")
    if COMFYUI_PATH else ""
)

PORT = 8199
BASE_URL = f"http://127.0.0.1:{PORT}"

pytestmark = pytest.mark.skipif(
    not E2E_ROOT
    or not os.path.isfile(os.path.join(E2E_ROOT, ".e2e_setup_complete")),
    reason="E2E_ROOT not set or E2E environment not ready",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_comfyui_strict() -> int:
    """Launch ComfyUI with security_level=strong (start_comfyui_strict.sh)."""
    env = {**os.environ, "E2E_ROOT": E2E_ROOT, "PORT": str(PORT)}
    r = subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "start_comfyui_strict.sh")],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Failed to start ComfyUI (strict):\n{r.stderr}")
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


def _restore_config_from_backup():
    """Restore config.ini from the .before-strict backup left by the script."""
    backup = MANAGER_CONFIG + ".before-strict"
    if os.path.isfile(backup):
        shutil.copyfile(backup, MANAGER_CONFIG)
        os.remove(backup)


@pytest.fixture(scope="module")
def comfyui_strict():
    """Start ComfyUI in strict mode for the duration of the module.

    Teardown order matters:
      1. Stop the server (so it releases the config file lock).
      2. Restore the original config.ini (so subsequent test modules see
         the default security_level=normal again).
    """
    pid = _start_comfyui_strict()
    try:
        yield pid
    finally:
        _stop_comfyui()
        _restore_config_from_backup()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSecurityGate403_SR4:
    """Goal SR4 — POST /v2/snapshot/remove must return 403 below `middle`.

    Handler: comfyui_manager/glob/manager_server.py:1535-1554
    Gate:    is_allowed_security_level("middle")
    Strict (security_level=strong) → False → 403.

    Negative check (verification_design.md §7.3): the target snapshot file
    on disk must NOT be removed when the gate rejects the request.
    """

    def test_remove_returns_403(self, comfyui_strict):
        # Seed a snapshot file directly on disk so we have something the
        # handler MIGHT delete if the gate were broken. We do not call
        # /v2/snapshot/save here because that path also requires server
        # state; touching a file is sufficient for the negative check.
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        seed_name = "secgate-sr4-seed"
        seed_path = os.path.join(SNAPSHOT_DIR, f"{seed_name}.json")
        with open(seed_path, "w") as f:
            f.write('{"snapshot": "seed for SR4 negative check"}')
        try:
            assert os.path.isfile(seed_path), "test seed file missing"

            resp = requests.post(
                f"{BASE_URL}/v2/snapshot/remove",
                params={"target": seed_name},
                timeout=10,
            )

            # Primary assertion: 403 from the security gate
            assert resp.status_code == 403, (
                f"SR4 SECURITY-GATE BYPASS: POST snapshot/remove?target="
                f"{seed_name} returned {resp.status_code} at "
                f"security_level=strong (expected 403). Response: "
                f"{resp.text[:200]}"
            )

            # Negative-side assertion: the target file was NOT deleted
            assert os.path.isfile(seed_path), (
                f"SR4 NEGATIVE-CHECK FAILURE: snapshot file {seed_path} was "
                f"deleted despite a 403 response — gate failed to block the "
                f"side effect."
            )
        finally:
            # Cleanup — remove the seed file we created
            if os.path.isfile(seed_path):
                os.remove(seed_path)

    # Positive counterpart (POST works at default after teardown) is covered
    # by test_e2e_secgate_default.py via its own ComfyUI startup; a
    # skip-placeholder was previously parked here for documentation but
    # removed in WI-MM because it added no verification and created a
    # stale-skip row. See reports/e2e_verification_audit.md § SECGATE.


# ---------------------------------------------------------------------------
# Config setter 403 contract (added in WI #255)
# ---------------------------------------------------------------------------
#
# Before WI #255 the three config setters below had NO security_level gate,
# so any caller could mutate db_mode / update_policy / channel_url even at
# security_level=strong. WI #255 added `is_allowed_security_level('middle')`
# to all three (glob + legacy) at the same risk tier as uninstall/update /
# snapshot/remove.
#
# These tests belong in the STRICT harness — at default `security_level =
# normal`, the 'middle' allow-set is [weak, normal, normal-] which INCLUDES
# normal, so the 403 path is not reachable. Strong excludes normal, so the
# rejection is observable.
CONFIG_SETTER_ENDPOINTS = [
    ("/v2/manager/db_mode", {"value": "local"}, "set_db_mode_api"),
    ("/v2/manager/policy/update", {"value": "nightly-comfyui"}, "set_update_policy_api"),
    ("/v2/manager/channel_url_list", {"value": "default"}, "set_channel_url"),
]


class TestConfigSetterRequiresMiddle:
    """Each of the 3 config-mutation POST handlers must return 403 under
    security_level=strong. Before WI #255 they returned 200 unconditionally.

    Handlers (glob):
      - comfyui_manager/glob/manager_server.py :: set_db_mode_api (L1954)
      - comfyui_manager/glob/manager_server.py :: set_update_policy_api (L1972)
      - comfyui_manager/glob/manager_server.py :: set_channel_url (L2000)
    Gate: is_allowed_security_level('middle')
    Strong → normal not in [weak, normal, normal-] → False → 403.

    Negative-check aspect: a 403 response means the config file was NOT
    mutated. We don't re-read config.ini here because the strict harness
    also patches it — checking for absence of mutation would require
    a pre/post diff that is brittle; the 403 status is the contract.
    """

    @pytest.mark.parametrize(
        "path,body,handler_name",
        CONFIG_SETTER_ENDPOINTS,
        ids=[p for p, _, _ in CONFIG_SETTER_ENDPOINTS],
    )
    def test_config_setter_returns_403(self, comfyui_strict, path, body, handler_name):
        resp = requests.post(
            f"{BASE_URL}{path}",
            json=body,
            timeout=10,
        )
        assert resp.status_code == 403, (
            f"CONFIG-SETTER SECURITY-GATE BYPASS: POST {path} "
            f"(handler {handler_name}) returned {resp.status_code} at "
            f"security_level=strong (expected 403). Config mutation must "
            f"require middle+. Response: {resp.text[:200]}"
        )
