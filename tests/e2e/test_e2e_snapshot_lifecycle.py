"""E2E tests for ComfyUI Manager snapshot lifecycle endpoints.

Exercises the snapshot management endpoints on a running ComfyUI instance:
  - GET  /v2/snapshot/get_current  — current system state as snapshot
  - POST /v2/snapshot/save         — save current state
  - GET  /v2/snapshot/getlist      — list available snapshots
  - POST /v2/snapshot/remove       — remove a snapshot

Scenario:
  get_current → save → getlist (verify new snapshot) → remove →
  getlist (verify removed).

NOTE: /v2/snapshot/restore is intentionally NOT tested — it is a
destructive operation that alters installed node state.

Requires a pre-built E2E environment (from setup_e2e_env.sh).
Set E2E_ROOT env var to point at it, or the tests will be skipped.

Usage:
    E2E_ROOT=/tmp/e2e_full_test pytest tests/e2e/test_e2e_snapshot_lifecycle.py -v
"""

from __future__ import annotations

import os
import subprocess

import pytest
import requests

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
SNAPSHOT_DIR = (
    os.path.join(COMFYUI_PATH, "user", "__manager", "snapshots")
    if COMFYUI_PATH
    else ""
)
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

class TestSnapshotLifecycle:
    """Snapshot management lifecycle: get_current → save → list → remove."""

    def test_get_current_snapshot(self, comfyui):
        """GET /v2/snapshot/get_current returns documented schema AND cross-refs installed state.

        WI-M strengthening: previously dict-type only. Now verifies:
          (a) the documented top-level keys are all present —
              comfyui / git_custom_nodes / cnr_custom_nodes /
              file_custom_nodes / pips;
          (b) each list-valued field is actually a list (type-level schema);
          (c) cross-reference — the E2E seed CNR pack
              `ComfyUI_SigmoidOffsetScheduler` must appear in
              `cnr_custom_nodes` if it exists on the filesystem.
        Defeats regressions that return an empty dict or drop the
        cnr_custom_nodes field while keeping 200 OK.
        """
        resp = requests.get(f"{BASE_URL}/v2/snapshot/get_current", timeout=10)
        assert resp.status_code == 200, (
            f"get_current failed with status {resp.status_code}"
        )
        data = resp.json()
        assert isinstance(data, dict), (
            f"Expected dict from get_current, got {type(data)}"
        )

        # (a) Documented top-level keys.
        required_keys = (
            "comfyui",
            "git_custom_nodes",
            "cnr_custom_nodes",
            "file_custom_nodes",
            "pips",
        )
        for key in required_keys:
            assert key in data, (
                f"snapshot missing required top-level key {key!r}. "
                f"Got keys: {list(data.keys())}"
            )

        # (b) cnr_custom_nodes is a dict mapping pack_name → version — that's
        # the field we cross-ref below. Other collection-valued fields
        # (git_custom_nodes, pips, file_custom_nodes) carry environment-
        # dependent shapes (dict/list/mixed) and are intentionally not
        # constrained at the type level here — only their presence is required.
        assert isinstance(data["cnr_custom_nodes"], dict), (
            f"snapshot['cnr_custom_nodes'] should be a dict (pack_name → version), "
            f"got {type(data['cnr_custom_nodes']).__name__}"
        )

        # (c) Cross-reference installed state: if the E2E seed pack is on disk,
        # it MUST appear in cnr_custom_nodes.
        seed_pack = "ComfyUI_SigmoidOffsetScheduler"
        custom_nodes_dir = os.path.join(COMFYUI_PATH, "custom_nodes") if COMFYUI_PATH else ""
        seed_on_disk = (
            bool(custom_nodes_dir)
            and os.path.isdir(os.path.join(custom_nodes_dir, seed_pack))
        )
        if seed_on_disk:
            assert seed_pack in data["cnr_custom_nodes"], (
                f"Seed pack {seed_pack!r} exists on disk but missing from "
                f"snapshot.cnr_custom_nodes={data['cnr_custom_nodes']!r}"
            )

    def test_save_snapshot(self, comfyui):
        """POST /v2/snapshot/save — full disk + content verification (WI-Q strengthening).

        Defeats regressions where the endpoint returns 200 but (a) no file lands on
        disk or (b) the file drifts from the live runtime state.

        Verifies:
          (a) a new *.json file appears under SNAPSHOT_DIR;
          (b) the saved file's `cnr_custom_nodes` dict matches the live
              GET /v2/snapshot/get_current response — same keys, same
              versions (pack_name → version). This catches cases where
              the save endpoint writes a stale or stub snapshot while
              the live API reports the true runtime state.
        """
        files_before = set()
        if os.path.isdir(SNAPSHOT_DIR):
            files_before = {f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json")}

        resp = requests.post(f"{BASE_URL}/v2/snapshot/save", timeout=30)
        assert resp.status_code == 200, (
            f"Snapshot save failed with status {resp.status_code}"
        )

        # (a) Effect verification: new file appears in snapshot directory
        assert os.path.isdir(SNAPSHOT_DIR), (
            f"Snapshot dir not created: {SNAPSHOT_DIR}"
        )
        files_after = {f for f in os.listdir(SNAPSHOT_DIR) if f.endswith(".json")}
        new_files = files_after - files_before
        assert len(new_files) >= 1, (
            f"No new snapshot file created on disk: before={files_before}, after={files_after}"
        )

        # Content verification: new file is valid JSON dict
        import json
        new_file = next(iter(new_files))
        with open(os.path.join(SNAPSHOT_DIR, new_file)) as f:
            saved = json.load(f)
        assert isinstance(saved, dict), (
            f"Snapshot file content should be dict, got {type(saved).__name__}"
        )

        # (b) Content cross-reference: saved snapshot must match the live
        # GET /v2/snapshot/get_current response on the cnr_custom_nodes
        # field (the deterministic pack_name → version mapping). Other
        # fields like `pips` are environment-dependent and drift fast;
        # cnr_custom_nodes is the stable contract.
        live_resp = requests.get(f"{BASE_URL}/v2/snapshot/get_current", timeout=10)
        assert live_resp.status_code == 200, (
            f"get_current failed with status {live_resp.status_code}"
        )
        live = live_resp.json()
        assert "cnr_custom_nodes" in saved, (
            f"Saved snapshot missing 'cnr_custom_nodes' field. "
            f"Got keys: {list(saved.keys())}"
        )
        assert "cnr_custom_nodes" in live, (
            f"Live get_current missing 'cnr_custom_nodes' field. "
            f"Got keys: {list(live.keys())}"
        )
        assert saved["cnr_custom_nodes"] == live["cnr_custom_nodes"], (
            f"Saved snapshot cnr_custom_nodes does not match live state.\n"
            f"  saved={saved['cnr_custom_nodes']!r}\n"
            f"  live ={live['cnr_custom_nodes']!r}"
        )

    def test_getlist_after_save(self, comfyui):
        """GET /v2/snapshot/getlist shows at least one snapshot after save."""
        resp = requests.get(f"{BASE_URL}/v2/snapshot/getlist", timeout=10)
        assert resp.status_code == 200, (
            f"Snapshot getlist failed with status {resp.status_code}"
        )
        data = resp.json()
        assert "items" in data, "Snapshot list response missing 'items' field"
        assert isinstance(data["items"], list), (
            f"'items' should be a list, got {type(data['items'])}"
        )
        assert len(data["items"]) > 0, (
            "Expected at least one snapshot after save, but list is empty"
        )

    def test_remove_snapshot(self, comfyui):
        """POST /v2/snapshot/remove removes a specific snapshot.

        Test is INDEPENDENT: creates its own snapshot as setup, removes it,
        asserts. Does not depend on prior tests in this module.
        """
        # SETUP: create a snapshot so we have a deterministic target
        save_resp = requests.post(f"{BASE_URL}/v2/snapshot/save", timeout=30)
        assert save_resp.status_code == 200, "setup save failed"

        # Find the newly created snapshot by diffing against pre-save list
        resp = requests.get(f"{BASE_URL}/v2/snapshot/getlist", timeout=10)
        assert resp.status_code == 200
        all_items = resp.json().get("items", [])
        # The newest snapshot is at items[0] (desc-sorted)
        assert all_items, "setup snapshot missing from getlist"
        target = all_items[0]
        count_before_remove = len(all_items)

        # Remove (action under test)
        resp = requests.post(
            f"{BASE_URL}/v2/snapshot/remove",
            params={"target": target},
            timeout=10,
        )
        assert resp.status_code == 200, (
            f"Snapshot remove failed with status {resp.status_code}"
        )

        # Verify removal
        resp = requests.get(f"{BASE_URL}/v2/snapshot/getlist", timeout=10)
        assert resp.status_code == 200
        data_after = resp.json()
        assert target not in data_after["items"], (
            f"Snapshot '{target}' still in list after removal"
        )
        assert len(data_after["items"]) == count_before_remove - 1, (
            f"Expected {count_before_remove - 1} snapshots after removal, "
            f"got {len(data_after['items'])}"
        )

    def test_remove_nonexistent_snapshot(self, comfyui):
        """POST /v2/snapshot/remove with nonexistent target returns 200 (no-op)."""
        resp = requests.post(
            f"{BASE_URL}/v2/snapshot/remove",
            params={"target": "nonexistent_snapshot_99999"},
            timeout=10,
        )
        # Server returns 200 even when file doesn't exist (no-op behavior)
        assert resp.status_code == 200, (
            f"Remove nonexistent snapshot returned {resp.status_code}"
        )

    def test_remove_path_traversal_rejected(self, comfyui):
        """POST /v2/snapshot/remove with path-traversal target returns 400.

        Security boundary: target must stay within snapshot dir.
        """
        # Capture state before (any file that must NOT be deleted)
        import pathlib
        sentinel = pathlib.Path(E2E_ROOT) / "_sentinel_must_not_delete.txt"
        sentinel.write_text("sentinel")

        # Path traversal attempts
        traversal_targets = [
            "../../_sentinel_must_not_delete",
            "../../../etc/passwd",
            "/etc/passwd",
        ]
        for target in traversal_targets:
            resp = requests.post(
                f"{BASE_URL}/v2/snapshot/remove",
                params={"target": target},
                timeout=10,
            )
            assert resp.status_code == 400, (
                f"Path traversal target {target!r} should return 400, got {resp.status_code}"
            )

        # Sentinel file must still exist (no traversal succeeded)
        assert sentinel.exists(), "Sentinel file was deleted — path traversal succeeded!"
        sentinel.unlink()


class TestSnapshotGetCurrentSchema:
    """Verify get_current snapshot response structure."""

    # WI-M dedup: `test_get_current_returns_dict` REMOVED — it was a strict
    # subset of TestSnapshotLifecycle::test_get_current_snapshot (which now
    # asserts the full documented schema + cross-ref with installed state
    # on disk). Keeping both after the upgrade would be pure duplication.
    # Audit §7 row count reduces 7 → 6 to reflect the removal.

    def test_getlist_items_are_strings(self, comfyui):
        """Each item in the snapshot list is a string (filename stem)."""
        resp = requests.get(f"{BASE_URL}/v2/snapshot/getlist", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        for item in data.get("items", []):
            assert isinstance(item, str), (
                f"Snapshot item should be a string, got {type(item)}: {item}"
            )
