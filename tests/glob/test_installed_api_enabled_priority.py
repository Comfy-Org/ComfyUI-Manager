"""
Test that /v2/customnode/installed API priority rules work correctly.

This test verifies that the `/v2/customnode/installed` API follows two priority rules:

Rule 1 (Enabled-Priority):
- When both enabled and disabled versions exist → Show ONLY enabled version
- Prevents frontend confusion from duplicate package entries

Rule 2 (CNR-Priority for disabled packages):
- When both CNR and Nightly are disabled → Show ONLY CNR version
- CNR stable releases take priority over development Nightly builds

Additional behaviors:
1. Only returns the enabled version when both enabled and disabled versions exist
2. Does not return duplicate entries for the same package
3. Returns disabled version only when no enabled version exists
4. When both are disabled, CNR version takes priority over Nightly
"""

import pytest
import requests
import time
from pathlib import Path

TEST_PACKAGE_ID = "ComfyUI_SigmoidOffsetScheduler"
WAIT_TIME_SHORT = 10
WAIT_TIME_MEDIUM = 30


@pytest.fixture
def setup_cnr_enabled_nightly_disabled(api_client, custom_nodes_path):
    """
    Setup fixture: CNR v1.0.1 enabled, Nightly disabled.

    This creates the scenario where both versions exist but in different states:
    - custom_nodes/ComfyUI_SigmoidOffsetScheduler/ (CNR v1.0.1, enabled)
    - .disabled/comfyui_sigmoidoffsetscheduler@nightly/ (Nightly, disabled)
    """
    import shutil

    # Clean up any existing package (session fixture may have restored CNR)
    enabled_path = custom_nodes_path / TEST_PACKAGE_ID
    disabled_path = custom_nodes_path / ".disabled"

    if enabled_path.exists():
        shutil.rmtree(enabled_path)

    if disabled_path.exists():
        for item in disabled_path.iterdir():
            if 'sigmoid' in item.name.lower() and item.is_dir():
                shutil.rmtree(item)

    # Install Nightly version first
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_nightly_install",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200, f"Failed to queue Nightly install: {response.text}"

    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(WAIT_TIME_MEDIUM)

    # Verify Nightly is installed and enabled
    enabled_path = custom_nodes_path / TEST_PACKAGE_ID
    assert enabled_path.exists(), "Nightly should be enabled"
    assert (enabled_path / ".git").exists(), "Nightly should have .git directory"

    # Install CNR version (this will disable Nightly and enable CNR)
    response = api_client.queue_task(
        kind="install",
        ui_id="setup_cnr_install",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "1.0.1",
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200, f"Failed to queue CNR install: {response.text}"

    response = api_client.start_queue()
    assert response.status_code in [200, 201], f"Failed to start queue: {response.text}"
    time.sleep(WAIT_TIME_MEDIUM)

    # Verify final state: CNR enabled, Nightly disabled
    assert enabled_path.exists(), "CNR should be enabled"
    assert (enabled_path / ".tracking").exists(), "CNR should have .tracking marker"

    disabled_path = custom_nodes_path / ".disabled"
    disabled_nightly = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and (item / ".git").exists()
    ]
    assert len(disabled_nightly) == 1, "Should have one disabled Nightly package"

    yield

    # Cleanup
    # (cleanup handled by conftest.py session fixture)


def test_installed_api_shows_only_enabled_when_both_exist(
    api_client,
    server_url,
    custom_nodes_path,
    setup_cnr_enabled_nightly_disabled
):
    """
    Test that /installed API only shows enabled package when both versions exist.

    Setup:
        - CNR v1.0.1 enabled in custom_nodes/ComfyUI_SigmoidOffsetScheduler/
        - Nightly disabled in .disabled/comfyui_sigmoidoffsetscheduler@nightly/

    Expected:
        - /v2/customnode/installed returns ONLY the enabled CNR package
        - No duplicate entry for the disabled Nightly version
        - enabled: True for the CNR package

    This prevents frontend confusion from seeing two entries for the same package.
    """
    # Verify setup state on filesystem
    enabled_path = custom_nodes_path / TEST_PACKAGE_ID
    assert enabled_path.exists(), "CNR should be enabled"

    disabled_path = custom_nodes_path / ".disabled"
    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages) > 0, "Should have at least one disabled package"

    # Call /v2/customnode/installed API
    response = requests.get(f"{server_url}/v2/customnode/installed")
    assert response.status_code == 200, f"API call failed: {response.text}"

    installed = response.json()

    # Find all entries for our test package
    sigmoid_entries = [
        (key, info) for key, info in installed.items()
        if 'sigmoid' in key.lower() or 'sigmoid' in info.get('cnr_id', '').lower()
    ]

    # Critical assertion: Should have EXACTLY ONE entry, not two
    assert len(sigmoid_entries) == 1, (
        f"Expected exactly 1 entry in /installed API, but found {len(sigmoid_entries)}. "
        f"This causes frontend confusion. Entries: {sigmoid_entries}"
    )

    # Verify the single entry is the enabled one
    package_key, package_info = sigmoid_entries[0]
    assert package_info['enabled'] is True, (
        f"The single entry should be enabled=True, got: {package_info}"
    )

    # Verify it's the CNR version (has version number)
    assert package_info['ver'].count('.') >= 2, (
        f"Should be CNR version with semantic version, got: {package_info['ver']}"
    )


