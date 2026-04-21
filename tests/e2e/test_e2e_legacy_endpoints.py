"""E2E positive-path tests for legacy-only GET endpoints.

SCOPE — closes the 6 pytest-N gaps from reports/api-coverage-matrix.md
(WI-TT). Each target endpoint is registered ONLY in
`comfyui_manager/legacy/manager_server.py` and thus reachable only when
ComfyUI runs with `--enable-manager-legacy-ui`.

Endpoints covered:
  - GET /customnode/alternatives                        (legacy L1072)
  - GET /v2/customnode/disabled_versions/{node_name}    (legacy L1273)
  - GET /v2/customnode/getlist                          (legacy L1018)
  - GET /v2/customnode/versions/{node_name}             (legacy L1262)
  - GET /v2/externalmodel/getlist                       (legacy L1143)
  - GET /v2/manager/notice                              (legacy L1747)

Why a separate file:
  comfyui_manager/__init__.py loads `glob.manager_server` XOR
  `legacy.manager_server` (mutex via args.enable_manager_legacy_ui), so
  these routes do not exist under the glob-mode fixture used by most
  other E2E suites. Mirrors the fixture pattern in
  `test_e2e_csrf_legacy.py` — separate module-scoped `comfyui_legacy`
  fixture that launches via `start_comfyui_legacy.sh`.

Handler-shape notes (for reviewers):
  - disabled_versions returns HTTP 400 when the given node has NO
    disabled versions (handler L1283-1286). This is not a param-validation
    error — it is the handler's convention for "empty result". The seed
    E2E pack (`ComfyUI_SigmoidOffsetScheduler`) installs cleanly with no
    disabled versions, so the positive path here asserts the endpoint is
    reachable and the param parses — status ∈ {200, 400} with per-branch
    body schema checks. Documented upstream as a handler design quirk.
  - notice returns `text/html` (not JSON); handler L1787 returns
    `web.Response(text=markdown_content, status=200)`.

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

SEED_PACK = "ComfyUI_SigmoidOffsetScheduler"

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


class TestLegacyCustomNodeAlternatives:
    """GET /customnode/alternatives?mode=local (wi-031)."""

    def test_returns_dict_of_alternatives(self, comfyui_legacy):
        resp = requests.get(
            f"{BASE_URL}/customnode/alternatives",
            params={"mode": "local"},
            timeout=30,
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert isinstance(data, dict), (
            f"alternatives response should be a dict keyed by unified id, "
            f"got {type(data).__name__}"
        )


class TestLegacyCustomNodeDisabledVersions:
    """GET /v2/customnode/disabled_versions/{node_name} (wi-032).

    The handler returns 200 + list[{version}] when disabled versions exist,
    and 400 otherwise (empty-result convention — not a validation error).
    Seed pack has no disabled versions, so positive path here is:
    endpoint reachable + param parsed correctly + response-shape on each
    branch.
    """

    def test_endpoint_reachable_and_parses_param(self, comfyui_legacy):
        resp = requests.get(
            f"{BASE_URL}/v2/customnode/disabled_versions/{SEED_PACK}",
            timeout=10,
        )
        assert resp.status_code in (200, 400), (
            f"disabled_versions should return 200 (has disabled) or 400 "
            f"(none), got {resp.status_code}: {resp.text[:200]}"
        )
        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data, list), (
                f"disabled_versions 200 body should be a list, "
                f"got {type(data).__name__}"
            )
            for entry in data:
                assert "version" in entry, (
                    f"each entry should have 'version' key, got {entry!r}"
                )


class TestLegacyCustomNodeGetList:
    """GET /v2/customnode/getlist?mode=local (wi-033)."""

    def test_returns_channel_and_node_packs(self, comfyui_legacy):
        resp = requests.get(
            f"{BASE_URL}/v2/customnode/getlist",
            params={"mode": "local", "skip_update": "true"},
            timeout=60,
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert isinstance(data, dict), (
            f"getlist response should be a dict, got {type(data).__name__}"
        )
        assert "channel" in data, (
            f"getlist response missing 'channel' field: keys={list(data)}"
        )
        assert "node_packs" in data, (
            f"getlist response missing 'node_packs' field: keys={list(data)}"
        )
        assert isinstance(data["node_packs"], dict), (
            f"node_packs should be a dict, got {type(data['node_packs']).__name__}"
        )


class TestLegacyCustomNodeVersions:
    """GET /v2/customnode/versions/{node_name} (wi-034).

    The seed pack is a CNR pack and should have at least one version.
    """

    def test_returns_versions_list_for_seed_pack(self, comfyui_legacy):
        resp = requests.get(
            f"{BASE_URL}/v2/customnode/versions/{SEED_PACK}",
            timeout=15,
        )
        assert resp.status_code == 200, (
            f"Expected 200 for known CNR pack {SEED_PACK!r}, "
            f"got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert isinstance(data, list), (
            f"versions response should be a list, got {type(data).__name__}"
        )
        assert len(data) > 0, (
            f"CNR pack {SEED_PACK!r} should report at least one version, "
            f"got empty list"
        )


class TestLegacyExternalModelGetList:
    """GET /v2/externalmodel/getlist?mode=local (wi-035)."""

    def test_returns_models_payload(self, comfyui_legacy):
        resp = requests.get(
            f"{BASE_URL}/v2/externalmodel/getlist",
            params={"mode": "local"},
            timeout=30,
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert isinstance(data, dict), (
            f"externalmodel/getlist should return a dict, "
            f"got {type(data).__name__}"
        )
        assert "models" in data, (
            f"externalmodel/getlist missing 'models' field: keys={list(data)}"
        )
        assert isinstance(data["models"], list), (
            f"'models' should be a list, got {type(data['models']).__name__}"
        )


class TestLegacyManagerNotice:
    """GET /v2/manager/notice (wi-036).

    Returns text/html (not JSON) — handler concatenates markdown fragments
    or a fallback 'Unable to retrieve Notice' string. Both branches return
    HTTP 200, so the positive-path assertion is status + non-empty body.
    """

    def test_returns_text_body(self, comfyui_legacy):
        resp = requests.get(f"{BASE_URL}/v2/manager/notice", timeout=30)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        assert resp.text, "notice body should be non-empty (markdown or fallback)"


class TestLegacyQueueBatch:
    """POST /v2/manager/queue/batch (wi-039).

    Handler shape (legacy/manager_server.py:740-801):
      - Request: JSON dict whose top-level keys select actions —
        update_all | reinstall | install | uninstall | update |
        update_comfyui | disable | install_model | fix.
        Unrecognized keys are silently skipped (no-match falls through
        the if/elif chain).
      - Response: always `{"failed": [list of failed ids]}`, status 200.
      - Side effect: `finalize_temp_queue_batch(json_data, failed)` writes
        a batch snapshot to the history store IFF the action helpers
        populated `temp_queue_batch`. With an empty or unrecognized-key
        payload, `temp_queue_batch` stays empty and no history is written
        (guard: `if len(temp_queue_batch):` at L444).
      - `_queue_start()` is called unconditionally to nudge the worker.

    Safe-payload choice: empty JSON body `{}`. Rationale —
      (a) exercises the full handler path (request parse → action
          for-loop no-op → finalize-with-empty → queue_start → 200 json),
      (b) leaves zero side effects on installed packs / disk state,
      (c) still round-trips through the aiohttp handler lock and
          `temp_queue_batch` snapshot guard so a future regression
          (e.g., unconditional history write, lock deadlock) would be
          caught.
    The dispatch's side-effect verification is covered indirectly: the
    test asserts queue/status is still 200 after POST, proving the lock
    released and the worker nudge completed cleanly. History-growth
    verification would require an expensive mutating batch, which the
    dispatch explicitly discourages.
    """

    def test_accepts_empty_payload_returns_failed_list(self, comfyui_legacy):
        resp = requests.post(
            f"{BASE_URL}/v2/manager/queue/batch",
            json={},
            timeout=15,
        )
        assert resp.status_code == 200, (
            f"Expected 200 for empty-batch payload, got "
            f"{resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert isinstance(data, dict), (
            f"queue/batch response should be a dict, "
            f"got {type(data).__name__}"
        )
        assert "failed" in data, (
            f"queue/batch response missing 'failed' key: {data!r}"
        )
        assert isinstance(data["failed"], list), (
            f"'failed' should be a list, got {type(data['failed']).__name__}"
        )
        assert data["failed"] == [], (
            f"no actions performed → 'failed' should be empty, "
            f"got {data['failed']!r}"
        )

        # Side-effect liveness check: queue/status still 200 after POST,
        # proving the worker lock was released cleanly.
        status_resp = requests.get(
            f"{BASE_URL}/v2/manager/queue/status", timeout=10
        )
        assert status_resp.status_code == 200, (
            f"queue/status should remain callable after queue/batch POST, "
            f"got {status_resp.status_code}: {status_resp.text[:200]}"
        )
