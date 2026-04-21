"""E2E tests for ComfyUI Manager configuration API endpoints.

Tests the dual GET (read) + POST (write) configuration endpoints:
- /v2/manager/db_mode
- /v2/manager/policy/update
- /v2/manager/channel_url_list

Each write test reads the original value, sets a new value via POST,
reads back via GET to verify, then restores the original to ensure
idempotency.

Requires a pre-built E2E environment (from setup_e2e_env.sh).
Set E2E_ROOT env var to point at it, or the tests will be skipped.

Usage:
    E2E_ROOT=/tmp/e2e_full_test pytest tests/e2e/test_e2e_config_api.py -v
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time

import pytest
import requests

E2E_ROOT = os.environ.get("E2E_ROOT", "")
COMFYUI_PATH = os.path.join(E2E_ROOT, "comfyui") if E2E_ROOT else ""
MANAGER_CONFIG_INI = (
    os.path.join(COMFYUI_PATH, "user", "__manager", "config.ini")
    if COMFYUI_PATH
    else ""
)
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scripts"
)

PORT = 8199
BASE_URL = f"http://127.0.0.1:{PORT}"

# Reboot recovery window (same as test_e2e_system_info TestReboot)
REBOOT_TIMEOUT = 60.0
REBOOT_INTERVAL = 2.0


def _read_config_ini_value(key: str) -> str | None:
    """Read a value directly from the manager config.ini (for disk-level assertion)."""
    if not os.path.isfile(MANAGER_CONFIG_INI):
        return None
    import configparser
    cp = configparser.ConfigParser()
    cp.read(MANAGER_CONFIG_INI)
    for section in cp.sections():
        if cp.has_option(section, key):
            return cp.get(section, key)
    return None


# ---------------------------------------------------------------------------
# Disk-persistence helpers (Stage2 WI-E PoC — reusable by the WEAK-rated 5
# tests listed in reports/e2e_verification_audit.md §4 once a follow-up WI
# propagates them). Callable with `None` expected value for "absent" checks.
# ---------------------------------------------------------------------------

def _assert_config_ini_contains(key: str, expected: str | None) -> None:
    """Assert the manager config.ini has ``key`` set to ``expected`` on disk.

    Interface:
        key       — config.ini option name (searched across all sections)
        expected  — the exact string value the key must hold, OR None to
                    assert the key is absent / config.ini missing.

    Raises AssertionError with pre/post hashes + on-disk value for diagnosis.
    The helper verifies persistence independently from the HTTP API —
    catches no-op handlers that return 200 without writing to disk.
    """
    actual = _read_config_ini_value(key)
    if expected is None:
        assert actual is None, (
            f"config.ini[{key}] expected absent, found {actual!r}"
        )
        return

    # For diagnosis on failure, capture a hash of the file so reviewers can
    # tell whether ANY mutation happened vs. the wrong-value case.
    file_hash = "<missing>"
    if os.path.isfile(MANAGER_CONFIG_INI):
        with open(MANAGER_CONFIG_INI, "rb") as fh:
            file_hash = hashlib.sha256(fh.read()).hexdigest()[:12]
    assert actual == expected, (
        f"config.ini[{key}] disk mismatch: expected {expected!r}, "
        f"got {actual!r} (file sha256[:12]={file_hash}, path={MANAGER_CONFIG_INI})"
    )


def _assert_config_ini_persists_across_reboot(
    key: str,
    expected: str,
    timeout: float = REBOOT_TIMEOUT,
) -> None:
    """Assert ``key=expected`` survives a ComfyUI reboot on disk AND via API.

    Interface:
        key      — config.ini option name
        expected — value the key must still hold post-reboot
        timeout  — max seconds to wait for the server to come back healthy

    Behavior:
        1. Issue POST /v2/manager/reboot (tolerates ConnectionError mid-
           response — server drops the connection during shutdown).
        2. Poll /system_stats until the server answers 200 or timeout.
        3. Re-read config.ini from disk → must equal ``expected``.
        4. Re-read the value via the appropriate GET endpoint (derived
           from the key) → must equal ``expected`` as well.

    Note: This helper WILL replace the ComfyUI process. Any fixture that
    pins a PID should treat the post-reboot PID as unknown. The
    module-scoped ``comfyui`` fixture's teardown calls stop_comfyui.sh,
    which kills by port rather than stored PID, so teardown continues
    to work.
    """
    try:
        resp = requests.post(f"{BASE_URL}/v2/manager/reboot", timeout=10)
        if resp.status_code == 403:
            pytest.skip(
                "reboot denied by security policy "
                "(E2E_SECURITY_LEVEL does not permit 'middle')"
            )
        assert resp.status_code == 200, (
            f"reboot returned unexpected status {resp.status_code}: {resp.text}"
        )
    except requests.ConnectionError:
        # Server closed the socket mid-reboot response. Expected on some
        # platforms; treat as success-so-far and rely on healthcheck below.
        pass

    time.sleep(2)  # grace period for shutdown

    deadline = time.monotonic() + timeout
    recovered = False
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/system_stats", timeout=5)
            if r.status_code == 200:
                recovered = True
                break
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(REBOOT_INTERVAL)
    assert recovered, (
        f"server did not recover within {timeout}s after reboot — "
        f"cannot verify {key!r} persistence"
    )

    # Disk side: config.ini preserved the value.
    _assert_config_ini_contains(key, expected)

    # API side: the restarted server re-read config.ini and serves the value.
    api_path = {
        "db_mode": "/v2/manager/db_mode",
        "update_policy": "/v2/manager/policy/update",
        "channel_url": "/v2/manager/channel_url_list",
    }.get(key)
    if api_path is None:
        return  # caller responsible for API verification for non-standard keys

    api_resp = requests.get(f"{BASE_URL}{api_path}", timeout=10)
    api_resp.raise_for_status()
    if api_path.endswith("channel_url_list"):
        # channel_url asymmetry: config.ini stores the full URL, API returns the
        # reverse-mapped channel NAME. When caller passes the URL as `expected`,
        # translate URL→NAME via the API's own `list` (`name::url` entries).
        # Callers passing a NAME (legacy path) continue to work unchanged.
        body = api_resp.json()
        actual_api = body.get("selected")
        expected_to_compare = expected
        if isinstance(expected, str) and "://" in expected:
            for entry in body.get("list", []):
                if isinstance(entry, str) and "::" in entry:
                    name, url = entry.split("::", 1)
                    if url == expected:
                        expected_to_compare = name
                        break
            else:
                # URL not in the known list → server reports "custom"
                expected_to_compare = "custom"
    else:
        actual_api = api_resp.text
        expected_to_compare = expected
    assert actual_api == expected_to_compare, (
        f"post-reboot API mismatch for {key}: "
        f"config.ini has {expected!r} but GET {api_path} returned {actual_api!r}"
    )

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


@pytest.fixture(scope="module", autouse=True)
def config_snapshot(comfyui):
    """Snapshot config values at module start, restore at module teardown.

    Guards against state leak if any in-module test fails mid-mutation
    (leaving config.ini in a corrupted/unexpected state that would poison
    "original" reads in subsequent tests).
    """
    snapshot = {
        "db_mode": requests.get(f"{BASE_URL}/v2/manager/db_mode", timeout=10).text,
        "update_policy": requests.get(
            f"{BASE_URL}/v2/manager/policy/update", timeout=10
        ).text,
        "channel_selected": requests.get(
            f"{BASE_URL}/v2/manager/channel_url_list", timeout=10
        ).json().get("selected"),
    }
    yield snapshot
    # Best-effort restore; log but don't fail if restore hits issues
    for path, key, value in (
        ("/v2/manager/db_mode", "db_mode", snapshot["db_mode"]),
        ("/v2/manager/policy/update", "update_policy", snapshot["update_policy"]),
        ("/v2/manager/channel_url_list", "channel_selected", snapshot["channel_selected"]),
    ):
        try:
            resp = requests.post(
                f"{BASE_URL}{path}",
                json={"value": value},
                timeout=10,
            )
            if not resp.ok:
                print(
                    f"[config_snapshot] restore FAILED for {key}={value!r}: "
                    f"status={resp.status_code}",
                )
        except Exception as e:  # noqa: BLE001
            print(f"[config_snapshot] restore EXCEPTION for {key}: {e}")


# ---------------------------------------------------------------------------
# Tests — db_mode
# ---------------------------------------------------------------------------

class TestConfigDbMode:
    """Test GET/POST /v2/manager/db_mode round-trip."""

    DB_MODE_VALUES = ("cache", "channel", "local", "remote")

    def test_read_db_mode(self, comfyui):
        """GET /v2/manager/db_mode returns a valid db mode string."""
        resp = requests.get(f"{BASE_URL}/v2/manager/db_mode", timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert resp.text in self.DB_MODE_VALUES, (
            f"Unexpected db_mode value: {resp.text!r}"
        )

    def test_set_and_restore_db_mode(self, comfyui):
        """POST sets db_mode, GET reads it back, disk + reboot persistence proven, then original is restored.

        Stage2 WI-E PoC — demonstrates the two disk-persistence helpers:
          * _assert_config_ini_contains        → disk-level verification
          * _assert_config_ini_persists_across_reboot → restart-survival verification

        This test is the first of the six §4 WEAK round-trip tests (per
        reports/e2e_verification_audit.md) to gain independent disk state
        assertions. Propagation to the other five is tracked as a follow-up
        WI — see the completion report accompanying this change.
        """
        # Read original — baseline for both round-trip and restore verification.
        resp = requests.get(f"{BASE_URL}/v2/manager/db_mode", timeout=10)
        resp.raise_for_status()
        original = resp.text

        # Pick a different value so the mutation is observable.
        new_mode = "local" if original != "local" else "remote"

        # Snapshot config.ini BEFORE mutation — reviewers can tell from
        # pre_hash vs. post_hash whether the POST actually touched the file.
        pre_hash = (
            hashlib.sha256(open(MANAGER_CONFIG_INI, "rb").read()).hexdigest()[:12]
            if os.path.isfile(MANAGER_CONFIG_INI)
            else "<missing>"
        )

        try:
            # Set new value via POST.
            resp = requests.post(
                f"{BASE_URL}/v2/manager/db_mode",
                json={"value": new_mode},
                timeout=10,
            )
            assert resp.status_code == 200, (
                f"POST db_mode failed: {resp.status_code} {resp.text}"
            )

            # (1) API round-trip — the existing WEAK check.
            resp = requests.get(f"{BASE_URL}/v2/manager/db_mode", timeout=10)
            resp.raise_for_status()
            assert resp.text == new_mode, (
                f"db_mode not updated: expected {new_mode!r}, got {resp.text!r}"
            )

            # (2) Disk persistence — helper #1 asserts config.ini on disk
            # reflects the new value. This defeats a "no-op handler that
            # caches in memory but never writes" regression.
            _assert_config_ini_contains("db_mode", new_mode)

            # Capture post-POST hash — assertion diagnostic only; failing the
            # above already reports the mismatch. Required for AC-5c evidence.
            post_hash = (
                hashlib.sha256(open(MANAGER_CONFIG_INI, "rb").read()).hexdigest()[:12]
                if os.path.isfile(MANAGER_CONFIG_INI)
                else "<missing>"
            )
            assert pre_hash != post_hash or pre_hash == "<missing>", (
                f"config.ini hash unchanged after POST: {pre_hash}; "
                f"server may be caching without writing to disk"
            )

            # (3) Reboot persistence — helper #2 restarts ComfyUI and
            # re-verifies both disk and API still report new_mode. This
            # defeats a "value only in memory, lost on restart" regression.
            # NOTE: this helper replaces the ComfyUI process; downstream
            # tests in this module will hit the fresh instance. The
            # module-scoped `comfyui` fixture's teardown kills by port, so
            # cleanup still works regardless of the new PID.
            _assert_config_ini_persists_across_reboot("db_mode", new_mode)
        finally:
            # Restore original value on whichever server instance is live
            # (pre- or post-reboot — the restored value also persists to
            # disk via the restarted handler).
            requests.post(
                f"{BASE_URL}/v2/manager/db_mode",
                json={"value": original},
                timeout=10,
            )

        # Verify restoration end-to-end: API + disk.
        resp = requests.get(f"{BASE_URL}/v2/manager/db_mode", timeout=10)
        resp.raise_for_status()
        assert resp.text == original, (
            f"Failed to restore db_mode: expected {original!r}, got {resp.text!r}"
        )
        _assert_config_ini_contains("db_mode", original)



# ---------------------------------------------------------------------------
# Tests — update policy
# ---------------------------------------------------------------------------

class TestConfigUpdatePolicy:
    """Test GET/POST /v2/manager/policy/update round-trip."""

    POLICY_VALUES = ("stable", "stable-comfyui", "nightly", "nightly-comfyui")

    def test_read_update_policy(self, comfyui):
        """GET /v2/manager/policy/update returns a valid policy string."""
        resp = requests.get(
            f"{BASE_URL}/v2/manager/policy/update", timeout=10
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert resp.text in self.POLICY_VALUES, (
            f"Unexpected policy value: {resp.text!r}"
        )

    def test_set_and_restore_update_policy(self, comfyui):
        """POST sets update policy, disk + reboot persistence proven, then original restored (WI-G).

        WI-G full-helper application (mirrors test_set_and_restore_db_mode PoC):
          * _assert_config_ini_contains        → disk-level verification
          * _assert_config_ini_persists_across_reboot → restart-survival verification
        """
        # Read original — baseline for both round-trip and restore verification.
        resp = requests.get(
            f"{BASE_URL}/v2/manager/policy/update", timeout=10
        )
        resp.raise_for_status()
        original = resp.text

        # Pick a different value
        new_policy = "nightly" if original != "nightly" else "stable"

        try:
            # Set new value via POST
            resp = requests.post(
                f"{BASE_URL}/v2/manager/policy/update",
                json={"value": new_policy},
                timeout=10,
            )
            assert resp.status_code == 200, (
                f"POST policy/update failed: {resp.status_code} {resp.text}"
            )

            # (1) API round-trip — existing WEAK check retained.
            resp = requests.get(
                f"{BASE_URL}/v2/manager/policy/update", timeout=10
            )
            resp.raise_for_status()
            assert resp.text == new_policy, (
                f"Policy not updated: expected {new_policy!r}, got {resp.text!r}"
            )

            # (2) Disk persistence — helper #1 proves config.ini on disk was mutated.
            _assert_config_ini_contains("update_policy", new_policy)

            # (3) Reboot persistence — helper #2 proves the value survives a
            # full ComfyUI restart on both disk and via API.
            _assert_config_ini_persists_across_reboot("update_policy", new_policy)
        finally:
            # Restore original value on whichever server instance is live.
            requests.post(
                f"{BASE_URL}/v2/manager/policy/update",
                json={"value": original},
                timeout=10,
            )

        # Verify restoration end-to-end: API + disk.
        resp = requests.get(
            f"{BASE_URL}/v2/manager/policy/update", timeout=10
        )
        resp.raise_for_status()
        assert resp.text == original, (
            f"Failed to restore policy: expected {original!r}, got {resp.text!r}"
        )
        _assert_config_ini_contains("update_policy", original)



# ---------------------------------------------------------------------------
# Tests — channel_url_list
# ---------------------------------------------------------------------------

class TestConfigChannelUrlList:
    """Test GET/POST /v2/manager/channel_url_list round-trip."""

    def test_read_channel_url_list(self, comfyui):
        """GET /v2/manager/channel_url_list returns {selected, list} structure."""
        resp = requests.get(
            f"{BASE_URL}/v2/manager/channel_url_list", timeout=10
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert "selected" in data, "Response missing 'selected' field"
        assert "list" in data, "Response missing 'list' field"
        assert isinstance(data["list"], list), (
            f"'list' should be an array, got {type(data['list']).__name__}"
        )
        assert isinstance(data["selected"], str), (
            f"'selected' should be a string, got {type(data['selected']).__name__}"
        )

    def test_channel_list_entries_are_name_url_strings(self, comfyui):
        """Each entry in channel list is a 'name::url' string."""
        resp = requests.get(
            f"{BASE_URL}/v2/manager/channel_url_list", timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        for i, entry in enumerate(data["list"]):
            assert isinstance(entry, str), (
                f"Entry {i} should be a string, got {type(entry).__name__}"
            )
            assert "::" in entry, (
                f"Entry {i} should contain '::' separator: {entry!r}"
            )

    def test_set_and_restore_channel(self, comfyui):
        """POST sets channel, disk + reboot persistence proven, then original restored (WI-G).

        WI-G full-helper application. Notes on the channel_url asymmetry:
          * config.ini stores the full URL under key `channel_url`
          * GET /channel_url_list returns the NAME (reverse-mapped from URL)
          * POST /channel_url_list accepts {value: NAME} and maps to URL
        The helpers resolve URL↔NAME internally when key == "channel_url".
        """
        # Read original — capture both NAME (for API round-trip) and URL (for disk checks).
        resp = requests.get(
            f"{BASE_URL}/v2/manager/channel_url_list", timeout=10
        )
        resp.raise_for_status()
        original_data = resp.json()
        original_selected = original_data["selected"]
        channel_map = {}  # name -> url
        for entry in original_data["list"]:
            if isinstance(entry, str) and "::" in entry:
                name, url = entry.split("::", 1)
                channel_map[name] = url
        original_url = channel_map.get(original_selected)
        available_channels = list(channel_map.keys())

        if len(available_channels) < 2:
            pytest.skip("Only one channel available, cannot test switching")

        # Pick a different channel (name + its URL)
        new_channel = next(
            (ch for ch in available_channels if ch != original_selected),
            None,
        )
        if new_channel is None or original_url is None:
            pytest.skip("No alternative channel found or original URL unresolved")
        new_channel_url = channel_map[new_channel]

        try:
            # Set new channel via POST (server maps NAME → URL internally)
            resp = requests.post(
                f"{BASE_URL}/v2/manager/channel_url_list",
                json={"value": new_channel},
                timeout=10,
            )
            assert resp.status_code == 200, (
                f"POST channel_url_list failed: {resp.status_code} {resp.text}"
            )

            # (1) API round-trip — existing WEAK check retained (verifies NAME).
            resp = requests.get(
                f"{BASE_URL}/v2/manager/channel_url_list", timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            assert data["selected"] == new_channel, (
                f"Channel not updated: expected {new_channel!r}, "
                f"got {data['selected']!r}"
            )

            # (2) Disk persistence — helper asserts config.ini holds the URL.
            _assert_config_ini_contains("channel_url", new_channel_url)

            # (3) Reboot persistence — helper reboots and re-verifies disk URL
            # + API NAME (internal URL→NAME translation handles the asymmetry).
            _assert_config_ini_persists_across_reboot("channel_url", new_channel_url)
        finally:
            # Restore original channel on whichever server instance is live.
            requests.post(
                f"{BASE_URL}/v2/manager/channel_url_list",
                json={"value": original_selected},
                timeout=10,
            )

        # Verify restoration end-to-end: API NAME + disk URL.
        resp = requests.get(
            f"{BASE_URL}/v2/manager/channel_url_list", timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        assert data["selected"] == original_selected, (
            f"Failed to restore channel: expected {original_selected!r}, "
            f"got {data['selected']!r}"
        )
        _assert_config_ini_contains("channel_url", original_url)


# ---------------------------------------------------------------------------
# Parametrized consolidations (WI-NN bloat Priority 3)
# ---------------------------------------------------------------------------
#
# Two parametrized tests below consolidate the 6 copy-paste tests that
# previously lived on the 3 per-endpoint TestConfig* classes:
#   * test_set_*_invalid_body (×3 endpoints)        → one parametrized
#   * test_set_*_junk_value_rejected / unknown_name  → one parametrized
#
# Cluster 1 (roundtrip, set_and_restore_* ×3) remained unparametrized:
# the channel_url_list case carries URL↔NAME asymmetry that the helpers
# resolve internally only when `key == "channel_url"`, and the channel-
# map extraction step has no counterpart in the db_mode/policy bodies.
# Forcing a single parametrized body produced a ~100-line branch soup;
# the three per-endpoint tests remain distinct functions for readability.


# Config endpoints that accept/reject via {"value": ...} JSON body + config.ini
# on-disk persistence. Each descriptor supplies the config.ini key AND the
# junk-value payload; the valid-values whitelist is used to both pick a
# valid restore target and to sanity-check post-rejection disk state.
_CONFIG_POST_ENDPOINTS = [
    pytest.param(
        "/v2/manager/db_mode",
        "db_mode",
        "pwned_junk_value_xyz",
        ("cache", "channel", "local", "remote"),
        id="db_mode",
    ),
    pytest.param(
        "/v2/manager/policy/update",
        "update_policy",
        "pwned_junk_policy_xyz",
        ("stable", "stable-comfyui", "nightly", "nightly-comfyui"),
        id="update_policy",
    ),
    pytest.param(
        "/v2/manager/channel_url_list",
        "channel_url",
        "pwned_unknown_channel_xyz",
        None,  # channel uses dynamic whitelist (name→url map); see _read_channel_selected
        id="channel_url_list",
    ),
]


def _read_channel_selected() -> str | None:
    resp = requests.get(f"{BASE_URL}/v2/manager/channel_url_list", timeout=10)
    if not resp.ok:
        return None
    return resp.json().get("selected")


class TestConfigPostNegativeContracts:
    """Parametrized negative-path tests for the 3 config POST endpoints.

    WI-NN Cluster 2 (invalid body) + Cluster 3 (junk value) consolidate the
    6 previous copy-paste tests. Each parametrize case exercises one endpoint;
    the two test functions cover the two negative contracts separately so
    failures still point at the correct contract.
    """

    @pytest.mark.parametrize("endpoint,key,_junk,_values", _CONFIG_POST_ENDPOINTS)
    def test_malformed_body_returns_400(self, comfyui, endpoint, key, _junk, _values):
        """WI-NN Cluster 2 (teng:ci-003/ci-008/ci-015 B9): malformed JSON → 400 + disk unchanged."""
        before = _read_config_ini_value(key)
        resp = requests.post(
            f"{BASE_URL}{endpoint}",
            data="not-json",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for malformed JSON on {endpoint}, got {resp.status_code}"
        )
        # Disk-state invariant — malformed POST must not touch config.ini.
        _assert_config_ini_contains(key, before)

    @pytest.mark.parametrize("endpoint,key,junk,values", _CONFIG_POST_ENDPOINTS)
    def test_junk_value_rejected(self, comfyui, endpoint, key, junk, values):
        """WI-NN Cluster 3 (teng:ci-004/ci-009/ci-014 B9): unknown/junk value → 400 + disk/API unchanged.

        For db_mode/policy the whitelist is static and verifiable directly
        via `_read_config_ini_value`. For channel_url_list the whitelist is
        dynamic (server-built name→url map), so we compare the API-level
        `selected` string before/after instead.
        """
        # Capture pre-state that the endpoint's own API exposes. Also capture
        # disk state for the static-whitelist endpoints.
        pre_disk = _read_config_ini_value(key)
        pre_api_selected = _read_channel_selected() if key == "channel_url" else None

        resp = requests.post(
            f"{BASE_URL}{endpoint}",
            json={"value": junk},
            timeout=10,
        )
        assert resp.status_code == 400, (
            f"Unknown/junk value on {endpoint} should return 400, got {resp.status_code}"
        )

        if values is not None:
            # Static whitelist: on-disk value must still be a whitelisted
            # value (server did not write junk).
            post_disk = _read_config_ini_value(key)
            assert post_disk in values, (
                f"config.ini {key} corrupted with junk value: {post_disk!r}"
            )
        else:
            # Dynamic whitelist (channel): API-level NAME must be unchanged.
            post_api_selected = _read_channel_selected()
            assert pre_api_selected == post_api_selected, (
                f"{endpoint} selected mutated on invalid request: "
                f"{pre_api_selected!r} -> {post_api_selected!r}"
            )
            # Also check config.ini URL is unchanged (if pre was present).
            assert _read_config_ini_value(key) == pre_disk, (
                f"config.ini {key} changed on invalid {endpoint} POST"
            )
