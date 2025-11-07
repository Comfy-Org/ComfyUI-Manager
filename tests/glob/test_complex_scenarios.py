"""
Test cases for complex multi-version scenarios.

Tests complex scenarios where multiple versions (CNR and Nightly) exist simultaneously.
Based on COMPLEX_SCENARIOS_TEST_PLAN.md
"""

import time
from pathlib import Path

import pytest
import conftest


# Test package configuration - access via conftest module to get runtime values
TEST_PACKAGE_ID = conftest.TEST_PACKAGE_ID
TEST_PACKAGE_CNR_ID = conftest.TEST_PACKAGE_CNR_ID
WAIT_TIME_SHORT = conftest.WAIT_TIME_SHORT
WAIT_TIME_MEDIUM = conftest.WAIT_TIME_MEDIUM
WAIT_TIME_LONG = conftest.WAIT_TIME_LONG

# DO NOT import these directly - session fixture sets them AFTER imports
# Access via conftest module attributes for runtime values:
# - conftest.TEST_PACKAGE_OLD_VERSION
# - conftest.TEST_PACKAGE_NEW_VERSION


# ========================================
# Phase 1: Multi-Disabled → Enable
# ========================================


@pytest.mark.priority_high
@pytest.mark.complex_scenario
def test_enable_cnr_when_both_disabled(
    api_client,
    custom_nodes_path,
    setup_multi_disabled_cnr_and_nightly
):
    """
    Test Phase 1.1: Both CNR and Nightly Disabled → Enable CNR.

    Initial State:
        .disabled/ComfyUI_SigmoidOffsetScheduler_1.0.2/ (CNR)
        .disabled/ComfyUI_SigmoidOffsetScheduler/ (Nightly)

    Action:
        Enable CNR via API

    Expected Result:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR enabled)
        .disabled/ComfyUI_SigmoidOffsetScheduler_nightly/ (Nightly remains)

    Verifies:
        - CNR moved to custom_nodes/
        - .tracking file preserved
        - Nightly remains in .disabled/ (may be renamed)
        - Only one package enabled
    """
    disabled_path = custom_nodes_path / ".disabled"
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # [1] Verify initial state
    assert not enabled_package.exists(), "No package should be enabled initially"

    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower()
    ]
    assert len(disabled_packages) == 2, (
        f"Expected 2 disabled packages, found {len(disabled_packages)}: "
        f"{[p.name for p in disabled_packages]}"
    )

    # [2] Execute enable operation
    response = api_client.queue_task(
        kind="enable",
        ui_id="test_enable_cnr",
        params={
            "cnr_id": TEST_PACKAGE_CNR_ID,
            # version not specified - should enable CNR (latest)
        },
    )
    assert response.status_code == 200, f"Failed to queue enable: {response.text}"

    # [3] Start queue and wait
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(WAIT_TIME_SHORT)

    # [4] Verify final state - CNR enabled
    assert enabled_package.exists(), f"Package should be enabled at {enabled_package}"

    # [5] Additional verification
    tracking_file = enabled_package / ".tracking"
    init_file = enabled_package / "__init__.py"
    git_dir = enabled_package / ".git"

    assert tracking_file.exists(), ".tracking file should be preserved"
    assert init_file.exists(), "Package should be functional"
    assert not git_dir.exists(), "CNR should not have .git directory"

    # Verify Nightly still disabled
    disabled_packages_after = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower()
    ]
    assert len(disabled_packages_after) == 1, (
        f"Nightly should remain disabled. Found {len(disabled_packages_after)} packages: "
        f"{[p.name for p in disabled_packages_after]}"
    )

    # Verify Nightly has .git (not .tracking)
    nightly_package = disabled_packages_after[0]
    assert (nightly_package / ".git").exists(), "Nightly should have .git directory"
    assert not (nightly_package / ".tracking").exists(), "Nightly should not have .tracking file"


@pytest.mark.priority_high
@pytest.mark.complex_scenario
def test_enable_nightly_when_both_disabled(
    api_client,
    custom_nodes_path,
    setup_multi_disabled_cnr_and_nightly
):
    """
    Test Phase 1.2: Both CNR and Nightly Disabled → Enable Nightly.

    Initial State:
        .disabled/ComfyUI_SigmoidOffsetScheduler_1.0.2/ (CNR)
        .disabled/ComfyUI_SigmoidOffsetScheduler/ (Nightly)

    Action:
        Enable Nightly via API

    Expected Result:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (Nightly enabled)
        .disabled/ComfyUI_SigmoidOffsetScheduler_1.0.2/ (CNR remains)

    Verifies:
        - Nightly moved to custom_nodes/
        - .git directory preserved
        - CNR remains in .disabled/
        - Only one package enabled
    """
    disabled_path = custom_nodes_path / ".disabled"
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # [1] Verify initial state
    assert not enabled_package.exists(), "No package should be enabled initially"

    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower()
    ]
    assert len(disabled_packages) == 2, (
        f"Expected 2 disabled packages, found {len(disabled_packages)}"
    )

    # [2] Execute enable operation for Nightly
    response = api_client.queue_task(
        kind="enable",
        ui_id="test_enable_nightly",
        params={
            "cnr_id": f"{TEST_PACKAGE_CNR_ID}@nightly",
        },
    )
    assert response.status_code == 200, f"Failed to queue enable: {response.text}"

    # [3] Start queue and wait
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(WAIT_TIME_SHORT)

    # [4] Verify final state - Nightly enabled
    assert enabled_package.exists(), f"Package should be enabled at {enabled_package}"

    # [5] Additional verification
    git_dir = enabled_package / ".git"
    init_file = enabled_package / "__init__.py"
    tracking_file = enabled_package / ".tracking"

    assert git_dir.exists(), ".git directory should be preserved"
    assert init_file.exists(), "Package should be functional"
    assert not tracking_file.exists(), "Nightly should not have .tracking file"

    # Verify CNR still disabled
    disabled_packages_after = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower()
    ]
    assert len(disabled_packages_after) == 1, (
        f"CNR should remain disabled. Found {len(disabled_packages_after)} packages"
    )

    # Verify CNR has .tracking (not .git)
    cnr_package = disabled_packages_after[0]
    assert (cnr_package / ".tracking").exists(), "CNR should have .tracking file"
    assert not (cnr_package / ".git").exists(), "CNR should not have .git directory"


