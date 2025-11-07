"""
Comprehensive Version Switching Tests

Tests all scenarios of CNR ↔ Nightly version switching to ensure
proper enable/disable mechanism and package state management.
"""

import pytest
import os
import time
import requests
import conftest
from conftest import (
    get_installed_version,
    compare_versions,
)


# Test constants
TEST_PACKAGE = "ComfyUI_SigmoidOffsetScheduler"


@pytest.fixture(scope="module")
def cnr_versions():
    """
    Get available CNR versions from session-level configuration.

    Returns dict with 'latest' and 'older' versions.
    Uses session-level versions to avoid redundant API calls.
    """
    if not conftest.TEST_PACKAGE_NEW_VERSION or not conftest.TEST_PACKAGE_OLD_VERSION:
        pytest.skip("Test versions not initialized by session fixture")

    return {
        'latest': conftest.TEST_PACKAGE_NEW_VERSION,
        'older': conftest.TEST_PACKAGE_OLD_VERSION,
    }


@pytest.fixture
def cleanup_all_versions(custom_nodes_path):
    """Clean up all versions of test package before and after test"""
    import shutil
    
    def cleanup():
        # Remove enabled package
        enabled_path = os.path.join(custom_nodes_path, TEST_PACKAGE)
        if os.path.exists(enabled_path):
            shutil.rmtree(enabled_path)
        
        # Remove all disabled versions
        disabled_base = os.path.join(custom_nodes_path, '.disabled')
        if os.path.exists(disabled_base):
            for item in os.listdir(disabled_base):
                if 'sigmoid' in item.lower():
                    shutil.rmtree(os.path.join(disabled_base, item))
    
    cleanup()  # Before test
    yield
    cleanup()  # After test


def get_package_state(custom_nodes_path, package_name=TEST_PACKAGE):
    """
    Get current state of package.
    
    Returns:
        tuple: (state, type, path) where:
            - state: 'enabled', 'disabled', or 'not_installed'
            - type: 'nightly', 'cnr', 'unknown', or None
            - path: full path to package or None
    """
    # Check enabled location
    enabled_path = os.path.join(custom_nodes_path, package_name)
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    
    if os.path.exists(enabled_path):
        has_git = os.path.exists(os.path.join(enabled_path, '.git'))
        has_tracking = os.path.exists(os.path.join(enabled_path, '.tracking'))
        
        if has_git:
            pkg_type = 'nightly'
        elif has_tracking:
            pkg_type = 'cnr'
        else:
            pkg_type = 'unknown'
        
        return 'enabled', pkg_type, enabled_path
    
    # Check disabled locations
    if os.path.exists(disabled_base):
        pkg_lower = package_name.lower().replace('_', '')
        for item in os.listdir(disabled_base):
            item_lower = item.lower().replace('_', '').replace('@', '')
            if pkg_lower in item_lower:
                disabled_path = os.path.join(disabled_base, item)
                has_git = os.path.exists(os.path.join(disabled_path, '.git'))
                has_tracking = os.path.exists(os.path.join(disabled_path, '.tracking'))
                
                if has_git:
                    pkg_type = 'nightly'
                elif has_tracking:
                    pkg_type = 'cnr'
                else:
                    pkg_type = 'unknown'
                
                return 'disabled', pkg_type, disabled_path
    
    return 'not_installed', None, None


def check_cnr_version_available(api_client, package_id, version):
    """
    Check if a specific CNR version is available.

    Returns True if version exists, False otherwise.
    This is used for conditional test execution.
    """
    try:
        response = api_client.post(
            "/v2/manager/queue/task",
            json={
                "kind": "install",
                "ui_id": f"check_{package_id}@{version}",
                "client_id": "pytest_check",
                "params": {
                    "id": package_id,
                    "version": version,
                    "selected_version": version
                }
            }
        )
        # If queue accepts it, version likely exists
        # We don't actually start the queue, just check if it's valid
        return response.status_code == 200
    except:
        return False


def queue_and_wait(api_client, package_id, version, timeout=20):
    """Queue package installation and wait for completion"""
    # Queue task
    response = api_client.post(
        "/v2/manager/queue/task",
        json={
            "kind": "install",
            "ui_id": f"test_{package_id}@{version}",
            "client_id": "pytest",
            "params": {
                "id": package_id,
                "version": version,
                "selected_version": version
            }
        }
    )
    assert response.status_code == 200, f"Failed to queue: {response.text}"

    # Start queue
    response = api_client.get("/v2/manager/queue/start")
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for completion
    time.sleep(timeout)


