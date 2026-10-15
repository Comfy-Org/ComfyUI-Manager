"""Regression checks for arguments passed through the legacy restart path."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'glob'))
from restart_command import build_restart_argv


class RestartCommandTests(unittest.TestCase):
    def test_preserves_arguments_and_paths_with_spaces(self):
        executable = r'C:\Program Files\Python\python.exe'
        script = r'C:\Users\A User\ComfyUI\main.py'
        original = [script, '--browser-profile', 'Profile 1', '--output-directory', r'C:\My Images']

        self.assertEqual(
            build_restart_argv(executable, original),
            [executable, *original],
        )

    def test_module_entry_point_and_standalone_flag(self):
        original = ['/apps/comfy/mainpkg/__main__.py', '--windows-standalone-build',
                    '--name', 'My Profile']
        self.assertEqual(
            build_restart_argv('/usr/bin/python3', original),
            ['/usr/bin/python3', '-m', 'mainpkg', '--name', 'My Profile'],
        )
        self.assertEqual(original[1], '--windows-standalone-build')

    def test_execv_preserves_argument_boundaries(self):
        with tempfile.TemporaryDirectory(prefix='comfy restart ') as tmp:
            script = Path(tmp) / 'main entry.py'
            script.write_text('import json, sys; print(json.dumps(sys.argv))\n')
            launcher = (
                'import os, sys; '
                'sys.path.insert(0, sys.argv[1]); '
                'from restart_command import build_restart_argv; '
                'os.execv(sys.executable, build_restart_argv(sys.executable, sys.argv[2:]))'
            )
            result = subprocess.run(
                [sys.executable, '-c', launcher, str(ROOT / 'glob'), str(script),
                 '--browser-profile', 'Profile 1'],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(json.loads(result.stdout), [str(script), '--browser-profile', 'Profile 1'])


if __name__ == '__main__':
    unittest.main()
