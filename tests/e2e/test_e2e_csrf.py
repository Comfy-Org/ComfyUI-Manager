"""E2E tests for the GET-rejection contract on state-changing endpoints.

SCOPE — important clarification:
This suite verifies ONE specific CSRF mitigation layer: that state-changing
endpoints reject HTTP GET requests (so that <img src="..."> / link-click /
redirect-based cross-origin triggers cannot mutate server state). This is
the contract established in commit 99caef55 which converted 12+ endpoints
from GET to POST.

NOT COVERED by this suite:
- Origin / Referer header validation
- Same-site cookie enforcement
- Anti-CSRF token verification
- Cross-site form POST defense

Those remaining CSRF defenses are handled separately (e.g., via the
origin_only_middleware at the aiohttp layer) and are the subject of
other test layers. Do NOT read PASS here as "CSRF fully solved" — read
it as "the method-conversion contract holds".

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

def _start_comfyui() -> int:
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
def comfyui():
    pid = _start_comfyui()
    yield pid
    _stop_comfyui()


# ---------------------------------------------------------------------------
# State-changing endpoints that MUST reject GET per CSRF mitigation contract
# ---------------------------------------------------------------------------

# (method, path, description) — derived from commit 99caef55 scope
STATE_CHANGING_POST_ENDPOINTS = [
    ("/v2/manager/queue/start", "start worker"),
    ("/v2/manager/queue/reset", "reset queue"),
    ("/v2/manager/queue/update_all", "update all packs"),
    ("/v2/manager/queue/update_comfyui", "update ComfyUI core"),
    ("/v2/manager/queue/install_model", "queue model download"),
    ("/v2/manager/queue/task", "enqueue task"),
    ("/v2/snapshot/save", "save snapshot"),
    ("/v2/snapshot/remove", "remove snapshot"),
    ("/v2/snapshot/restore", "restore snapshot"),
    ("/v2/manager/reboot", "reboot server"),
    ("/v2/comfyui_manager/comfyui_switch_version", "switch ComfyUI version"),
    ("/v2/customnode/import_fail_info", "import fail info"),
    ("/v2/customnode/import_fail_info_bulk", "bulk import fail info"),
]


class TestStateChangingEndpointsRejectGet:
    """Every state-changing endpoint MUST reject HTTP GET.

    This is the narrow CSRF-mitigation contract established by the
    GET→POST conversion (commit 99caef55). It blocks <img>-tag,
    link-click, and redirect-based cross-origin triggers. Full origin
    verification is a separate layer and is NOT tested here.
    """

    @pytest.mark.parametrize(
        "path,description",
        STATE_CHANGING_POST_ENDPOINTS,
        ids=[p for p, _ in STATE_CHANGING_POST_ENDPOINTS],
    )
    def test_get_is_rejected(self, comfyui, path, description):
        resp = requests.get(
            f"{BASE_URL}{path}",
            timeout=10,
            allow_redirects=False,
        )
        # GET must NOT succeed with any 2xx or redirect status on a
        # state-changing endpoint. Prior assertion had a Python operator-
        # precedence bug (`A or (X is False)` → dead code). Use explicit
        # membership check instead.
        assert resp.status_code not in range(200, 400), (
            f"CSRF-CONTRACT BYPASS: GET {path} returned {resp.status_code} "
            f"(2xx/3xx indicates accept or redirect — endpoint must reject): "
            f"{description}"
        )
        # Narrow the accepted rejection statuses to method-not-allowed /
        # not-found / forbidden / bad-request. Other 4xx/5xx codes are
        # suspicious and should be investigated.
        assert resp.status_code in (400, 403, 404, 405), (
            f"GET {path} returned unexpected status {resp.status_code} "
            f"(expected 400/403/404/405): {resp.text[:200]}"
        )


class TestCsrfPostWorks:
    """Sanity check: the POST counterparts actually work (CSRF fix didn't break the API)."""

    def test_queue_reset_post_works(self, comfyui):
        """POST queue/reset should succeed (the same path rejects GET)."""
        resp = requests.post(f"{BASE_URL}/v2/manager/queue/reset", timeout=10)
        assert resp.status_code == 200, (
            f"POST queue/reset should succeed, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_snapshot_save_post_works(self, comfyui):
        """POST snapshot/save should succeed."""
        resp = requests.post(f"{BASE_URL}/v2/snapshot/save", timeout=30)
        assert resp.status_code == 200, (
            f"POST snapshot/save should succeed, got {resp.status_code}: {resp.text[:200]}"
        )
        # Cleanup — remove the snapshot we just created
        list_resp = requests.get(f"{BASE_URL}/v2/snapshot/getlist", timeout=10)
        if list_resp.ok:
            items = list_resp.json().get("items", [])
            if items:
                requests.post(
                    f"{BASE_URL}/v2/snapshot/remove",
                    params={"target": items[0]},
                    timeout=10,
                )


class TestCsrfReadEndpointsStillAllowGet:
    """Negative control: read-only endpoints should still allow GET.

    Ensures the CSRF fix didn't over-correct by making pure-read endpoints
    POST-only, which would break the UI.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "/v2/manager/version",
            "/v2/manager/db_mode",
            "/v2/manager/policy/update",
            "/v2/manager/channel_url_list",
            "/v2/manager/queue/status",
            "/v2/manager/queue/history_list",
            "/v2/manager/is_legacy_manager_ui",
            "/v2/customnode/installed",
            "/v2/snapshot/getlist",
            "/v2/snapshot/get_current",
            "/v2/comfyui_manager/comfyui_versions",
        ],
    )
    def test_get_read_endpoint_succeeds(self, comfyui, path):
        resp = requests.get(f"{BASE_URL}{path}", timeout=10)
        assert resp.status_code == 200, (
            f"Read endpoint GET {path} should succeed, got {resp.status_code}: "
            f"{resp.text[:200]}"
        )


# ---------------------------------------------------------------------------
# Content-Type gate — second CSRF mitigation layer
# ---------------------------------------------------------------------------
#
# GET→POST conversion alone does NOT block <form method=POST> from a malicious
# cross-origin page, because browsers mark form submissions with one of three
# CORS "simple request" Content-Types (Fetch spec §3.2.3) and do NOT preflight
# them. These 9 high-risk state mutation endpoints therefore additionally
# reject those three MIME types at the handler entry. Bare POST (no body) and
# application/json remain accepted — same-origin fetch() and existing
# manager-core JS callers are unaffected.
#
# Source of truth for the gated handler list:
# comfyui_manager/common/manager_security.py :: reject_simple_form_post
# comfyui_manager/glob/manager_server.py     :: 9 handlers call it
FORM_REJECTED_POST_ENDPOINTS = [
    "/v2/manager/queue/update_all",
    "/v2/snapshot/remove",
    "/v2/snapshot/restore",
    "/v2/snapshot/save",
    "/v2/manager/queue/reset",
    "/v2/manager/queue/start",
    "/v2/manager/queue/update_comfyui",
    # "/v2/comfyui_manager/comfyui_switch_version"  — removed in WI #258:
    # migrated from query-string to JSON body, now a body-reading handler.
    # Per the module policy in common/manager_security.py, body-reading
    # handlers are NOT gated (CORS preflight on application/json already
    # blocks cross-origin form POST forgery).
    "/v2/manager/reboot",
]

SIMPLE_FORM_CONTENT_TYPES = [
    "application/x-www-form-urlencoded",
    "multipart/form-data; boundary=----WebKitFormBoundaryTest",
    "text/plain",
]


class TestFormContentTypeRejected:
    """Every gated state-changing endpoint MUST reject CORS simple-request
    Content-Types to block preflight-less <form method=POST> CSRF.

    Matrix: 9 endpoints × 3 Content-Types = 27 assertions.
    """

    @pytest.mark.parametrize(
        "content_type",
        SIMPLE_FORM_CONTENT_TYPES,
        ids=["urlencoded", "multipart", "textplain"],
    )
    @pytest.mark.parametrize(
        "path",
        FORM_REJECTED_POST_ENDPOINTS,
        ids=FORM_REJECTED_POST_ENDPOINTS,
    )
    def test_form_content_type_rejected(self, comfyui, path, content_type):
        """POST with a simple-form Content-Type must be rejected with 400.

        The handler's Content-Type gate runs BEFORE the security_level check,
        so the expected status is 400 even under security levels that would
        otherwise return 403.
        """
        resp = requests.post(
            f"{BASE_URL}{path}",
            headers={"Content-Type": content_type},
            data="",  # empty body still counts: browsers would not preflight
            timeout=10,
        )
        assert resp.status_code == 400, (
            f"CSRF FORM-POST GATE BYPASS: POST {path} with "
            f"Content-Type={content_type!r} returned {resp.status_code} "
            f"(expected 400): {resp.text[:200]}"
        )


class TestNoBodyPostStillAccepted:
    """Positive control: bare POST (no body, no Content-Type) must still pass
    the form-content-type gate.

    The existing frontend (snapshot.js, comfyui-manager.js, etc.) issues
    fetch()/XHR POSTs without an explicit body for these idempotent-ish
    operations; a regression here would break those callers.
    """

    @pytest.mark.parametrize(
        "path",
        # Subset — pick endpoints whose happy path is deterministic under the
        # default E2E environment. queue/update_comfyui, snapshot/restore etc.
        # have side effects (spawn worker, stage restore file) or require
        # a specific security level that isn't guaranteed here.
        [
            "/v2/manager/queue/reset",
            "/v2/manager/queue/start",
            "/v2/snapshot/save",
        ],
        ids=["queue-reset", "queue-start", "snapshot-save"],
    )
    def test_no_body_post_still_accepted(self, comfyui, path):
        """Bare POST (no Content-Type, no body) must NOT be rejected by the
        form-content-type gate. Any response other than 400-with-form-text
        proves the gate did not fire."""
        resp = requests.post(f"{BASE_URL}{path}", timeout=30)
        # The gate returns 400 with a very specific text. Non-gate 400s
        # (validation errors, etc.) are allowed — we only assert the gate
        # itself didn't trigger.
        if resp.status_code == 400:
            assert "Invalid Content-Type for this endpoint" not in resp.text, (
                f"POST {path} (bare) hit the form-content-type gate: "
                f"{resp.text[:200]}"
            )
