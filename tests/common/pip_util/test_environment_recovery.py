"""
Test environment corruption and recovery (Priority 1)

Tests that packages deleted or modified during installation are restored
"""

import json
from pathlib import Path

import pytest


@pytest.fixture
def restore_policy(temp_policy_dir):
    """Create policy with restore section for lightweight packages"""
    policy_content = {
        "six": {
            "restore": [
                {
                    "target": "six",
                    "version": "1.16.0",
                    "reason": "six must be maintained at 1.16.0 for compatibility"
                }
            ]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.mark.integration
def test_package_deletion_and_restore(
    restore_policy,
    mock_manager_util,
    mock_context,
    reset_test_venv,
    get_installed_packages,
    install_packages,
    uninstall_packages
):
    """
    Test package deleted by installation is restored

    Priority: 1 (Essential)

    Purpose:
        Verify that when a package installation deletes another package,
        the restore policy can bring it back with the correct version.

    Based on DEPENDENCY_TREE_CONTEXT.md:
        six==1.16.0 must be maintained for compatibility
        After deletion, should restore to exactly 1.16.0
    """
    from comfyui_manager.common.pip_util import PipBatch

    # Verify six is initially installed at expected version
    initial = get_installed_packages()
    assert "six" in initial
    assert initial["six"] == "1.16.0", f"Expected six==1.16.0, got {initial['six']}"

    with PipBatch() as batch:
        # Manually remove six to simulate deletion by another package
        uninstall_packages("six")

        # Check six was deleted
        installed_after_delete = batch._get_installed_packages()
        assert "six" not in installed_after_delete, "six should be deleted"

        # Restore six
        restored = batch.ensure_installed()
        final_packages = batch._get_installed_packages()

    # Verify six was restored to EXACT required version (not latest)
    assert "six" in restored, "six should be in restored list"
    assert final_packages["six"] == "1.16.0", \
        "six should be restored to exact version 1.16.0 (not 1.17.0 latest)"


@pytest.fixture
def version_change_policy(temp_policy_dir):
    """Create policy for version change test with real packages"""
    policy_content = {
        "urllib3": {
            "restore": [
                {
                    "condition": {
                        "type": "installed",
                        "spec": "!=1.26.15"
                    },
                    "target": "urllib3",
                    "version": "1.26.15",
                    "reason": "urllib3 must be 1.26.15 for compatibility"
                }
            ]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.mark.integration
def test_version_change_and_restore(
    version_change_policy,
    mock_manager_util,
    mock_context,
    reset_test_venv,
    get_installed_packages,
    install_packages
):
    """
    Test package version changed by installation is restored

    Priority: 1 (Essential)

    Purpose:
        Verify that when a package installation changes another package's
        version, the restore policy can revert it to the required version.

    Based on DEPENDENCY_TREE_CONTEXT.md:
        urllib3 can upgrade from 1.26.15 (1.x) to 2.5.0 (2.x)
        Restore policy with condition "!=1.26.15" should downgrade back
        This tests downgrade capability (not just upgrade prevention)
    """
    from comfyui_manager.common.pip_util import PipBatch

    # Verify urllib3 1.26.15 is installed
    initial = get_installed_packages()
    assert "urllib3" in initial
    assert initial["urllib3"] == "1.26.15", f"Expected urllib3==1.26.15, got {initial['urllib3']}"

    with PipBatch() as batch:
        # Manually upgrade urllib3 to 2.x to simulate version change
        # This is a MAJOR version upgrade (1.x → 2.x)
        install_packages("urllib3==2.1.0")

        installed_after = batch._get_installed_packages()
        # Verify version was changed to 2.x
        assert installed_after["urllib3"] == "2.1.0", \
            f"urllib3 should be upgraded to 2.1.0, got {installed_after['urllib3']}"
        assert installed_after["urllib3"].startswith("2."), \
            "urllib3 should be at 2.x series"

        # Restore urllib3 to 1.26.15 (this is a DOWNGRADE from 2.x to 1.x)
        restored = batch.ensure_installed()
        final = batch._get_installed_packages()

    # Verify condition was satisfied (2.1.0 != 1.26.15) and restore was triggered
    assert "urllib3" in restored, "urllib3 should be in restored list"

    # Verify version was DOWNGRADED from 2.x back to 1.x
    assert final["urllib3"] == "1.26.15", \
        "urllib3 should be downgraded to 1.26.15 (from 2.1.0)"
    assert final["urllib3"].startswith("1."), \
        f"urllib3 should be back at 1.x series, got {final['urllib3']}"