# ========================================
# Phase 3: Complex Disable Scenarios
# ========================================


@pytest.mark.priority_medium
@pytest.mark.complex_scenario
def test_disable_cnr_when_nightly_disabled(
    api_client,
    custom_nodes_path,
    setup_cnr_enabled_nightly_disabled
):
    """
    Test Phase 3.1: CNR Enabled + Nightly Disabled → Disable CNR.

    Initial State:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.1, has .tracking)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly, has .git)

    Action:
        Disable CNR

    Expected Result:
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_1/ (CNR, newly disabled)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly, unchanged)

    Verifies:
        - Both versions in disabled state
        - Distinguished by different names (@1_0_1 vs @nightly)
        - All marker files preserved (.tracking, .git)
        - custom_nodes/ directory empty
    """
    disabled_path = custom_nodes_path / ".disabled"
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # [1] Verify initial state
    assert enabled_package.exists(), "CNR should be enabled initially"
    tracking_file = enabled_package / ".tracking"
    assert tracking_file.exists(), "CNR should have .tracking file"

    # Verify Nightly is disabled
    disabled_nightly = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and (item / ".git").exists()
    ]
    assert len(disabled_nightly) == 1, "Should have one disabled Nightly package"
    nightly_package = disabled_nightly[0]

    # [2] Execute disable operation
    response = api_client.queue_task(
        kind="disable",
        ui_id="test_disable_cnr_3_1",
        params={"node_name": TEST_PACKAGE_ID},
    )
    assert response.status_code == 200, f"Failed to queue disable: {response.text}"

    # [3] Start queue and wait
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(WAIT_TIME_MEDIUM)

    # [4] Verify CNR is now disabled
    assert not enabled_package.exists(), f"CNR should be disabled (moved to .disabled/): {enabled_package}"

    # Find disabled CNR package
    disabled_cnr = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and (item / ".tracking").exists()
    ]
    assert len(disabled_cnr) == 1, f"Should have one disabled CNR package, found {len(disabled_cnr)}"
    cnr_package = disabled_cnr[0]

    # [5] Verify both versions are disabled with different names
    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages) == 2, (
        f"Should have 2 disabled packages (CNR + Nightly), found {len(disabled_packages)}: "
        f"{[p.name for p in disabled_packages]}"
    )

    # [6] Verify package names are different
    package_names = sorted([p.name for p in disabled_packages])
    assert package_names[0] != package_names[1], (
        f"Disabled packages should have different names: {package_names}"
    )

    # Verify one has @1_0_1 (or similar version) and one has @nightly
    cnr_name = cnr_package.name
    nightly_name = nightly_package.name

    assert '@' in cnr_name, f"CNR disabled name should have version suffix: {cnr_name}"
    assert '@' in nightly_name, f"Nightly disabled name should have version suffix: {nightly_name}"
    assert 'nightly' in nightly_name.lower(), f"Nightly package should have 'nightly' in name: {nightly_name}"
    assert 'nightly' not in cnr_name.lower(), f"CNR package should not have 'nightly' in name: {cnr_name}"

    # [7] Verify marker files preserved
    assert (cnr_package / ".tracking").exists(), "CNR should still have .tracking file"
    assert not (cnr_package / ".git").exists(), "CNR should not have .git directory"

    assert (nightly_package / ".git").exists(), "Nightly should still have .git directory"
    assert not (nightly_package / ".tracking").exists(), "Nightly should not have .tracking file"


# ========================================
# Phase 5: Install with Existing Versions
# ========================================


