import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from _install_flags_testutil import GIT_LOCATION
from test_git_commit_and_submodules import git_with_local_submodules, head, repository, repository_with_a_submodule

pytest.importorskip('pygit2')

# For a git server: what `pack-objects` writes to stderr reaches the client as a progress message, here the first
# two bytes of a Korean character. pygit2 decodes each piece of a message, and a piece can end like that.
MESSAGE_CUT_IN_A_CHARACTER = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'uploadpack.packObjectsHook',
                              'GIT_CONFIG_VALUE_0': """sh -c 'printf "\\355\\225" >&2; exec "$@"' --"""}


@pytest.fixture(autouse=True)
def git_finds_its_repository_by_the_directory(monkeypatch):
    for name in GIT_LOCATION:
        monkeypatch.delenv(name, raising=False)


def run_with_pygit2(tmp_path, code):
    (tmp_path / 'no-git').mkdir(exist_ok=True)
    common = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'comfyui_manager', 'common')
    code = f'import sys; sys.path.insert(0, {common!r}); import git_compat\nassert git_compat.USE_PYGIT2\n{code}\n'
    env = {key: value for key, value in os.environ.items() if key not in ('GIT_EXE_PATH', 'GIT_PYTHON_GIT_EXECUTABLE')}
    return subprocess.run([sys.executable, '-c', code], env={**env, 'PATH': str(tmp_path / 'no-git'), 'CM_USE_PYGIT2': '1'},
                          capture_output=True, text=True)


def update_submodules_with_pygit2(tmp_path, clone, init=True, first=''):
    return run_with_pygit2(tmp_path, f'{first}\ngit_compat.open_repo({str(clone)!r}).submodule_update(init={init})')


def test_pygit2_updates_the_fetched_submodules_beside_one_never_fetched(tmp_path):
    library = repository(tmp_path / 'library')
    origin = tmp_path / 'origin'
    origin.mkdir()
    git_with_local_submodules(origin, 'init', '-q')
    for name in ('a-never-fetched', 'b-fetched'):
        git_with_local_submodules(origin, 'submodule', 'add', '-q', str(tmp_path / 'library'), name)
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'two submodules')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(origin), str(clone))
    git_with_local_submodules(clone, 'submodule', 'update', '-q', '--init', 'b-fetched')
    git_with_local_submodules(clone / 'b-fetched', 'checkout', '-q', library[0])
    (tmp_path / 'no-git').mkdir()
    common = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'comfyui_manager', 'common')
    code = (f'import sys; sys.path.insert(0, {common!r}); import git_compat\n'
            f'assert git_compat.USE_PYGIT2\ngit_compat.open_repo({str(clone)!r}).submodule_update(init=False)\n')
    env = {key: value for key, value in os.environ.items() if key not in ('GIT_EXE_PATH', 'GIT_PYTHON_GIT_EXECUTABLE')}

    child = subprocess.run([sys.executable, '-c', code], env={**env, 'PATH': str(tmp_path / 'no-git'), 'CM_USE_PYGIT2': '1'},
                           capture_output=True, text=True)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'b-fetched') == library[1]
    assert os.listdir(clone / 'a-never-fetched') == []


def test_pygit2_updates_a_submodule_of_a_submodule(tmp_path):
    library, _ = repository_with_a_submodule(tmp_path)
    outer = tmp_path / 'outer'
    outer.mkdir()
    git_with_local_submodules(outer, 'init', '-q')
    git_with_local_submodules(outer, 'submodule', 'add', '-q', str(tmp_path / 'origin'), 'origin')
    git_with_local_submodules(outer, 'commit', '-q', '-a', '-m', 'a submodule with a submodule')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(outer), str(clone))

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert (clone / 'origin/library/__init__.py').exists()
    assert head(clone / 'origin/library') == library[1]

    git_with_local_submodules(clone / 'origin/library', 'checkout', '-q', library[0])
    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'origin/library') == library[1]

    git_with_local_submodules(clone / 'origin/library', 'checkout', '-q', library[0])
    child = update_submodules_with_pygit2(tmp_path, clone, init=False)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'origin/library') == library[1]