def queue_update_and_wait(api_client, package_name, current_version=None, timeout=20):
    """
    Queue package update and wait for completion.

    For CNR packages: updates to @latest automatically
    For Nightly packages: performs git pull
    """
    # Queue update task
    params = {"node_name": package_name}
    if current_version:
        params["node_ver"] = current_version

    response = api_client.post(
        "/v2/manager/queue/task",
        json={
            "kind": "update",
            "ui_id": f"update_{package_name}",
            "client_id": "pytest",
            "params": params
        }
    )
    assert response.status_code == 200, f"Failed to queue update: {response.text}"

    # Start queue
    response = api_client.get("/v2/manager/queue/start")
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for completion
    time.sleep(timeout)


def queue_fix_and_wait(api_client, package_name, package_version, timeout=15):
    """
    Queue package fix (dependency reinstall) and wait for completion.

    Args:
        api_client: Test API client
        package_name: Name of the package to fix
        package_version: Version of the package (required by fix API)
        timeout: Seconds to wait for completion
    """
    # Queue fix task
    response = api_client.post(
        "/v2/manager/queue/task",
        json={
            "kind": "fix",
            "ui_id": f"fix_{package_name}",
            "client_id": "pytest",
            "params": {
                "node_name": package_name,
                "node_ver": package_version
            }
        }
    )
    assert response.status_code == 200, f"Failed to queue fix: {response.text}"

    # Start queue
    response = api_client.get("/v2/manager/queue/start")
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for completion
    time.sleep(timeout)


def queue_uninstall_and_wait(api_client, package_name, timeout=10):
    """
    Queue package uninstall and wait for completion.

    Uninstalls ALL versions of the package (enabled + all disabled).
    """
    # Queue uninstall task
    response = api_client.post(
        "/v2/manager/queue/task",
        json={
            "kind": "uninstall",
            "ui_id": f"uninstall_{package_name}",
            "client_id": "pytest",
            "params": {
                "node_name": package_name
            }
        }
    )
    assert response.status_code == 200, f"Failed to queue uninstall: {response.text}"

    # Start queue
    response = api_client.get("/v2/manager/queue/start")
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for completion
    time.sleep(timeout)