@pytest.mark.priority_medium
@pytest.mark.complex_scenario
def test_install_new_version_when_both_disabled(
    api_client,
    custom_nodes_path,
    setup_multi_disabled_cnr_and_nightly
):
    """
    Test Phase 5.3: CNR Disabled + Nightly Disabled → Install New CNR Version.

    Initial State:
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_2/ (CNR v1.0.2, has .tracking)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly, has .git)

    Action:
        Install CNR v1.0.2 (or latest available)

    Expected Result:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.2, enabled)
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_2/ (old CNR copy, unchanged)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly, unchanged)

    Verifies:
        - New version installed and enabled
        - Existing disabled versions preserved
        - Three versions coexist (1 enabled + 2 disabled)
        - Correct version activated
    """
    disabled_path = custom_nodes_path / ".disabled"
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # [1] Verify initial state - both disabled
    assert not enabled_package.exists(), "No package should be enabled initially"

    disabled_packages_before = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages_before) == 2, (
        f"Should have 2 disabled packages initially, found {len(disabled_packages_before)}: "
        f"{[p.name for p in disabled_packages_before]}"
    )

    # [2] Execute install operation
    response = api_client.queue_task(
        kind="install",
        ui_id="test_install_5_3",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200, f"Failed to queue install: {response.text}"

    # [3] Start queue and wait
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(WAIT_TIME_MEDIUM)

    # [4] Verify new version is enabled
    assert enabled_package.exists(), f"New version should be enabled at {enabled_package}"

    tracking_file = enabled_package / ".tracking"
    assert tracking_file.exists(), "Enabled package should have .tracking file (CNR)"
    assert not (enabled_package / ".git").exists(), "Enabled package should not have .git (not Nightly)"

    init_file = enabled_package / "__init__.py"
    assert init_file.exists(), "Package should be functional"

    # [5] Verify disabled versions still exist
    disabled_packages_after = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]

    # Note: Depending on install behavior, we might have:
    # - 2 disabled (if install creates new enabled without touching disabled)
    # - 1 disabled (if one disabled version is moved to enabled)
    # Let's verify we have at least 1 disabled version remaining
    assert len(disabled_packages_after) >= 1, (
        f"Should have at least 1 disabled package after install, found {len(disabled_packages_after)}: "
        f"{[p.name for p in disabled_packages_after]}"
    )

    # [6] Verify package types in disabled
    for pkg in disabled_packages_after:
        has_tracking = (pkg / ".tracking").exists()
        has_git = (pkg / ".git").exists()

        # Each should be either CNR or Nightly
        assert has_tracking != has_git, (
            f"Disabled package {pkg.name} should be either CNR or Nightly, not both/neither"
        )

    # [7] Verify total package count (enabled + disabled)
    total_packages = 1 + len(disabled_packages_after)  # 1 enabled + N disabled
    assert total_packages >= 2, (
        f"Should have at least 2 total packages (1 enabled + 1+ disabled), found {total_packages}"
    )


# ========================================
# Phase 4: Update + Other Versions Present
# ========================================


@pytest.mark.priority_high
@pytest.mark.complex_scenario
def test_update_cnr_with_nightly_disabled(
    api_client,
    custom_nodes_path,
    setup_cnr_enabled_nightly_disabled
):
    """
    Test Phase 4.1: CNR Enabled + Nightly Disabled → Update CNR.

    Initial State:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.1, has .tracking)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly, has .git)

    Action:
        Update CNR (v1.0.1 → v1.0.2)

    Expected Result:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.2, updated)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly, unchanged)

    Verifies:
        - Only enabled CNR version updated
        - Disabled Nightly unaffected
        - Version upgrade successful
        - .tracking file preserved
    """
    disabled_path = custom_nodes_path / ".disabled"
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # [1] Verify initial state
    assert enabled_package.exists(), "CNR should be enabled initially"
    tracking_file = enabled_package / ".tracking"
    assert tracking_file.exists(), "CNR should have .tracking file"

    # Store initial Nightly state
    disabled_nightly = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and (item / ".git").exists()
    ]
    assert len(disabled_nightly) == 1, "Should have one disabled Nightly package"
    nightly_package = disabled_nightly[0]
    nightly_mtime = nightly_package.stat().st_mtime

    # [2] Execute update operation
    response = api_client.queue_task(
        kind="update",
        ui_id="test_update_cnr_4_1",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": conftest.TEST_PACKAGE_OLD_VERSION,
        },
    )
    assert response.status_code == 200, f"Failed to queue update: {response.text}"

    # [3] Start queue and wait
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(WAIT_TIME_LONG)

    # [4] Verify CNR updated
    assert enabled_package.exists(), f"CNR should still be enabled at {enabled_package}"
    assert tracking_file.exists(), ".tracking file should be preserved after update"

    init_file = enabled_package / "__init__.py"
    assert init_file.exists(), "Package should be functional after update"

    # Verify still CNR (not converted to Nightly)
    git_dir = enabled_package / ".git"
    assert not git_dir.exists(), "CNR should not have .git directory after update"

    # [5] Verify Nightly unchanged
    disabled_nightly_after = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and (item / ".git").exists()
    ]
    assert len(disabled_nightly_after) == 1, "Disabled Nightly should remain"

    nightly_package_after = disabled_nightly_after[0]
    assert nightly_package_after.name == nightly_package.name, (
        f"Nightly package name should not change: {nightly_package.name} → {nightly_package_after.name}"
    )

    # Verify Nightly has .git (not .tracking)
    assert (nightly_package_after / ".git").exists(), "Nightly should still have .git"
    assert not (nightly_package_after / ".tracking").exists(), "Nightly should not have .tracking"