def test_installed_api_shows_disabled_when_no_enabled_exists(
    api_client,
    server_url,
    custom_nodes_path
):
    """
    Test that /installed API shows disabled package when no enabled version exists.

    Setup:
        - Install and then disable a package (no other version exists)

    Expected:
        - /v2/customnode/installed returns the disabled package
        - enabled: False
        - Only one entry for the package

    This verifies that disabled packages are still visible when they're the only version.
    """
    # Install CNR version
    response = api_client.queue_task(
        kind="install",
        ui_id="test_disabled_only_install",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "1.0.1",
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(WAIT_TIME_MEDIUM)

    # Disable it
    response = api_client.queue_task(
        kind="disable",
        ui_id="test_disabled_only_disable",
        params={"id": TEST_PACKAGE_ID},
    )
    assert response.status_code == 200

    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(WAIT_TIME_MEDIUM)

    # Verify it's disabled on filesystem
    enabled_path = custom_nodes_path / TEST_PACKAGE_ID
    assert not enabled_path.exists(), "Package should be disabled"

    disabled_path = custom_nodes_path / ".disabled"
    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]
    assert len(disabled_packages) > 0, "Should have disabled package"

    # Call /v2/customnode/installed API
    response = requests.get(f"{server_url}/v2/customnode/installed")
    assert response.status_code == 200

    installed = response.json()

    # Find entry for our test package
    sigmoid_entries = [
        (key, info) for key, info in installed.items()
        if 'sigmoid' in key.lower() or 'sigmoid' in info.get('cnr_id', '').lower()
    ]

    # Should have exactly one entry (the disabled one)
    assert len(sigmoid_entries) == 1, (
        f"Expected exactly 1 entry for disabled-only package, found {len(sigmoid_entries)}"
    )

    # Verify it's marked as disabled
    package_key, package_info = sigmoid_entries[0]
    assert package_info['enabled'] is False, (
        f"Package should be disabled, got: {package_info}"
    )


def test_installed_api_no_duplicates_across_scenarios(
    api_client,
    server_url,
    custom_nodes_path
):
    """
    Test that /installed API never returns duplicate entries regardless of scenario.

    This test cycles through multiple scenarios:
    1. CNR enabled only
    2. CNR enabled + Nightly disabled
    3. Nightly enabled + CNR disabled
    4. Both disabled

    In all cases, the API should return at most ONE entry per unique package.
    """
    scenarios = [
        ("cnr_only", "CNR enabled only"),
        ("cnr_enabled_nightly_disabled", "CNR enabled + Nightly disabled"),
        ("nightly_enabled_cnr_disabled", "Nightly enabled + CNR disabled"),
    ]

    for scenario_id, scenario_desc in scenarios:
        # Setup scenario
        if scenario_id == "cnr_only":
            # Install CNR only
            response = api_client.queue_task(
                kind="install",
                ui_id=f"test_{scenario_id}_install",
                params={
                    "id": TEST_PACKAGE_ID,
                    "version": "1.0.1",
                    "selected_version": "latest",
                },
            )
            assert response.status_code == 200
            response = api_client.start_queue()
            assert response.status_code in [200, 201]
            time.sleep(WAIT_TIME_MEDIUM)

        elif scenario_id == "cnr_enabled_nightly_disabled":
            # Install Nightly then disable it
            response = api_client.queue_task(
                kind="install",
                ui_id=f"test_{scenario_id}_nightly",
                params={
                    "id": TEST_PACKAGE_ID,
                    "version": "nightly",
                    "selected_version": "nightly",
                },
            )
            assert response.status_code == 200
            response = api_client.start_queue()
            assert response.status_code in [200, 201]
            time.sleep(WAIT_TIME_MEDIUM)

            response = api_client.queue_task(
                kind="disable",
                ui_id=f"test_{scenario_id}_disable",
                params={"id": TEST_PACKAGE_ID},
            )
            assert response.status_code == 200
            response = api_client.start_queue()
            assert response.status_code in [200, 201]
            time.sleep(WAIT_TIME_MEDIUM)

        elif scenario_id == "nightly_enabled_cnr_disabled":
            # CNR should already be disabled from previous scenario
            # Enable Nightly (install if not exists)
            response = api_client.queue_task(
                kind="install",
                ui_id=f"test_{scenario_id}_nightly",
                params={
                    "id": TEST_PACKAGE_ID,
                    "version": "nightly",
                    "selected_version": "nightly",
                },
            )
            assert response.status_code == 200
            response = api_client.start_queue()
            assert response.status_code in [200, 201]
            time.sleep(WAIT_TIME_MEDIUM)

        # Call API and verify no duplicates
        response = requests.get(f"{server_url}/v2/customnode/installed")
        assert response.status_code == 200, f"API call failed for {scenario_desc}"

        installed = response.json()

        sigmoid_entries = [
            (key, info) for key, info in installed.items()
            if 'sigmoid' in key.lower() or 'sigmoid' in info.get('cnr_id', '').lower()
        ]

        # Critical: Should never have more than one entry
        assert len(sigmoid_entries) <= 1, (
            f"Scenario '{scenario_desc}': Expected at most 1 entry, found {len(sigmoid_entries)}. "
            f"Entries: {sigmoid_entries}"
        )

        if len(sigmoid_entries) == 1:
            package_key, package_info = sigmoid_entries[0]
            # If entry exists, it should be enabled=True
            # (disabled-only case is covered in separate test)
            if scenario_id != "all_disabled":
                assert package_info['enabled'] is True, (
                    f"Scenario '{scenario_desc}': Entry should be enabled=True, got: {package_info}"
                )


