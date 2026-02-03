"""
Test policy priority and conflicts (Priority 2)

Tests that user policies override base policies correctly
"""

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def conflicting_policies(temp_policy_dir, temp_user_policy_dir):
    """Create conflicting base and user policies"""
    # Base policy
    base_content = {
        "numpy": {
            "apply_first_match": [
                {
                    "type": "skip",
                    "reason": "Base policy skip"
                }
            ]
        }
    }
    base_file = temp_policy_dir / "pip-policy.json"
    base_file.write_text(json.dumps(base_content, indent=2))

    # User policy (should override)
    user_content = {
        "numpy": {
            "apply_first_match": [
                {
                    "type": "force_version",
                    "version": "1.26.0",
                    "reason": "User override"
                }
            ]
        }
    }
    user_file = temp_user_policy_dir / "pip-policy.user.json"
    user_file.write_text(json.dumps(user_content, indent=2))

    return base_file, user_file


@pytest.mark.unit
def test_user_policy_overrides_base_policy(
    conflicting_policies,
    mock_manager_util,
    mock_context,
    mock_subprocess_success
):
    """
    Test user policy completely replaces base policy

    Priority: 2 (Important)

    Purpose:
        Verify that user policy completely overrides base policy
        at the package level (not section-level merge).
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import get_pip_policy

    policy = get_pip_policy()

    # Verify user policy replaced base policy
    assert "numpy" in policy
    assert "apply_first_match" in policy["numpy"]
    assert len(policy["numpy"]["apply_first_match"]) == 1

    # Should be force_version (user), not skip (base)
    assert policy["numpy"]["apply_first_match"][0]["type"] == "force_version"
    assert policy["numpy"]["apply_first_match"][0]["version"] == "1.26.0"

    # Base policy skip should be completely gone
    assert not any(
        item["type"] == "skip"
        for item in policy["numpy"]["apply_first_match"]
    )


@pytest.fixture
def first_match_policy(temp_policy_dir):
    """Create policy with multiple apply_first_match entries"""
    policy_content = {
        "pkg": {
            "apply_first_match": [
                {
                    "condition": {
                        "type": "installed",
                        "package": "numpy"
                    },
                    "type": "force_version",
                    "version": "1.0"
                },
                {
                    "type": "force_version",
                    "version": "2.0"
                },
                {
                    "type": "skip"
                }
            ]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.fixture
def mock_first_match_subprocess(monkeypatch):
    """Mock subprocess for first match test"""
    call_sequence = []

    installed_packages = {
        "numpy": "1.26.0"
    }

    def mock_run(cmd, **kwargs):
        call_sequence.append(cmd)

        # pip freeze
        if "freeze" in cmd:
            output = "\n".join([f"{pkg}=={ver}" for pkg, ver in installed_packages.items()])
            return subprocess.CompletedProcess(cmd, 0, output, "")

        # pip install
        if "install" in cmd and "pkg" in cmd:
            if "pkg==1.0" in cmd:
                installed_packages["pkg"] = "1.0"
            return subprocess.CompletedProcess(cmd, 0, "", "")

        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("subprocess.run", mock_run)
    return call_sequence, installed_packages


@pytest.mark.integration
def test_first_match_stops_at_first_satisfied(
    first_match_policy,
    mock_manager_util,
    mock_context,
    mock_first_match_subprocess
):
    """
    Test apply_first_match stops at first satisfied condition

    Priority: 2 (Important)

    Purpose:
        Verify that in apply_first_match, only the first policy
        with a satisfied condition is executed (exclusive execution).
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    call_sequence, installed_packages = mock_first_match_subprocess

    with PipBatch() as batch:
        result = batch.install("pkg")

    # Verify installation succeeded
    assert result is True

    # First condition satisfied (numpy installed), so version 1.0 applied
    install_calls = [cmd for cmd in call_sequence if "install" in cmd and "pkg" in cmd]
    assert len(install_calls) > 0
    assert "pkg==1.0" in install_calls[0]
    assert "pkg==2.0" not in str(call_sequence)  # Second policy not applied
