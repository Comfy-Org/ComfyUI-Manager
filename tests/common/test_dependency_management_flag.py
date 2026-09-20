"""
Tests for the `dependency_management` opt-out switch.

Covers the module-level flag, the value parser shared with prestartup, and
the early-return in `PIPFixer.fix_broken()`. The prestartup gates (unified
resolver, lazy install) are exercised end-to-end; the unit tests here lock
in the read paths and the short-circuit semantics.
"""

import subprocess
import sys
import types
import unittest
from unittest import mock


def _import_manager_util():
    # `comfyui_manager/__init__.py` imports `comfy.cli_args` at module load
    # time; stub the host-side modules so the unit under test can be imported
    # without a full ComfyUI runtime.
    for name in ("comfy", "comfy.cli_args"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["comfy.cli_args"].args = types.SimpleNamespace(base_directory=None)

    from comfyui_manager.common import manager_util  # noqa: WPS433
    return manager_util


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

        with mock.patch.object(subprocess, "check_output") as patched:
            _Stub().fix_broken()

        patched.assert_not_called()

    def test_pip_fixer_runs_when_enabled(self):
        # Enabled path should at least call subprocess (via get_installed_packages).
        self.manager_util.dependency_management_enabled = True

        class _Stub(self.manager_util.PIPFixer):
            def __init__(self):
                self.prev_pip_versions = {}
                self.comfyui_path = "/nonexistent"
                self.manager_files_path = "/nonexistent"

        with mock.patch.object(subprocess, "check_output", return_value="Package Version\n------- -------\n") as patched:
            try:
                _Stub().fix_broken()
            except Exception:
                # Other internal paths (opencv, frontend) may raise on a stub
                # tree — we only care that subprocess was reached at least once.
                pass

        self.assertGreaterEqual(patched.call_count, 1)

    def test_make_pip_cmd_not_gated(self):
        # make_pip_cmd is consulted for both read and write ops (pip list,
        # pip install, …). Gating it would break read paths the UI relies on.
        # Assert the helper still produces a runnable command when the flag
        # is off — gating happens at call sites that perform writes.
        self.manager_util.dependency_management_enabled = False

        cmd = self.manager_util.make_pip_cmd(["list"])
        self.assertIsInstance(cmd, list)
        self.assertGreaterEqual(len(cmd), 3)
        self.assertIn("list", cmd)

        cmd = self.manager_util.make_pip_cmd(["install", "some-pkg"])
        self.assertIn("install", cmd)
        self.assertIn("some-pkg", cmd)


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
