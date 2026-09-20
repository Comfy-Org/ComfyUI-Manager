"""
Edge cases and boundary conditions (Priority 3)

Tests empty policies, malformed JSON, and edge cases
"""

import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.unit
def test_empty_base_policy_uses_default_installation(
    empty_policy_file,
    mock_manager_util,
    mock_context
):
    """
    Test default installation with empty policy

    Priority: 3 (Recommended)

    Purpose:
        Verify that when policy is empty, the system falls back
        to default installation behavior.
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import get_pip_policy

    policy = get_pip_policy()

    assert policy == {}


@pytest.fixture
def malformed_policy_file(temp_policy_dir):
    """Create malformed JSON policy file"""
    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text("{invalid json content")
    return policy_file


@pytest.mark.unit
def test_json_parse_error_fallback_to_empty(
    malformed_policy_file,
    mock_manager_util,
    mock_context,
    capture_logs
):
    """
    Test empty dict on JSON parse error

    Priority: 3 (Recommended)

    Purpose:
        Verify that malformed JSON results in empty policy
        with appropriate error logging.
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import get_pip_policy

    policy = get_pip_policy()

    assert policy == {}
    # Should have error log about parsing failure
    assert any("parse" in record.message.lower() for record in capture_logs.records)


@pytest.mark.unit
def test_unknown_condition_type_returns_false(
    mock_manager_util,
    mock_context,
    capture_logs
):
    """
    Test unknown condition type returns False

    Priority: 3 (Recommended)

    Purpose:
        Verify that unknown condition types are handled gracefully
        by returning False with a warning.
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    condition = {"type": "unknown_type", "some_field": "value"}

    result = batch._evaluate_condition(condition, "pkg", {})

    assert result is False
    # Should have warning about unknown type
    assert any("unknown" in record.message.lower() for record in capture_logs.records)


@pytest.fixture
def self_reference_policy(temp_policy_dir):
    """Create policy with self-reference"""
    policy_content = {
        "critical-package": {
            "restore": [
                {
                    "condition": {
                        "type": "installed",
                        "spec": "!=1.2.3"
                    },
                    "target": "critical-package",
                    "version": "1.2.3"
                }
            ]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.fixture
def mock_self_reference_subprocess(monkeypatch):
    """Mock subprocess for self-reference test"""
    call_sequence = []

    installed_packages = {
        "critical-package": "1.2.2"
    }

    def mock_run(cmd, **kwargs):
        call_sequence.append(cmd)

        # pip freeze
        if "freeze" in cmd:
            output = "\n".join([f"{pkg}=={ver}" for pkg, ver in installed_packages.items()])
            return subprocess.CompletedProcess(cmd, 0, output, "")

        # pip install
        if "install" in cmd and "critical-package==1.2.3" in cmd:
            installed_packages["critical-package"] = "1.2.3"
            return subprocess.CompletedProcess(cmd, 0, "", "")

        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("subprocess.run", mock_run)
    return call_sequence, installed_packages


@pytest.mark.integration
def test_restore_self_version_check(
    self_reference_policy,
    mock_manager_util,
    mock_context,
    mock_self_reference_subprocess
):
    """
    Test restore policy checking its own version

    Priority: 3 (Recommended)

    Purpose:
        Verify that when a condition omits the package field,
        it correctly defaults to checking the package itself.
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    call_sequence, installed_packages = mock_self_reference_subprocess

    with PipBatch() as batch:
        restored = batch.ensure_installed()
        final = batch._get_installed_packages()

    # Condition should evaluate with self-reference
    # "1.2.2" != "1.2.3" → True
    assert "critical-package" in restored
    assert final["critical-package"] == "1.2.3"


@pytest.fixture
def partial_failure_policy(temp_policy_dir):
    """Create policy for multiple uninstalls"""
    policy_content = {
        "pkg-a": {
            "uninstall": [{"target": "old-pkg-1"}]
        },
        "pkg-b": {
            "uninstall": [{"target": "old-pkg-2"}]
        },
        "pkg-c": {
            "uninstall": [{"target": "old-pkg-3"}]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.fixture
def mock_partial_failure_subprocess(monkeypatch):
    """Mock subprocess with one failure"""
    call_sequence = []

    installed_packages = {
        "old-pkg-1": "1.0",
        "old-pkg-2": "1.0",
        "old-pkg-3": "1.0"
    }

    def mock_run(cmd, **kwargs):
        call_sequence.append(cmd)

        # pip freeze
        if "freeze" in cmd:
            output = "\n".join([f"{pkg}=={ver}" for pkg, ver in installed_packages.items()])
            return subprocess.CompletedProcess(cmd, 0, output, "")

        # pip uninstall
        if "uninstall" in cmd:
            if "old-pkg-2" in cmd:
                # Fail on pkg-2
                raise subprocess.CalledProcessError(1, cmd, "", "Uninstall failed")
            else:
                # Success on others
                for pkg in ["old-pkg-1", "old-pkg-3"]:
                    if pkg in cmd:
                        installed_packages.pop(pkg, None)
                return subprocess.CompletedProcess(cmd, 0, "", "")

        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("subprocess.run", mock_run)
    return call_sequence, installed_packages


@pytest.mark.integration
def test_ensure_not_installed_continues_on_individual_failure(
    partial_failure_policy,
    mock_manager_util,
    mock_context,
    mock_partial_failure_subprocess,
    capture_logs
):
    """
    Test partial failure handling

    Priority: 2 (Important)

    Purpose:
        Verify that when one package removal fails, the system
        continues processing other packages.
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    call_sequence, installed_packages = mock_partial_failure_subprocess

    with PipBatch() as batch:
        removed = batch.ensure_not_installed()

    # Verify partial success
    assert "old-pkg-1" in removed
    assert "old-pkg-3" in removed
    assert "old-pkg-2" not in removed  # Failed

    # Verify warning logged for failure
    assert any("warning" in record.levelname.lower() for record in capture_logs.records)
