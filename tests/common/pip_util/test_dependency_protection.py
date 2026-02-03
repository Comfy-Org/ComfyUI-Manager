"""
Test dependency version protection with pin (Priority 1)

Tests that existing dependency versions are protected by pin_dependencies policy
"""

import json
from pathlib import Path

import pytest


@pytest.fixture
def pin_policy(temp_policy_dir):
    """Create policy with pin_dependencies for lightweight real packages"""
    policy_content = {
        "requests": {
            "apply_all_matches": [
                {
                    "type": "pin_dependencies",
                    "pinned_packages": ["urllib3", "certifi", "charset-normalizer"],
                    "on_failure": "retry_without_pin"
                }
            ]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.mark.integration
def test_dependency_version_protection_with_pin(
    pin_policy,
    mock_manager_util,
    mock_context,
    reset_test_venv,
    get_installed_packages
):
    """
    Test existing dependency versions are protected by pin

    Priority: 1 (Essential)

    Purpose:
        Verify that when installing a package that would normally upgrade
        dependencies, the pin_dependencies policy protects existing versions.

    Based on DEPENDENCY_TREE_CONTEXT.md:
        Without pin: urllib3 1.26.15 → 2.5.0 (MAJOR upgrade)
        With pin: urllib3 stays at 1.26.15 (protected)
    """
    from comfyui_manager.common.pip_util import PipBatch

    # Verify initial packages are installed (from requirements-test-base.txt)
    initial = get_installed_packages()
    assert "urllib3" in initial
    assert "certifi" in initial
    assert "charset-normalizer" in initial

    # Record initial versions (from DEPENDENCY_TREE_CONTEXT.md)
    initial_urllib3 = initial["urllib3"]
    initial_certifi = initial["certifi"]
    initial_charset = initial["charset-normalizer"]

    # Verify expected OLD versions
    assert initial_urllib3 == "1.26.15", f"Expected urllib3==1.26.15, got {initial_urllib3}"
    assert initial_certifi == "2023.7.22", f"Expected certifi==2023.7.22, got {initial_certifi}"
    assert initial_charset == "3.2.0", f"Expected charset-normalizer==3.2.0, got {initial_charset}"

    # Verify idna is NOT installed initially
    assert "idna" not in initial, "idna should not be pre-installed"

    with PipBatch() as batch:
        result = batch.install("requests")
        final_packages = batch._get_installed_packages()

    # Verify installation succeeded
    assert result is True
    assert "requests" in final_packages

    # Verify versions were maintained (not upgraded to latest)
    # Without pin, these would upgrade to: urllib3==2.5.0, certifi==2025.8.3, charset-normalizer==3.4.3
    assert final_packages["urllib3"] == "1.26.15", "urllib3 should remain at 1.26.15 (prevented 2.x upgrade)"
    assert final_packages["certifi"] == "2023.7.22", "certifi should remain at 2023.7.22 (prevented 2025.x upgrade)"
    assert final_packages["charset-normalizer"] == "3.2.0", "charset-normalizer should remain at 3.2.0"

    # Verify new dependency was added (idna is NOT pinned, so it gets installed)
    assert "idna" in final_packages, "idna should be installed as new dependency"
    assert final_packages["idna"] == "3.10", f"Expected idna==3.10, got {final_packages['idna']}"

    # Verify requests was installed at expected version
    assert final_packages["requests"] == "2.32.5", f"Expected requests==2.32.5, got {final_packages['requests']}"


@pytest.fixture
def python_dateutil_policy(temp_policy_dir):
    """Create policy for python-dateutil with six pinning"""
    policy_content = {
        "python-dateutil": {
            "apply_all_matches": [
                {
                    "type": "pin_dependencies",
                    "pinned_packages": ["six"],
                    "reason": "Protect six from upgrading"
                }
            ]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.mark.integration
def test_dependency_chain_with_six_pin(
    python_dateutil_policy,
    mock_manager_util,
    mock_context,
    reset_test_venv,
    get_installed_packages
):
    """
    Test python-dateutil + six dependency chain with pin

    Priority: 2 (Important)

    Purpose:
        Verify that pin_dependencies protects actual dependencies
        (six is a real dependency of python-dateutil).

    Based on DEPENDENCY_TREE_CONTEXT.md:
        python-dateutil depends on six>=1.5
        Without pin: six 1.16.0 → 1.17.0
        With pin: six stays at 1.16.0 (protected)
    """
    from comfyui_manager.common.pip_util import PipBatch

    # Verify six is installed
    initial = get_installed_packages()
    assert "six" in initial
    initial_six = initial["six"]

    # Verify expected OLD version
    assert initial_six == "1.16.0", f"Expected six==1.16.0, got {initial_six}"

    with PipBatch() as batch:
        result = batch.install("python-dateutil")
        final_packages = batch._get_installed_packages()

    # Verify installation succeeded
    assert result is True

    # Verify final versions
    assert "python-dateutil" in final_packages
    assert final_packages["python-dateutil"] == "2.9.0.post0", f"Expected python-dateutil==2.9.0.post0"

    # Verify six was NOT upgraded (without pin, would upgrade to 1.17.0)
    assert "six" in final_packages
    assert final_packages["six"] == "1.16.0", "six should remain at 1.16.0 (prevented 1.17.0 upgrade)"


@pytest.mark.integration
def test_pin_only_affects_specified_packages(
    pin_policy,
    mock_manager_util,
    mock_context,
    reset_test_venv,
    get_installed_packages
):
    """
    Test that pin only affects specified packages, not all dependencies

    Priority: 1 (Essential)

    Purpose:
        Verify that idna (new dependency) is installed even though
        other dependencies are pinned. This tests that pin is selective,
        not global.

    Based on DEPENDENCY_TREE_CONTEXT.md:
        idna is a NEW dependency (not in initial environment)
        Pin only affects: urllib3, certifi, charset-normalizer
        idna should be installed at latest version (3.10)
    """
    from comfyui_manager.common.pip_util import PipBatch

    # Verify initial state
    initial = get_installed_packages()
    assert "idna" not in initial, "idna should not be pre-installed"
    assert "requests" not in initial, "requests should not be pre-installed"

    with PipBatch() as batch:
        result = batch.install("requests")
        final_packages = batch._get_installed_packages()

    # Verify installation succeeded
    assert result is True

    # Verify idna was installed (NOT pinned, so gets latest)
    assert "idna" in final_packages, "idna should be installed as new dependency"
    assert final_packages["idna"] == "3.10", "idna should be at latest version 3.10 (not pinned)"

    # Verify requests was installed
    assert "requests" in final_packages
    assert final_packages["requests"] == "2.32.5"


@pytest.mark.integration
def test_major_version_jump_prevention(
    pin_policy,
    mock_manager_util,
    mock_context,
    reset_test_venv,
    get_installed_packages,
    install_packages,
    uninstall_packages
):
    """
    Test that pin prevents MAJOR version jumps (breaking changes)

    Priority: 1 (Essential)

    Purpose:
        Verify that pin prevents urllib3 1.x → 2.x major upgrade.
        This is the most important test because urllib3 2.0 has
        breaking API changes.

    Based on DEPENDENCY_TREE_CONTEXT.md:
        urllib3 1.26.15 → 2.5.0 is a MAJOR version jump
        urllib3 2.0 removed deprecated APIs
        requests accepts both: urllib3<3,>=1.21.1
    """
    from comfyui_manager.common.pip_util import PipBatch

    # Verify initial urllib3 version
    initial = get_installed_packages()
    assert initial["urllib3"] == "1.26.15", "Expected urllib3==1.26.15"

    # First, test WITHOUT pin to verify urllib3 would upgrade to 2.x
    # (This simulates what would happen without our protection)
    uninstall_packages("urllib3", "certifi", "charset-normalizer")
    install_packages("requests")

    without_pin = get_installed_packages()

    # Verify urllib3 was upgraded to 2.x without pin
    assert "urllib3" in without_pin
    assert without_pin["urllib3"].startswith("2."), \
        f"Without pin, urllib3 should upgrade to 2.x, got {without_pin['urllib3']}"

    # Now reset and test WITH pin
    uninstall_packages("requests", "urllib3", "certifi", "charset-normalizer", "idna")
    install_packages("urllib3==1.26.15", "certifi==2023.7.22", "charset-normalizer==3.2.0")

    with PipBatch() as batch:
        result = batch.install("requests")
        final_packages = batch._get_installed_packages()

    # Verify installation succeeded
    assert result is True

    # Verify urllib3 stayed at 1.x (prevented major version jump)
    assert final_packages["urllib3"] == "1.26.15", \
        "Pin should prevent urllib3 from upgrading to 2.x (breaking changes)"

    # Verify it's specifically 1.x, not 2.x
    assert final_packages["urllib3"].startswith("1."), \
        f"urllib3 should remain at 1.x series, got {final_packages['urllib3']}"
