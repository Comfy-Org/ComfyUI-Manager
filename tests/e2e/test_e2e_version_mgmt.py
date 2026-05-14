"""E2E tests for ComfyUI Manager version management endpoints.

Exercises the version management endpoints on a running ComfyUI instance:
  - GET  /v2/comfyui_manager/comfyui_versions         — list versions + current
  - POST /v2/comfyui_manager/comfyui_switch_version    — switch version (negative tests only)

Scenario:
  List versions → verify response has 'versions' array and 'current'
  string. For switch_version: test missing params returns 400 (actual
  version switching is destructive and NOT tested here).

Requires a pre-built E2E environment (from setup_e2e_env.sh).
Set E2E_ROOT env var to point at it, or the tests will be skipped.

Usage:
    E2E_ROOT=/tmp/e2e_full_test pytest tests/e2e/test_e2e_version_mgmt.py -v
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
    reason="E2E_ROOT not set or E2E environment not ready (run setup_e2e_env.sh first)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_comfyui() -> int:
    """Start ComfyUI and return its PID."""
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
    raise RuntimeError(f"Could not parse PID from start_comfyui output:\n{r.stdout}")


def _stop_comfyui():
    """Stop ComfyUI."""
    env = {**os.environ, "E2E_ROOT": E2E_ROOT, "PORT": str(PORT)}
    subprocess.run(
        ["bash", os.path.join(SCRIPTS_DIR, "stop_comfyui.sh")],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def comfyui():
    """Start ComfyUI once for the module, stop after all tests."""
    pid = _start_comfyui()
    yield pid
    _stop_comfyui()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestComfyUIVersions:
    """Verify /v2/comfyui_manager/comfyui_versions response structure."""

    def test_versions_response_contract(self, comfyui):
        """GET /v2/comfyui_manager/comfyui_versions — full response contract.

        Merged by WI-NN (bloat Priority 3, Cluster 7): absorbs the four previous
        single-GET tests (test_versions_endpoint + test_versions_list_not_empty +
        test_versions_items_are_strings + test_current_is_in_versions) into one
        contract block. All 4 original tests hit the same endpoint; merging
        removes 3 redundant round-trips and keeps every unique assertion.
        """
        resp = requests.get(
            f"{BASE_URL}/v2/comfyui_manager/comfyui_versions", timeout=10
        )
        # (a) status + top-level schema (was test_versions_endpoint)
        assert resp.status_code == 200, (
            f"comfyui_versions failed with status {resp.status_code}"
        )
        data = resp.json()
        assert "versions" in data, "Response missing 'versions' field"
        assert "current" in data, "Response missing 'current' field"
        assert isinstance(data["versions"], list), (
            f"'versions' should be a list, got {type(data['versions'])}"
        )
        assert isinstance(data["current"], str), (
            f"'current' should be a string, got {type(data['current'])}"
        )

        # (b) versions list is non-empty (was test_versions_list_not_empty)
        assert len(data["versions"]) > 0, (
            "Expected at least one version in the list"
        )

        # (c) every entry is a string (was test_versions_items_are_strings)
        for v in data["versions"]:
            assert isinstance(v, str), (
                f"Version entry should be a string, got {type(v)}: {v}"
            )

        # (d) current appears in versions list (was test_current_is_in_versions).
        # Keep the "empty current" guard — handler emits "" if git state can't
        # resolve a tag, which is non-ideal but not a contract violation.
        if data["current"] and data["versions"]:
            assert data["current"] in data["versions"], (
                f"Current version '{data['current']}' not found in versions list"
            )


class TestSwitchVersionNegative:
    """Negative tests for /v2/comfyui_manager/comfyui_switch_version.

    Actual version switching is destructive and NOT exercised.
    Only error paths (missing params, validation failures) are tested.
    """

    @pytest.mark.parametrize(
        "req_params",
        [
            pytest.param(None, id="no-params"),
            pytest.param({"ver": "v1.0.0"}, id="partial-params-ver-only"),
        ],
    )
    def test_switch_version_missing_required_params_rejected(self, comfyui, req_params):
        """POST without full (ver, client_id, ui_id) must be rejected.

        WI-OO Item 5 (bloat dbg:ci-018 B9+B1): merges the previously-separate
        `missing_all_params` and `missing_client_id` tests. At the default
        security_level=normal the high+ gate returns 403 BEFORE any param
        validation runs, so both fully-empty and partial-param requests
        exercise the same rejection path. Parametrized across both input
        equivalence classes — keeps both inputs exercised as distinct
        pytest invocations for diagnostics, without duplicating the body.

        WI #258: Migrated from query-string (params=) to JSON body (json=).
        When req_params is None we send no body at all (bare POST).
        """
        url = f"{BASE_URL}/v2/comfyui_manager/comfyui_switch_version"
        if req_params is None:
            resp = requests.post(url, timeout=10)
        else:
            resp = requests.post(url, json=req_params, timeout=10)
        assert resp.status_code in (400, 403), (
            f"Expected 400 or 403 for missing/partial params "
            f"(req_params={req_params!r}), got {resp.status_code}"
        )

    def test_switch_version_validation_error_body(self, comfyui):
        """Validation error (400) returns structured Pydantic error body.

        WI-L strengthening: previously accepted 'error field present OR plain
        text'. The contract is stricter — the ValidationError path emits
        exactly:
          {"error": "Validation error", "details": [<pydantic error entries>]}
        We now assert the full schema: the `error` sentinel string, the
        `details` list, and that each detail entry carries the Pydantic
        triplet (loc / msg / type). This defeats a regression where the server
        falls through to the generic `except Exception` branch (which returns
        status=400 with an EMPTY body — would currently still pass old check).

        WI #258: Send a well-formed JSON body with required fields missing
        to reach the Pydantic validator (not the json.JSONDecodeError branch,
        which produces a plain-text 400). An empty JSON object {} fails the
        required-field check for `ver`/`client_id`/`ui_id` uniformly.
        """
        resp = requests.post(
            f"{BASE_URL}/v2/comfyui_manager/comfyui_switch_version",
            json={},
            timeout=10,
        )
        if resp.status_code == 403:
            pytest.skip(
                "Server security level blocks switch_version with 403 before "
                "validation runs; validation-error-body contract not reachable"
            )
        assert resp.status_code == 400, (
            f"Expected 400 validation error, got {resp.status_code}: {resp.text[:200]}"
        )
        # Pydantic validation returns JSON with 'error' + 'details' list.
        try:
            data = resp.json()
        except requests.exceptions.JSONDecodeError:
            pytest.fail(
                f"400 response should be JSON but got plain text: {resp.text[:200]}"
            )
        assert "error" in data, (
            f"400 response must include 'error' field, got: {data!r}"
        )
        assert data["error"] == "Validation error", (
            f"'error' field must be the exact 'Validation error' sentinel, got {data['error']!r}"
        )
        assert "details" in data, (
            f"400 response must include 'details' list, got: {data!r}"
        )
        details = data["details"]
        assert isinstance(details, list), (
            f"'details' must be a list, got {type(details).__name__}"
        )
        assert len(details) >= 1, (
            "'details' must contain at least one Pydantic error entry, got empty list"
        )
        # Each entry is a Pydantic error dict with canonical keys.
        for i, entry in enumerate(details):
            assert isinstance(entry, dict), (
                f"details[{i}] must be a dict, got {type(entry).__name__}"
            )
            for required_key in ("loc", "msg", "type"):
                assert required_key in entry, (
                    f"details[{i}] missing Pydantic key {required_key!r}: {entry!r}"
                )