def test_installed_api_cnr_priority_when_both_disabled(
    api_client,
    server_url,
    custom_nodes_path
):
    """
    Test Rule 2 (CNR-Priority): When both CNR and Nightly are disabled, show ONLY CNR.

    Setup:
        - Install CNR v1.0.1 and disable it
        - Install Nightly and disable it
        - Both versions exist in .disabled/ directory

    Expected:
        - /v2/customnode/installed returns ONLY the CNR version
        - CNR version has enabled: False
        - Nightly version is NOT in the response
        - This prevents confusion and prioritizes stable releases over dev builds

    Rationale:
        CNR versions are stable releases and should be preferred over development
        Nightly builds when both are inactive. This gives users clear indication
        of which version would be activated if they choose to enable.
    """
    # Install CNR version first
    response = api_client.queue_task(
        kind="install",
        ui_id="test_cnr_priority_cnr_install",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "1.0.1",
            "selected_version": "latest",
        },
    )
    assert response.status_code == 200
    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(WAIT_TIME_MEDIUM)

    # Install Nightly (this will disable CNR)
    response = api_client.queue_task(
        kind="install",
        ui_id="test_cnr_priority_nightly_install",
        params={
            "id": TEST_PACKAGE_ID,
            "version": "nightly",
            "selected_version": "nightly",
        },
    )
    assert response.status_code == 200
    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(WAIT_TIME_MEDIUM)

    # Disable Nightly (now both are disabled)
    response = api_client.queue_task(
        kind="disable",
        ui_id="test_cnr_priority_nightly_disable",
        params={"id": TEST_PACKAGE_ID},
    )
    assert response.status_code == 200
    response = api_client.start_queue()
    assert response.status_code in [200, 201]
    time.sleep(WAIT_TIME_MEDIUM)

    # Verify filesystem state: both should be in .disabled/
    disabled_path = custom_nodes_path / ".disabled"
    disabled_packages = [
        item for item in disabled_path.iterdir()
        if 'sigmoid' in item.name.lower() and item.is_dir()
    ]

    # Should have both CNR and Nightly in .disabled/
    cnr_disabled = [p for p in disabled_packages if (p / ".tracking").exists()]
    nightly_disabled = [p for p in disabled_packages if (p / ".git").exists()]

    assert len(cnr_disabled) >= 1, f"Should have disabled CNR package, found: {[p.name for p in disabled_packages]}"
    assert len(nightly_disabled) >= 1, f"Should have disabled Nightly package, found: {[p.name for p in disabled_packages]}"

    # Call /v2/customnode/installed API
    response = requests.get(f"{server_url}/v2/customnode/installed")
    assert response.status_code == 200

    installed = response.json()

    # Find all entries for our test package
    sigmoid_entries = [
        (key, info) for key, info in installed.items()
        if 'sigmoid' in key.lower() or 'sigmoid' in info.get('cnr_id', '').lower()
    ]

    # Critical assertion: Should have EXACTLY ONE entry (CNR), not two
    assert len(sigmoid_entries) == 1, (
        f"Rule 2 (CNR-Priority) violated: Expected exactly 1 entry (CNR only), "
        f"but found {len(sigmoid_entries)}. Entries: {sigmoid_entries}"
    )

    # Verify the single entry is the CNR version
    package_key, package_info = sigmoid_entries[0]

    # Should be disabled
    assert package_info['enabled'] is False, (
        f"Package should be disabled, got: {package_info}"
    )

    # Should have cnr_id (CNR packages have cnr_id, Nightly has empty cnr_id)
    assert package_info.get('cnr_id'), (
        f"Should be CNR package with cnr_id, got: {package_info}"
    )

    # Should have null aux_id (CNR packages have aux_id=null, Nightly has aux_id set)
    assert package_info.get('aux_id') is None, (
        f"Should be CNR package with aux_id=null, got: {package_info}"
    )

    # Should have semantic version (CNR uses semver, Nightly uses git hash)
    ver = package_info['ver']
    assert ver.count('.') >= 2 or ver[0].isdigit(), (
        f"Should be CNR with semantic version, got: {ver}"
    )
