"""
Test cases for Enable/Disable API endpoints.

Tests enable/disable operations through /v2/manager/queue/task with kind="enable"/"disable"
"""

import os
import time
from pathlib import Path

import pytest


# Test package configuration
TEST_PACKAGE_ID = "ComfyUI_SigmoidOffsetScheduler"
TEST_PACKAGE_CNR_ID = "comfyui_sigmoidoffsetscheduler"  # lowercase for operations
TEST_PACKAGE_VERSION = "1.0.2"


@pytest.fixture
def setup_package_for_disable(api_client, custom_nodes_path):
    """Install a CNR package for disable testing."""
    # Install CNR package first
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_disable_test",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(8)

    # Verify installed
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    assert package_path.exists(), "Package should be installed before disable test"

    yield

    # Cleanup - remove all versions
    import shutil
    if package_path.exists():
        shutil.rmtree(package_path)

    disabled_base = custom_nodes_path / ".disabled"
    if disabled_base.exists():
        for item in disabled_base.iterdir():
            if 'sigmoid' in item.name.lower():
                shutil.rmtree(item)


@pytest.fixture
def setup_package_for_enable(api_client, custom_nodes_path):
    """Install and disable a CNR package for enable testing."""
    import shutil

    package_path = custom_nodes_path / TEST_PACKAGE_ID
    disabled_base = custom_nodes_path / ".disabled"

    # Cleanup BEFORE test - remove all existing versions
    def _cleanup():
        if package_path.exists():
            shutil.rmtree(package_path)

        if disabled_base.exists():
            for item in disabled_base.iterdir():
                if 'sigmoid' in item.name.lower():
                    shutil.rmtree(item)

        # Small delay to ensure filesystem operations complete
        time.sleep(0.5)

    # Clean up any leftover packages from previous tests
    _cleanup()

    # Install CNR package first
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_enable_test_install",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(8)

    # Disable the package
    response = api_client.queue_task(
        kind="disable",
        ui_id="setup_enable_test_disable",
        params={
            "node_name": TEST_PACKAGE_ID,
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(3)

    # Verify disabled
    assert not package_path.exists(), "Package should be disabled before enable test"

    yield

    # Cleanup AFTER test - remove all versions
    _cleanup()


@pytest.mark.priority_high
def test_disable_package(api_client, custom_nodes_path, setup_package_for_disable):
    """
    Test disabling a package (move to .disabled/).

    Verifies:
    - Package moves from custom_nodes/ to .disabled/
    - Marker files (.tracking) are preserved
    - Package no longer in enabled location
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    disabled_base = custom_nodes_path / ".disabled"

    # Verify package is enabled before disable
    assert package_path.exists(), "Package should be enabled initially"
    tracking_file = package_path / ".tracking"
    has_tracking = tracking_file.exists()

    # Disable the package
    response = api_client.queue_task(
        kind="disable",
        ui_id="test_disable",
        params={
            "node_name": TEST_PACKAGE_ID,
        },
    )
    assert response.status_code == 200, f"Failed to queue disable task: {response.text}"

    # Start queue
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for disable to complete
    time.sleep(3)

    # Verify package is disabled
    assert not package_path.exists(), f"Package should not exist in enabled location: {package_path}"

    # Verify package exists in .disabled/
    assert disabled_base.exists(), ".disabled/ directory should exist"

    disabled_packages = [item for item in disabled_base.iterdir() if 'sigmoid' in item.name.lower()]
    assert len(disabled_packages) == 1, f"Expected 1 disabled package, found {len(disabled_packages)}"

    disabled_package = disabled_packages[0]

    # Verify marker files are preserved
    if has_tracking:
        disabled_tracking = disabled_package / ".tracking"
        assert disabled_tracking.exists(), ".tracking file should be preserved in disabled package"


@pytest.mark.priority_high
def test_enable_package(api_client, custom_nodes_path, setup_package_for_enable):
    """
    Test enabling a disabled package (restore from .disabled/).

    Verifies:
    - Package moves from .disabled/ to custom_nodes/
    - Marker files (.tracking) are preserved
    - Package is functional in enabled location
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    disabled_base = custom_nodes_path / ".disabled"

    # Verify package is disabled before enable
    assert not package_path.exists(), "Package should be disabled initially"

    disabled_packages = [item for item in disabled_base.iterdir() if 'sigmoid' in item.name.lower()]
    assert len(disabled_packages) == 1, "One disabled package should exist"

    disabled_package = disabled_packages[0]
    has_tracking = (disabled_package / ".tracking").exists()

    # Enable the package
    response = api_client.queue_task(
        kind="enable",
        ui_id="test_enable",
        params={
            "cnr_id": TEST_PACKAGE_CNR_ID,
        },
    )
    assert response.status_code == 200, f"Failed to queue enable task: {response.text}"

    # Start queue
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for enable to complete
    time.sleep(3)

    # Verify package is enabled
    assert package_path.exists(), f"Package should exist in enabled location: {package_path}"

    # Verify package removed from .disabled/
    disabled_packages_after = [item for item in disabled_base.iterdir() if 'sigmoid' in item.name.lower()]
    assert len(disabled_packages_after) == 0, f"Expected 0 disabled packages, found {len(disabled_packages_after)}"

    # Verify marker files are preserved
    if has_tracking:
        tracking_file = package_path / ".tracking"
        assert tracking_file.exists(), ".tracking file should be preserved after enable"


@pytest.mark.priority_high
def test_duplicate_disable(api_client, custom_nodes_path, setup_package_for_disable):
    """
    Test duplicate disable operations (should skip).

    Verifies:
    - First disable succeeds
    - Second disable on already-disabled package skips without error
    - Package state remains unchanged
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    disabled_base = custom_nodes_path / ".disabled"

    # First disable
    response = api_client.queue_task(
        kind="disable",
        ui_id="test_duplicate_disable_1",
        params={
            "node_name": TEST_PACKAGE_ID,
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(3)

    # Verify first disable succeeded
    assert not package_path.exists(), "Package should be disabled after first disable"
    disabled_packages = [item for item in disabled_base.iterdir() if 'sigmoid' in item.name.lower()]
    assert len(disabled_packages) == 1, "One disabled package should exist"

    # Second disable (duplicate)
    response = api_client.queue_task(
        kind="disable",
        ui_id="test_duplicate_disable_2",
        params={
            "node_name": TEST_PACKAGE_ID,
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(3)

    # Verify state unchanged - still disabled
    assert not package_path.exists(), "Package should remain disabled"
    disabled_packages_after = [item for item in disabled_base.iterdir() if 'sigmoid' in item.name.lower()]
    assert len(disabled_packages_after) == 1, "Still should have one disabled package"


@pytest.mark.priority_high
def test_duplicate_enable(api_client, custom_nodes_path, setup_package_for_enable):
    """
    Test duplicate enable operations (should skip).

    Verifies:
    - First enable succeeds
    - Second enable on already-enabled package skips without error
    - Package state remains unchanged
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    disabled_base = custom_nodes_path / ".disabled"

    # First enable
    response = api_client.queue_task(
        kind="enable",
        ui_id="test_duplicate_enable_1",
        params={
            "cnr_id": TEST_PACKAGE_CNR_ID,
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(3)

    # Verify first enable succeeded
    assert package_path.exists(), "Package should be enabled after first enable"
    disabled_packages = [item for item in disabled_base.iterdir() if 'sigmoid' in item.name.lower()]
    assert len(disabled_packages) == 0, "No disabled packages should exist"

    # Second enable (duplicate)
    response = api_client.queue_task(
        kind="enable",
        ui_id="test_duplicate_enable_2",
        params={
            "cnr_id": TEST_PACKAGE_CNR_ID,
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(3)

    # Verify state unchanged - still enabled
    assert package_path.exists(), "Package should remain enabled"
    disabled_packages_after = [item for item in disabled_base.iterdir() if 'sigmoid' in item.name.lower()]
    assert len(disabled_packages_after) == 0, "Still should have no disabled packages"


@pytest.mark.priority_high
def test_enable_disable_cycle(api_client, custom_nodes_path):
    """
    Test complete enable/disable cycle.

    Verifies:
    - Install → Disable → Enable → Disable works correctly
    - Marker files preserved throughout cycle
    - No orphaned packages after multiple cycles
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    disabled_base = custom_nodes_path / ".disabled"

    # Step 1: Install CNR package
    response = api_client.queue_task(
        kind="install",
        ui_id="test_cycle_install",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(8)

    assert package_path.exists(), "Package should be installed"
    tracking_file = package_path / ".tracking"
    assert tracking_file.exists(), "CNR package should have .tracking file"

    # Step 2: Disable
    response = api_client.queue_task(
        kind="disable",
        ui_id="test_cycle_disable_1",
        params={"node_name": TEST_PACKAGE_ID},
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(3)

    assert not package_path.exists(), "Package should be disabled"

    # Step 3: Enable
    response = api_client.queue_task(
        kind="enable",
        ui_id="test_cycle_enable",
        params={"cnr_id": TEST_PACKAGE_CNR_ID},
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(3)

    assert package_path.exists(), "Package should be enabled again"
    assert tracking_file.exists(), ".tracking file should be preserved"

    # Step 4: Disable again
    response = api_client.queue_task(
        kind="disable",
        ui_id="test_cycle_disable_2",
        params={"node_name": TEST_PACKAGE_ID},
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(3)

    assert not package_path.exists(), "Package should be disabled again"

    # Verify no orphaned packages
    disabled_packages = [item for item in disabled_base.iterdir() if 'sigmoid' in item.name.lower()]
    assert len(disabled_packages) == 1, f"Expected exactly 1 disabled package, found {len(disabled_packages)}"

    # Cleanup
    import shutil
    for item in disabled_packages:
        shutil.rmtree(item)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
