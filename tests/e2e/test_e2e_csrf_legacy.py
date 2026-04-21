"""E2E tests for the GET-rejection contract on legacy-mode state-changing endpoints.

SCOPE — important clarification:
This suite is the LEGACY-MODE counterpart to test_e2e_csrf.py. It verifies the
same CSRF mitigation contract — that state-changing endpoints reject HTTP GET —
but against the legacy manager_server module loaded via --enable-manager-legacy-ui.

Why a separate file:
comfyui_manager/__init__.py loads `glob.manager_server` XOR `legacy.manager_server`
(mutex via args.enable_manager_legacy_ui). So a single ComfyUI process exposes
either the glob route table or the legacy route table, never both. Verifying
legacy CSRF mitigation requires its own server lifecycle with the legacy flag
set, which is incompatible with the module-scoped glob fixture in test_e2e_csrf.py.

Coverage gap closed by this file:
Commit 99caef55 ("fix(security): mitigate CSRF on state-changing endpoints")
applied the GET→POST conversion to BOTH glob/manager_server.py (91 line diff)
and legacy/manager_server.py (92 line diff). However, test_e2e_csrf.py only
exercises glob mode (start_comfyui.sh uses --enable-manager without
--enable-manager-legacy-ui). Without this file, anyone reverting a legacy
@routes.post back to @routes.get would not be caught by CI.

Endpoint list — derived empirically from the working tree (NOT statically from
the 99caef55 diff), because subsequent legacy refactoring removed several
endpoints that were initially in scope (e.g., queue/abort_current). The list
mirrors test_e2e_csrf.py's STATE_CHANGING_POST_ENDPOINTS for parity, with three
adjustments:
  - Drop /v2/manager/queue/task    (glob-only; legacy uses queue/batch instead)
  - Add  /v2/manager/queue/batch   (legacy task enqueue, mirrors queue/task role)
  - Drop /v2/manager/db_mode, /v2/manager/policy/update, /v2/manager/channel_url_list
    from REJECT-GET. These are split into @routes.get (read) + @routes.post
    (write) in BOTH glob and legacy. The CSRF mitigation contract applies only
    to the POST half — GET legitimately serves the current value. They remain
    in the ALLOW-GET list below. (test_e2e_csrf.py erroneously includes them in
    both lists, so the equivalent assertions fail there too — see follow-up note
    in WI-FF completion_report.)

Legacy-parity additions (WI-JJ):
  - /v2/customnode/install/git_url, /v2/customnode/install/pip — legacy-only
    install endpoints. Added to LEGACY_STATE_CHANGING_POST_ENDPOINTS for
    GET-rejection coverage; happy-path install E2E remains out of scope.
  - /v2/manager/is_legacy_manager_ui legacy-side flag value asserted True via
    TestLegacyIsLegacyManagerUIReturnsTrue — symmetric to the glob-side
    False assertion in test_e2e_system_info.py::test_returns_boolean_field.

NOT COVERED by this suite (same caveats as test_e2e_csrf.py):
- Origin / Referer header validation
- Same-site cookie enforcement
- Anti-CSRF token verification
- Cross-site form POST defense

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
# Helpers — start_comfyui_legacy.sh wrapper sets ENABLE_LEGACY_UI=1 which
# translates to --enable-manager-legacy-ui inside start_comfyui.sh.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# State-changing legacy endpoints that MUST reject GET per CSRF mitigation contract
# ---------------------------------------------------------------------------

# (path, description) — mirrors test_e2e_csrf.py STATE_CHANGING_POST_ENDPOINTS,
# with queue/task replaced by queue/batch (legacy task-enqueue equivalent).
LEGACY_STATE_CHANGING_POST_ENDPOINTS = [
    ("/v2/manager/queue/start", "start worker"),
    ("/v2/manager/queue/reset", "reset queue"),
    ("/v2/manager/queue/update_all", "update all packs"),
    ("/v2/manager/queue/update_comfyui", "update ComfyUI core"),
    ("/v2/manager/queue/install_model", "queue model download"),
    ("/v2/manager/queue/batch", "enqueue task batch (legacy)"),
    ("/v2/snapshot/save", "save snapshot"),
    ("/v2/snapshot/remove", "remove snapshot"),
    ("/v2/snapshot/restore", "restore snapshot"),
    ("/v2/manager/reboot", "reboot server"),
    ("/v2/comfyui_manager/comfyui_switch_version", "switch ComfyUI version"),
    # NOTE: db_mode, policy/update, channel_url_list have a legitimate GET handler
    # for reading the current value; only POST mutates state. Verified separately
    # in TestLegacyCsrfReadEndpointsStillAllowGet below.
    ("/v2/customnode/import_fail_info", "import fail info"),
    ("/v2/customnode/import_fail_info_bulk", "bulk import fail info"),
    # Legacy-only install endpoints (no glob counterpart). Added in WI-JJ to
    # extend CSRF GET-rejection coverage — these are state-changing (they
    # enqueue install tasks) and must not be triggerable via <img>/link.
    ("/v2/customnode/install/git_url", "install custom node by git URL (legacy-only)"),
    ("/v2/customnode/install/pip", "install pip package for custom node (legacy-only)"),
]


class TestLegacyStateChangingEndpointsRejectGet:
    """Every legacy state-changing endpoint MUST reject HTTP GET.

    Verifies the CSRF-mitigation contract on the legacy server module
    under --enable-manager-legacy-ui. Mirrors the glob-side test in
    test_e2e_csrf.py::TestStateChangingEndpointsRejectGet.
    """

    @pytest.mark.parametrize(
        "path,description",
        LEGACY_STATE_CHANGING_POST_ENDPOINTS,
        ids=[p for p, _ in LEGACY_STATE_CHANGING_POST_ENDPOINTS],
    )
    def test_get_is_rejected(self, comfyui_legacy, path, description):
        resp = requests.get(
            f"{BASE_URL}{path}",
            timeout=10,
            allow_redirects=False,
        )
        assert resp.status_code not in range(200, 400), (
            f"CSRF-CONTRACT BYPASS (legacy): GET {path} returned "
            f"{resp.status_code} (2xx/3xx indicates accept or redirect — "
            f"endpoint must reject): {description}"
        )
        assert resp.status_code in (400, 403, 404, 405), (
            f"GET {path} returned unexpected status {resp.status_code} "
            f"(expected 400/403/404/405): {resp.text[:200]}"
        )


class TestLegacyCsrfPostWorks:
    """Sanity check: the legacy POST counterparts actually work."""

    def test_queue_reset_post_works(self, comfyui_legacy):
        """POST queue/reset should succeed (the same path rejects GET)."""
        resp = requests.post(f"{BASE_URL}/v2/manager/queue/reset", timeout=10)
        assert resp.status_code == 200, (
            f"POST queue/reset should succeed, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_snapshot_save_post_works(self, comfyui_legacy):
        """POST snapshot/save should succeed on legacy."""
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


class TestLegacyCsrfReadEndpointsStillAllowGet:
    """Negative control: read-only legacy endpoints should still allow GET.

    Ensures the CSRF fix didn't over-correct on legacy by making pure-read
    endpoints POST-only, which would break the legacy UI.
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
    def test_get_read_endpoint_succeeds(self, comfyui_legacy, path):
        resp = requests.get(f"{BASE_URL}{path}", timeout=10)
        assert resp.status_code == 200, (
            f"Legacy read endpoint GET {path} should succeed, got "
            f"{resp.status_code}: {resp.text[:200]}"
        )