def test_pygit2_leaves_a_submodule_of_a_submodule_that_was_never_fetched_alone(tmp_path):
    repository_with_a_submodule(tmp_path)
    outer, clone = tmp_path / 'outer', tmp_path / 'clone'
    outer.mkdir()
    git_with_local_submodules(outer, 'init', '-q')
    git_with_local_submodules(outer, 'submodule', 'add', '-q', str(tmp_path / 'origin'), 'origin')
    git_with_local_submodules(outer, 'commit', '-q', '-a', '-m', 'a submodule with a submodule')
    git_with_local_submodules(tmp_path, 'clone', '-q', str(outer), str(clone))
    git_with_local_submodules(clone, 'submodule', 'update', '-q', '--init', 'origin')

    child = update_submodules_with_pygit2(tmp_path, clone, init=False)

    assert child.returncode == 0, child.stderr
    assert os.listdir(clone / 'origin/library') == []


def test_pygit2_passes_over_a_submodule_that_gitmodules_alone_names(tmp_path):
    """As git does: an entry left in `.gitmodules` for a submodule that was removed is not a failure."""
    library, _ = repository_with_a_submodule(tmp_path)
    with open(tmp_path / 'origin/.gitmodules', 'a', encoding='utf-8') as gitmodules:
        gitmodules.write(f'[submodule "a-removed"]\n\tpath = a-removed\n\turl = {(tmp_path / "nowhere").as_posix()}\n')
    git_with_local_submodules(tmp_path / 'origin', 'commit', '-q', '-a', '-m', 'an entry without a submodule')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(tmp_path / 'origin'), str(clone))

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == library[1]


@pytest.mark.parametrize('init', [True, False])
def test_pygit2_passes_over_a_submodule_that_gitmodules_alone_names_whose_directory_was_fetched(tmp_path, init):
    """As git leaves it after a pull that removed the submodule: its directory is still there."""
    library, _ = repository_with_a_submodule(tmp_path)
    origin, clone = tmp_path / 'origin', tmp_path / 'clone'
    git_with_local_submodules(origin, 'submodule', 'add', '-q', str(tmp_path / 'library'), 'a-removed')
    git_with_local_submodules(origin, 'commit', '-q', '-m', 'a submodule that is removed next')
    git_with_local_submodules(tmp_path, 'clone', '-q', '--recursive', str(origin), str(clone))
    git_with_local_submodules(origin, 'rm', '-q', '--cached', 'a-removed')
    git_with_local_submodules(origin, 'commit', '-q', '-m', 'an entry without a submodule')
    git_with_local_submodules(clone, 'pull', '-q')
    git_with_local_submodules(clone / 'library', 'checkout', '-q', library[0])

    child = update_submodules_with_pygit2(tmp_path, clone, init=init)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == library[1]


@pytest.mark.parametrize('init', [True, False])
def test_pygit2_updates_a_submodule_whose_name_is_not_its_path(tmp_path, init):
    repository(tmp_path / 'library')
    origin, clone = tmp_path / 'origin', tmp_path / 'clone'
    origin.mkdir()
    git_with_local_submodules(origin, 'init', '-q')
    git_with_local_submodules(origin, 'submodule', 'add', '-q', '--name', 'vendor', str(tmp_path / 'library'), 'third_party/library')
    git_with_local_submodules(origin, 'commit', '-q', '-m', 'a submodule with a name of its own')
    if init:
        git_with_local_submodules(tmp_path, 'clone', '-q', str(origin), str(clone))
    else:
        git_with_local_submodules(tmp_path, 'clone', '-q', '--recursive', str(origin), str(clone))
        git_with_local_submodules(clone / 'third_party/library', 'checkout', '-q', 'HEAD~1')

    child = update_submodules_with_pygit2(tmp_path, clone, init=init)

    assert child.returncode == 0, child.stderr
    assert (clone / 'third_party/library/__init__.py').read_text() == 'VERSION = 2'


