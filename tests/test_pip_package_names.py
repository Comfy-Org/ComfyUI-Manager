"""Exercise the real pip guards without running Manager's startup side effects."""

import ast
import re
from types import SimpleNamespace

import pytest

from manager_test_utils import GLOB_DIR, load_manager_util

GUARDS = [
    (GLOB_DIR / "manager_core.py", "is_blacklisted"),
    (GLOB_DIR.resolve().parent / "prestartup_script.py", "is_installed"),
]


@pytest.fixture
def manager_util(monkeypatch):
    """Feed pip's display names through the production inventory parser."""
    module = load_manager_util()
    inventory = "Package Version\n------- -------\nOpenCV-Python 5.0.0.93\nnumpy 2.0.0\n"
    monkeypatch.setattr(module.subprocess, "check_output", lambda *args, **kwargs: inventory)
    return module


@pytest.fixture(params=GUARDS, ids=[f"{path.name}:{name}" for path, name in GUARDS])
def guard(request, manager_util):
    """Compile unchanged function bodies; do not import startup/install hooks."""
    path, name = request.param
    if not path.exists():
        pytest.skip("MANAGER_GLOB_DIR points at a glob directory without prestartup_script.py beside it")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    config = SimpleNamespace(pip_blacklist=set(), pip_downgrade_blacklist=["opencv-python", "numpy"])
    namespace = {"re": re, "cm_global": config, "manager_util": manager_util}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name], config, name


@pytest.mark.parametrize(
    "requirement",
    ["opencv-python~=4.8.1.78", "OpenCV_Python==4.8.1.78", "OPENCV-PYTHON<4.9.0", "opencv-python"],
)
def test_protected_package_is_recognized(guard, requirement):
    """A display-name alias must not bypass downgrade protection."""
    check, _, _ = guard
    assert check(requirement) is True


def test_blacklist_entry_uses_the_same_name_format(guard):
    """Configuration aliases must match the inventory and requirement names."""
    check, config, _ = guard
    config.pip_downgrade_blacklist = ["OpenCV_Python"]
    assert check("opencv-python~=4.8.1.78") is True
    config.pip_downgrade_blacklist = []
    config.pip_blacklist = {"OpenCV-Python"}
    assert check("opencv_python>=6.0.0") is True


def test_upgrade_is_still_allowed(guard):
    """Protection must not suppress an upgrade to a newer required version."""
    check, _, _ = guard
    assert check("opencv-python>=6.0.0") is False


def test_missing_package_is_not_reported_installed(guard):
    """A protected name alone does not mean the package is installed."""
    check, config, _ = guard
    config.pip_downgrade_blacklist.append("missing-package")
    assert check("missing-package==1.0.0") is False


def test_existing_simple_package_protection(guard):
    """The existing NumPy downgrade guard must continue to work."""
    check, _, _ = guard
    assert check("numpy==1.26.4") is True


def test_unprotected_installed_package(guard):
    """Installed status remains distinct from blacklist membership."""
    check, config, name = guard
    config.pip_downgrade_blacklist = []
    assert check("opencv-python") is (name == "is_installed")