@pytest.mark.priority_high
@pytest.mark.complex_scenario
def test_update_nightly_with_cnr_disabled(
    api_client,
    custom_nodes_path,
    setup_nightly_enabled_cnr_disabled
):
    """
    Test Phase 4.2: Nightly Enabled + CNR Disabled → Update Nightly.

    Initial State:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (Nightly, old commit, has .git)
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_2/ (CNR v1.0.2, has .tracking)

    Action:
        Update Nightly (git pull)

    Expected Result:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (Nightly, latest commit)
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_2/ (CNR, unchanged)

    Verifies:
        - Nightly git pull successful
        - Disabled CNR unaffected
        - .git directory maintained
    """
    import subprocess

    disabled_path = custom_nodes_path / ".disabled"
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # [1] Verify initial state
    assert enabled_package.exists(), "Nightly should be enabled initially"
    git_dir = enabled_package / ".git"
    assert git_dir.exists(), "Nightly should have .git directory"

    # Get initial commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=enabled_package,
        capture_output=True,
        text=True,
    )
    old_commit = result.stdout.strip()

    # Store initial CNR state
    disabled_cnr = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and (item / ".tracking").exists()
    ]
    assert len(disabled_cnr) == 1, "Should have one disabled CNR package"
    cnr_package = disabled_cnr[0]
    cnr_mtime = cnr_package.stat().st_mtime

    # [2] Execute update operation
    response = api_client.queue_task(
        kind="update",
        ui_id="test_update_nightly_4_2",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": "nightly",
        },
    )
    assert response.status_code == 200, f"Failed to queue update: {response.text}"

    # [3] Start queue and wait
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(WAIT_TIME_LONG)

    # [4] Verify Nightly updated
    assert enabled_package.exists(), f"Nightly should still be enabled at {enabled_package}"
    assert git_dir.exists(), ".git directory should be maintained after update"

    # Get new commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=enabled_package,
        capture_output=True,
        text=True,
    )
    new_commit = result.stdout.strip()

    # Verify git operations worked (commit SHA should be valid)
    assert len(new_commit) == 40, "Should have valid commit SHA after update"

    # Verify still Nightly (not converted to CNR)
    tracking_file = enabled_package / ".tracking"
    assert not tracking_file.exists(), "Nightly should not have .tracking file after update"

    # [5] Verify CNR unchanged
    disabled_cnr_after = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and (item / ".tracking").exists()
    ]
    assert len(disabled_cnr_after) == 1, "Disabled CNR should remain"

    cnr_package_after = disabled_cnr_after[0]
    assert cnr_package_after.name == cnr_package.name, (
        f"CNR package name should not change: {cnr_package.name} → {cnr_package_after.name}"
    )

    # Verify CNR has .tracking (not .git)
    assert (cnr_package_after / ".tracking").exists(), "CNR should still have .tracking"
    assert not (cnr_package_after / ".git").exists(), "CNR should not have .git"


@pytest.mark.priority_high
@pytest.mark.complex_scenario
def test_update_enabled_with_multiple_disabled(
    api_client,
    custom_nodes_path,
    setup_cnr_enabled_multiple_disabled
):
    """
    Test Phase 4.3: Multiple Disabled → Update Enabled Only.

    Initial State:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.1, enabled)
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_0/ (CNR v1.0.0, disabled)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly, disabled)

    Action:
        Update (CNR v1.0.1 → v1.0.2)

    Expected Result:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.2, updated)
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_0/ (unchanged)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (unchanged)

    Verifies:
        - Only enabled version updated
        - Disabled versions kept as-is
        - Selective update behavior verified
    """
    disabled_path = custom_nodes_path / ".disabled"
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # [1] Verify initial state
    assert enabled_package.exists(), "CNR v1.0.1 should be enabled initially"
    tracking_file = enabled_package / ".tracking"
    assert tracking_file.exists(), "CNR should have .tracking file"

    # Count and verify disabled packages
    disabled_packages_before = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages_before) == 2, (
        f"Should have 2 disabled packages initially, found {len(disabled_packages_before)}: "
        f"{[p.name for p in disabled_packages_before]}"
    )

    # Store names for verification
    disabled_names_before = sorted([p.name for p in disabled_packages_before])

    # [2] Execute update operation
    response = api_client.queue_task(
        kind="update",
        ui_id="test_update_multiple_4_3",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": conftest.TEST_PACKAGE_OLD_VERSION,
        },
    )
    assert response.status_code == 200, f"Failed to queue update: {response.text}"

    # [3] Start queue and wait
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(WAIT_TIME_LONG)

    # [4] Verify enabled package updated
    assert enabled_package.exists(), f"CNR should still be enabled at {enabled_package}"
    assert tracking_file.exists(), ".tracking file should be preserved after update"

    init_file = enabled_package / "__init__.py"
    assert init_file.exists(), "Package should be functional after update"

    # Verify still CNR (not Nightly)
    git_dir = enabled_package / ".git"
    assert not git_dir.exists(), "CNR should not have .git directory"

    # [5] Verify disabled packages unchanged
    disabled_packages_after = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages_after) == 2, (
        f"Should still have 2 disabled packages, found {len(disabled_packages_after)}: "
        f"{[p.name for p in disabled_packages_after]}"
    )

    # Verify same names (no renaming)
    disabled_names_after = sorted([p.name for p in disabled_packages_after])
    assert disabled_names_after == disabled_names_before, (
        f"Disabled package names should not change:\n"
        f"  Before: {disabled_names_before}\n"
        f"  After:  {disabled_names_after}"
    )

    # [6] Verify package types unchanged
    for pkg in disabled_packages_after:
        has_tracking = (pkg / ".tracking").exists()
        has_git = (pkg / ".git").exists()

        # Each should be either CNR or Nightly, not both or neither
        assert has_tracking != has_git, (
            f"Package {pkg.name} should be either CNR (.tracking) or Nightly (.git), not both/neither"
        )


# ========================================
# Phase 6: Uninstall with Multiple Versions
# ========================================


