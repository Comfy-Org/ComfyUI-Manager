"""E2E tests for ComfyUI Manager queue lifecycle endpoints.

Exercises the queue management endpoints on a running ComfyUI instance:
  - GET  /v2/manager/queue/status       — queue status JSON
  - GET  /v2/manager/queue/history      — task history (filterable)
  - GET  /v2/manager/queue/history_list — batch history IDs
  - POST /v2/manager/queue/reset        — reset queue
  - POST /v2/manager/queue/start        — start processing

Scenario:
  reset → verify clean status → queue a task → start → wait for
  completion → check history → verify history_list → reset → verify
  status returns to clean state.

Requires a pre-built E2E environment (from setup_e2e_env.sh).
Set E2E_ROOT env var to point at it, or the tests will be skipped.

Usage:
    E2E_ROOT=/tmp/e2e_full_test pytest tests/e2e/test_e2e_queue_lifecycle.py -v
"""

from __future__ import annotations

import os
import subprocess
import time

import pytest
import requests

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
HISTORY_DIR = (
    os.path.join(COMFYUI_PATH, "user", "__manager", "batch_history")
    if COMFYUI_PATH
    else ""
)
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scripts"
)

PORT = 8199
BASE_URL = f"http://127.0.0.1:{PORT}"

# Polling configuration
POLL_TIMEOUT = 30
POLL_INTERVAL = 0.5

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


