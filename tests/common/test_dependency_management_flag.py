"""
Tests for the `dependency_management` opt-out switch without a ComfyUI runtime.

Load the actual utility module and startup functions with isolated collaborators;
never execute startup's host-side registration, network, or interpreter mutations.
"""

import ast
import importlib.util
import logging
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


_PACKAGE = Path(__file__).resolve().parents[2] / "comfyui_manager"


def _import_manager_util():
    # Other tests replace the public module with a resolver stub. Import a fresh
    # private instance rather than depending on collection order or booting the
    # package's __init__, which imports the full ComfyUI application.
    spec = importlib.util.spec_from_file_location(
        "dependency_management_test_util", _PACKAGE / "common" / "manager_util.py"
    )
    module = importlib.util.module_from_spec(spec)
    # HTTP is unrelated to dependency policy and is never called by these tests.
    with mock.patch.dict(sys.modules, {"aiohttp": types.ModuleType("aiohttp")}):
        spec.loader.exec_module(module)
    return module


def _startup_namespace(manager_util):
    return {
        "manager_util": manager_util,
        "os": os,
        "logging": logging,
        "default_conf": {},
        "processed_install": set(),
        "_unified_resolver_succeeded": False,
        "comfy_path": "/externally-managed-comfy",
        "process_wrap": mock.Mock(return_value=0),
        "is_installed": mock.Mock(return_value=False),
        "remap_pip_package": lambda package: package,
    }


def _load_startup_nodes(namespace, predicate):
    path = _PACKAGE / "prestartup_script.py"
    parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes = [node for node in parsed.body if predicate(node)]
    if not nodes:
        raise AssertionError("Startup policy code was not found")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)


class DependencyManagementFlagTest(unittest.TestCase):
    def setUp(self):
        self.manager_util = _import_manager_util()
        self._prev = self.manager_util.dependency_management_enabled
        self.addCleanup(setattr, self.manager_util, "dependency_management_enabled", self._prev)

    def test_default_is_enabled(self):
        # Default must preserve today's behavior.
        self.assertTrue(self._prev)

    def test_pip_fixer_short_circuits_when_disabled(self):
        self.manager_util.dependency_management_enabled = False

        class _Stub(self.manager_util.PIPFixer):
            def __init__(self):  # bypass parent init
                pass

        with mock.patch.object(self.manager_util, "get_installed_packages") as patched:
            _Stub().fix_broken()

        patched.assert_not_called()

    def test_pip_fixer_runs_when_enabled(self):
        # The enabled path must read the current installed package inventory.
        self.manager_util.dependency_management_enabled = True

        class _Stub(self.manager_util.PIPFixer):
            def __init__(self):
                self.prev_pip_versions = {}
                self.comfyui_path = "/nonexistent"
                self.manager_files_path = "/nonexistent"

        class InventoryRead(Exception):
            pass

        with mock.patch.object(self.manager_util, "get_installed_packages", side_effect=InventoryRead) as patched:
            with self.assertRaises(InventoryRead):
                _Stub().fix_broken()

        patched.assert_called_once_with(True)

    def test_make_pip_cmd_not_gated(self):
        # make_pip_cmd is consulted for both read and write ops (pip list,
        # pip install, …). Gating it would break read paths the UI relies on.
        # Assert the helper still produces a runnable command when the flag
        # is off — gating happens at call sites that perform writes.
        self.manager_util.dependency_management_enabled = False

        with mock.patch.object(self.manager_util, "get_pip_cmd", return_value=[sys.executable, "-m", "pip"]):
            cmd = self.manager_util.make_pip_cmd(["list"])
            install_cmd = self.manager_util.make_pip_cmd(["install", "some-pkg"])
        self.assertIsInstance(cmd, list)
        self.assertGreaterEqual(len(cmd), 3)
        self.assertIn("list", cmd)

        self.assertIn("install", install_cmd)
        self.assertIn("some-pkg", install_cmd)