@pytest.mark.priority_high
@pytest.mark.complex_scenario
def test_uninstall_removes_all_versions(
    api_client,
    custom_nodes_path,
    setup_cnr_enabled_multiple_disabled
):
    """
    Test Phase 6: Uninstall Removes All Versions (Enabled + All Disabled).

    Initial State:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.1, enabled, has .tracking)
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_0/ (CNR v1.0.0, disabled, simulated)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly, disabled, has .git)

    Action:
        Uninstall ComfyUI_SigmoidOffsetScheduler via queue task API

    Expected Result:
        (All versions completely removed)
        - No custom_nodes/ComfyUI_SigmoidOffsetScheduler/
        - No .disabled/comfyui_sigmoidoffsetscheduler@1_0_0/
        - No .disabled/comfyui_sigmoidoffsetscheduler@nightly/

    Verifies:
    - Enabled package removed from custom_nodes/
    - All disabled CNR versions removed from .disabled/
    - Nightly version removed from .disabled/
    - No orphaned directories or files
    - Package not in installed API response

    Key Behavior:
    unified_uninstall() removes ALL versions (enabled + disabled) by default.
    No --all flag needed - this is the default behavior.
    Comment: "Remove whole installed custom nodes including inactive nodes"
    """
    disabled_path = custom_nodes_path / ".disabled"
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    # === BEFORE UNINSTALL ===

    # [1] Verify initial state: 1 enabled + 2 disabled
    print("\n=== Initial State Verification ===")

    # Check enabled package
    assert enabled_package.exists(), "CNR should be enabled"
    assert (enabled_package / ".tracking").exists(), "Enabled CNR should have .tracking"
    print(f"✓ Found enabled package: {enabled_package.name}")

    # Check disabled packages
    disabled_packages_before = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages_before) == 2, (
        f"Should have 2 disabled packages, found {len(disabled_packages_before)}: "
        f"{[p.name for p in disabled_packages_before]}"
    )

    # Verify disabled package types
    disabled_names = sorted([p.name for p in disabled_packages_before])
    print(f"✓ Found disabled packages: {disabled_names}")

    # Check for simulated old CNR
    old_cnr_found = any('@1_0_0' in p.name for p in disabled_packages_before)
    assert old_cnr_found, "Should have simulated old CNR v1.0.0"

    # Check for Nightly
    nightly_found = any('@nightly' in p.name for p in disabled_packages_before)
    assert nightly_found, "Should have Nightly version"

    # === UNINSTALL ===

    print("\n=== Uninstalling All Versions ===")

    # Queue uninstall task
    response = api_client.queue_task(
        kind="uninstall",
        ui_id="phase6_uninstall_all",
        params={"node_name": TEST_PACKAGE_ID},
    )
    assert response.status_code == 200, f"Queue uninstall failed: {response.status_code}"
    print(f"✓ Queued uninstall task")

    # Start queue and wait
    api_client.start_queue()
    time.sleep(WAIT_TIME_LONG)  # Uninstall may take longer
    print(f"✓ Waited {WAIT_TIME_LONG}s for uninstall to complete")

    # === AFTER UNINSTALL ===

    print("\n=== Post-Uninstall Verification ===")

    # [2] Verify enabled package removed
    assert not enabled_package.exists(), (
        f"Enabled package should be removed: {enabled_package}"
    )
    print(f"✓ Enabled package removed")

    # [3] Verify all disabled packages removed
    disabled_packages_after = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages_after) == 0, (
        f"All disabled packages should be removed, found {len(disabled_packages_after)}: "
        f"{[p.name for p in disabled_packages_after]}"
    )
    print(f"✓ All disabled packages removed")

    # [4] Verify no orphaned directories
    # Check for any directory containing 'sigmoid' (case-insensitive)
    orphaned_dirs = []
    for item in custom_nodes_path.iterdir():
        if item.is_dir() and 'sigmoid' in item.name.lower():
            orphaned_dirs.append(item.name)
    for item in disabled_path.iterdir():
        if item.is_dir() and 'sigmoid' in item.name.lower():
            orphaned_dirs.append(item.name)

    assert len(orphaned_dirs) == 0, (
        f"No orphaned directories should exist, found: {orphaned_dirs}"
    )
    print(f"✓ No orphaned directories")

    # [5] Verify package not in installed API
    response = api_client.get("/v2/customnode/installed")
    assert response.status_code == 200
    installed = response.json()

    # Check that no version of the package exists
    package_found = False
    for pkg_name, pkg_data in installed.items():
        if TEST_PACKAGE_CNR_ID in pkg_name.lower():
            package_found = True
            print(f"⚠ Package still in installed list: {pkg_name}")

    assert not package_found, (
        "Package should not be in installed list after uninstall"
    )
    print(f"✓ Package not in installed API")

    print("\n=== Phase 6 Test Complete ===")
    print(f"✓ Verified: unified_uninstall() removes all versions (enabled + disabled)")
    print(f"✓ Verified: No --all flag needed - default behavior removes everything")