def test_pygit2_passes_over_a_submodule_whose_name_is_not_one_that_git_accepts(tmp_path):
    """As git does at a clone: a name is a folder in `.git/modules`, and one that leads out of it is not followed."""
    library, _ = repository_with_a_submodule(tmp_path)
    origin, clone = tmp_path / 'origin', tmp_path / 'clone'
    git_with_local_submodules(origin, 'submodule', 'add', '-q', '--name', 'another', str(tmp_path / 'library'), 'another')
    gitmodules = (origin / '.gitmodules').read_text()
    (origin / '.gitmodules').write_text(gitmodules.replace('[submodule "another"]', '[submodule "../../../beside"]'))
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'a name that leads out')
    git_with_local_submodules(tmp_path, 'clone', '-q', str(origin), str(clone))

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == library[1]
    assert os.listdir(clone / 'another') == []
    assert not (tmp_path / 'beside').exists()


def test_pygit2_passes_over_a_submodule_whose_path_leads_out_of_the_nodepack(tmp_path):
    library = repository(tmp_path / 'library')
    origin, clone = tmp_path / 'origin', tmp_path / 'packs/clone'
    origin.mkdir()
    git_with_local_submodules(origin, 'init', '-q')

    def object_of(kind, text):
        return subprocess.run(['git', kind, *(['-w', '--stdin'] if kind == 'hash-object' else [])], cwd=origin, input=text, check=True,
                              capture_output=True, text=True).stdout.strip()

    gitmodules = f'[submodule "outside"]\n\tpath = a/../../outside\n\turl = {(tmp_path / "library").as_posix()}\n'
    tree = object_of('mktree', f'160000 commit {library[1]}\toutside\n')
    for name in ('..', '..'):
        tree = object_of('mktree', f'040000 tree {tree}\t{name}\n')
    tree = object_of('mktree', f'100644 blob {object_of("hash-object", gitmodules)}\t.gitmodules\n040000 tree {tree}\ta\n')
    commit = subprocess.run(['git', '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit-tree', tree, '-m', 'a path that leads out'],
                            cwd=origin, check=True, capture_output=True, text=True).stdout.strip()
    git_with_local_submodules(origin, 'update-ref', 'HEAD', commit)
    (tmp_path / 'packs').mkdir()
    # git does not check such a tree out
    git_with_local_submodules(tmp_path, 'clone', '-q', '--no-checkout', str(origin), str(clone))
    (clone / '.gitmodules').write_text(gitmodules)

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert not (tmp_path / 'packs/outside').exists()


def test_pygit2_passes_over_a_submodule_without_a_url(tmp_path):
    library, _ = repository_with_a_submodule(tmp_path)
    origin, clone = tmp_path / 'origin', tmp_path / 'clone'
    git_with_local_submodules(origin, 'submodule', 'add', '-q', str(tmp_path / 'library'), 'a-without-a-url')
    git_with_local_submodules(origin, 'config', '-f', '.gitmodules', '--unset', 'submodule.a-without-a-url.url')
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'an entry without a url')
    git_with_local_submodules(tmp_path, 'clone', '-q', str(origin), str(clone))

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == library[1]
    assert os.listdir(clone / 'a-without-a-url') == []


def add_repository_without_gitmodules(tmp_path, origin):
    repository(origin / 'stray')
    git_with_local_submodules(origin, 'add', 'stray')
    git_with_local_submodules(origin, 'commit', '-q', '-m', 'a repository added without `git submodule`')
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(origin), str(clone))
    return clone


def test_pygit2_passes_over_a_commit_in_the_tree_without_gitmodules(tmp_path):
    repository(tmp_path / 'origin')
    clone = add_repository_without_gitmodules(tmp_path, tmp_path / 'origin')

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert os.listdir(clone / 'stray') == []


