"""
pytest configuration and shared fixtures for pip_util.py tests

This file provides common fixtures and configuration for all tests.
Uses real isolated venv for actual pip operations.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock

import pytest


# =============================================================================
# Test venv Management
# =============================================================================

@pytest.fixture(scope="session")
def test_venv_path():
    """
    Get path to test venv (must be created by setup_test_env.sh)

    Returns:
        Path: Path to test venv directory
    """
    venv_path = Path(__file__).parent / "test_venv"
    if not venv_path.exists():
        pytest.fail(
            f"Test venv not found at {venv_path}.\n"
            "Please run: ./setup_test_env.sh"
        )
    return venv_path


@pytest.fixture(scope="session")
def test_pip_cmd(test_venv_path):
    """
    Get pip command for test venv

    Returns:
        List[str]: pip command prefix for subprocess
    """
    pip_path = test_venv_path / "bin" / "pip"
    if not pip_path.exists():
        pytest.fail(f"pip not found at {pip_path}")
    return [str(pip_path)]


@pytest.fixture
def reset_test_venv(test_pip_cmd):
    """
    Reset test venv to initial state before each test

    This fixture:
    1. Records current installed packages
    2. Yields control to test
    3. Restores original packages after test
    """
    # Get initial state
    result = subprocess.run(
        test_pip_cmd + ["freeze"],
        capture_output=True,
        text=True,
        check=True
    )
    initial_packages = result.stdout.strip()

    yield

    # Restore initial state
    # Uninstall everything except pip, setuptools, wheel
    result = subprocess.run(
        test_pip_cmd + ["freeze"],
        capture_output=True,
        text=True,
        check=True
    )
    current_packages = result.stdout.strip()

    if current_packages:
        packages_to_remove = []
        for line in current_packages.split('\n'):
            if line and '==' in line:
                pkg = line.split('==')[0].lower()
                if pkg not in ['pip', 'setuptools', 'wheel']:
                    packages_to_remove.append(pkg)

        if packages_to_remove:
            subprocess.run(
                test_pip_cmd + ["uninstall", "-y"] + packages_to_remove,
                capture_output=True,
                check=False  # Don't fail if package doesn't exist
            )

    # Reinstall initial packages
    if initial_packages:
        # Create temporary requirements file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(initial_packages)
            temp_req = f.name

        try:
            subprocess.run(
                test_pip_cmd + ["install", "-r", temp_req],
                capture_output=True,
                check=True
            )
        finally:
            Path(temp_req).unlink()


# =============================================================================
# Directory and Path Fixtures
# =============================================================================

@pytest.fixture
def temp_policy_dir(tmp_path):
    """
    Create temporary directory for policy files

    Returns:
        Path: Temporary directory for storing test policy files
    """
    policy_dir = tmp_path / "policies"
    policy_dir.mkdir()
    return policy_dir


@pytest.fixture
def temp_user_policy_dir(tmp_path):
    """
    Create temporary directory for user policy files

    Returns:
        Path: Temporary directory for storing user policy files
    """
    user_dir = tmp_path / "user_policies"
    user_dir.mkdir()
    return user_dir


# =============================================================================
# Module Setup and Mocking
# =============================================================================

@pytest.fixture(autouse=True)
def setup_pip_util(monkeypatch, test_pip_cmd):
    """
    Setup pip_util module for testing with real venv

    This fixture:
    1. Mocks comfy module (not needed for tests)
    2. Adds comfyui_manager to path
    3. Patches make_pip_cmd to use test venv
    4. Resets policy cache
    """
    # Mock comfy module before importing anything
    comfy_mock = MagicMock()
    cli_args_mock = MagicMock()
    cli_args_mock.args = MagicMock()
    comfy_mock.cli_args = cli_args_mock
    sys.modules['comfy'] = comfy_mock
    sys.modules['comfy.cli_args'] = cli_args_mock

    # Add comfyui_manager parent to path so relative imports work
    comfyui_manager_path = str(Path(__file__).parent.parent.parent.parent)
    if comfyui_manager_path not in sys.path:
        sys.path.insert(0, comfyui_manager_path)

    # Import pip_util
    from comfyui_manager.common import pip_util

    # Patch make_pip_cmd to use test venv pip
    def make_test_pip_cmd(args: List[str]) -> List[str]:
        return test_pip_cmd + args

    monkeypatch.setattr(
        pip_util.manager_util,
        "make_pip_cmd",
        make_test_pip_cmd
    )

    # Reset policy cache
    pip_util._pip_policy_cache = None

    yield

    # Cleanup
    pip_util._pip_policy_cache = None


@pytest.fixture
def mock_manager_util(monkeypatch, temp_policy_dir):
    """
    Mock manager_util module paths

    Args:
        monkeypatch: pytest monkeypatch fixture
        temp_policy_dir: Temporary policy directory
    """
    from comfyui_manager.common import pip_util

    monkeypatch.setattr(
        pip_util.manager_util,
        "comfyui_manager_path",
        str(temp_policy_dir)
    )


@pytest.fixture
def mock_context(monkeypatch, temp_user_policy_dir):
    """
    Mock context module paths

    Args:
        monkeypatch: pytest monkeypatch fixture
        temp_user_policy_dir: Temporary user policy directory
    """
    from comfyui_manager.common import pip_util

    monkeypatch.setattr(
        pip_util.context,
        "manager_files_path",
        str(temp_user_policy_dir)
    )


# =============================================================================
# Platform Mocking Fixtures
# =============================================================================

@pytest.fixture
def mock_platform_linux(monkeypatch):
    """Mock platform.system() to return 'Linux'"""
    monkeypatch.setattr("platform.system", lambda: "Linux")


@pytest.fixture
def mock_platform_windows(monkeypatch):
    """Mock platform.system() to return 'Windows'"""
    monkeypatch.setattr("platform.system", lambda: "Windows")


@pytest.fixture
def mock_platform_darwin(monkeypatch):
    """Mock platform.system() to return 'Darwin' (macOS)"""
    monkeypatch.setattr("platform.system", lambda: "Darwin")


@pytest.fixture
def mock_torch_cuda_available(monkeypatch):
    """Mock torch.cuda.is_available() to return True"""
    class MockCuda:
        @staticmethod
        def is_available():
            return True

    class MockTorch:
        cuda = MockCuda()

    import sys
    monkeypatch.setitem(sys.modules, "torch", MockTorch())


@pytest.fixture
def mock_torch_cuda_unavailable(monkeypatch):
    """Mock torch.cuda.is_available() to return False"""
    class MockCuda:
        @staticmethod
        def is_available():
            return False

    class MockTorch:
        cuda = MockCuda()

    import sys
    monkeypatch.setitem(sys.modules, "torch", MockTorch())


@pytest.fixture
def mock_torch_not_installed(monkeypatch):
    """Mock torch as not installed (ImportError)"""
    import sys
    if "torch" in sys.modules:
        monkeypatch.delitem(sys.modules, "torch")


# =============================================================================
# Helper Functions
# =============================================================================

@pytest.fixture
def get_installed_packages(test_pip_cmd):
    """
    Helper to get currently installed packages in test venv

    Returns:
        Callable that returns Dict[str, str] of installed packages
    """
    def _get_installed() -> Dict[str, str]:
        result = subprocess.run(
            test_pip_cmd + ["freeze"],
            capture_output=True,
            text=True,
            check=True
        )

        packages = {}
        for line in result.stdout.strip().split('\n'):
            if line and '==' in line:
                pkg, ver = line.split('==', 1)
                packages[pkg] = ver

        return packages

    return _get_installed


@pytest.fixture
def install_packages(test_pip_cmd):
    """
    Helper to install packages in test venv

    Returns:
        Callable that installs packages
    """
    def _install(*packages):
        subprocess.run(
            test_pip_cmd + ["install"] + list(packages),
            capture_output=True,
            check=True
        )

    return _install


@pytest.fixture
def uninstall_packages(test_pip_cmd):
    """
    Helper to uninstall packages in test venv

    Returns:
        Callable that uninstalls packages
    """
    def _uninstall(*packages):
        subprocess.run(
            test_pip_cmd + ["uninstall", "-y"] + list(packages),
            capture_output=True,
            check=False  # Don't fail if package doesn't exist
        )

    return _uninstall


# =============================================================================
# Test Data Factories
# =============================================================================

@pytest.fixture
def make_policy():
    """
    Factory fixture for creating policy dictionaries

    Returns:
        Callable that creates policy dict from parameters
    """
    def _make_policy(
        package_name: str,
        policy_type: str,
        section: str = "apply_first_match",
        **kwargs
    ) -> Dict:
        policy_item = {"type": policy_type}
        policy_item.update(kwargs)

        return {
            package_name: {
                section: [policy_item]
            }
        }

    return _make_policy