class TestLegacyIsLegacyManagerUIReturnsTrue:
    """Legacy-mode parity for TestIsLegacyManagerUI in test_e2e_system_info.py.

    The glob-side test (`system_info.py::test_returns_boolean_field`) asserts
    the flag returns False under start_comfyui.sh (which omits
    --enable-manager-legacy-ui). This test asserts the symmetric contract:
    under start_comfyui_legacy.sh the handler must return True.

    Launcher-deterministic: `tests/e2e/scripts/start_comfyui_legacy.sh` sets
    ENABLE_LEGACY_UI=1, which start_comfyui.sh translates to
    --enable-manager-legacy-ui. `action='store_true'` makes the flag True,
    so the handler at legacy/manager_server.py:995-999 must return
    `{"is_legacy_manager_ui": True}`.

    Without this assertion, a regression that silently drops the CLI flag
    (e.g., mis-edited MANAGER_FLAGS in start_comfyui.sh) would leave the
    legacy route table in place while the flag-value response reverted to
    False — breaking UI mode detection for any frontend code that keys off
    this endpoint.
    """

    def test_returns_true_under_legacy_mode(self, comfyui_legacy):
        resp = requests.get(
            f"{BASE_URL}/v2/manager/is_legacy_manager_ui", timeout=10
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}"
        )
        data = resp.json()
        assert "is_legacy_manager_ui" in data, (
            f"Response missing 'is_legacy_manager_ui' field: {data}"
        )
        assert data["is_legacy_manager_ui"] is True, (
            f"Legacy launcher sets --enable-manager-legacy-ui; expected True, "
            f"got {data['is_legacy_manager_ui']!r}. "
            f"If start_comfyui_legacy.sh stopped propagating ENABLE_LEGACY_UI=1, "
            f"fix the wrapper rather than relaxing this assertion."
        )