def test_pygit2_updates_the_submodules_beside_a_commit_that_gitmodules_does_not_name(tmp_path):
    library, _ = repository_with_a_submodule(tmp_path)
    clone = add_repository_without_gitmodules(tmp_path, tmp_path / 'origin')

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == library[1]


def test_pygit2_does_not_pass_over_a_submodule_it_could_not_fetch(tmp_path):
    repository_with_a_submodule(tmp_path)
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(tmp_path / 'origin'), str(clone))
    # moved, as git makes files read-only that Windows does not remove
    (tmp_path / 'library').rename(tmp_path / 'library.away')

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode != 0, child.stderr
    assert 'GitCommandError' in child.stderr


def test_pygit2_does_not_pass_over_a_git_that_did_not_come_back(tmp_path):
    repository_with_a_submodule(tmp_path)
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(tmp_path / 'origin'), str(clone))
    # moved, as git makes files read-only that Windows does not remove
    (tmp_path / 'library').rename(tmp_path / 'library.away')
    late = ('import subprocess\n'
            'def late(command, timeout, **_):\n'
            '    raise subprocess.TimeoutExpired(command, timeout)\n'
            'subprocess.run = late')

    child = update_submodules_with_pygit2(tmp_path, clone, first=late)

    assert child.returncode != 0, child.stderr
    assert 'TimeoutExpired' in child.stderr


@pytest.mark.parametrize('submodules', [['library'], ['asset', 'library']], ids=['alone', 'after one that was fetched'])
def test_pygit2_fetches_a_submodule_whose_fetch_failed_at_the_update_before(tmp_path, submodules):
    origin, pack = tmp_path / 'origin', tmp_path / 'pack'
    repository(origin)
    git_with_local_submodules(tmp_path, 'clone', '-q', str(origin), str(pack))
    for name in submodules:
        repository(tmp_path / name)
        git_with_local_submodules(origin, 'submodule', 'add', '-q', str(tmp_path / name), name)
    git_with_local_submodules(origin, 'commit', '-q', '-m', 'submodules')
    (tmp_path / 'library').rename(tmp_path / 'library.away')
    update = (f'repo = git_compat.open_repo({str(pack)!r})\n'
              'commit = repo.head_commit_hexsha\n'
              'repo.pull_ff_only()\n'
              'try:\n'
              '    repo.submodule_update()\n'
              'except Exception:\n'
              '    repo.undo_pull(commit)\n'
              '    raise')

    child = run_with_pygit2(tmp_path, update)

    assert child.returncode != 0, child.stderr
    assert head(pack) != head(origin)

    (tmp_path / 'library.away').rename(tmp_path / 'library')
    child = run_with_pygit2(tmp_path, update)

    assert child.returncode == 0, child.stderr
    assert head(pack) == head(origin)
    for name in submodules:
        assert (pack / name / '__init__.py').read_text() == 'VERSION = 2'


def library_with_a_commit_that_was_never_pushed(tmp_path):
    library, _ = repository_with_a_submodule(tmp_path)
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', '--recursive', str(tmp_path / 'origin'), str(clone))
    git_with_local_submodules(clone / 'library', 'checkout', '-q', '-b', 'work')
    git_with_local_submodules(clone / 'library', 'commit', '-q', '--allow-empty', '-m', 'a commit that was never pushed')
    never_pushed = head(clone / 'library')
    git_with_local_submodules(clone / 'library', 'checkout', '-q', library[1])
    return clone, library[1], never_pushed


def removed_by_git(clone):
    git_with_local_submodules(clone, 'submodule', 'deinit', '-q', '-f', 'library')


def removed_by_hand(clone):
    shutil.rmtree(clone / 'library')


def removed_with_a_head_that_names_no_branch(clone):
    removed_by_git(clone)
    (clone / '.git/modules/library/HEAD').write_text('ref: refs/heads/a-branch-that-is-not-there\n')


