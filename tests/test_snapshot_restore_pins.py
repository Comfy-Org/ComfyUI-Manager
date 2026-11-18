"""Restoring a snapshot compares each node pack with the version or commit the snapshot pins.

A registry node pack already at the pinned version is left as it is, without asking the
registry about it. A git node pack is checked out at the pinned commit; the hash is the
bare 40 characters both when it is read from a repository whose HEAD is detached and when
it comes from a snapshot that an older version saved with the newline still attached.

The restore runs in the isolated child of tests/test_install_flags_config.py, against the
real glob/manager_core and a real git repository.
"""

import importlib.util

import pytest

from manager_test_utils import GLOB_DIR
from test_install_flags_config import _run_child


COMMIT = '0123456789abcdef0123456789abcdef01234567'

PRELUDE = '''
import asyncio, pathlib, subprocess
from unittest.mock import AsyncMock, Mock
import cnr_utils, manager_util
core = manager_core
nodes = pathlib.Path(tmp) / 'custom_nodes'
nodes.mkdir()
core.get_default_custom_nodes_path = lambda: str(nodes)
manager_util.restore_pip_snapshot = Mock(return_value=[])
manager = core.UnifiedManager()
manager.reload = AsyncMock()
manager.get_custom_nodes = AsyncMock(return_value={})
core.unified_manager = manager

def restore(**snapshot):
    path = pathlib.Path(tmp) / 'snapshot.json'
    path.write_text(json.dumps({'cnr_custom_nodes': {}, 'git_custom_nodes': {}, 'file_custom_nodes': [], **snapshot}))
    return asyncio.run(core.restore_snapshot(str(path)))

def git(*args):
    return subprocess.run(['git', *args], cwd=nodes / 'fixture', check=True, capture_output=True, text=True).stdout.strip()
'''


def run(body):
    return _run_child(PRELUDE + body)


@pytest.mark.parametrize('head, expected', [
    (COMMIT + '\n', COMMIT),
    ('ref: refs/heads/main\n', COMMIT),
])
def test_commit_hash_has_no_trailing_newline(tmp_path, head, expected):
    spec = importlib.util.spec_from_file_location('_git_utils_under_test', GLOB_DIR / 'git_utils.py')
    git_utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(git_utils)

    (tmp_path / '.git/refs/heads').mkdir(parents=True)
    (tmp_path / '.git/HEAD').write_text(head)
    (tmp_path / '.git/refs/heads/main').write_text(COMMIT + '\n')

    assert git_utils.get_commit_hash(str(tmp_path)) == expected


def test_registry_pack_at_the_pinned_version_is_left_alone():
    data = run('''
(nodes / 'fixture').mkdir()
manager.active_nodes['fixture'] = ('2.0.0', str(nodes / 'fixture'))
query = Mock(side_effect=OSError('the registry cannot be reached'))
cnr_utils.requests.get = query
error = None
try:
    restore(cnr_custom_nodes={'fixture': '2.0.0'})
except Exception as e:
    error = repr(e)
print(json.dumps({'queries': query.call_count, 'error': error, 'version': manager.active_nodes['fixture'][0]}))
''')
    assert data == {'queries': 0, 'error': None, 'version': '2.0.0'}


def test_registry_pack_at_another_version_is_switched():
    data = run('''
manager.active_nodes['fixture'] = ('1.0.0', str(nodes / 'fixture'))
manager.cnr_switch_version = Mock(return_value=core.ManagedResult('switch-cnr'))
restore(cnr_custom_nodes={'fixture': '2.0.0'})
print(json.dumps({'switched_to': list(manager.cnr_switch_version.call_args.args)}))
''')
    assert data == {'switched_to': ['fixture', '2.0.0']}


@pytest.mark.parametrize('newline', ['', '\n'])
def test_git_pack_is_checked_out_at_the_pinned_commit(newline):
    data = run(f'''
newline = {newline!r}
repo_url = 'https://github.com/owner/fixture'
(nodes / 'fixture').mkdir()
git('init', '-q')
commits = []
for version in (1, 2):
    (nodes / 'fixture/__init__.py').write_text('VERSION = %d' % version)
    git('add', '.')
    git('-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '-q', '-m', 'version %d' % version)
    commits.append(git('rev-parse', 'HEAD'))
manager.active_nodes['fixture'] = ('nightly', str(nodes / 'fixture'))
manager.repo_cnr_map[repo_url] = {{'id': 'fixture'}}
manager.install_by_id = AsyncMock(return_value=core.ManagedResult('skip'))
restore(git_custom_nodes={{repo_url: {{'hash': commits[0] + newline, 'disabled': False}}}})
print(json.dumps({{'at_first_commit': git('rev-parse', 'HEAD') == commits[0],
    'file': (nodes / 'fixture/__init__.py').read_text()}}))
''')
    assert data == {'at_first_commit': True, 'file': 'VERSION = 1'}
