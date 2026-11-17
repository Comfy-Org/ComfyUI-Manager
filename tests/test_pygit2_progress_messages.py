"""A progress message of the server that is not UTF-8 by itself does not end a clone or a fetch of the pygit2 backend.

pygit2 decodes each piece of such a message as UTF-8 before it hands it on, and a piece can end in the
middle of a character: with a server that writes its messages in Korean, a clone failed now and then.
Each case runs in a process of its own, with pygit2 asked for and no git executable on `PATH`, against a
`git daemon` whose message is the first two bytes of a Korean character. The server of the cases with a proxy, in
tests/test_pygit2_submodules.py, writes the same message.
"""

import os
import shutil
import socket
import subprocess
import time

import pytest

from _install_flags_testutil import GIT_LOCATION
from test_git_commit_and_submodules import git_with_local_submodules, head, repository
from test_pygit2_submodules import MESSAGE_CUT_IN_A_CHARACTER, git_host_behind_a_proxy, pin, run_with_pygit2  # noqa: F401

pytest.importorskip('pygit2')


@pytest.fixture(autouse=True)
def git_finds_its_repository_by_the_directory(monkeypatch):
    for name in GIT_LOCATION:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def git_host(tmp_path):
    """The directory that a `git daemon` serves, and its url."""
    exec_path = subprocess.run(['git', '--exec-path'], capture_output=True, text=True).stdout.strip()
    if not shutil.which('git-daemon', path=exec_path):
        pytest.skip('git daemon is not installed')
    served = tmp_path / 'served'
    served.mkdir()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    daemon = subprocess.Popen(['git', 'daemon', '--export-all', '--reuseaddr', f'--base-path={served}', '--listen=127.0.0.1', f'--port={port}', str(served)],
                              env={**os.environ, **MESSAGE_CUT_IN_A_CHARACTER},
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                socket.create_connection(('127.0.0.1', port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        yield served, f'git://127.0.0.1:{port}'
    finally:
        daemon.terminate()
        daemon.wait()


def test_clone(tmp_path, git_host):
    served, url = git_host
    repository(served / 'fixture')

    child = run_with_pygit2(tmp_path, f"git_compat.clone_repo({url + '/fixture'!r}, {str(tmp_path / 'clone')!r})")

    assert child.returncode == 0, child.stderr[-600:]
    assert (tmp_path / 'clone/__init__.py').read_text() == 'VERSION = 2'


def test_fetch(tmp_path, git_host):
    served, url = git_host
    repository(served / 'fixture')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', url + '/fixture', str(clone))
    (served / 'fixture/__init__.py').write_text('VERSION = 3')
    git_with_local_submodules(served / 'fixture', 'commit', '-q', '-a', '-m', 'version 3')

    child = run_with_pygit2(tmp_path, f'git_compat.open_repo({str(clone)!r}).fetch_remote_by_index(0)')

    assert child.returncode == 0, child.stderr[-600:]
    git_with_local_submodules(clone, 'cat-file', '-e', head(served / 'fixture'))


def test_update_of_the_submodules(tmp_path, git_host):
    served, url = git_host
    repository(served / 'library')
    origin = tmp_path / 'origin'
    origin.mkdir()
    git_with_local_submodules(origin, 'init', '-q')
    git_with_local_submodules(origin, 'submodule', 'add', '-q', url + '/library', 'library')
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'a submodule')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(origin), str(clone))

    child = run_with_pygit2(tmp_path, f'git_compat.open_repo({str(clone)!r}).submodule_update()')

    assert child.returncode == 0, child.stderr[-600:]
    assert (clone / 'library/__init__.py').read_text() == 'VERSION = 2'


def test_update_of_the_submodules_that_are_fetched(tmp_path, git_host):
    served, url = git_host
    repository(served / 'library')
    origin = tmp_path / 'origin'
    origin.mkdir()
    git_with_local_submodules(origin, 'init', '-q')
    git_with_local_submodules(origin, 'submodule', 'add', '-q', url + '/library', 'library')
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'a submodule')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', '--recurse-submodules', str(origin), str(clone))
    # a commit that the clone of the submodule does not have yet
    (served / 'library/__init__.py').write_text('VERSION = 3')
    git_with_local_submodules(served / 'library', 'commit', '-q', '-a', '-m', 'version 3')
    pin(clone, 'library', head(served / 'library'))

    child = run_with_pygit2(tmp_path, f'git_compat.open_repo({str(clone)!r}).submodule_update(init=False)')

    assert child.returncode == 0, child.stderr[-600:]
    assert (clone / 'library/__init__.py').read_text() == 'VERSION = 3'


def test_fetch_of_a_remote_with_an_ssh_url(tmp_path, git_host_behind_a_proxy):  # noqa: F811
    """It is fetched over https, from a remote that is made for the fetch."""
    repository(tmp_path / 'fixture')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(tmp_path / 'fixture'), str(clone))
    git_with_local_submodules(clone, 'remote', 'set-url', 'origin', 'git@localhost:fixture')
    (tmp_path / 'fixture/__init__.py').write_text('VERSION = 3')
    git_with_local_submodules(tmp_path / 'fixture', 'commit', '-q', '-a', '-m', 'version 3')

    child = run_with_pygit2(tmp_path, f'git_compat.open_repo({str(clone)!r}).fetch_remote_by_index(0)')

    assert child.returncode == 0, child.stderr[-600:]
    git_with_local_submodules(clone, 'cat-file', '-e', head(tmp_path / 'fixture'))