@pytest.mark.parametrize('remove', [removed_by_git, removed_by_hand, removed_with_a_head_that_names_no_branch])
def test_pygit2_checks_a_submodule_out_again_with_the_commits_that_are_in_it_alone(tmp_path, remove):
    clone, pinned, never_pushed = library_with_a_commit_that_was_never_pushed(tmp_path)
    remove(clone)

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert (clone / 'library/__init__.py').read_text() == 'VERSION = 2'
    assert head(clone / 'library') == pinned
    assert subprocess.run(['git', 'cat-file', '-e', never_pushed], cwd=clone / 'library').returncode == 0
    top = subprocess.run(['git', '--git-dir', str(clone / '.git/modules/library'), 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    assert os.path.samefile(top.stdout.strip(), clone / 'library'), top.stderr


def test_pygit2_checks_out_again_a_submodule_whose_name_is_not_its_path(tmp_path):
    library = repository(tmp_path / 'library')
    origin, clone = tmp_path / 'origin', tmp_path / 'clone'
    origin.mkdir()
    git_with_local_submodules(origin, 'init', '-q')
    git_with_local_submodules(origin, 'submodule', 'add', '-q', '--name', 'vendor', str(tmp_path / 'library'), 'third_party/library')
    git_with_local_submodules(origin, 'commit', '-q', '-m', 'a submodule with a name of its own')
    child = run_with_pygit2(tmp_path, f'git_compat.clone_repo({str(origin)!r}, {str(clone)!r})')
    assert child.returncode == 0, child.stderr
    git_with_local_submodules(clone / 'third_party/library', 'commit', '-q', '--allow-empty', '-m', 'a commit that was never pushed')
    never_pushed = head(clone / 'third_party/library')
    git_with_local_submodules(clone / 'third_party/library', 'checkout', '-q', library[1])
    shutil.rmtree(clone / 'third_party/library')

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'third_party/library') == library[1]
    assert subprocess.run(['git', 'cat-file', '-e', never_pushed], cwd=clone / 'third_party/library').returncode == 0


def test_pygit2_leaves_the_repository_of_another_submodule_where_it_is(tmp_path):
    """git keeps the repository of a submodule in `.git/modules` under its name, and pygit2 under its path: `lib` is both here."""
    repository(tmp_path / 'library')
    repository(tmp_path / 'another')
    origin, clone = tmp_path / 'origin', tmp_path / 'clone'
    origin.mkdir()
    git_with_local_submodules(origin, 'init', '-q')
    git_with_local_submodules(origin, 'submodule', 'add', '-q', '--name', 'lib', str(tmp_path / 'library'), 'vendor/lib')
    git_with_local_submodules(origin, 'commit', '-q', '-m', 'a submodule named lib')
    git_with_local_submodules(tmp_path, 'clone', '-q', '--recursive', str(origin), str(clone))
    git_with_local_submodules(origin, 'submodule', 'add', '-q', '--name', 'another', str(tmp_path / 'another'), 'lib')
    git_with_local_submodules(origin, 'commit', '-q', '-m', 'a submodule at lib')
    git_with_local_submodules(clone, 'pull', '-q')

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode != 0
    assert os.listdir(clone / 'lib') == []
    top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=clone / 'vendor/lib', check=True, capture_output=True, text=True)
    assert os.path.samefile(top.stdout.strip(), clone / 'vendor/lib')


def test_pygit2_fetches_a_submodule_where_a_folder_that_is_no_repository_is_left(tmp_path):
    library, _ = repository_with_a_submodule(tmp_path)
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', str(tmp_path / 'origin'), str(clone))
    (clone / '.git/modules/library').mkdir(parents=True)
    (clone / '.git/modules/library/a-file').write_text('')

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == library[1]
    assert os.listdir(clone / '.git/modules/library') != ['a-file', 'config']


@pytest.mark.parametrize('names_its_folder', [True, False])
def test_pygit2_keeps_what_was_changed_in_a_submodule_that_is_at_its_commit(tmp_path, names_its_folder):
    repository_with_a_submodule(tmp_path)
    clone = tmp_path / 'clone'
    git_with_local_submodules(tmp_path, 'clone', '-q', '--recursive', str(tmp_path / 'origin'), str(clone))
    (clone / 'library/__init__.py').write_text('changed by the user')
    if not names_its_folder:
        git_with_local_submodules(clone / 'library', 'config', '--unset', 'core.worktree')

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert (clone / 'library/__init__.py').read_text() == 'changed by the user'


