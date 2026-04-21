"""E2E tests for ComfyUI Manager custom node information endpoints.

Tests the custom node information and mapping endpoints:
- GET  /v2/customnode/getmappings     — node-to-package mappings
- GET  /v2/customnode/fetch_updates   — update check (deprecated, 410)
- GET  /v2/customnode/installed       — installed packages dict
- POST /v2/customnode/import_fail_info      — single node failure info
- POST /v2/customnode/import_fail_info_bulk — bulk node failure info

Requires a pre-built E2E environment (from setup_e2e_env.sh).
Set E2E_ROOT env var to point at it, or the tests will be skipped.

Usage:
    E2E_ROOT=/tmp/e2e_full_test pytest tests/e2e/test_e2e_customnode_info.py -v
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
# Tests — getmappings
# ---------------------------------------------------------------------------

class TestCustomNodeMappings:
    """Test GET /v2/customnode/getmappings."""

    def test_getmappings_returns_dict(self, comfyui):
        """GET /v2/customnode/getmappings?mode=local returns non-empty mapping with valid per-entry schema.

        WI-M strengthening: previously only dict-type check. Now verifies
        content-level invariants: non-empty DB (the manager ships with the
        full custom-node mappings baked in), and every entry conforms to
        the documented `[node_list: list, metadata: dict]` shape on a
        random sample. Defeats a regression where the DB loader returns
        an empty `{}` (dict type PASS, zero-utility content).
        """
        resp = requests.get(
            f"{BASE_URL}/v2/customnode/getmappings",
            params={"mode": "local"},
            timeout=30,
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert isinstance(data, dict), (
            f"Expected dict response, got {type(data).__name__}"
        )
        # Content: at least 1 entry (E2E env ships the stock DB with thousands
        # of mappings; anything < 100 suggests DB load regression).
        assert len(data) >= 100, (
            f"getmappings returned only {len(data)} entries — DB load regression?"
        )
        # Structural sample: first 5 entries must conform to [node_list, metadata].
        for i, (key, entry) in enumerate(list(data.items())[:5]):
            assert isinstance(entry, list) and len(entry) >= 2, (
                f"Entry {i} ({key!r}) not [node_list, metadata]: {entry!r}"
            )
            assert isinstance(entry[0], list), (
                f"Entry {i} node_list is not a list: {type(entry[0]).__name__}"
            )
            assert isinstance(entry[1], dict), (
                f"Entry {i} metadata is not a dict: {type(entry[1]).__name__}"
            )


# ---------------------------------------------------------------------------
# Tests — fetch_updates (deprecated)
# ---------------------------------------------------------------------------

class TestFetchUpdates:
    """Test GET /v2/customnode/fetch_updates (deprecated endpoint)."""

    def test_fetch_updates_returns_deprecated(self, comfyui):
        """GET /v2/customnode/fetch_updates returns 410 Gone with deprecation notice."""
        resp = requests.get(
            f"{BASE_URL}/v2/customnode/fetch_updates",
            params={"mode": "local"},
            timeout=10,
        )
        assert resp.status_code == 410, (
            f"Expected 410 (Gone) for deprecated endpoint, got {resp.status_code}"
        )
        data = resp.json()
        assert data.get("deprecated") is True, (
            "Response should include 'deprecated: true'"
        )


# ---------------------------------------------------------------------------
# Tests — installed
# ---------------------------------------------------------------------------

class TestInstalledPacks:
    """Test GET /v2/customnode/installed."""

    def test_installed_returns_dict(self, comfyui):
        """GET /v2/customnode/installed returns dict containing seeded E2E pack with valid per-entry schema.

        WI-M strengthening: previously only dict-type check. The E2E setup
        seeds `ComfyUI_SigmoidOffsetScheduler` (the test package used across
        task_operations/endpoint tests); its presence is a hard precondition
        for most other tests. We now assert it's in the installed dict AND
        that its entry has the documented InstalledPack fields
        (cnr_id/ver/enabled). Defeats a regression where `installed` returns
        an empty dict despite packs existing on disk.
        """
        resp = requests.get(
            f"{BASE_URL}/v2/customnode/installed", timeout=10
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert isinstance(data, dict), (
            f"Expected dict response, got {type(data).__name__}"
        )
        # Content: E2E seed pack must be present.
        seed_pack = "ComfyUI_SigmoidOffsetScheduler"
        assert seed_pack in data, (
            f"Seeded E2E pack {seed_pack!r} missing from installed dict. "
            f"Keys: {list(data.keys())}"
        )
        # Schema: the seed pack's entry must carry the documented fields.
        entry = data[seed_pack]
        assert isinstance(entry, dict), (
            f"{seed_pack} entry should be a dict, got {type(entry).__name__}"
        )
        for required_key in ("cnr_id", "ver", "enabled"):
            assert required_key in entry, (
                f"{seed_pack} entry missing required key {required_key!r}: {entry!r}"
            )

    def test_installed_imported_mode(self, comfyui):
        """GET ?mode=imported returns the frozen startup snapshot with schema.

        WI-T Cluster G target 4 (research-cluster-g.md Strategy A):
          (a) status 200 + dict body (contract)
          (b) E2E seed pack `ComfyUI_SigmoidOffsetScheduler` is in the snapshot
          (c) each entry carries the documented InstalledPack schema —
              cnr_id / ver / enabled (aux_id is Optional)
          (d) frozen-at-startup invariant (cheap form) — no install has run
              since server start, so imported keys == default keys.

        Design intent (glob/manager_server.py:1510-1520): `imported` returns
        the module-level `startup_time_installed_node_packs` captured once at
        import; `default` re-scans the filesystem. At test time they must
        agree on keys. Divergence post-install is covered by the
        [E2E-DEBT] companion below.
        """
        # (a) Frozen snapshot
        resp_imp = requests.get(
            f"{BASE_URL}/v2/customnode/installed",
            params={"mode": "imported"},
            timeout=10,
        )
        assert resp_imp.status_code == 200, (
            f"Expected 200 for imported mode, got {resp_imp.status_code}"
        )
        imported = resp_imp.json()
        assert isinstance(imported, dict), (
            f"Expected dict response, got {type(imported).__name__}"
        )

        # (b) E2E seed pack must appear in the startup snapshot
        seed = "ComfyUI_SigmoidOffsetScheduler"
        assert seed in imported, (
            f"seed pack {seed!r} missing from imported snapshot; "
            f"keys={list(imported)}"
        )

        # (c) Schema: each entry carries cnr_id / ver / enabled
        entry = imported[seed]
        assert isinstance(entry, dict), (
            f"{seed} entry should be dict, got {type(entry).__name__}: {entry!r}"
        )
        for required in ("cnr_id", "ver", "enabled"):
            assert required in entry, (
                f"{seed} entry missing required field {required!r}: {entry!r}"
            )

        # (d) Frozen invariant (cheap form): no install has run since startup,
        # so imported keys must equal default keys at this point.
        resp_def = requests.get(
            f"{BASE_URL}/v2/customnode/installed", timeout=10,
        )
        assert resp_def.status_code == 200
        default = resp_def.json()
        assert set(imported.keys()) == set(default.keys()), (
            f"imported != default at startup (no install has run): "
            f"only-imported={set(imported) - set(default)}, "
            f"only-default={set(default) - set(imported)}"
        )

    # WI-OO Item 4 (bloat reviewer:ci-013 B7 stale-skip): removed
    # `test_imported_mode_is_frozen_after_install` — the body was a TODO stub
    # masked by a skip marker. With no install trigger between the two
    # imported-mode GETs, `snap_before == snap_after` held trivially; the test
    # could not prove the frozen-invariant it claimed. The E2E-DEBT for a true
    # mid-session install (Strategy B) remains — when revisited, add a fresh
    # test that actually exercises /v2/customnode/install or FS manipulation
    # between the two snapshots. Strategy A (cheap equality at startup) is
    # already covered by `test_installed_imported_mode` above.


# ---------------------------------------------------------------------------
# Tests — import_fail_info
# ---------------------------------------------------------------------------

class TestImportFailInfo:
    """Test POST /v2/customnode/import_fail_info."""

    def test_unknown_cnr_id_returns_400(self, comfyui):
        """POST with unknown cnr_id returns 400 (no failure info available)."""
        resp = requests.post(
            f"{BASE_URL}/v2/customnode/import_fail_info",
            json={"cnr_id": "nonexistent_pack_that_does_not_exist_12345"},
            timeout=10,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for unknown cnr_id, got {resp.status_code}"
        )

    def test_missing_fields_returns_400(self, comfyui):
        """POST without cnr_id or url returns 400."""
        resp = requests.post(
            f"{BASE_URL}/v2/customnode/import_fail_info",
            json={"invalid_field": "value"},
            timeout=10,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for missing fields, got {resp.status_code}"
        )

    def test_invalid_body_returns_error(self, comfyui):
        """POST with non-dict body returns 400."""
        resp = requests.post(
            f"{BASE_URL}/v2/customnode/import_fail_info",
            json="not-a-dict",
            timeout=10,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for non-dict body, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Tests — import_fail_info_bulk
# ---------------------------------------------------------------------------

class TestImportFailInfoBulk:
    """Test POST /v2/customnode/import_fail_info_bulk."""

    def test_bulk_with_cnr_ids_returns_dict(self, comfyui):
        """POST with cnr_ids list returns 200 with results dict."""
        resp = requests.post(
            f"{BASE_URL}/v2/customnode/import_fail_info_bulk",
            json={"cnr_ids": ["nonexistent_pack_12345"]},
            timeout=30,
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert isinstance(data, dict), (
            f"Expected dict response, got {type(data).__name__}"
        )
        # Unknown pack should have null value (no error info)
        assert "nonexistent_pack_12345" in data, (
            "Response should contain entry for requested cnr_id"
        )
        assert data["nonexistent_pack_12345"] is None, (
            "Unknown pack should map to null (no import failure info)"
        )

    def test_bulk_empty_lists_returns_400(self, comfyui):
        """POST with empty cnr_ids and no urls returns 400."""
        resp = requests.post(
            f"{BASE_URL}/v2/customnode/import_fail_info_bulk",
            json={"cnr_ids": [], "urls": []},
            timeout=10,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for empty lists, got {resp.status_code}"
        )

    def test_bulk_with_urls_returns_dict(self, comfyui):
        """POST with urls list returns 200 + per-url result of None (unknown) or dict (found).

        WI-M strengthening: previously only dict-type check. Now verifies
        per-url result correctness: each requested URL MUST appear as a key,
        and the value is either `None` (unknown URL — expected for the fake
        URL we send) or a `dict` (populated fail-info). Anything else
        (e.g. a bare string, a list, or missing-key) is a schema violation.
        """
        fake_url = "https://github.com/nonexistent/nonexistent-node-pack"
        resp = requests.post(
            f"{BASE_URL}/v2/customnode/import_fail_info_bulk",
            json={"urls": [fake_url]},
            timeout=30,
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert isinstance(data, dict), (
            f"Expected dict response, got {type(data).__name__}"
        )
        # Content: the URL we queried must be a key in the response.
        assert fake_url in data, (
            f"Requested URL missing from bulk response. Expected key {fake_url!r}, "
            f"got keys: {list(data.keys())}"
        )
        # Per-URL value must be None (unknown, expected here) or dict (populated).
        result = data[fake_url]
        assert result is None or isinstance(result, dict), (
            f"bulk[{fake_url!r}] must be None or dict, got {type(result).__name__}: {result!r}"
        )
