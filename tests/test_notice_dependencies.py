"""Exercise notice dependency installation without starting ComfyUI or pip."""
import ast
import builtins
import importlib.metadata
import itertools
import os
import re
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

import toml
from packaging.requirements import Requirement

from manager_test_utils import load_manager_util

ROOT = Path(__file__).resolve().parent.parent


class NoticeDependencyTest(unittest.TestCase):
    def test_util_can_load_before_nh3_is_installed(self):
        with patch.dict(sys.modules, {'nh3': None}):
            util = load_manager_util()
            self.assertEqual(util.escape_html_attribute('<text>'), '&lt;text&gt;')
            with self.assertRaises(ModuleNotFoundError):
                util.sanitize_html_fragment('<p>notice</p>')

    def test_bootstrap_installs_missing_or_outdated_nh3_before_importing_it(self):
        manifest = (ROOT / 'requirements.txt').read_text()
        commented_manifest = '\n# Dependencies\n--index-url https://pypi.org/simple\n' + manifest.replace(
            'nh3>=0.3.7', '  nh3>=0.3.7  # notice sanitizer',
        )
        for installed_version, requirements in itertools.product(
            (None, '0.3.0', '0.3.7rc1', '0.3.7', '0.4.0'), (manifest, commented_manifest),
        ):
            with self.subTest(installed_version=installed_version, commented=requirements == commented_manifest):
                source = (ROOT / 'prestartup_script.py').read_text()
                node = next(n for n in ast.parse(source).body
                            if isinstance(n, ast.FunctionDef) and n.name == 'ensure_dependencies')
                installer = Mock()
                namespace = {
                    '__file__': str(ROOT / 'prestartup_script.py'),
                    'os': os,
                    're': re,
                    'subprocess': types.SimpleNamespace(
                        check_output=installer, CalledProcessError=subprocess.CalledProcessError,
                    ),
                    'manager_util': types.SimpleNamespace(make_pip_cmd=lambda args: args),
                }
                exec(compile(ast.Module(body=[node], type_ignores=[]), '<bootstrap>', 'exec'), namespace)
                needs_install = installed_version in (None, '0.3.0', '0.3.7rc1')
                modules = {name: types.ModuleType(name) for name in ('git', 'toml', 'rich', 'chardet')}
                # An old native module must not be imported before pip upgrades it.
                modules['nh3'] = None if needs_install else types.ModuleType('nh3')
                failure = importlib.metadata.PackageNotFoundError('nh3') if installed_version is None else None
                with patch.dict(sys.modules, modules), patch(
                    'importlib.metadata.version', return_value=installed_version, side_effect=failure,
                ), patch('builtins.open', mock_open(read_data=requirements)), patch('builtins.print'), patch(
                    'builtins.__import__', wraps=builtins.__import__,
                ) as imports:
                    namespace['ensure_dependencies']()
                nh3_imports = [call for call in imports.call_args_list if call.args[0] == 'nh3']
                self.assertEqual(len(nh3_imports), 0 if needs_install else 1)
                if needs_install:
                    installer.assert_called_once_with(['install', '-r', str(ROOT / 'requirements.txt')])
                else:
                    installer.assert_not_called()

    def test_dependency_manifests_agree_on_notice_requirements(self):
        lines = (re.split(r'\s+#', line.strip(), maxsplit=1)[0]
                 for line in (ROOT / 'requirements.txt').read_text().splitlines())
        pip_requirements = {
            req.name: req for req in map(Requirement, (line for line in lines if line and not line.startswith(('#', '-'))))
        }
        project_requirements = {
            req.name: req for req in map(Requirement, toml.load(ROOT / 'pyproject.toml')['project']['dependencies'])
        }
        for name in ('nh3', 'packaging'):
            with self.subTest(name=name):
                self.assertEqual(str(pip_requirements[name]), str(project_requirements[name]))
