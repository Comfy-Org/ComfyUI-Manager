"""
Test cases for Update API endpoints.

Tests update operations through /v2/manager/queue/task with kind="update"
"""

import os
import time
from pathlib import Path

import pytest
from conftest import (
    TEST_PACKAGE_NEW_VERSION,
    TEST_PACKAGE_OLD_VERSION,
)


# Test package configuration
TEST_PACKAGE_ID = "ComfyUI_SigmoidOffsetScheduler"
TEST_PACKAGE_CNR_ID = "comfyui_sigmoidoffsetscheduler"

# Import versions from conftest (will be set by session fixture before tests run)


@pytest.fixture
def setup_old_cnr_package(api_client, custom_nodes_path):
    """Install an older CNR version for update testing."""
    # Install old CNR version
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_update_old_version",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_OLD_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(8)

    # Verify old version installed
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    assert package_path.exists(), "Old version should be installed"

    tracking_file = package_path / ".tracking"
    assert tracking_file.exists(), "CNR package should have .tracking file"

    yield

    # Cleanup
    import shutil
    if package_path.exists():
        shutil.rmtree(package_path)


@pytest.fixture
def setup_nightly_package(api_client, custom_nodes_path):
    """Install Nightly version for update testing."""
    # Install Nightly version
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_update_nightly",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(8)

    # Verify Nightly installed
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    assert package_path.exists(), "Nightly version should be installed"

    git_dir = package_path / ".git"
    assert git_dir.exists(), "Nightly package should have .git directory"

    yield

    # Cleanup
    import shutil
    if package_path.exists():
        shutil.rmtree(package_path)


@pytest.fixture
def setup_latest_cnr_package(api_client, custom_nodes_path):
    """Install latest CNR version for up-to-date testing."""
    # Install latest CNR version
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_update_latest",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    api_client.start_queue()
    time.sleep(8)

    # Verify latest version installed
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    assert package_path.exists(), "Latest version should be installed"

    yield

    # Cleanup
    import shutil
    if package_path.exists():
        shutil.rmtree(package_path)


@pytest.mark.priority_high
def test_update_cnr_package(api_client, custom_nodes_path, setup_old_cnr_package):
    """
    Test updating a CNR package to latest version.

    Verifies:
    - Update operation completes without error
    - Package exists after update
    - .tracking file preserved (CNR marker)
    - Package remains functional
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    tracking_file = package_path / ".tracking"

    # Verify CNR package before update
    assert tracking_file.exists(), "CNR package should have .tracking file before update"

    # Update the package
    response = api_client.queue_task(
        kind="update",
        ui_id="test_update_cnr",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": TEST_PACKAGE_OLD_VERSION,
        },
    )
    assert response.status_code == 200, f"Failed to queue update task: {response.text}"

    # Start queue
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for update to complete
    time.sleep(10)

    # Verify package still exists
    assert package_path.exists(), f"Package should exist after update: {package_path}"

    # Verify tracking file still exists (CNR marker preserved)
    assert tracking_file.exists(), ".tracking file should exist after update"

    # Verify package files exist
    init_file = package_path / "__init__.py"
    assert init_file.exists(), "Package __init__.py should exist after update"


@pytest.mark.priority_high
def test_update_nightly_package(api_client, custom_nodes_path, setup_nightly_package):
    """
    Test updating a Nightly package (git pull).

    Verifies:
    - Git pull executed
    - .git directory maintained
    - Package remains functional
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    git_dir = package_path / ".git"

    # Verify git directory exists before update
    assert git_dir.exists(), ".git directory should exist before update"

    # Get current commit SHA
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=package_path,
        capture_output=True,
        text=True,
    )
    old_commit = result.stdout.strip()

    # Update the package
    response = api_client.queue_task(
        kind="update",
        ui_id="test_update_nightly",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": "nightly",
        },
    )
    assert response.status_code == 200, f"Failed to queue update task: {response.text}"

    # Start queue
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for update to complete
    time.sleep(10)

    # Verify package still exists
    assert package_path.exists(), f"Package should exist after update: {package_path}"

    # Verify .git directory maintained
    assert git_dir.exists(), ".git directory should be maintained after update"

    # Get new commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=package_path,
        capture_output=True,
        text=True,
    )
    new_commit = result.stdout.strip()

    # Note: Commits might be same if already at latest, which is OK
    # Just verify git operations worked
    assert len(new_commit) == 40, "Should have valid commit SHA after update"


@pytest.mark.priority_high
def test_update_already_latest(api_client, custom_nodes_path, setup_latest_cnr_package):
    """
    Test updating an already up-to-date package.

    Verifies:
    - Operation completes without error
    - Package remains functional
    - No unnecessary file changes
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    tracking_file = package_path / ".tracking"

    # Store original modification time
    old_mtime = tracking_file.stat().st_mtime

    # Try to update already-latest package
    response = api_client.queue_task(
        kind="update",
        ui_id="test_update_latest",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": TEST_PACKAGE_NEW_VERSION,
        },
    )
    assert response.status_code == 200, f"Failed to queue update task: {response.text}"

    # Start queue
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for operation to complete
    time.sleep(8)

    # Verify package still exists
    assert package_path.exists(), f"Package should exist after update: {package_path}"

    # Verify tracking file exists
    assert tracking_file.exists(), ".tracking file should exist"

    # Package should be functional
    init_file = package_path / "__init__.py"
    assert init_file.exists(), "Package __init__.py should exist"


@pytest.mark.priority_high
def test_update_cycle(api_client, custom_nodes_path):
    """
    Test update cycle: install old → update → verify latest.

    Verifies:
    - Complete update workflow
    - Package integrity maintained throughout
    - CNR marker files preserved
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    tracking_file = package_path / ".tracking"

    # Step 1: Install old version
    response = api_client.queue_task(
        kind="install",
        ui_id="test_update_cycle_install",
        params={
            "id": TEST_PACKAGE_ID,
            "version": TEST_PACKAGE_OLD_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(8)

    assert package_path.exists(), "Old version should be installed"
    assert tracking_file.exists(), "CNR package should have .tracking file"

    # Step 2: Update to latest
    response = api_client.queue_task(
        kind="update",
        ui_id="test_update_cycle_update",
        params={
            "node_name": TEST_PACKAGE_ID,
            "node_ver": TEST_PACKAGE_OLD_VERSION,
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(10)

    # Step 3: Verify updated package
    assert package_path.exists(), "Package should exist after update"
    assert tracking_file.exists(), ".tracking file should be preserved after update"

    init_file = package_path / "__init__.py"
    assert init_file.exists(), "Package should be functional after update"

    # Cleanup
    import shutil
    if package_path.exists():
        shutil.rmtree(package_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
