"""
Test pin failure and retry logic (Priority 1)

Tests that installation with pinned dependencies can retry without pins on failure
"""

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def retry_policy(temp_policy_dir):
    """Create policy with retry_without_pin"""
    policy_content = {
        "new-pkg": {
            "apply_all_matches": [
                {
                    "type": "pin_dependencies",
                    "pinned_packages": ["numpy", "pandas"],
                    "on_failure": "retry_without_pin"
                }
            ]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.fixture
def mock_retry_subprocess(monkeypatch):
    """Mock subprocess that fails with pins, succeeds without"""
    call_sequence = []
    attempt_count = [0]

    installed_packages = {
        "numpy": "1.26.0",
        "pandas": "2.0.0"
    }

    def mock_run(cmd, **kwargs):
        call_sequence.append(cmd)

        # pip freeze
        if "freeze" in cmd:
            output = "\n".join([f"{pkg}=={ver}" for pkg, ver in installed_packages.items()])
            return subprocess.CompletedProcess(cmd, 0, output, "")

        # pip install
        if "install" in cmd and "new-pkg" in cmd:
            attempt_count[0] += 1

            # First attempt with pins - FAIL
            if attempt_count[0] == 1 and "numpy==1.26.0" in cmd and "pandas==2.0.0" in cmd:
                raise subprocess.CalledProcessError(1, cmd, "", "Dependency conflict")

            # Second attempt without pins - SUCCESS
            if attempt_count[0] == 2:
                installed_packages["new-pkg"] = "1.0.0"
                # Without pins, versions might change
                return subprocess.CompletedProcess(cmd, 0, "", "")

        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("subprocess.run", mock_run)
    return call_sequence, installed_packages, attempt_count


@pytest.mark.integration
def test_pin_failure_retry_without_pin_succeeds(
    retry_policy,
    mock_manager_util,
    mock_context,
    mock_retry_subprocess,
    capture_logs
):
    """
    Test retry without pin succeeds after pin failure

    Priority: 1 (Essential)

    Purpose:
        Verify that when installation with pinned dependencies fails,
        the system automatically retries without pins and succeeds.
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    call_sequence, installed_packages, attempt_count = mock_retry_subprocess

    with PipBatch() as batch:
        result = batch.install("new-pkg")

    # Verify installation succeeded on retry
    assert result is True

    # Verify two installation attempts were made
    install_calls = [cmd for cmd in call_sequence if "install" in cmd and "new-pkg" in cmd]
    assert len(install_calls) == 2

    # First attempt had pins
    first_call = install_calls[0]
    assert "new-pkg" in first_call
    assert "numpy==1.26.0" in first_call
    assert "pandas==2.0.0" in first_call

    # Second attempt had no pins (just new-pkg)
    second_call = install_calls[1]
    assert "new-pkg" in second_call
    assert "numpy==1.26.0" not in second_call
    assert "pandas==2.0.0" not in second_call

    # Verify warning log
    assert any("retrying without pins" in record.message.lower() for record in capture_logs.records)


@pytest.fixture
def fail_policy(temp_policy_dir):
    """Create policy with on_failure: fail"""
    policy_content = {
        "pytorch-addon": {
            "apply_all_matches": [
                {
                    "condition": {
                        "type": "installed",
                        "package": "torch",
                        "spec": ">=2.0.0"
                    },
                    "type": "pin_dependencies",
                    "pinned_packages": ["torch", "torchvision", "torchaudio"],
                    "on_failure": "fail"
                }
            ]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.fixture
def mock_fail_subprocess(monkeypatch):
    """Mock subprocess that always fails"""
    call_sequence = []

    installed_packages = {
        "torch": "2.1.0",
        "torchvision": "0.16.0",
        "torchaudio": "2.1.0"
    }

    def mock_run(cmd, **kwargs):
        call_sequence.append(cmd)

        # pip freeze
        if "freeze" in cmd:
            output = "\n".join([f"{pkg}=={ver}" for pkg, ver in installed_packages.items()])
            return subprocess.CompletedProcess(cmd, 0, output, "")

        # pip install - ALWAYS FAIL
        if "install" in cmd and "pytorch-addon" in cmd:
            raise subprocess.CalledProcessError(1, cmd, "", "Installation failed")

        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("subprocess.run", mock_run)
    return call_sequence, installed_packages


@pytest.mark.integration
def test_pin_failure_with_fail_raises_exception(
    fail_policy,
    mock_manager_util,
    mock_context,
    mock_fail_subprocess,
    capture_logs
):
    """
    Test exception is raised when on_failure is "fail"

    Priority: 1 (Essential)

    Purpose:
        Verify that when on_failure is set to "fail", installation
        failure with pinned dependencies raises an exception and
        does not retry.
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    call_sequence, installed_packages = mock_fail_subprocess

    with PipBatch() as batch:
        # Should raise exception
        with pytest.raises(subprocess.CalledProcessError):
            batch.install("pytorch-addon")

    # Verify only one installation attempt was made (no retry)
    install_calls = [cmd for cmd in call_sequence if "install" in cmd and "pytorch-addon" in cmd]
    assert len(install_calls) == 1

    # Verify it had pins
    install_cmd = install_calls[0]
    assert "pytorch-addon" in install_cmd
    assert "torch==2.1.0" in install_cmd
    assert "torchvision==0.16.0" in install_cmd
    assert "torchaudio==2.1.0" in install_cmd
