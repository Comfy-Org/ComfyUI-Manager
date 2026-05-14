"""E2E demonstration that the high+ T2 SECGATE-PENDING Goals are testable
at the DEFAULT security_level=normal — no strict-mode harness needed.

WI-KK research finding (see decision-trail wi-kk-t2-secgate-harness-...):
The 8 T2 SECGATE-PENDING Goals listed in reports/e2e_verification_audit.md
were assumed to all need a restricted-security-level harness. After reading
comfyui_manager/glob/utils/security_utils.py:14-40 the actual gate semantics
become clear:

  - is_local_mode = is_loopback(args.listen) → True for our 127.0.0.1 setup
  - For Risk=high+: returns True iff security_level in [WEAK, NORMAL_]
  - The default normal IS NOT in that set → high+ operations return False → 403

So the high+ Goals are ALREADY 403-testable at default config:
  - CV4 (comfyui_switch_version)              ← THIS file proves it
  - IM4 (install_model non-safetensors)       ← deferred (see note below)
  - LGU2 (customnode/install/git_url)         ← deferred (legacy-only endpoint)
  - LPP2 (customnode/install/pip)             ← deferred (legacy-only endpoint)

CV4 is the cleanest demonstration: it is registered in glob and has a
synchronous is_allowed_security_level('high+') guard at
comfyui_manager/glob/manager_server.py:1856 that returns 403 directly.

Goals deferred to follow-up WIs (with notes for the audit-reflect WI):
  - IM4: the non-safetensors check happens DEEP in the install pipeline (in
    get_risky_level + the worker), not at the HTTP handler. There is NO
    synchronous 403 from POST /v2/manager/queue/install_model — the handler
    accepts the JSON and queues a task; rejection only surfaces during task
    execution. This requires a queue-observation test pattern, not a simple
    HTTP 403 check.
  - LGU2 / LPP2: registered ONLY in legacy/manager_server.py (1502, 1522),
    not in glob. Testing them requires the legacy fixture
    (start_comfyui_legacy.sh) — fits naturally into a follow-up
    test_e2e_secgate_legacy_default.py module.

This file therefore demonstrates the harness-not-needed insight with the
single Goal where it cleanly applies (CV4) and documents the audit-reflect
implications inline.

Requires a pre-built E2E environment (from setup_e2e_env.sh).
"""

from __future__ import annotations

import os
import subprocess

import pytest
import requests

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scripts"
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

def _start_comfyui_default() -> int:
    """Launch ComfyUI at the default security_level (normal) — glob mode."""
    env = {**os.environ, "E2E_ROOT": E2E_ROOT, "PORT": str(PORT)}
    r = subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "start_comfyui.sh")],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Failed to start ComfyUI (default):\n{r.stderr}")
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
def comfyui_default():
    pid = _start_comfyui_default()
    try:
        yield pid
    finally:
        _stop_comfyui()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSecurityGate403_CV4:
    """Goal CV4 — POST /v2/comfyui_manager/comfyui_switch_version must
    return 403 below `high+`. At the default security_level=normal +
    is_local_mode=True, NORMAL is NOT in the allowed-set [WEAK, NORMAL_]
    for the high+ check, so the 403 path triggers WITHOUT any harness.

    Handler: comfyui_manager/glob/manager_server.py:1854-1858
    Gate:    is_allowed_security_level("high+")
    """

    def test_switch_version_returns_403_at_default(self, comfyui_default):
        # We deliberately send a syntactically valid JSON body so the
        # request would reach the Pydantic validation step IF the gate
        # were broken. The gate is the FIRST check in the handler, so
        # 403 must precede any 400-from-validation outcome.
        # Body transport (JSON) per WI #258 — previously query string.
        resp = requests.post(
            f"{BASE_URL}/v2/comfyui_manager/comfyui_switch_version",
            json={"ver": "v0.12.1", "client_id": "secgate-cv4", "ui_id": "secgate-cv4"},
            timeout=10,
        )

        assert resp.status_code == 403, (
            f"CV4 SECURITY-GATE BYPASS: POST comfyui_switch_version returned "
            f"{resp.status_code} at security_level=normal (expected 403). "
            f"This means the high+ gate is broken — version downgrade attacks "
            f"would succeed. Response: {resp.text[:200]}"
        )
