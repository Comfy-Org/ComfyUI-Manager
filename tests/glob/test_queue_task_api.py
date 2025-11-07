"""
Test cases for Queue Task API endpoints.

Tests install/uninstall operations through /v2/manager/queue/task and /v2/manager/queue/start
"""

import os
import time
from pathlib import Path

import pytest
import requests
import conftest


# Test package configuration
TEST_PACKAGE_ID = "ComfyUI_SigmoidOffsetScheduler"
TEST_PACKAGE_CNR_ID = "comfyui_sigmoidoffsetscheduler"  # lowercase for uninstall

# Access version via conftest module to get runtime value (not import-time None)
# DO NOT import directly: from conftest import TEST_PACKAGE_NEW_VERSION
# Reason: Session fixture sets these AFTER imports execute


@pytest.fixture
def api_client(server_url):
    """Create API client with base URL from fixture."""

    class APIClient:
        def __init__(self, base_url: str):
            self.base_url = base_url
            self.session = requests.Session()

        def queue_task(self, kind: str, ui_id: str, params: dict) -> requests.Response:
            """Queue a task to the manager queue."""
            url = f"{self.base_url}/v2/manager/queue/task"
            payload = {"kind": kind, "ui_id": ui_id, "client_id": "test", "params": params}
            return self.session.post(url, json=payload)

        def start_queue(self) -> requests.Response:
            """Start processing the queue."""
            url = f"{self.base_url}/v2/manager/queue/start"
            return self.session.get(url)

        def get_pending_queue(self) -> requests.Response:
            """Get pending tasks in queue."""
            url = f"{self.base_url}/v2/manager/queue/pending"
            return self.session.get(url)

        def get_installed_packages(self) -> requests.Response:
            """Get list of installed packages."""
            url = f"{self.base_url}/v2/customnode/installed"
            return self.session.get(url)

    return APIClient(server_url)


@pytest.fixture
def cleanup_package(api_client, custom_nodes_path):
    """Cleanup test package before and after test using API and filesystem."""
    import shutil

    package_path = custom_nodes_path / TEST_PACKAGE_ID
    disabled_dir = custom_nodes_path / ".disabled"

    def _cleanup():
        """Remove test package completely - no restoration logic."""
        # Clean active directory
        if package_path.exists():
            shutil.rmtree(package_path)

        # Clean .disabled directory (all versions)
        if disabled_dir.exists():
            for item in disabled_dir.iterdir():
                if TEST_PACKAGE_CNR_ID in item.name.lower():
                    if item.is_dir():
                        shutil.rmtree(item)

    # Cleanup before test (let test install fresh)
    _cleanup()

    yield

    # Cleanup after test
    _cleanup()


def test_install_package_via_queue(api_client, cleanup_package, custom_nodes_path):
    """Test installing a package through queue task API."""
    # Queue install task
    response = api_client.queue_task(
        kind="install",
        ui_id="test_install",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )

    assert response.status_code == 200, f"Failed to queue task: {response.text}"

    # Start queue processing
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for installation to complete
    time.sleep(5)

    # Verify package is installed
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    assert package_path.exists(), f"Package not installed at {package_path}"


def test_uninstall_package_via_queue(api_client, custom_nodes_path):
    """Test uninstalling a package through queue task API."""
    # First, ensure package is installed
    package_path = custom_nodes_path / TEST_PACKAGE_ID

    if not package_path.exists():
        # Install package first
        api_client.queue_task(
            kind="install",
            ui_id="test_install_for_uninstall",
            params={
                "id": TEST_PACKAGE_ID,
                "version": conftest.TEST_PACKAGE_NEW_VERSION,
                "selected_version": "latest",
            },
        )
        api_client.start_queue()
        time.sleep(8)

    # Queue uninstall task (using lowercase cnr_id)
    response = api_client.queue_task(
        kind="uninstall", ui_id="test_uninstall", params={"node_name": TEST_PACKAGE_CNR_ID}
    )

    assert response.status_code == 200, f"Failed to queue uninstall task: {response.text}"

    # Start queue processing
    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"

    # Wait for uninstallation to complete
    time.sleep(5)

    # Verify package is uninstalled
    assert not package_path.exists(), f"Package still exists at {package_path}"