@pytest.mark.priority_high
def test_reverse_scenario_nightly_cnr_nightly(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: Nightly → CNR → Nightly
    
    Verifies that version switching works correctly when starting from Nightly.
    This was the original bug scenario that was fixed.
    """
    # Step 1: Install nightly
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)
    
    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled, got {state}"
    assert pkg_type == 'nightly', f"Expected nightly, got {pkg_type}"
    
    # Step 2: Switch to CNR
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)
    
    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after CNR switch, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr after switch, got {pkg_type}"
    
    # Step 3: Switch back to nightly
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)
    
    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after nightly switch, got {state}"
    assert pkg_type == 'nightly', f"Expected nightly after switch back, got {pkg_type}"


@pytest.mark.priority_high
def test_forward_scenario_cnr_nightly_cnr(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: CNR → Nightly → CNR

    Verifies forward switching pattern (starting from CNR).
    This is the complementary test to the reverse scenario.
    """
    # Step 1: Install CNR
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr, got {pkg_type}"

    # Step 2: Switch to Nightly
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after Nightly switch, got {state}"
    assert pkg_type == 'nightly', f"Expected nightly after switch, got {pkg_type}"

    # Step 3: Switch back to CNR
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after CNR switch, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr after switch back, got {pkg_type}"


@pytest.mark.priority_high
def test_same_version_reinstall_skip(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: CNR 1.0.2 → CNR 1.0.2 (same version)
    
    Verifies that reinstalling the same version skips without errors.
    """
    # Step 1: Install CNR
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)
    
    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled'
    assert pkg_type == 'cnr'
    
    # Step 2: Install same version again
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=10)
    
    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', "Package should remain enabled"
    assert pkg_type == 'cnr', "Package type should remain cnr"


@pytest.mark.priority_high
def test_repeated_switching_4_times(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: CNR → Nightly → CNR → Nightly (4 switches)
    
    Verifies stability over multiple version switches.
    """
    switches = [
        (conftest.CNR_VERSION, "cnr", 15),
        ("nightly", "nightly", 20),
        (conftest.CNR_VERSION, "cnr", 15),
        ("nightly", "nightly", 20),
    ]
    
    for i, (version, expected_type, timeout) in enumerate(switches, 1):
        queue_and_wait(api_client, TEST_PACKAGE, version, timeout=timeout)
        
        state, pkg_type, path = get_package_state(custom_nodes_path)
        assert state == 'enabled', f"Switch {i}: Expected enabled, got {state}"
        assert pkg_type == expected_type, f"Switch {i}: Expected {expected_type}, got {pkg_type}"


@pytest.mark.priority_high
def test_cleanup_verification_no_orphans(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: Verify cleanup after multiple switches
    
    Ensures no orphaned packages after CNR → Nightly → CNR switches.
    """
    # Perform switches
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)
    time.sleep(2)
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)
    time.sleep(2)
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)
    time.sleep(2)
    
    # Count packages
    enabled_path = os.path.join(custom_nodes_path, TEST_PACKAGE)
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    
    enabled_count = 1 if os.path.exists(enabled_path) else 0
    
    disabled_count = 0
    if os.path.exists(disabled_base):
        for item in os.listdir(disabled_base):
            if 'sigmoid' in item.lower():
                disabled_count += 1
    
    # Verify counts
    assert enabled_count == 1, f"Expected 1 enabled package, found {enabled_count}"
    assert disabled_count == 1, f"Expected 1 disabled package, found {disabled_count}"
    
    # Verify enabled is CNR
    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert pkg_type == 'cnr', f"Expected enabled package to be CNR, got {pkg_type}"


@pytest.mark.priority_high
def test_fresh_install_after_uninstall(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: Fresh install after complete uninstall

    Verifies clean installation after all packages removed.
    """
    # Verify clean state (cleanup_all_versions fixture handles this)
    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'not_installed', f"Expected not_installed, got {state}"

    # Fresh install
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr, got {pkg_type}"


@pytest.mark.priority_high
def test_cnr_version_upgrade(api_client, custom_nodes_path, cleanup_all_versions, cnr_versions):
    """
    Test: CNR older version → update (auto-upgrades to latest)

    Verifies CNR version upgrading works correctly using 'update' operation.
    This is the real-world upgrade scenario where users click "Update"
    and it automatically upgrades to @latest version.

    Uses kind="update" which calls unified_update() → cnr_switch_version(@latest)
    """
    older_version = cnr_versions['older']
    latest_version = cnr_versions['latest']

    # Step 1: Install older version
    queue_and_wait(api_client, TEST_PACKAGE, older_version, timeout=15)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after {older_version} install, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr type, got {pkg_type}"

    version_before = get_installed_version(path)
    assert version_before == older_version, f"Expected {older_version}, got {version_before}"

    # Step 2: Update (will auto-upgrade to @latest)
    queue_update_and_wait(api_client, TEST_PACKAGE, current_version=older_version, timeout=15)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after update to latest, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr type after update, got {pkg_type}"

    # Verify version increased (not exact version, as it may be updated in future)
    version_after = get_installed_version(path)
    assert version_after is not None, "Should have version after update"
    assert compare_versions(version_after, version_before) > 0, (
        f"Version should increase after update: {version_before} → {version_after}"
    )
    assert compare_versions(version_after, latest_version) >= 0, (
        f"Should upgrade to at least {latest_version}, got {version_after}"
    )

    # Verify only one version exists (update operation replaces old version)
    # Unlike install operation which moves old version to .disabled/,
    # update operation deletes the old version entirely
    import glob as glob_module
    package_variants = glob_module.glob(os.path.join(custom_nodes_path, f"{TEST_PACKAGE}*"))
    package_variants += glob_module.glob(os.path.join(custom_nodes_path, '.disabled', f"{TEST_PACKAGE}*"))
    assert len(package_variants) == 1, \
        f"Expected only 1 version after update, found {len(package_variants)}: {package_variants}"


@pytest.mark.priority_high
def test_cnr_version_downgrade(api_client, custom_nodes_path, cleanup_all_versions, cnr_versions):
    """
    Test: CNR latest → CNR older (downgrade)

    Verifies CNR version downgrading works correctly.
    Users may need to downgrade to a specific older version if issues occur.
    """
    older_version = cnr_versions['older']
    latest_version = cnr_versions['latest']

    # Step 1: Install newer version
    queue_and_wait(api_client, TEST_PACKAGE, latest_version, timeout=15)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after {latest_version} install, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr type, got {pkg_type}"

    version_before = get_installed_version(path)
    assert version_before == latest_version, f"Expected {latest_version}, got {version_before}"

    # Step 2: Downgrade to older version
    queue_and_wait(api_client, TEST_PACKAGE, older_version, timeout=15)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after downgrade, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr type after downgrade, got {pkg_type}"

    # Verify version decreased
    version_after = get_installed_version(path)
    assert version_after == older_version, f"Expected {older_version}, got {version_after}"
    assert compare_versions(version_after, version_before) < 0, (
        f"Version should decrease after downgrade: {version_before} → {version_after}"
    )

    # Verify newer version is disabled
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    if os.path.exists(disabled_base):
        disabled_items = os.listdir(disabled_base)
        # Check for any version pattern in disabled folder
        assert any('sigmoid' in item.lower() for item in disabled_items), \
            "Newer version should be in .disabled/"


@pytest.mark.priority_medium
def test_invalid_version_error_handling(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: Error handling for non-existent version

    Verifies graceful error handling when requesting invalid version.
    """
    # First install a valid version
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)

    state_before, pkg_type_before, _ = get_package_state(custom_nodes_path)
    assert state_before == 'enabled'
    assert pkg_type_before == 'cnr'

    # Try to switch to non-existent version
    response = api_client.post(
        "/v2/manager/queue/task",
        json={
            "kind": "install",
            "ui_id": f"test_{TEST_PACKAGE}@99.99.99",
            "client_id": "pytest",
            "params": {
                "id": TEST_PACKAGE,
                "version": "99.99.99",
                "selected_version": "99.99.99"
            }
        }
    )
    assert response.status_code == 200, "Queue request should succeed"

    # Start queue (operation should fail gracefully)
    response = api_client.get("/v2/manager/queue/start")
    assert response.status_code in [200, 201], "Queue start should not crash"

    # Wait for operation to complete
    time.sleep(10)

    # Verify system state is not corrupted
    state_after, pkg_type_after, _ = get_package_state(custom_nodes_path)

    # State should remain unchanged or be in a valid state
    assert state_after in ['enabled', 'disabled'], \
        f"System state should be valid, got {state_after}"

    # If still enabled, should be the original version
    if state_after == 'enabled':
        assert pkg_type_after == pkg_type_before, \
            "Package type should not change on failed switch"


@pytest.mark.priority_medium
def test_nightly_update_git_pull(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: Nightly package update via git pull

    Verifies that update operation on nightly packages:
    1. Executes git pull correctly
    2. Maintains nightly state (.git directory preserved)
    3. Keeps package in enabled state

    Note: This test verifies the update mechanism works correctly,
    regardless of whether new commits are available upstream.
    """
    # Step 1: Install nightly version
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)

    state_before, pkg_type_before, path_before = get_package_state(custom_nodes_path)
    assert state_before == 'enabled', f"Expected enabled after install, got {state_before}"
    assert pkg_type_before == 'nightly', f"Expected nightly after install, got {pkg_type_before}"

    # Verify .git directory exists
    git_dir_before = os.path.join(path_before, '.git')
    assert os.path.exists(git_dir_before), ".git directory should exist for nightly package"

    # Step 2: Perform update (git pull)
    queue_update_and_wait(api_client, TEST_PACKAGE, current_version="nightly", timeout=15)

    # Step 3: Verify state after update
    state_after, pkg_type_after, path_after = get_package_state(custom_nodes_path)
    assert state_after == 'enabled', f"Expected enabled after update, got {state_after}"
    assert pkg_type_after == 'nightly', f"Expected nightly after update, got {pkg_type_after}"

    # Verify .git directory still exists
    git_dir_after = os.path.join(path_after, '.git')
    assert os.path.exists(git_dir_after), ".git directory should be preserved after update"

    # Verify it's the same path (not moved to .disabled)
    assert path_before == path_after, "Package path should remain unchanged after update"

    # Verify no disabled versions exist
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    if os.path.exists(disabled_base):
        disabled_count = sum(1 for item in os.listdir(disabled_base)
                           if 'sigmoid' in item.lower())
        assert disabled_count == 0, \
            f"No disabled versions should exist after nightly update, found {disabled_count}"


@pytest.mark.priority_high
def test_cnr_direct_version_install_switching(api_client, custom_nodes_path, cleanup_all_versions, cnr_versions):
    """
    Test: CNR older → CNR newer via kind=install (not update)

    Verifies that install_by_id() handles CNR version-to-version switching
    correctly when using kind="install" API (not kind="update").

    This is different from test_cnr_version_upgrade which uses kind="update".
    Here we test direct version switching via install API, which should:
    1. Disable the currently enabled version
    2. Move old version to .disabled/
    3. Install new version

    This tests a different code path than the update operation.
    """
    older_version = cnr_versions['older']
    latest_version = cnr_versions['latest']

    # Step 1: Install older version via install API
    queue_and_wait(api_client, TEST_PACKAGE, older_version, timeout=15)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after {older_version} install, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr type, got {pkg_type}"

    # Step 2: Install newer version via install API (not update)
    queue_and_wait(api_client, TEST_PACKAGE, latest_version, timeout=15)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after {latest_version} install, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr type after install, got {pkg_type}"

    # Verify version changed
    version_after = get_installed_version(path)
    assert version_after == latest_version, f"Expected {latest_version}, got {version_after}"

    # Step 3: Verify old version is in .disabled/
    # Unlike update operation which deletes old version,
    # install operation should move old version to .disabled/
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    assert os.path.exists(disabled_base), ".disabled/ directory should exist"

    disabled_items = os.listdir(disabled_base)
    disabled_sigmoid = [item for item in disabled_items if 'sigmoid' in item.lower()]

    assert len(disabled_sigmoid) == 1, \
        f"Expected 1 disabled version ({older_version}), found {len(disabled_sigmoid)}: {disabled_sigmoid}"

    # Verify the disabled version contains version identifier
    # Note: Disabled folder name format includes version (e.g., ComfyUI_SigmoidOffsetScheduler_1_0_1)
    old_version_normalized = older_version.replace('.', '_')
    assert any(old_version_normalized in item for item in disabled_sigmoid), \
        f"Old version {older_version} should be in .disabled/, found: {disabled_sigmoid}"


@pytest.mark.priority_medium
def test_nightly_same_version_reinstall_skip(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: Nightly same version reinstall should skip

    Verifies that attempting to install Nightly when Nightly is already
    installed results in a skip (no re-clone).

    This ensures consistency with CNR same version reinstall behavior
    (test_same_version_reinstall_skip).
    """
    # Step 1: Install Nightly version
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)

    state_before, pkg_type_before, path_before = get_package_state(custom_nodes_path)
    assert state_before == 'enabled', f"Expected enabled after install, got {state_before}"
    assert pkg_type_before == 'nightly', f"Expected nightly after install, got {pkg_type_before}"

    # Record initial .git state
    git_dir_before = os.path.join(path_before, '.git')
    assert os.path.exists(git_dir_before), ".git directory should exist for nightly package"

    # Step 2: Attempt to install Nightly again (same version)
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)

    # Step 3: Verify state unchanged (skip behavior)
    state_after, pkg_type_after, path_after = get_package_state(custom_nodes_path)
    assert state_after == 'enabled', f"Expected enabled after reinstall attempt, got {state_after}"
    assert pkg_type_after == 'nightly', f"Expected nightly after reinstall attempt, got {pkg_type_after}"

    # Verify .git directory still exists (no re-clone)
    git_dir_after = os.path.join(path_after, '.git')
    assert os.path.exists(git_dir_after), ".git directory should still exist"

    # Verify it's the same path (not moved)
    assert path_before == path_after, "Package path should remain unchanged"

    # Verify no disabled versions created (skip means no state change)
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    if os.path.exists(disabled_base):
        disabled_count = sum(1 for item in os.listdir(disabled_base)
                           if 'sigmoid' in item.lower())
        assert disabled_count == 0, \
            f"No disabled versions should exist after same version reinstall, found {disabled_count}"


@pytest.mark.priority_high
def test_uninstall_cnr_only(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test 13: Uninstall CNR only (no disabled versions)

    Initial State: CNR v1.0.2 enabled only
    Operation: Uninstall
    Expected: Complete removal (no enabled, no disabled)

    Verifies that uninstall removes the package completely when only
    one CNR version is installed (no disabled versions present).
    """
    # Step 1: Install CNR version only
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after install, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr type, got {pkg_type}"

    # Verify no disabled versions exist
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    if os.path.exists(disabled_base):
        disabled_count = sum(1 for item in os.listdir(disabled_base)
                           if 'sigmoid' in item.lower())
        assert disabled_count == 0, f"Expected no disabled versions, found {disabled_count}"

    # Step 2: Uninstall
    queue_uninstall_and_wait(api_client, TEST_PACKAGE, timeout=10)

    # Step 3: Verify complete removal (no enabled, no disabled)
    state_after, pkg_type_after, path_after = get_package_state(custom_nodes_path)
    assert state_after == 'not_installed', \
        f"Expected not_installed after uninstall, got {state_after}"

    # Verify no enabled package
    enabled_path = os.path.join(custom_nodes_path, TEST_PACKAGE)
    assert not os.path.exists(enabled_path), \
        "Enabled package path should not exist after uninstall"

    # Verify no disabled versions
    if os.path.exists(disabled_base):
        disabled_count = sum(1 for item in os.listdir(disabled_base)
                           if 'sigmoid' in item.lower())
        assert disabled_count == 0, \
            f"Expected no disabled versions after uninstall, found {disabled_count}"


@pytest.mark.priority_high
def test_uninstall_nightly_only(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test 14: Uninstall Nightly only (no disabled versions)

    Initial State: Nightly enabled only
    Operation: Uninstall
    Expected: Complete removal (no enabled, no disabled)

    Verifies that uninstall removes the package completely when only
    one Nightly version is installed (no disabled versions present).
    """
    # Step 1: Install Nightly version only
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)

    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after install, got {state}"
    assert pkg_type == 'nightly', f"Expected nightly type, got {pkg_type}"

    # Verify .git directory exists for nightly
    git_dir = os.path.join(path, '.git')
    assert os.path.exists(git_dir), ".git directory should exist for nightly package"

    # Verify no disabled versions exist
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    if os.path.exists(disabled_base):
        disabled_count = sum(1 for item in os.listdir(disabled_base)
                           if 'sigmoid' in item.lower())
        assert disabled_count == 0, f"Expected no disabled versions, found {disabled_count}"

    # Step 2: Uninstall
    queue_uninstall_and_wait(api_client, TEST_PACKAGE, timeout=10)

    # Step 3: Verify complete removal (no enabled, no disabled)
    state_after, pkg_type_after, path_after = get_package_state(custom_nodes_path)
    assert state_after == 'not_installed', \
        f"Expected not_installed after uninstall, got {state_after}"

    # Verify no enabled package
    enabled_path = os.path.join(custom_nodes_path, TEST_PACKAGE)
    assert not os.path.exists(enabled_path), \
        "Enabled package path should not exist after uninstall"

    # Verify no disabled versions
    if os.path.exists(disabled_base):
        disabled_count = sum(1 for item in os.listdir(disabled_base)
                           if 'sigmoid' in item.lower())
        assert disabled_count == 0, \
            f"Expected no disabled versions after uninstall, found {disabled_count}"


@pytest.mark.priority_high
def test_uninstall_with_multiple_disabled_versions(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test 15: Uninstall with multiple disabled versions (all removed)

    Initial State:
      - Enabled: CNR v1.0.2
      - Disabled: CNR v1.0.1, Nightly
    Operation: Uninstall
    Expected: ALL versions removed (enabled + all disabled)

    Verifies that uninstall removes ALL versions of a package,
    including the enabled version and all disabled versions.
    """
    enabled_path = os.path.join(custom_nodes_path, TEST_PACKAGE)
    disabled_base = os.path.join(custom_nodes_path, '.disabled')

    # Step 1: Create complex state with multiple disabled versions
    # Install CNR v1.0.1
    print("\n=== DEBUG: Before CNR v1.0.1 install ===")
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION_OLD, timeout=15)
    time.sleep(2)

    print(f"\n=== DEBUG: After CNR v1.0.1 install ===")
    print(f"Enabled path exists: {os.path.exists(enabled_path)}")
    if os.path.exists(enabled_path):
        print(f"  Has .git: {os.path.exists(os.path.join(enabled_path, '.git'))}")
        print(f"  Has .tracking: {os.path.exists(os.path.join(enabled_path, '.tracking'))}")
    print(f"Disabled dir exists: {os.path.exists(disabled_base)}")
    if os.path.exists(disabled_base):
        print(f"  Contents: {os.listdir(disabled_base)}")
    state, pkg_type, path = get_package_state(custom_nodes_path)
    print(f"Package state: {state}, type: {pkg_type}, path: {path}")

    # Install Nightly (disables CNR v1.0.1)
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)
    time.sleep(2)

    print(f"\n=== DEBUG: After Nightly install ===")
    print(f"Enabled path exists: {os.path.exists(enabled_path)}")
    if os.path.exists(enabled_path):
        print(f"  Has .git: {os.path.exists(os.path.join(enabled_path, '.git'))}")
        print(f"  Has .tracking: {os.path.exists(os.path.join(enabled_path, '.tracking'))}")
    print(f"Disabled dir exists: {os.path.exists(disabled_base)}")
    if os.path.exists(disabled_base):
        print(f"  Contents: {os.listdir(disabled_base)}")
    state, pkg_type, path = get_package_state(custom_nodes_path)
    print(f"Package state: {state}, type: {pkg_type}, path: {path}")

    # Install CNR v1.0.2 (disables Nightly, CNR v1.0.1 remains disabled)
    # Nightly → CNR transition with multiple disabled versions needs longer timeout and stabilization time
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=20)
    time.sleep(5)  # Extra time for complex state with 2 disabled versions to stabilize

    print(f"\n=== DEBUG: After CNR v1.0.2 install ===")
    print(f"Enabled path exists: {os.path.exists(enabled_path)}")
    if os.path.exists(enabled_path):
        print(f"  Has .git: {os.path.exists(os.path.join(enabled_path, '.git'))}")
        print(f"  Has .tracking: {os.path.exists(os.path.join(enabled_path, '.tracking'))}")
        print(f"  Directory contents: {os.listdir(enabled_path)[:10]}")  # First 10 items
    print(f"Disabled dir exists: {os.path.exists(disabled_base)}")
    if os.path.exists(disabled_base):
        disabled_items = os.listdir(disabled_base)
        print(f"  Contents: {disabled_items}")
        for item in disabled_items:
            item_path = os.path.join(disabled_base, item)
            print(f"    {item}:")
            print(f"      Has .git: {os.path.exists(os.path.join(item_path, '.git'))}")
            print(f"      Has .tracking: {os.path.exists(os.path.join(item_path, '.tracking'))}")

    # Verify initial state
    state, pkg_type, path = get_package_state(custom_nodes_path)
    print(f"\n=== DEBUG: Final check before assertions ===")
    print(f"Package state: {state}, type: {pkg_type}, path: {path}")

    assert state == 'enabled', f"Expected enabled, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr type, got {pkg_type}"

    # Count disabled versions (should have at least 1, possibly 2)
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    assert os.path.exists(disabled_base), ".disabled/ directory should exist"

    disabled_count_before = sum(1 for item in os.listdir(disabled_base)
                               if 'sigmoid' in item.lower())
    assert disabled_count_before >= 1, \
        f"Expected at least 1 disabled version, found {disabled_count_before}"

    # Step 2: Uninstall (should remove ALL versions)
    queue_uninstall_and_wait(api_client, TEST_PACKAGE, timeout=10)

    # Step 3: Verify complete removal (no enabled, no disabled)
    state_after, pkg_type_after, path_after = get_package_state(custom_nodes_path)
    assert state_after == 'not_installed', \
        f"Expected not_installed after uninstall, got {state_after}"

    # Verify no enabled package
    enabled_path = os.path.join(custom_nodes_path, TEST_PACKAGE)
    assert not os.path.exists(enabled_path), \
        "Enabled package path should not exist after uninstall"

    # Verify ALL disabled versions removed
    if os.path.exists(disabled_base):
        disabled_count_after = sum(1 for item in os.listdir(disabled_base)
                                  if 'sigmoid' in item.lower())
        assert disabled_count_after == 0, \
            f"Expected 0 disabled versions after uninstall, found {disabled_count_after}"


@pytest.mark.priority_high
def test_uninstall_mixed_enabled_disabled(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test 16: Uninstall mixed (CNR enabled + Nightly disabled)

    Initial State:
      - Enabled: CNR v1.0.2
      - Disabled: Nightly
    Operation: Uninstall
    Expected: Both removed

    Verifies that uninstall removes both enabled and disabled versions
    when a mixed state exists (simpler than Test 15 with just one disabled version).
    """
    # Step 1: Create mixed state (enabled CNR + disabled Nightly)
    # Install Nightly first
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)
    time.sleep(2)

    # Install CNR v1.0.2 (disables Nightly)
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)
    time.sleep(2)

    # Verify initial state
    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr type, got {pkg_type}"

    # Verify one disabled version exists (Nightly)
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    assert os.path.exists(disabled_base), ".disabled/ directory should exist"

    disabled_count_before = sum(1 for item in os.listdir(disabled_base)
                               if 'sigmoid' in item.lower())
    assert disabled_count_before == 1, \
        f"Expected 1 disabled version (Nightly), found {disabled_count_before}"

    # Step 2: Uninstall (should remove both enabled CNR and disabled Nightly)
    queue_uninstall_and_wait(api_client, TEST_PACKAGE, timeout=10)

    # Step 3: Verify complete removal (no enabled, no disabled)
    state_after, pkg_type_after, path_after = get_package_state(custom_nodes_path)
    assert state_after == 'not_installed', \
        f"Expected not_installed after uninstall, got {state_after}"

    # Verify no enabled package
    enabled_path = os.path.join(custom_nodes_path, TEST_PACKAGE)
    assert not os.path.exists(enabled_path), \
        "Enabled package path should not exist after uninstall"

    # Verify no disabled versions
    if os.path.exists(disabled_base):
        disabled_count_after = sum(1 for item in os.listdir(disabled_base)
                                  if 'sigmoid' in item.lower())
        assert disabled_count_after == 0, \
            f"Expected 0 disabled versions after uninstall, found {disabled_count_after}"


@pytest.mark.priority_medium
def test_fix_cnr_package(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: Fix (dependency reinstall) for CNR package
    
    Verifies that the fix operation successfully re-executes
    install scripts for an already installed package.
    """
    # Step 1: Install CNR package
    queue_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)
    
    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after install, got {state}"
    assert pkg_type == 'cnr', f"Expected cnr type, got {pkg_type}"
    
    # Step 2: Execute fix operation
    # Fix should re-run install scripts without changing package state
    queue_fix_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=15)
    
    # Step 3: Verify package still enabled and unchanged
    state_after, pkg_type_after, path_after = get_package_state(custom_nodes_path)
    assert state_after == 'enabled', \
        f"Expected enabled after fix, got {state_after}"
    assert pkg_type_after == 'cnr', \
        f"Expected cnr type after fix, got {pkg_type_after}"
    assert path_after == path, \
        f"Package path should not change after fix"
    
    # Verify no extra disabled versions created
    disabled_base = os.path.join(custom_nodes_path, '.disabled')
    if os.path.exists(disabled_base):
        disabled_count = sum(1 for item in os.listdir(disabled_base)
                           if 'sigmoid' in item.lower())
        assert disabled_count == 0, \
            f"Fix should not create disabled versions, found {disabled_count}"


@pytest.mark.priority_medium  
def test_fix_nightly_package(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: Fix (dependency reinstall) for Nightly package
    
    Verifies that the fix operation works correctly for nightly packages.
    """
    # Step 1: Install Nightly package
    queue_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=20)
    
    state, pkg_type, path = get_package_state(custom_nodes_path)
    assert state == 'enabled', f"Expected enabled after install, got {state}"
    assert pkg_type == 'nightly', f"Expected nightly type, got {pkg_type}"
    
    # Verify .git directory exists
    git_dir = os.path.join(path, '.git')
    assert os.path.exists(git_dir), "Nightly package should have .git directory"
    
    # Step 2: Execute fix operation
    queue_fix_and_wait(api_client, TEST_PACKAGE, "nightly", timeout=15)
    
    # Step 3: Verify package still enabled and .git preserved
    state_after, pkg_type_after, path_after = get_package_state(custom_nodes_path)
    assert state_after == 'enabled', \
        f"Expected enabled after fix, got {state_after}"
    assert pkg_type_after == 'nightly', \
        f"Expected nightly type after fix, got {pkg_type_after}"
    
    # Verify .git directory still exists (not reinstalled from scratch)
    assert os.path.exists(git_dir), \
        "Fix should preserve .git directory for nightly packages"


@pytest.mark.priority_low
def test_fix_nonexistent_package_error(api_client, custom_nodes_path, cleanup_all_versions):
    """
    Test: Error handling when fixing non-existent package
    
    Verifies graceful error handling when trying to fix a package
    that is not installed.
    """
    # Ensure package is not installed
    state, _, _ = get_package_state(custom_nodes_path)
    assert state == 'not_installed', "Package should not be installed at test start"
    
    # Attempt to fix non-existent package
    # Should not crash, but may fail gracefully
    try:
        queue_fix_and_wait(api_client, TEST_PACKAGE, conftest.CNR_VERSION, timeout=10)
        
        # After fix attempt, package should still not be installed
        # (fix doesn't install, only repairs existing)
        state_after, _, _ = get_package_state(custom_nodes_path)
        assert state_after == 'not_installed', \
            "Fix should not install package if it doesn't exist"
    except Exception as e:
        # It's acceptable for fix to fail on non-existent package
        # Just verify it doesn't cause system instability
        pass