# ---------------------------------------------------------------------------
# Content-Type gate — legacy-side parity with test_e2e_csrf.py
# ---------------------------------------------------------------------------
#
# The 9 legacy handlers mirrored from glob each call
# manager_security.reject_simple_form_post() before their security-level
# check. This suite verifies the legacy route table enforces the same
# CORS-simple-request Content-Type rejection contract.
LEGACY_FORM_REJECTED_POST_ENDPOINTS = [
    "/v2/manager/queue/update_all",
    "/v2/snapshot/remove",
    "/v2/snapshot/restore",
    "/v2/snapshot/save",
    "/v2/manager/queue/reset",
    "/v2/manager/queue/start",
    "/v2/manager/queue/update_comfyui",
    # "/v2/comfyui_manager/comfyui_switch_version"  — removed in WI #258:
    # migrated from query-string to JSON body on legacy + glob in parallel,
    # body-reading handler is not Content-Type-gated (see module policy in
    # common/manager_security.py).
    "/v2/manager/reboot",
]

LEGACY_SIMPLE_FORM_CONTENT_TYPES = [
    "application/x-www-form-urlencoded",
    "multipart/form-data; boundary=----WebKitFormBoundaryTest",
    "text/plain",
]


class TestLegacyFormContentTypeRejected:
    """Legacy counterpart to TestFormContentTypeRejected in test_e2e_csrf.py.

    Matrix: 9 endpoints × 3 Content-Types = 27 assertions against the legacy
    route table.
    """

    @pytest.mark.parametrize(
        "content_type",
        LEGACY_SIMPLE_FORM_CONTENT_TYPES,
        ids=["urlencoded", "multipart", "textplain"],
    )
    @pytest.mark.parametrize(
        "path",
        LEGACY_FORM_REJECTED_POST_ENDPOINTS,
        ids=LEGACY_FORM_REJECTED_POST_ENDPOINTS,
    )
    def test_form_content_type_rejected(
        self, comfyui_legacy, path, content_type
    ):
        """POST with a simple-form Content-Type must be rejected with 400
        on the legacy route table as well."""
        resp = requests.post(
            f"{BASE_URL}{path}",
            headers={"Content-Type": content_type},
            data="",
            timeout=10,
        )
        assert resp.status_code == 400, (
            f"CSRF FORM-POST GATE BYPASS (legacy): POST {path} with "
            f"Content-Type={content_type!r} returned {resp.status_code} "
            f"(expected 400): {resp.text[:200]}"
        )


class TestLegacyNoBodyPostStillAccepted:
    """Positive control for the legacy route table: bare POST still works."""

    @pytest.mark.parametrize(
        "path",
        [
            "/v2/manager/queue/reset",
            "/v2/manager/queue/start",
            "/v2/snapshot/save",
        ],
        ids=["queue-reset", "queue-start", "snapshot-save"],
    )
    def test_no_body_post_still_accepted(self, comfyui_legacy, path):
        """Bare POST (no Content-Type, no body) must not hit the gate on
        legacy either."""
        resp = requests.post(f"{BASE_URL}{path}", timeout=30)
        if resp.status_code == 400:
            assert "Invalid Content-Type for this endpoint" not in resp.text, (
                f"POST {path} (bare, legacy) hit the form-content-type gate: "
                f"{resp.text[:200]}"
            )


class TestLegacySetChannelUrlRejectsInvalid:
    """Legacy set_channel_url must reject unknown channel names with 400
    (MAJOR fix — previously silently returned 200).

    Parity with glob set_channel_url and with set_db_mode /
    set_update_policy whitelist enforcement.
    """

    def test_invalid_channel_returns_400(self, comfyui_legacy):
        resp = requests.post(
            f"{BASE_URL}/v2/manager/channel_url_list",
            json={"value": "definitely-not-a-real-channel"},
            timeout=10,
        )
        assert resp.status_code == 400, (
            f"Legacy set_channel_url accepted unknown channel silently: "
            f"status={resp.status_code}, body={resp.text[:300]}"
        )
        assert "Invalid channel name" in resp.text, (
            f"Expected 'Invalid channel name' in rejection text; got: "
            f"{resp.text[:300]}"
        )