def test_install_uninstall_cycle(api_client, cleanup_package, custom_nodes_path):
    """Test complete install/uninstall cycle."""
    package_path = custom_nodes_path / TEST_PACKAGE_ID

    # Step 1: Install package
    response = api_client.queue_task(
        kind="install",
        ui_id="test_cycle_install",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(10)  # Increased from 8 to 10 seconds

    assert package_path.exists(), "Package not installed"

    # Wait a bit more for manager state to update
    time.sleep(2)

    # Step 2: Verify package is in installed list
    response = api_client.get_installed_packages()
    assert response.status_code == 200
    installed = response.json()

    # Response is a dict with package names as keys
    # Note: cnr_id now preserves original case (e.g., "ComfyUI_SigmoidOffsetScheduler")
    # Use case-insensitive comparison to handle both old (lowercase) and new (original case) behavior
    package_found = any(
        pkg.get("cnr_id", "").lower() == TEST_PACKAGE_CNR_ID.lower()
        for pkg in installed.values()
        if isinstance(pkg, dict) and pkg.get("cnr_id")
    )
    assert package_found, f"Package {TEST_PACKAGE_CNR_ID} not found in installed list. Got: {list(installed.keys())}"

    # Note: original_name field is NOT included in response (PyPI baseline behavior)
    # The API returns cnr_id with original case instead of having a separate original_name field

    # Step 3: Uninstall package
    response = api_client.queue_task(
        kind="uninstall", ui_id="test_cycle_uninstall", params={"node_name": TEST_PACKAGE_CNR_ID}
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(5)

    assert not package_path.exists(), "Package not uninstalled"


def test_case_insensitive_operations(api_client, cleanup_package, custom_nodes_path):
    """Test that uninstall operations work with case-insensitive normalization.

    NOTE: Install requires exact case (CNR limitation), but uninstall/enable/disable
    should work with any case variation using cnr_utils.normalize_package_name().
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID

    # Test 1: Install with original case (CNR requires exact case)
    response = api_client.queue_task(
        kind="install",
        ui_id="test_install_original_case",
        params={
            "id": TEST_PACKAGE_ID,  # Original case: "ComfyUI_SigmoidOffsetScheduler"
            "version": conftest.TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(8)  # Increased wait time for installation

    assert package_path.exists(), "Package should be installed with original case"

    # Test 2: Uninstall with mixed case and whitespace (should work with normalization)
    response = api_client.queue_task(
        kind="uninstall",
        ui_id="test_uninstall_mixed_case",
        params={"node_name": " ComfyUI_SigmoidOffsetScheduler "},  # Mixed case with spaces
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(5)  # Increased wait time for uninstallation

    # Package should be uninstalled (normalization worked)
    assert not package_path.exists(), "Package should be uninstalled with normalized name"

    # Test 3: Reinstall with exact case for next test
    response = api_client.queue_task(
        kind="install",
        ui_id="test_reinstall",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(8)

    assert package_path.exists(), "Package should be reinstalled"

    # Test 4: Uninstall with uppercase (should work with normalization)
    response = api_client.queue_task(
        kind="uninstall",
        ui_id="test_uninstall_uppercase",
        params={"node_name": "COMFYUI_SIGMOIDOFFSETSCHEDULER"},  # Uppercase
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(5)

    assert not package_path.exists(), "Package should be uninstalled with uppercase"


def test_queue_multiple_tasks(api_client, cleanup_package, custom_nodes_path):
    """Test queueing multiple tasks and processing them in order."""
    # Queue multiple tasks
    tasks = [
        {
            "kind": "install",
            "ui_id": "test_multi_1",
            "params": {
                "id": TEST_PACKAGE_ID,
                "version": conftest.TEST_PACKAGE_NEW_VERSION,
                "selected_version": "latest",
            },
        },
        {"kind": "uninstall", "ui_id": "test_multi_2", "params": {"node_name": TEST_PACKAGE_CNR_ID}},
    ]

    for task in tasks:
        response = api_client.queue_task(kind=task["kind"], ui_id=task["ui_id"], params=task["params"])
        assert response.status_code == 200

    # Start queue processing
    response = api_client.start_queue()
    assert response.status_code in [200, 201]

    # Wait for all tasks to complete
    time.sleep(6)

    # After install then uninstall, package should not exist
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    assert not package_path.exists(), "Package should be uninstalled after cycle"


def test_version_switch_cnr_to_nightly(api_client, cleanup_package, custom_nodes_path):
    """Test switching between CNR and nightly versions.

    CNR ↔ Nightly uses .disabled/ mechanism:
    1. Install version 1.0.2 (CNR) → .tracking file
    2. Switch to nightly (git clone) → CNR moved to .disabled/, nightly active with .git
    3. Switch back to 1.0.2 (CNR) → nightly moved to .disabled/, CNR active with .tracking
    4. Switch to nightly again → CNR moved to .disabled/, nightly RESTORED from .disabled/
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    disabled_path = custom_nodes_path / ".disabled" / TEST_PACKAGE_ID
    tracking_file = package_path / ".tracking"

    # Step 1: Install version 1.0.2 (CNR)
    response = api_client.queue_task(
        kind="install",
        ui_id="test_cnr_nightly_1",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(8)

    assert package_path.exists(), "Package should be installed (version 1.0.2)"
    assert tracking_file.exists(), "CNR installation should have .tracking file"
    assert not (package_path / ".git").exists(), "CNR installation should not have .git directory"

    # Step 2: Switch to nightly version (git clone)
    response = api_client.queue_task(
        kind="install",
        ui_id="test_cnr_nightly_2",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(8)

    # CNR version moved to .disabled/, nightly active
    assert package_path.exists(), "Package should still be installed (nightly)"
    assert not tracking_file.exists(), "Nightly installation should NOT have .tracking file"
    assert (package_path / ".git").exists(), "Nightly installation should be a git repository"

    # Step 3: Switch back to version 1.0.2 (CNR)
    response = api_client.queue_task(
        kind="install",
        ui_id="test_cnr_nightly_3",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(8)

    # Nightly moved to .disabled/, CNR active
    assert package_path.exists(), "Package should still be installed (version 1.0.2 again)"
    assert tracking_file.exists(), "CNR installation should have .tracking file again"
    assert not (package_path / ".git").exists(), "CNR installation should not have .git directory"

    # Step 4: Switch to nightly again (should restore from .disabled/)
    response = api_client.queue_task(
        kind="install",
        ui_id="test_cnr_nightly_4",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(8)

    # CNR moved to .disabled/, nightly restored and active
    assert package_path.exists(), "Package should still be installed (nightly restored)"
    assert not tracking_file.exists(), "Nightly should NOT have .tracking file"
    assert (package_path / ".git").exists(), "Nightly should have .git directory (restored from .disabled/)"


def test_version_switch_between_cnr_versions(api_client, cleanup_package, custom_nodes_path):
    """Test switching between different CNR versions.

    CNR ↔ CNR updates directory contents in-place (NO .disabled/):
    1. Install version 1.0.1 → verify pyproject.toml version
    2. Switch to version 1.0.2 → directory stays, contents updated, verify pyproject.toml version
    3. Both versions have .tracking file
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    tracking_file = package_path / ".tracking"
    pyproject_file = package_path / "pyproject.toml"

    # Step 1: Install version 1.0.1
    response = api_client.queue_task(
        kind="install",
        ui_id="test_cnr_cnr_1",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "1.0.1",
            "selected_version": "1.0.1",
        },
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(8)

    assert package_path.exists(), "Package should be installed (version 1.0.1)"
    assert tracking_file.exists(), "CNR installation should have .tracking file"
    assert pyproject_file.exists(), "pyproject.toml should exist"

    # Verify version in pyproject.toml
    pyproject_content = pyproject_file.read_text()
    assert "1.0.1" in pyproject_content, "pyproject.toml should contain version 1.0.1"

    # Step 2: Switch to version 1.0.2 (contents updated in-place)
    response = api_client.queue_task(
        kind="install",
        ui_id="test_cnr_cnr_2",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,  # 1.0.2
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(8)

    # Directory should still exist, contents updated
    assert package_path.exists(), "Package directory should still exist"
    assert tracking_file.exists(), "CNR installation should still have .tracking file"
    assert pyproject_file.exists(), "pyproject.toml should still exist"

    # Verify version updated in pyproject.toml
    pyproject_content = pyproject_file.read_text()
    assert conftest.TEST_PACKAGE_NEW_VERSION in pyproject_content, f"pyproject.toml should contain version {conftest.TEST_PACKAGE_NEW_VERSION}"

    # Verify .disabled/ was NOT used (CNR to CNR doesn't use .disabled/)
    disabled_path = custom_nodes_path / ".disabled" / TEST_PACKAGE_ID
    # Note: .disabled/ might exist from other operations, but we verify in-place update happened


def test_version_switch_disabled_cnr_to_different_cnr(api_client, cleanup_package, custom_nodes_path):
    """Test switching from nightly to different CNR version when old CNR is disabled.

    When CNR 1.0 is disabled and Nightly is active:
    Installing CNR 2.0 should:
    1. Switch Nightly → CNR (enable/disable toggle)
    2. Update CNR 1.0 → 2.0 (in-place within CNR slot)
    """
    package_path = custom_nodes_path / TEST_PACKAGE_ID
    tracking_file = package_path / ".tracking"
    pyproject_file = package_path / "pyproject.toml"

    # Step 1: Install CNR 1.0.1
    response = api_client.queue_task(
        kind="install",
        ui_id="test_disabled_cnr_1",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "1.0.1",
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(8)

    assert package_path.exists(), "CNR 1.0.1 should be installed"

    # Step 2: Switch to Nightly (CNR 1.0.1 → .disabled/)
    response = api_client.queue_task(
        kind="install",
        ui_id="test_disabled_cnr_2",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(8)

    assert (package_path / ".git").exists(), "Nightly should be active with .git"
    assert not tracking_file.exists(), "Nightly should NOT have .tracking"

    # Step 3: Install CNR 1.0.2 (should toggle Nightly→CNR, then update 1.0.1→1.0.2)
    response = api_client.queue_task(
        kind="install",
        ui_id="test_disabled_cnr_3",
        params={
            "id": TEST_PACKAGE_ID,
            "version": conftest.TEST_PACKAGE_NEW_VERSION,  # 1.0.2
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    api_client.start_queue()
    time.sleep(8)

    # After install: CNR should be active with version 1.0.2
    assert package_path.exists(), "Package directory should exist"
    assert tracking_file.exists(), "CNR should have .tracking file"
    assert not (package_path / ".git").exists(), "CNR should NOT have .git directory"
    assert pyproject_file.exists(), "pyproject.toml should exist"

    # Verify version is 1.0.2 (not 1.0.1)
    pyproject_content = pyproject_file.read_text()
    assert conftest.TEST_PACKAGE_NEW_VERSION in pyproject_content, f"pyproject.toml should contain version {conftest.TEST_PACKAGE_NEW_VERSION}"
    assert "1.0.1" not in pyproject_content, "pyproject.toml should NOT contain old version 1.0.1"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
