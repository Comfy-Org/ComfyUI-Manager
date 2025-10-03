"""
Unit tests for package spec parsing and condition evaluation

Tests core utility functions
"""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.unit
def test_parse_package_spec_name_only(mock_manager_util, mock_context):
    """Test parsing package name without version"""
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    name, spec = batch._parse_package_spec("numpy")

    assert name == "numpy"
    assert spec is None


@pytest.mark.unit
def test_parse_package_spec_exact_version(mock_manager_util, mock_context):
    """Test parsing package with exact version"""
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    name, spec = batch._parse_package_spec("numpy==1.26.0")

    assert name == "numpy"
    assert spec == "==1.26.0"


@pytest.mark.unit
def test_parse_package_spec_min_version(mock_manager_util, mock_context):
    """Test parsing package with minimum version"""
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    name, spec = batch._parse_package_spec("pandas>=2.0.0")

    assert name == "pandas"
    assert spec == ">=2.0.0"


@pytest.mark.unit
def test_parse_package_spec_hyphenated_name(mock_manager_util, mock_context):
    """Test parsing package with hyphens"""
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    name, spec = batch._parse_package_spec("scikit-learn>=1.0")

    assert name == "scikit-learn"
    assert spec == ">=1.0"


@pytest.mark.unit
def test_evaluate_condition_none(mock_manager_util, mock_context):
    """Test None condition always returns True"""
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    result = batch._evaluate_condition(None, "numpy", {})

    assert result is True


@pytest.mark.unit
def test_evaluate_condition_installed_package_exists(mock_manager_util, mock_context):
    """Test installed condition when package exists"""
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    condition = {"type": "installed", "package": "numpy"}
    installed = {"numpy": "1.26.0"}

    result = batch._evaluate_condition(condition, "numba", installed)

    assert result is True


@pytest.mark.unit
def test_evaluate_condition_installed_package_not_exists(mock_manager_util, mock_context):
    """Test installed condition when package doesn't exist"""
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    condition = {"type": "installed", "package": "numpy"}
    installed = {}

    result = batch._evaluate_condition(condition, "numba", installed)

    assert result is False


@pytest.mark.unit
def test_evaluate_condition_platform_os_match(
    mock_manager_util,
    mock_context,
    mock_platform_linux
):
    """Test platform OS condition matching"""
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    condition = {"type": "platform", "os": "linux"}

    result = batch._evaluate_condition(condition, "package", {})

    assert result is True


@pytest.mark.unit
def test_evaluate_condition_platform_gpu_available(
    mock_manager_util,
    mock_context,
    mock_torch_cuda_available
):
    """Test GPU detection when available"""
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    condition = {"type": "platform", "has_gpu": True}

    result = batch._evaluate_condition(condition, "package", {})

    assert result is True


@pytest.mark.unit
def test_evaluate_condition_platform_gpu_not_available(
    mock_manager_util,
    mock_context,
    mock_torch_cuda_unavailable
):
    """Test GPU detection when not available"""
    import sys
    # Path setup handled by conftest.py

    from comfyui_manager.common.pip_util import PipBatch

    batch = PipBatch()
    condition = {"type": "platform", "has_gpu": True}

    result = batch._evaluate_condition(condition, "package", {})

    assert result is False