def _wait_for(predicate, timeout=POLL_TIMEOUT, interval=POLL_INTERVAL):
    """Poll *predicate* until it returns True or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


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

class TestQueueLifecycle:
    """Queue management lifecycle: reset → status → task → start → history."""

    def test_reset_queue(self, comfyui):
        """POST /v2/manager/queue/reset returns 200 AND all queue counts are zeroed.

        WI-L strengthening: previously status-only. Now verifies the post-reset
        status payload reports a fully-quiescent queue. `wipe_queue()` only
        clears `pending_tasks` unconditionally (see manager_server.py:396-403),
        but at the start of this module-scoped fixture no task has been run, so
        all counts — pending / in_progress / total / done / is_processing —
        must be 0/False. Any non-zero count here would indicate a leak from an
        earlier test module or a reset-handler regression.
        """
        resp = requests.post(f"{BASE_URL}/v2/manager/queue/reset", timeout=10)
        assert resp.status_code == 200, (
            f"Queue reset failed with status {resp.status_code}"
        )
        status = requests.get(f"{BASE_URL}/v2/manager/queue/status", timeout=10)
        assert status.status_code == 200
        data = status.json()
        assert data["pending_count"] == 0, (
            f"pending_count != 0 after reset: {data['pending_count']}"
        )
        assert data["in_progress_count"] == 0, (
            f"in_progress_count != 0 after reset: {data['in_progress_count']}"
        )
        assert data["total_count"] == 0, (
            f"total_count != 0 after reset: {data['total_count']}"
        )
        assert data["done_count"] == 0, (
            f"done_count != 0 after reset (fresh module): {data['done_count']}"
        )
        assert data["is_processing"] is False, (
            f"is_processing should be False after reset, got {data['is_processing']!r}"
        )

    def test_status_with_client_id_filter(self, comfyui):
        """GET /v2/manager/queue/status?client_id=X returns client-scoped counts."""
        resp = requests.get(
            f"{BASE_URL}/v2/manager/queue/status",
            params={"client_id": "e2e-queue-test"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["client_id"] == "e2e-queue-test", (
            f"Expected client_id echo, got {data.get('client_id')}"
        )
        assert "total_count" in data, "Filtered response missing 'total_count'"
        assert "pending_count" in data, "Filtered response missing 'pending_count'"

    def test_start_queue_already_idle(self, comfyui):
        """POST /v2/manager/queue/start on empty queue returns 200 or 201 AND worker stabilizes to idle.

        WI-L strengthening: previously status-only. The contract:
          - 200 = worker thread newly started; on empty queue it finds no work,
                  calls `task_queue.finalize()` no-op (done_count==0), and exits.
          - 201 = worker already alive; same stabilization expected.
        In either case the post-condition is: pending==0, in_progress==0,
        is_processing eventually False (worker exits within a few seconds
        when there's nothing to do). This defeats a regression where
        `start_worker()` accidentally spawns a hot-loop that never exits.
        """
        # Ensure idle baseline (pending empty before start).
        requests.post(f"{BASE_URL}/v2/manager/queue/reset", timeout=10)
        pre = requests.get(f"{BASE_URL}/v2/manager/queue/status", timeout=10).json()
        assert pre["pending_count"] == 0, (
            f"Pre-condition: pending_count must be 0 before idle-start test, got {pre['pending_count']}"
        )

        resp = requests.post(f"{BASE_URL}/v2/manager/queue/start", timeout=10)
        assert resp.status_code in (200, 201), (
            f"Queue start returned unexpected status {resp.status_code}"
        )

        # Worker observation: either it never flipped (201 + already-idle worker
        # that stays idle) or it flipped True→False (200 + brief run). Poll
        # until is_processing is False with stable pending/in_progress==0.
        deadline = time.monotonic() + 10.0
        final = None
        while time.monotonic() < deadline:
            r = requests.get(f"{BASE_URL}/v2/manager/queue/status", timeout=5)
            if r.status_code == 200:
                final = r.json()
                if (
                    final["pending_count"] == 0
                    and final["in_progress_count"] == 0
                    and final["is_processing"] is False
                ):
                    break
            time.sleep(0.3)
        assert final is not None, "queue/status never returned 200 during poll"
        assert final["pending_count"] == 0, (
            f"pending_count non-zero after start on empty queue: {final['pending_count']}"
        )
        assert final["in_progress_count"] == 0, (
            f"in_progress_count non-zero after start on empty queue: {final['in_progress_count']}"
        )
        assert final["is_processing"] is False, (
            f"worker did not stabilize to idle within 10s: is_processing={final['is_processing']!r} — "
            f"possible hot-loop regression in start_worker() / task_worker"
        )

    def test_queue_task_and_history(self, comfyui):
        """Full lifecycle: queue task → start → wait → verify history."""
        # Reset to clean slate. Note: reset wipes pending/running but not
        # file-based batch history, so we track completion by our OWN ui_id
        # rather than a global done_count which can reflect unrelated tasks.
        requests.post(f"{BASE_URL}/v2/manager/queue/reset", timeout=10)

        UI_ID = "e2e-queue-lifecycle"
        # Queue a lightweight task (install a small CNR package)
        task_payload = {
            "ui_id": UI_ID,
            "client_id": UI_ID,
            "kind": "install",
            "params": {
                "id": "ComfyUI_SigmoidOffsetScheduler",
                "version": "1.0.1",
                "selected_version": "latest",
                "mode": "remote",
                "channel": "default",
            },
        }
        resp = requests.post(
            f"{BASE_URL}/v2/manager/queue/task",
            json=task_payload,
            timeout=10,
        )
        assert resp.status_code == 200, (
            f"Queue task failed with status {resp.status_code}: {resp.text}"
        )

        # Start processing
        resp = requests.post(f"{BASE_URL}/v2/manager/queue/start", timeout=10)
        assert resp.status_code in (200, 201), (
            f"Queue start failed with status {resp.status_code}"
        )

        # Wait for OUR task to complete: status.pending_count filtered by
        # this client_id drops to 0 AND is_processing for our client is false.
        # This avoids the global-done_count race from stale history.
        def _our_task_completed():
            r = requests.get(
                f"{BASE_URL}/v2/manager/queue/status",
                params={"client_id": UI_ID},
                timeout=10,
            )
            if r.status_code != 200:
                return False
            d = r.json()
            return (
                d.get("pending_count", 1) == 0
                and d.get("in_progress_count", 1) == 0
                and d.get("done_count", 0) >= 1
            )

        assert _wait_for(_our_task_completed, timeout=120), (
            "Our queued task did not complete within timeout"
        )

        # Check history. If the server returns 400, it is the known
        # TaskHistoryItem serialization bug — surface it via pytest.skip
        # with a specific reason rather than silently passing, so the bug
        # remains visible.
        resp = requests.get(f"{BASE_URL}/v2/manager/queue/history", timeout=10)
        # Server-side fix: TaskHistoryItem now serializes via model_dump(mode='json').
        # Any 400 is a genuine failure, not a tolerated server bug.
        assert resp.status_code == 200, (
            f"Queue history unexpected status {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert "history" in data, "History response missing 'history' field"

    def test_history_with_ui_id_filter(self, comfyui):
        """GET /v2/manager/queue/history?ui_id=X returns entries matching the filter.

        WI-T Cluster C target 1: previously 200-or-400-accept without filter-
        semantic check. Now asserts:
          - 200 OK
          - response contains 'history' field (dict)
          - every returned entry's ui_id actually matches the filter value.

        Seed strategy: query unfiltered first — if history is non-empty, pick
        an existing ui_id; otherwise enqueue + wait on a lightweight install
        to seed one. Defeats regressions where the server accepts the ui_id
        param but returns the full unfiltered history.
        """
        # Discover an existing ui_id via unfiltered call; seed if empty.
        all_resp = requests.get(f"{BASE_URL}/v2/manager/queue/history", timeout=10)
        assert all_resp.status_code == 200, (
            f"Unfiltered history unexpected status {all_resp.status_code}: {all_resp.text[:200]}"
        )
        all_history = all_resp.json().get("history", {})

        def _extract_ui_ids(h):
            """Shape-resilient ui_id extractor (WI-P pattern)."""
            if isinstance(h, dict):
                # Either {ui_id: task_data} map or a single task-dict with 'ui_id'
                if "ui_id" in h and ("kind" in h or "params" in h):
                    uid = h.get("ui_id")
                    return [uid] if uid is not None else []
                return list(h.keys())
            if isinstance(h, list):
                return [e.get("ui_id") for e in h if isinstance(e, dict) and "ui_id" in e]
            return []

        ids = _extract_ui_ids(all_history) if isinstance(all_history, (dict, list)) else []
        if ids:
            target_ui_id = ids[0]
        else:
            # Seed a lightweight install so the filter has a target.
            target_ui_id = "e2e-hist-filter-seed"
            seed_payload = {
                "ui_id": target_ui_id,
                "client_id": target_ui_id,
                "kind": "install",
                "params": {
                    "id": "ComfyUI_SigmoidOffsetScheduler",
                    "version": "1.0.1",
                    "selected_version": "latest",
                    "mode": "remote",
                    "channel": "default",
                },
            }
            r = requests.post(f"{BASE_URL}/v2/manager/queue/task", json=seed_payload, timeout=10)
            assert r.status_code == 200, f"seed queue/task failed: {r.status_code} {r.text[:200]}"
            r = requests.post(f"{BASE_URL}/v2/manager/queue/start", timeout=10)
            assert r.status_code in (200, 201), f"seed queue/start failed: {r.status_code}"

            def _seed_done():
                s = requests.get(
                    f"{BASE_URL}/v2/manager/queue/status",
                    params={"client_id": target_ui_id},
                    timeout=5,
                )
                if s.status_code != 200:
                    return False
                d = s.json()
                return (
                    d.get("pending_count", 1) == 0
                    and d.get("in_progress_count", 1) == 0
                    and d.get("done_count", 0) >= 1
                )

            assert _wait_for(_seed_done, timeout=120), (
                "seed task for ui_id filter did not complete within timeout"
            )

        # Filter request (action under test)
        resp = requests.get(
            f"{BASE_URL}/v2/manager/queue/history",
            params={"ui_id": target_ui_id},
            timeout=10,
        )
        assert resp.status_code == 200, (
            f"Filtered history unexpected status {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert "history" in data, "Filtered history response missing 'history' field"

        # Filter semantics: every returned entry must match target_ui_id.
        returned_ids = _extract_ui_ids(data["history"])
        assert returned_ids, (
            f"filter for ui_id={target_ui_id!r} returned empty; "
            f"unfiltered showed ids={ids!r}"
        )
        for uid in returned_ids:
            assert uid == target_ui_id, (
                f"filter leaked other ui_id: got {uid!r}, expected {target_ui_id!r} "
                f"(full response ids={returned_ids!r})"
            )

    def test_history_with_pagination(self, comfyui):
        """GET /v2/manager/queue/history honors max_items + offset consistently.

        WI-T Cluster C target 2: previously only checked the cap (max_items=1).
        Now also verifies:
          - unfiltered total is stable (reference count N),
          - max_items=1 → len ≤ 1 (cap),
          - max_items ≥ N → len == N (no silent truncation),
          - when N ≥ 2: offset=0 and offset=1 return different keys
            (offset actually advances through the list).
        """
        # Reference: full unfiltered count
        full_resp = requests.get(f"{BASE_URL}/v2/manager/queue/history", timeout=10)
        assert full_resp.status_code == 200, (
            f"Unfiltered history unexpected status {full_resp.status_code}"
        )
        full_history = full_resp.json().get("history", {})
        assert isinstance(full_history, dict), (
            f"expected dict for unfiltered history, got {type(full_history).__name__}"
        )
        full_n = len(full_history)

        # (1) Cap: max_items=1 → ≤1 entry
        r1 = requests.get(
            f"{BASE_URL}/v2/manager/queue/history",
            params={"max_items": "1", "offset": "0"},
            timeout=10,
        )
        assert r1.status_code == 200, (
            f"Paginated history unexpected status {r1.status_code}: {r1.text[:200]}"
        )
        h1 = r1.json().get("history", {})
        assert isinstance(h1, dict), f"expected dict, got {type(h1).__name__}"
        assert len(h1) <= 1, (
            f"Pagination cap violated: max_items=1 but got {len(h1)} entries"
        )

        # (2) Large max_items returns everything available (no silent truncation)
        large_cap = max(full_n, 1) + 100
        r_all = requests.get(
            f"{BASE_URL}/v2/manager/queue/history",
            params={"max_items": str(large_cap), "offset": "0"},
            timeout=10,
        )
        assert r_all.status_code == 200
        h_all = r_all.json().get("history", {})
        assert isinstance(h_all, dict)
        assert len(h_all) == full_n, (
            f"Pagination inconsistency: unfiltered={full_n} entries, "
            f"max_items={large_cap} returned {len(h_all)}"
        )

        # (3) Offset progression (only when ≥2 entries exist)
        if full_n >= 2:
            r_off0 = requests.get(
                f"{BASE_URL}/v2/manager/queue/history",
                params={"max_items": "1", "offset": "0"},
                timeout=10,
            ).json().get("history", {})
            r_off1 = requests.get(
                f"{BASE_URL}/v2/manager/queue/history",
                params={"max_items": "1", "offset": "1"},
                timeout=10,
            ).json().get("history", {})
            if r_off0 and r_off1:
                assert set(r_off0.keys()) != set(r_off1.keys()), (
                    f"offset progression failed: offset=0 keys={list(r_off0.keys())!r} == "
                    f"offset=1 keys={list(r_off1.keys())!r}"
                )

    def test_history_list(self, comfyui):
        """GET /v2/manager/queue/history_list returns batch IDs matching disk state.

        WI-T Cluster C target 3: previously shape-only. Now cross-references
        the API response against the filesystem batch_history directory —
        Manager stores one JSON file per batch under user/__manager/batch_history/,
        and the handler returns their basenames (without .json) sorted by mtime.
        API ∩ FS must be equal: no phantom ids, no missing ids.
        """
        # API
        resp = requests.get(f"{BASE_URL}/v2/manager/queue/history_list", timeout=10)
        assert resp.status_code == 200, (
            f"History list failed with status {resp.status_code}"
        )
        data = resp.json()
        assert "ids" in data, "History list response missing 'ids' field"
        api_ids = data["ids"]
        assert isinstance(api_ids, list), (
            f"'ids' should be a list, got {type(api_ids)}"
        )

        # Filesystem cross-reference
        if not os.path.isdir(HISTORY_DIR):
            # If dir absent, API must also be empty (no phantom entries).
            assert not api_ids, (
                f"API returned {len(api_ids)} ids but {HISTORY_DIR} does not exist"
            )
            return

        fs_ids = {
            f[:-5]
            for f in os.listdir(HISTORY_DIR)
            if f.endswith(".json")
            and os.path.isfile(os.path.join(HISTORY_DIR, f))
        }
        api_id_set = set(api_ids)
        assert api_id_set == fs_ids, (
            f"API history_list diverges from filesystem:\n"
            f"  only-in-api={api_id_set - fs_ids}\n"
            f"  only-on-fs ={fs_ids - api_id_set}\n"
            f"  HISTORY_DIR={HISTORY_DIR}"
        )

    def test_history_path_traversal_rejected(self, comfyui):
        """GET /v2/manager/queue/history with path-traversal id is rejected.

        Security boundary: id must stay within manager_batch_history_path.
        Defense in depth:
          1. 400 status (server rejects the request)
          2. Response body contains no file content (leak check)
          3. Sentinel file outside the history dir is NOT read/touched
          4. Multiple traversal variants (bare, encoded, backslash, absolute)
        """
        import pathlib
        # Sentinel in E2E_ROOT — target with various traversal encodings
        sentinel = pathlib.Path(E2E_ROOT) / "_history_sentinel_must_not_read.txt"
        sentinel_content = "sentinel-content-secret-xyz-12345"
        sentinel.write_text(sentinel_content)

        try:
            traversal_ids = [
                "../../../etc/passwd",
                "../../secret",
                "/etc/passwd",
                # Sentinel-targeted variants (would reach _history_sentinel... if traversal works)
                "../../../_history_sentinel_must_not_read",
                "../../_history_sentinel_must_not_read",
                # URL-encoded traversal
                "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
                "%2e%2e/etc/passwd",
                # Backslash (Windows-style)
                "..\\..\\etc\\passwd",
                # Null byte injection attempt (classic bypass)
                "legit_id\x00/../../etc/passwd",
            ]
            for bad_id in traversal_ids:
                resp = requests.get(
                    f"{BASE_URL}/v2/manager/queue/history",
                    params={"id": bad_id},
                    timeout=10,
                )
                assert resp.status_code == 400, (
                    f"Path traversal id {bad_id!r} should return 400, got {resp.status_code}"
                )
                # Content leak check — no /etc/passwd OR sentinel leaked
                body = resp.text
                assert "root:" not in body, (
                    f"Traversal id {bad_id!r} leaked /etc/passwd content"
                )
                assert sentinel_content not in body, (
                    f"Traversal id {bad_id!r} leaked sentinel file content — "
                    f"path traversal actually succeeded!"
                )

            # Sentinel file must still exist (no accidental writes/deletes via traversal)
            assert sentinel.exists(), "Sentinel file was deleted — traversal side-effect!"
            assert sentinel.read_text() == sentinel_content, (
                "Sentinel file was modified — traversal side-effect!"
            )
        finally:
            sentinel.unlink(missing_ok=True)
