import ast
import os
import subprocess
import sys

import pytest

from legacy_html_testutil import PACKAGE


@pytest.mark.parametrize('use_pygit2, line', [
    ('', '[ComfyUI-Manager] Using GitPython backend'),
    ('1', '[ComfyUI-Manager] Using pygit2 backend (CM_USE_PYGIT2=1)'),
])
def test_git_backend_is_not_told_by_the_import_so_that_cm_cli_writes_only_the_output_of_its_command(use_pygit2, line):
    done = subprocess.run([sys.executable, '-c', 'import git_compat; print(git_compat.BACKEND_LINE)'], capture_output=True, text=True,
                          cwd=PACKAGE / 'common', env={**os.environ, 'CM_USE_PYGIT2': use_pygit2})

    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [line]
    assert line not in done.stderr


def test_git_backend_is_told_by_the_server_at_its_start():
    body = ast.parse((PACKAGE / 'prestartup_script.py').read_text(encoding='utf-8')).body
    told = [number for number, statement in enumerate(body) if ast.unparse(statement) == 'print(git_compat.BACKEND_LINE, file=sys.stderr)']
    imported = [number for number, statement in enumerate(body) if ast.unparse(statement) == 'from .common import git_compat']

    assert len(told) == 1 and told[0] == imported[0] + 1