def test_pygit2_checks_a_submodule_out_again_without_a_clone_when_a_proxy_is_set(tmp_path, monkeypatch):
    clone, pinned, _ = library_with_a_commit_that_was_never_pushed(tmp_path)
    removed_by_git(clone)
    (tmp_path / 'home').mkdir()
    (tmp_path / 'home/.gitconfig').write_text('[http]\n\tproxy = http://127.0.0.1:9\n')
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))

    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == pinned


class GitHostBehindAProxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def handle(self):
        # one that did not ask the proxy begins with a TLS hello, and is not answered
        if self.connection.recv(1, socket.MSG_PEEK) == b'C':
            super().handle()

    def do_CONNECT(self):
        self.send_response(200)
        self.end_headers()
        self.connection = self.server.tls.wrap_socket(self.connection, server_side=True)
        self.rfile = self.connection.makefile('rb')
        self.wfile = self.connection.makefile('wb', 0)

    def finish(self):
        super().finish()
        self.connection.close()

    def do_GET(self):
        url = urlsplit(self.path)
        self.server.asked.add(url.path.split('/')[1])
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        cgi = {'GIT_PROJECT_ROOT': self.server.root, 'GIT_HTTP_EXPORT_ALL': '1', 'REQUEST_METHOD': self.command,
               'PATH_INFO': url.path, 'QUERY_STRING': url.query, 'CONTENT_TYPE': self.headers.get('Content-Type', '')}
        answer = subprocess.run([self.server.backend], input=body, env={**os.environ, **cgi, **MESSAGE_CUT_IN_A_CHARACTER}, check=True, capture_output=True).stdout
        headers, _, content = answer.partition(b'\r\n\r\n')
        status = headers.partition(b'Status: ')[2].split(b'\r\n')[0] or b'200 OK'
        self.wfile.write(b'HTTP/1.1 %s\r\nContent-Length: %d\r\n%s\r\n\r\n%s' % (status, len(content), headers, content))

    do_POST = do_GET

    def log_message(self, *args):
        pass


@pytest.fixture
def git_host_behind_a_proxy(tmp_path, monkeypatch):
    backend = os.path.join(subprocess.run(['git', '--exec-path'], check=True, capture_output=True, text=True).stdout.strip(), 'git-http-backend')
    if not os.path.exists(backend) or shutil.which('openssl') is None:
        pytest.skip('git-http-backend and openssl are needed')

    # https, and a name: libgit2 leaves the proxy aside for http, and does not match a certificate with an address
    certificate, key = str(tmp_path / 'certificate.pem'), str(tmp_path / 'key.pem')
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-keyout', key, '-out', certificate,
                    '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'], check=True, capture_output=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), GitHostBehindAProxy)
    server.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.tls.load_cert_chain(certificate, key)
    server.backend, server.root, server.asked = backend, str(tmp_path), set()
    server.url = 'https://localhost:%d/' % server.server_port

    (tmp_path / 'home').mkdir()
    (tmp_path / 'home/.gitconfig').write_text('[http]\n\tproxy = http://127.0.0.1:%d\n' % server.server_port)
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('SSL_CERT_FILE', certificate)

    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


def pin(path, submodule, commit):
    git_with_local_submodules(path, 'update-index', '--cacheinfo', f'160000,{commit},{submodule}')
    git_with_local_submodules(path, 'commit', '-q', '-m', f'{submodule} at {commit}')
    return head(path)


