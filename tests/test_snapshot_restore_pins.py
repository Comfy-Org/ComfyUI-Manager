"""Restoring a snapshot compares each nodepack with the version or commit the snapshot pins.

A Registry nodepack already at the pinned version is left as it is, without asking the
Registry about it. A git nodepack is checked out at the pinned commit hash; the hash is
the bare 40 characters both when it is read from a repository whose HEAD is detached and
when it comes from a snapshot that an older version saved with the newline still attached.
"""

import asyncio
import json
import subprocess
from unittest.mock import AsyncMock, Mock

import pytest

from _install_flags_testutil import import_context, import_reader


COMMIT = '0123456789abcdef0123456789abcdef01234567'
REPO_URL = 'https://github.com/owner/fixture'


def git(path, *args):
    return subprocess.run(['git', *args], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(params=['glob', 'legacy'])
def core(request, monkeypatch, tmp_path):
    core = import_reader(request.param)
    monkeypatch.setattr(core, 'get_default_custom_nodes_path', lambda: str(tmp_path))
    monkeypatch.setattr(core.manager_util, 'restore_pip_snapshot', Mock())
    return core


@pytest.fixture
def manager(core, monkeypatch):
    manager = core.UnifiedManager()
    manager.reload = AsyncMock()
    manager.get_custom_nodes = AsyncMock(return_value={})
    monkeypatch.setattr(core, 'unified_manager', manager)
    return manager


def restore(core, tmp_path, **snapshot):
    path = tmp_path / 'snapshot.json'
    path.write_text(json.dumps({'cnr_custom_nodes': {}, 'git_custom_nodes': {}, 'file_custom_nodes': [], **snapshot}))
    asyncio.run(core.restore_snapshot(str(path)))


@pytest.mark.parametrize('head, expected', [
    (COMMIT + '\n', COMMIT),
    ('ref: refs/heads/main\n', COMMIT),
])
def test_commit_hash_has_no_trailing_newline(tmp_path, head, expected):
    import_context()
    from comfyui_manager.common import git_utils

    (tmp_path / '.git/refs/heads').mkdir(parents=True)
    (tmp_path / '.git/HEAD').write_text(head)
    (tmp_path / '.git/refs/heads/main').write_text(COMMIT + '\n')

    assert git_utils.get_commit_hash(str(tmp_path)) == expected


def test_registry_pack_at_the_pinned_version_is_left_alone(core, manager, monkeypatch, tmp_path):
    installed = tmp_path / 'fixture'
    installed.mkdir()
    manager.active_nodes['fixture'] = ('2.0.0', str(installed))
    query = Mock(side_effect=AssertionError('a pack at the pinned version must not query the Registry'))
    monkeypatch.setattr(core.cnr_utils.requests, 'get', query)

    restore(core, tmp_path, cnr_custom_nodes={'fixture': '2.0.0'})

    query.assert_not_called()
    assert manager.active_nodes['fixture'] == ('2.0.0', str(installed))


def test_registry_pack_at_another_version_is_switched(core, manager, tmp_path):
    manager.active_nodes['fixture'] = ('1.0.0', str(tmp_path / 'fixture'))
    manager.cnr_switch_version = Mock(return_value=core.ManagedResult('switch-cnr'))

    restore(core, tmp_path, cnr_custom_nodes={'fixture': '2.0.0'})

    assert manager.cnr_switch_version.call_args.args == ('fixture', '2.0.0')


@pytest.fixture
def pack(tmp_path):
    """A git nodepack with two commits, checked out at the second; returns its path and the two hashes."""
    path = tmp_path / 'fixture'
    path.mkdir()
    git(path, 'init', '-q')
    commits = []
    for version in (1, 2):
        (path / '__init__.py').write_text(f'VERSION = {version}\n')
        git(path, 'add', '.')
        git(path, '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '-q', '-m', f'version {version}')
        commits.append(git(path, 'rev-parse', 'HEAD'))
    return path, commits


@pytest.mark.parametrize('newline', ['', '\n'])
def test_git_pack_is_checked_out_at_the_pinned_commit(core, manager, pack, tmp_path, newline):
    path, (first, second) = pack
    manager.active_nodes['fixture'] = ('nightly', str(path))
    manager.repo_cnr_map[REPO_URL] = {'id': 'fixture'}
    manager.install_by_id = AsyncMock(return_value=core.ManagedResult('skip'))
    assert git(path, 'rev-parse', 'HEAD') == second

    restore(core, tmp_path, git_custom_nodes={REPO_URL: {'hash': first + newline, 'disabled': False}})

    assert git(path, 'rev-parse', 'HEAD') == first
    assert (path / '__init__.py').read_text() == 'VERSION = 1\n'