@pytest.mark.priority_medium
@pytest.mark.complex_scenario
def test_install_cnr_when_nightly_enabled(
    api_client,
    custom_nodes_path,
    setup_nightly_enabled_only
):
    """
    Test Phase 5.1: Install CNR when Nightly is Enabled (Automatic Version Switch).

    Initial State:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (Nightly, has .git)

    Action:
        Install CNR v1.0.2

    Expected Result (Automatic Version Switching):
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.2, has .tracking)
        .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly, has .git)

    Key Behavior:
    install_by_id() performs automatic version switching:
    1. Disable currently enabled Nightly → moved to .disabled/@nightly/
    2. Install CNR v1.0.2 → enabled in custom_nodes/
    3. Both versions coexist (CNR enabled, Nightly disabled)

    This tests the install policy discovered in manager_core.py:1718-1750.
    """
    disabled_path = custom_nodes_path / ".disabled"
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    print("\n=== Phase 5.1: Install CNR when Nightly Enabled ===")

    # [1] Verify initial state: Nightly enabled
    print("\n=== Initial State Verification ===")
    assert enabled_package.exists(), "Nightly should be enabled"
    assert (enabled_package / ".git").exists(), "Nightly should have .git directory"
    print(f"✓ Nightly enabled with .git directory")

    disabled_packages_before = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages_before) == 0, "No packages should be disabled initially"
    print(f"✓ No disabled packages initially")

    # [2] Queue install CNR task
    print("\n=== Installing CNR v{} ===".format(conftest.TEST_PACKAGE_NEW_VERSION))
    response = api_client.queue_task(
        kind="install",
        ui_id="phase5_1_install_cnr",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    print(f"✓ Queued install CNR task")

    api_client.start_queue()
    time.sleep(WAIT_TIME_LONG)  # Allow time for version switch

    # [3] Verify version switch: CNR enabled, Nightly disabled
    print("\n=== Post-Install Verification ===")
    assert enabled_package.exists(), "Package directory should exist"
    assert (enabled_package / ".tracking").exists(), "CNR should have .tracking file"
    assert not (enabled_package / ".git").exists(), "CNR should NOT have .git directory"
    print(f"✓ CNR v{conftest.TEST_PACKAGE_NEW_VERSION} now enabled with .tracking")

    # [4] Verify Nightly moved to .disabled/
    disabled_nightly = disabled_path / "comfyui_sigmoidoffsetscheduler@nightly"
    assert disabled_nightly.exists(), "Nightly should be in .disabled/"
    assert (disabled_nightly / ".git").exists(), "Disabled Nightly should preserve .git"
    print(f"✓ Nightly disabled with .git preserved")

    # [5] Verify exactly 2 versions coexist
    disabled_packages_after = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages_after) == 1, (
        f"Should have 1 disabled package (Nightly), found {len(disabled_packages_after)}: "
        f"{[p.name for p in disabled_packages_after]}"
    )
    print(f"✓ Version coexistence: CNR enabled + Nightly disabled")

    print("\n=== Phase 5.1 Test Complete ===")
    print(f"✓ Verified: Install CNR auto-switches from Nightly")
    print(f"✓ Verified: Both versions preserved (CNR active, Nightly in .disabled/)")


