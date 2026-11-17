"""
Test full workflow integration (Priority 1)

Tests the complete uninstall → install → restore workflow
"""

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def workflow_policy(temp_policy_dir):
    """Create policy for full workflow test"""
    policy_content = {
        "target-package": {
            "uninstall": [
                {
                    "condition": {
                        "type": "installed",
                        "package": "conflicting-pkg"
                    },
                    "target": "conflicting-pkg",
                    "reason": "Conflicts with target-package"
                }
            ],
            "apply_all_matches": [
                {
                    "type": "pin_dependencies",
                    "pinned_packages": ["numpy", "pandas"]
                }
            ]
        },
        "critical-package": {
            "restore": [
                {
                    "target": "critical-package",
                    "version": "1.2.3",
                    "reason": "Critical package must be 1.2.3"
                }
            ]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.fixture
def mock_workflow_subprocess(monkeypatch):
    """Mock subprocess for workflow test"""
    call_sequence = []

    # Initial environment: conflicting-pkg, numpy, pandas, critical-package
    installed_packages = {
        "conflicting-pkg": "1.0.0",
        "numpy": "1.26.0",
        "pandas": "2.0.0",
        "critical-package": "1.2.3"
    }

    def mock_run(cmd, **kwargs):
        call_sequence.append(cmd)

        # pip freeze
        if "freeze" in cmd:
            output = "\n".join([f"{pkg}=={ver}" for pkg, ver in installed_packages.items()])
            return subprocess.CompletedProcess(cmd, 0, output, "")

        # pip uninstall
        if "uninstall" in cmd:
            # Remove conflicting-pkg
            if "conflicting-pkg" in cmd:
                installed_packages.pop("conflicting-pkg", None)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        # pip install target-package (deletes critical-package)
        if "install" in cmd and "target-package" in cmd:
            # Simulate target-package installation deleting critical-package
            installed_packages.pop("critical-package", None)
            installed_packages["target-package"] = "1.0.0"
            return subprocess.CompletedProcess(cmd, 0, "", "")

        # pip install critical-package (restore)
        if "install" in cmd and "critical-package==1.2.3" in cmd:
            installed_packages["critical-package"] = "1.2.3"
            return subprocess.CompletedProcess(cmd, 0, "", "")

        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("subprocess.run", mock_run)
    return call_sequence, installed_packages


@pytest.mark.integration
def test_uninstall_install_restore_workflow(
    workflow_policy,
    mock_manager_util,
    mock_context,
    mock_workflow_subprocess
):
    """
    Test complete uninstall → install → restore workflow

    Priority: 1 (Essential)

    Purpose:
        Verify the complete workflow executes in correct order:
        1. ensure_not_installed() removes conflicting packages
        2. install() applies policies (pin_dependencies)
        3. ensure_installed() restores deleted packages
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    call_sequence, installed_packages = mock_workflow_subprocess

    with PipBatch() as batch:
        # Step 1: uninstall - remove conflicting packages
        removed = batch.ensure_not_installed()

        # Step 2: install target-package with pinned dependencies
        result = batch.install("target-package")

        # Step 3: restore critical-package that was deleted
        restored = batch.ensure_installed()

    # Verify Step 1: conflicting-pkg was removed
    assert "conflicting-pkg" in removed

    # Verify Step 2: target-package was installed with pinned dependencies
    assert result is True
    # Check that pip install was called with pinned packages
    install_calls = [cmd for cmd in call_sequence if "install" in cmd and "target-package" in cmd]
    assert len(install_calls) > 0
    install_cmd = install_calls[0]
    assert "target-package" in install_cmd
    assert "numpy==1.26.0" in install_cmd
    assert "pandas==2.0.0" in install_cmd

    # Verify Step 3: critical-package was restored
    assert "critical-package" in restored

    # Verify final state
    assert "conflicting-pkg" not in installed_packages
    assert "critical-package" in installed_packages
    assert installed_packages["critical-package"] == "1.2.3"
    assert "target-package" in installed_packages


@pytest.mark.integration
def test_cache_invalidation_across_workflow(
    workflow_policy,
    mock_manager_util,
    mock_context,
    mock_workflow_subprocess
):
    """
    Test cache is correctly refreshed at each workflow step

    Priority: 1 (Essential)

    Purpose:
        Verify that the cache is invalidated and refreshed after each
        operation (uninstall, install, restore) to reflect current state.
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    call_sequence, installed_packages = mock_workflow_subprocess

    with PipBatch() as batch:
        # Initial cache state
        cache1 = batch._get_installed_packages()
        assert "conflicting-pkg" in cache1
        assert "critical-package" in cache1

        # After uninstall
        removed = batch.ensure_not_installed()
        cache2 = batch._get_installed_packages()
        assert "conflicting-pkg" not in cache2  # Removed

        # After install (critical-package gets deleted by target-package)
        batch.install("target-package")
        cache3 = batch._get_installed_packages()
        assert "target-package" in cache3  # Added
        assert "critical-package" not in cache3  # Deleted by target-package

        # After restore
        restored = batch.ensure_installed()
        cache4 = batch._get_installed_packages()
        assert "critical-package" in cache4  # Restored

    # Verify cache was refreshed at each step
    assert cache1 != cache2  # Changed after uninstall
    assert cache2 != cache3  # Changed after install
    assert cache3 != cache4  # Changed after restore
