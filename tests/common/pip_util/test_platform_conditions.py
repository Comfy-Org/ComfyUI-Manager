"""
Test platform-specific conditions (Priority 2)

Tests OS and GPU detection for conditional policies
"""

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def platform_policy(temp_policy_dir):
    """Create policy with platform conditions"""
    policy_content = {
        "onnxruntime": {
            "apply_first_match": [
                {
                    "condition": {
                        "type": "platform",
                        "os": "linux",
                        "has_gpu": True
                    },
                    "type": "replace",
                    "replacement": "onnxruntime-gpu"
                }
            ]
        }
    }

    policy_file = temp_policy_dir / "pip-policy.json"
    policy_file.write_text(json.dumps(policy_content, indent=2))
    return policy_file


@pytest.fixture
def mock_platform_subprocess(monkeypatch):
    """Mock subprocess for platform test"""
    call_sequence = []
    installed_packages = {}

    def mock_run(cmd, **kwargs):
        call_sequence.append(cmd)

        # pip freeze
        if "freeze" in cmd:
            output = "\n".join([f"{pkg}=={ver}" for pkg, ver in installed_packages.items()])
            return subprocess.CompletedProcess(cmd, 0, output, "")

        # pip install
        if "install" in cmd:
            if "onnxruntime-gpu" in cmd:
                installed_packages["onnxruntime-gpu"] = "1.0.0"
            elif "onnxruntime" in cmd:
                installed_packages["onnxruntime"] = "1.0.0"
            return subprocess.CompletedProcess(cmd, 0, "", "")

        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("subprocess.run", mock_run)
    return call_sequence, installed_packages


@pytest.mark.integration
def test_linux_gpu_uses_gpu_package(
    platform_policy,
    mock_manager_util,
    mock_context,
    mock_platform_subprocess,
    mock_platform_linux,
    mock_torch_cuda_available
):
    """
    Test GPU-specific package on Linux + GPU

    Priority: 2 (Important)

    Purpose:
        Verify that platform-conditional policies correctly detect
        Linux + GPU and install the appropriate package variant.
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    call_sequence, installed_packages = mock_platform_subprocess

    with PipBatch() as batch:
        result = batch.install("onnxruntime")

    # Verify installation succeeded
    assert result is True

    # Verify GPU version was installed
    install_calls = [cmd for cmd in call_sequence if "install" in cmd]
    assert any("onnxruntime-gpu" in str(cmd) for cmd in install_calls)
    assert "onnxruntime-gpu" in installed_packages


@pytest.mark.integration
def test_windows_no_gpu_uses_cpu_package(
    platform_policy,
    mock_manager_util,
    mock_context,
    mock_platform_subprocess,
    mock_platform_windows,
    mock_torch_cuda_unavailable
):
    """
    Test CPU package on Windows + No GPU

    Priority: 2 (Important)

    Purpose:
        Verify that when platform conditions are not met,
        the original package is installed without replacement.
    """
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    call_sequence, installed_packages = mock_platform_subprocess

    with PipBatch() as batch:
        result = batch.install("onnxruntime")

    # Verify installation succeeded
    assert result is True

    # Verify CPU version was installed (no GPU replacement)
    install_calls = [cmd for cmd in call_sequence if "install" in cmd]
    assert any("onnxruntime" in str(cmd) for cmd in install_calls)
    assert "onnxruntime-gpu" not in str(call_sequence)
    assert "onnxruntime" in installed_packages
    assert "onnxruntime-gpu" not in installed_packages