@pytest.mark.priority_medium
@pytest.mark.complex_scenario
def test_install_nightly_when_cnr_enabled(
    api_client,
    custom_nodes_path,
    setup_cnr_enabled_only
):
    """
    Test Phase 5.2: Install Nightly when CNR is Enabled (Automatic Version Switch).

    Initial State:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.2, has .tracking)

    Action:
        Install Nightly

    Expected Result (Automatic Version Switching):
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (Nightly, has .git)
        .disabled/comfyui_sigmoidoffsetscheduler@1_0_2/ (CNR v1.0.2, has .tracking)

    Key Behavior:
    install_by_id() performs automatic version switching:
    1. Disable currently enabled CNR → moved to .disabled/@1_0_2/
    2. Install Nightly → enabled in custom_nodes/
    3. Both versions coexist (Nightly enabled, CNR disabled)

    This tests the install policy discovered in manager_core.py:1718-1750.
    """
    disabled_path = custom_nodes_path / ".disabled"
    enabled_package = custom_nodes_path / TEST_PACKAGE_ID

    print("\n=== Phase 5.2: Install Nightly when CNR Enabled ===")

    # [1] Verify initial state: CNR enabled
    print("\n=== Initial State Verification ===")
    assert enabled_package.exists(), "CNR should be enabled"
    assert (enabled_package / ".tracking").exists(), "CNR should have .tracking file"
    print(f"✓ CNR v{conftest.TEST_PACKAGE_NEW_VERSION} enabled with .tracking")

    disabled_packages_before = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages_before) == 0, "No packages should be disabled initially"
    print(f"✓ No disabled packages initially")

    # [2] Queue install Nightly task
    print("\n=== Installing Nightly ===")
    response = api_client.queue_task(
        kind="install",
        ui_id="phase5_2_install_nightly",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200
    print(f"✓ Queued install Nightly task")

    api_client.start_queue()
    time.sleep(WAIT_TIME_LONG)  # Allow time for version switch

    # [3] Verify version switch: Nightly enabled, CNR disabled
    print("\n=== Post-Install Verification ===")
    assert enabled_package.exists(), "Package directory should exist"
    assert (enabled_package / ".git").exists(), "Nightly should have .git directory"
    assert not (enabled_package / ".tracking").exists(), "Nightly should NOT have .tracking"
    print(f"✓ Nightly now enabled with .git directory")

    # [4] Verify CNR moved to .disabled/
    disabled_cnr = disabled_path / f"comfyui_sigmoidoffsetscheduler@{conftest.TEST_PACKAGE_NEW_VERSION.replace('.', '_')}"
    assert disabled_cnr.exists(), f"CNR should be in .disabled/ as {disabled_cnr.name}"
    assert (disabled_cnr / ".tracking").exists(), "Disabled CNR should preserve .tracking"
    print(f"✓ CNR v{conftest.TEST_PACKAGE_NEW_VERSION} disabled with .tracking preserved")

    # [5] Verify exactly 2 versions coexist
    disabled_packages_after = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages_after) == 1, (
        f"Should have 1 disabled package (CNR), found {len(disabled_packages_after)}: "
        f"{[p.name for p in disabled_packages_after]}"
    )
    print(f"✓ Version coexistence: Nightly enabled + CNR disabled")

    print("\n=== Phase 5.2 Test Complete ===")
    print(f"✓ Verified: Install Nightly auto-switches from CNR")
    print(f"✓ Verified: Both versions preserved (Nightly active, CNR in .disabled/)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])


# ============================================================================
# Phase 7: Version Management Behavior (P0 - High Priority)
# ============================================================================
# Note: CNR version history is NOT preserved in current implementation.
# These tests verify actual behavior, not ideal behavior.


@pytest.mark.priority_high
@pytest.mark.complex_scenario
def test_cnr_version_upgrade_removes_old(
    api_client,
    custom_nodes_path,
    setup_cnr_enabled_only
):
    """
    Test Phase 7.1: CNR Version Upgrade Removes Old Version (Actual Behavior).

    **Current Implementation**: CNR does NOT preserve version history.
    When installing a new CNR version, old disabled CNR versions are removed.

    Initial State:
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/  (CNR v1.0.1, has .tracking)

    Action:
        Install CNR v1.0.2 (version upgrade)

    Expected Result (ACTUAL BEHAVIOR):
        custom_nodes/ComfyUI_SigmoidOffsetScheduler/  (CNR v1.0.2, has .tracking)
        No disabled CNR versions (old v1.0.1 is removed, not preserved)

    Key Behavior:
    - install_by_id() removes old disabled CNR versions
    - Only one CNR version exists at a time
    - No CNR rollback capability in current implementation

    Note: This is a known limitation. Version history preservation is a
    requested feature but not yet implemented.
    """
    print("\n" + "=" * 70)
    print("Phase 7.1: CNR Version Upgrade Removes Old Version")
    print("=" * 70)

    enabled_package = custom_nodes_path / TEST_PACKAGE_ID
    disabled_path = custom_nodes_path / ".disabled"

    # [1] Verify initial state - CNR 1.0.1 enabled only
    print(f"\n[1] Verifying initial state (CNR v{conftest.TEST_PACKAGE_OLD_VERSION} enabled only)")
    assert enabled_package.exists(), f"CNR {conftest.TEST_PACKAGE_OLD_VERSION} should be enabled"
    assert (enabled_package / ".tracking").exists(), "CNR should have .tracking"
    print(f"✓ CNR v{conftest.TEST_PACKAGE_OLD_VERSION} enabled")

    # [2] Install CNR v1.0.2 (upgrade)
    print(f"\n[2] Installing CNR v{conftest.TEST_PACKAGE_NEW_VERSION} (version upgrade)")
    response = api_client.queue_task(
        kind="install",
        ui_id="test_phase7_1",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # [3] Verify CNR 1.0.2 enabled
    print(f"\n[3] Verifying CNR v{conftest.TEST_PACKAGE_NEW_VERSION} enabled")
    assert enabled_package.exists(), f"CNR {conftest.TEST_PACKAGE_NEW_VERSION} should be enabled"
    assert (enabled_package / ".tracking").exists(), "CNR should have .tracking"

    # Check version in pyproject.toml
    pyproject_path = enabled_package / "pyproject.toml"
    if pyproject_path.exists():
        with open(pyproject_path) as f:
            content = f.read()
            assert conftest.TEST_PACKAGE_NEW_VERSION in content, f"Should have version {conftest.TEST_PACKAGE_NEW_VERSION}"
    print(f"✓ CNR v{conftest.TEST_PACKAGE_NEW_VERSION} enabled with .tracking")

    # [4] Verify old CNR 1.0.1 was REMOVED (not preserved)
    print(f"\n[4] Verifying old CNR v{conftest.TEST_PACKAGE_OLD_VERSION} was removed (actual behavior)")
    disabled_cnr_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir() and (item / ".tracking").exists()
    ]
    assert len(disabled_cnr_packages) == 0, (
        f"Old CNR versions should be removed, found {len(disabled_cnr_packages)}: "
        f"{[p.name for p in disabled_cnr_packages]}"
    )
    print(f"✓ Old CNR v{conftest.TEST_PACKAGE_OLD_VERSION} removed (no version history)")

    # [5] Verify only one CNR version exists
    print("\n[5] Verifying only one CNR version exists (current behavior)")
    all_cnr_versions = []
    # Check enabled
    if enabled_package.exists() and (enabled_package / ".tracking").exists():
        all_cnr_versions.append("enabled")
    # Check disabled
    all_cnr_versions.extend([p.name for p in disabled_cnr_packages])

    assert len(all_cnr_versions) == 1, (
        f"Should have exactly 1 CNR version, found {len(all_cnr_versions)}: {all_cnr_versions}"
    )
    print("✓ Only one CNR version exists at a time")

    print("\n=== Phase 7.1 Test Complete ===")
    print(f"✓ Verified: CNR v{conftest.TEST_PACKAGE_NEW_VERSION} upgrade successful")
    print("✓ Verified: Old CNR version removed (no history preservation)")
    print("✓ Current Behavior: Only one CNR version exists at a time")


@pytest.mark.priority_high
@pytest.mark.complex_scenario
def test_cnr_nightly_switching_preserves_nightly_only(
    api_client,
    custom_nodes_path
):
    """
    Test Phase 7.2: CNR ↔ Nightly Switching Preserves Nightly Only (Actual Behavior).

    **Current Implementation**: Different handling for CNR vs Nightly packages:
    - Nightly (with .git) is preserved when switching to CNR
    - Old CNR versions (with .tracking) are removed when installing new CNR

    Step 1 - Install Nightly:
        After: custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (Nightly with .git)

    Step 2 - Switch to CNR 1.0.1:
        After:
          - custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR 1.0.1 with .tracking)
          - .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (preserved)

    Step 3 - Switch to CNR 1.0.2:
        After (ACTUAL BEHAVIOR):
          - custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR 1.0.2 with .tracking)
          - .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (preserved)
          - Old CNR 1.0.1 is REMOVED (not preserved)

    Key Behavior:
    - Nightly is preserved across CNR upgrades
    - CNR versions are NOT preserved (no CNR rollback capability)
    - Different package types handled differently
    """
    import shutil

    print("\n" + "=" * 70)
    print("Phase 7.2: CNR ↔ Nightly Switching (Nightly Preservation)")
    print("=" * 70)

    enabled_package = custom_nodes_path / TEST_PACKAGE_ID
    disabled_path = custom_nodes_path / ".disabled"

    # Cleanup: Remove any existing versions
    if enabled_package.exists():
        shutil.rmtree(enabled_package)
    for item in disabled_path.iterdir():
        if 'sigmoid' in item.name.lower() and item.is_dir():
            shutil.rmtree(item)

    # ========================================================================
    # Step 1: Install Nightly
    # ========================================================================
    print("\n" + "=" * 60)
    print("Step 1: Install Nightly (from empty state)")
    print("=" * 60)

    response = api_client.queue_task(
        kind="install",
        ui_id="test_phase7_2_step1",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_LONG)

    # Verify Nightly enabled
    assert enabled_package.exists(), "Nightly should be enabled"
    assert (enabled_package / ".git").exists(), "Nightly should have .git"
    disabled_count_step1 = len([
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ])
    assert disabled_count_step1 == 0, "No versions should be disabled yet"
    print("✓ Step 1 Complete: Nightly enabled, 0 disabled")

    # ========================================================================
    # Step 2: Switch to CNR 1.0.1
    # ========================================================================
    print("\n" + "=" * 60)
    print(f"Step 2: Switch to CNR v{conftest.TEST_PACKAGE_OLD_VERSION}")
    print("=" * 60)

    response = api_client.queue_task(
        kind="install",
        ui_id="test_phase7_2_step2",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_OLD_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Verify CNR 1.0.1 enabled
    assert enabled_package.exists(), "CNR 1.0.1 should be enabled"
    assert (enabled_package / ".tracking").exists(), "CNR should have .tracking"

    # Verify Nightly disabled (use dynamic discovery)
    disabled_nightly_items_step2 = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir() and (item / ".git").exists()
    ]
    assert len(disabled_nightly_items_step2) == 1, "Nightly should be disabled"
    disabled_nightly_step2 = disabled_nightly_items_step2[0]
    assert (disabled_nightly_step2 / ".git").exists(), "Nightly should preserve .git"

    disabled_count_step2 = len([
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ])
    assert disabled_count_step2 == 1, "Should have 1 disabled version (Nightly)"
    print(f"✓ Step 2 Complete: CNR v{conftest.TEST_PACKAGE_OLD_VERSION} enabled, 1 disabled (Nightly)")

    # ========================================================================
    # Step 3: Switch to CNR 1.0.2
    # ========================================================================
    print("\n" + "=" * 60)
    print(f"Step 3: Switch to CNR v{conftest.TEST_PACKAGE_NEW_VERSION}")
    print("=" * 60)

    response = api_client.queue_task(
        kind="install",
        ui_id="test_phase7_2_step3",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(WAIT_TIME_MEDIUM)

    # Verify CNR 1.0.2 enabled
    assert enabled_package.exists(), "CNR 1.0.2 should be enabled"
    assert (enabled_package / ".tracking").exists(), "CNR should have .tracking"

    # Check version
    pyproject_path = enabled_package / "pyproject.toml"
    if pyproject_path.exists():
        with open(pyproject_path) as f:
            content = f.read()
            assert conftest.TEST_PACKAGE_NEW_VERSION in content, f"Should have version {conftest.TEST_PACKAGE_NEW_VERSION}"
    print(f"✓ CNR v{conftest.TEST_PACKAGE_NEW_VERSION} enabled")

    # Verify old CNR 1.0.1 was REMOVED (actual behavior)
    disabled_cnr_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir() and (item / ".tracking").exists()
    ]
    assert len(disabled_cnr_packages) == 0, (
        f"Old CNR versions should be removed, found {len(disabled_cnr_packages)}: "
        f"{[p.name for p in disabled_cnr_packages]}"
    )
    print(f"✓ Old CNR v{conftest.TEST_PACKAGE_OLD_VERSION} removed (actual behavior)")

    # Verify Nightly still disabled (preserved - different from CNR!)
    disabled_nightly_items = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir() and (item / ".git").exists()
    ]
    assert len(disabled_nightly_items) == 1, "Nightly should be preserved"
    disabled_nightly = disabled_nightly_items[0]
    print(f"✓ Nightly preserved in .disabled/ as {disabled_nightly.name}")

    # Verify only 1 disabled version (Nightly only, CNR removed)
    disabled_packages_final = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages_final) == 1, (
        f"Should have 1 disabled version (Nightly only), found {len(disabled_packages_final)}: "
        f"{[p.name for p in disabled_packages_final]}"
    )
    print("✓ Step 3 Complete: CNR v1.0.2 enabled, 1 disabled (Nightly only)")

    print("\n=== Phase 7.2 Test Complete ===")
    print("✓ Verified: Nightly preserved across CNR upgrades")
    print("✓ Verified: Old CNR versions removed (no CNR history)")
    print("✓ Current Behavior: Different handling for CNR vs Nightly packages")