class StartupDependencyPolicyTest(unittest.TestCase):
    def setUp(self):
        self.manager_util = _import_manager_util()
        self.namespace = _startup_namespace(self.manager_util)
        _load_startup_nodes(
            self.namespace,
            lambda node: isinstance(node, ast.FunctionDef)
            and node.name in {"read_dependency_management_mode", "execute_lazy_install_script"},
        )

    def test_config_off(self):
        self.namespace["default_conf"]["dependency_management"] = "off"
        with mock.patch.dict(os.environ, {}, clear=True):
            self.namespace["read_dependency_management_mode"]()
        self.assertFalse(self.manager_util.dependency_management_enabled)

    def test_environment_wins_in_both_directions(self):
        for config, environment, expected in [("off", "on", True), ("on", "off", False)]:
            with self.subTest(config=config, environment=environment):
                self.namespace["default_conf"]["dependency_management"] = config
                with mock.patch.dict(os.environ, {"COMFYUI_MANAGER_DEPENDENCY_MANAGEMENT": environment}, clear=True):
                    self.namespace["read_dependency_management_mode"]()
                self.assertEqual(self.manager_util.dependency_management_enabled, expected)

    def test_lazy_requirements_are_skipped_when_disabled(self):
        self.manager_util.dependency_management_enabled = False
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "requirements.txt").write_text("example-package==1.0\n")
            self.namespace["execute_lazy_install_script"](directory, sys.executable)
        self.namespace["process_wrap"].assert_not_called()

    def test_lazy_requirements_are_installed_when_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "requirements.txt").write_text("example-package==1.0\n")
            with (
                mock.patch.object(self.manager_util, "robust_readlines", return_value=["example-package==1.0\n"]),
                mock.patch.object(self.manager_util, "make_pip_cmd", return_value=["pip", "install", "example-package==1.0"]),
            ):
                self.namespace["execute_lazy_install_script"](directory, sys.executable)
            self.namespace["process_wrap"].assert_called_once_with(
                ["pip", "install", "example-package==1.0"], directory
            )

    def test_explicit_node_install_script_is_not_gated(self):
        self.manager_util.dependency_management_enabled = False
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "install.py").write_text("# Explicitly scheduled node installation\n")
            self.namespace["execute_lazy_install_script"](directory, sys.executable)
            call = self.namespace["process_wrap"].call_args
            self.assertEqual(call.args, ([sys.executable, "install.py"], directory))
            self.assertEqual(call.kwargs["env"]["COMFYUI_FOLDERS_BASE_PATH"], self.namespace["comfy_path"])

    def test_disabled_startup_preserves_explicit_resolver_preference(self):
        self.manager_util.dependency_management_enabled = False
        self.manager_util.use_unified_resolver = True
        _load_startup_nodes(
            self.namespace,
            lambda node: isinstance(node, ast.If)
            and any(isinstance(part, ast.Attribute) and part.attr == "use_unified_resolver" for part in ast.walk(node.test)),
        )
        self.assertTrue(self.manager_util.use_unified_resolver)
        self.assertFalse(self.namespace["_unified_resolver_succeeded"])


class IsOffValueTest(unittest.TestCase):
    """`is_off_value` is the single source of truth for the config/env vocabulary."""

    def setUp(self):
        self.manager_util = _import_manager_util()

    def test_off_synonyms(self):
        for value in ("off", "OFF", " false ", "0", "no", "Disabled"):
            with self.subTest(value=value):
                self.assertTrue(self.manager_util.is_off_value(value))

    def test_on_values(self):
        # Anything not in the off vocabulary — including the empty string and
        # typos — keeps dependency management enabled. Better to be noisy than
        # to silently swallow installs.
        for value in ("on", "true", "1", "yes", "enabled", "auto", "", "  ", "off-ish"):
            with self.subTest(value=value):
                self.assertFalse(self.manager_util.is_off_value(value))


if __name__ == "__main__":
    unittest.main()