def test_pygit2_fetches_the_submodules_through_the_proxy(tmp_path, git_host_behind_a_proxy):
    library, _ = repository_with_a_submodule(tmp_path)
    origin, outer, clone = tmp_path / 'origin', tmp_path / 'outer', tmp_path / 'clone'
    git_with_local_submodules(origin, 'config', '-f', '.gitmodules', 'submodule.library.url', '../library')
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'the library beside it')
    outer.mkdir()
    git_with_local_submodules(outer, 'init', '-q')
    git_with_local_submodules(outer, 'submodule', 'add', '-q', '../origin', 'origin')
    git_with_local_submodules(outer, 'commit', '-q', '-a', '-m', 'a submodule with a submodule')

    cloned = f'git_compat.clone_repo({git_host_behind_a_proxy.url + "outer"!r}, {str(clone)!r})'
    child = update_submodules_with_pygit2(tmp_path, clone, first=cloned)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'origin/library') == library[1]
    assert git_host_behind_a_proxy.asked == {'outer', 'origin', 'library'}

    (tmp_path / 'library/__init__.py').write_text('VERSION = 3')
    git_with_local_submodules(tmp_path / 'library', 'commit', '-q', '-a', '-m', 'version 3')
    later = head(tmp_path / 'library')
    pin(clone, 'origin', pin(origin, 'library', later))
    child = update_submodules_with_pygit2(tmp_path, clone)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'origin/library') == later

    (tmp_path / 'library/__init__.py').write_text('VERSION = 4')
    git_with_local_submodules(tmp_path / 'library', 'commit', '-q', '-a', '-m', 'version 4')
    latest = head(tmp_path / 'library')
    pin(clone, 'origin', pin(origin, 'library', latest))
    child = update_submodules_with_pygit2(tmp_path, clone, init=False)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'origin/library') == latest


def test_pygit2_fetches_a_submodule_with_an_ssh_url_over_https(tmp_path, git_host_behind_a_proxy):
    library, _ = repository_with_a_submodule(tmp_path)
    origin, clone = tmp_path / 'origin', tmp_path / 'clone'
    git_with_local_submodules(origin, 'config', '-f', '.gitmodules', 'submodule.library.url', 'git@localhost:library')
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'an ssh url')

    cloned = f'git_compat.clone_repo({git_host_behind_a_proxy.url + "origin"!r}, {str(clone)!r})'
    child = update_submodules_with_pygit2(tmp_path, clone, first=cloned)

    assert child.returncode == 0, child.stderr
    assert head(clone / 'library') == library[1]


def test_pull_of_the_git_helper_with_pygit2_updates_a_pack_whose_submodule_is_at_another_commit(tmp_path):
    library = repository(tmp_path / 'library')
    origin = tmp_path / 'origin'
    origin.mkdir()
    git_with_local_submodules(origin, 'init', '-q')
    git_with_local_submodules(origin, 'submodule', 'add', '-q', str(tmp_path / 'library'), 'library')
    git_with_local_submodules(origin / 'library', 'checkout', '-q', library[0])
    git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'library at its first commit')
    pack = tmp_path / 'custom_nodes/pack'
    git_with_local_submodules(tmp_path, 'clone', '-q', '--recursive', str(origin), str(pack))
    git_with_local_submodules(origin, 'commit', '-q', '--allow-empty', '-m', 'a commit to pull')
    git_with_local_submodules(pack / 'library', 'checkout', '-q', library[1])
    (tmp_path / 'folder_paths.py').touch()
    (tmp_path / 'no-git').mkdir()
    helper = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'comfyui_manager', 'common', 'git_helper.py')
    env = {key: value for key, value in os.environ.items() if key not in ('GIT_EXE_PATH', 'GIT_PYTHON_GIT_EXECUTABLE')}

    pulled = subprocess.run([sys.executable, helper, '--pull', str(pack)], cwd=pack.parent, capture_output=True, text=True,
                            env={**env, 'PATH': str(tmp_path / 'no-git'), 'CM_USE_PYGIT2': '1', 'COMFYUI_PATH': str(tmp_path)})

    assert (pulled.returncode, head(pack)) == (0, head(origin)), pulled.stdout + pulled.stderr
    assert head(pack / 'library') == library[0]
