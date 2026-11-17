"""The commit of a git nodepack is read from its `.git`, and a checkout brings its submodules along.

Both `manager_core` modules are run, on git repositories of a temporary directory.
"""

import shutil
import subprocess

import git
import pytest

from _install_flags_testutil import GIT_LOCATION
from test_snapshot_restore_pins import core  # noqa: F401


@pytest.fixture(autouse=True)
def git_finds_its_repository_by_the_directory(monkeypatch):
    for name in GIT_LOCATION:
        monkeypatch.delenv(name, raising=False)


def head(path):
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


def repository(path):
    """A git repository with two commits at `path`; their hashes."""
    path.mkdir(parents=True)
    commits = []
    for version in (1, 2):
        (path / '__init__.py').write_text('VERSION = %d' % version)
        for args in (['init', '-q'], ['add', '.'],
                     ['-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '-q', '-m', 'version %d' % version]):
            subprocess.run(['git', *args], cwd=path, check=True, capture_output=True)
        commits.append(head(path))
    return commits


def git_with_local_submodules(path, *args):
    subprocess.run(['git', '-c', 'protocol.file.allow=always', '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', *args],
                   cwd=path, check=True, capture_output=True)


def repository_with_a_submodule(tmp_path):
    """A repository `origin` whose two commits pin the two commits of its submodule `library`; the hashes of both."""
    library = repository(tmp_path / 'library')
    origin = tmp_path / 'origin'
    origin.mkdir()
    git_with_local_submodules(origin, 'init', '-q')
    git_with_local_submodules(origin, 'submodule', 'add', '-q', str(tmp_path / 'library'), 'library')
    pinned_commits = []
    for commit in library:
        git_with_local_submodules(origin / 'library', 'checkout', '-q', commit)
        git_with_local_submodules(origin, 'commit', '-q', '-a', '-m', 'library at ' + commit)
        pinned_commits.append(head(origin))
    return library, pinned_commits


def test_commit_of_a_pack_whose_refs_are_packed_is_read(core, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    subprocess.run(['git', 'pack-refs', '--all'], cwd=tmp_path / 'fixture', check=True)
    with open(tmp_path / 'fixture/.git/packed-refs', 'a') as packed:
        packed.write('\n')
    branch = (tmp_path / 'fixture/.git/HEAD').read_text().strip()[5:]

    assert not (tmp_path / 'fixture/.git' / branch).exists()
    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == commits[1]


def test_commit_is_read_beside_refs_that_are_not_utf8(core, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    subprocess.run(['git', 'pack-refs', '--all'], cwd=tmp_path / 'fixture', check=True)
    packed = tmp_path / 'fixture/.git/packed-refs'
    packed.write_bytes(b'0123456789abcdef0123456789abcdef01234567 refs/heads/\xff\xfe\n' + packed.read_bytes())

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == commits[1]


def test_head_that_is_not_utf8_gives_no_commit(core, tmp_path):  # noqa: F811
    (tmp_path / 'fixture/.git').mkdir(parents=True)
    (tmp_path / 'fixture/.git/HEAD').write_bytes(b'ref: refs/heads/\xff\xfe\n')

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == 'unknown'


def test_packed_ref_is_matched_by_its_bytes(core, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    subprocess.run(['git', 'pack-refs', '--all'], cwd=tmp_path / 'fixture', check=True)
    git_dir = tmp_path / 'fixture/.git'
    other = b'0123456789abcdef0123456789abcdef01234567 refs/heads/release-\xff\n'
    (git_dir / 'packed-refs').write_bytes(other + (git_dir / 'packed-refs').read_bytes())
    (git_dir / 'HEAD').write_bytes(b'ref: refs/heads/release-\xfe\n')

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == 'unknown'

    (git_dir / 'packed-refs').write_bytes(other + commits[1].encode() + b' refs/heads/release-\xfe\n')

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == commits[1]


def test_checkout_brings_the_submodules_to_the_commit(core, tmp_path):  # noqa: F811
    library, pinned_commits = repository_with_a_submodule(tmp_path)
    git_with_local_submodules(tmp_path, 'clone', '-q', '--recursive', str(tmp_path / 'origin'), 'fixture')

    assert core.repo_switch_commit(str(tmp_path / 'fixture'), pinned_commits[0]) is True
    assert head(tmp_path / 'fixture') == pinned_commits[0]
    assert head(tmp_path / 'fixture/library') == library[0]


def test_submodules_are_brought_to_the_commit_of_a_pack_that_is_at_it_already(core, tmp_path):  # noqa: F811
    """As after a restore whose checkout succeeded and whose update of the submodules failed."""
    library, pinned_commits = repository_with_a_submodule(tmp_path)
    git_with_local_submodules(tmp_path, 'clone', '-q', '--recursive', str(tmp_path / 'origin'), 'fixture')
    git_with_local_submodules(tmp_path / 'fixture/library', 'checkout', '-q', library[0])

    assert core.repo_switch_commit(str(tmp_path / 'fixture'), pinned_commits[1]) is False
    assert head(tmp_path / 'fixture/library') == library[1]


def test_submodule_that_was_never_fetched_is_left_alone_in_a_pack_that_is_at_the_commit(core, tmp_path):  # noqa: F811
    """A snapshot does not hold the state of the submodules; one that cannot be reached is not a failure of the pack."""
    library, pinned_commits = repository_with_a_submodule(tmp_path)
    git_with_local_submodules(tmp_path, 'clone', '-q', str(tmp_path / 'origin'), 'fixture')
    shutil.rmtree(tmp_path / 'library')

    assert core.repo_switch_commit(str(tmp_path / 'fixture'), pinned_commits[1]) is False
    assert list((tmp_path / 'fixture/library').iterdir()) == []


def test_git_is_not_run_for_the_submodules_of_a_pack_that_has_none(core, tmp_path, monkeypatch):  # noqa: F811
    """A restore goes through every git pack; on Windows each git command takes about half a second."""
    commits = repository(tmp_path / 'fixture')
    ran = []
    execute = git.Git.execute

    def recorded(self, command, *args, **kwargs):
        ran.append(list(command))
        return execute(self, command, *args, **kwargs)

    monkeypatch.setattr(git.Git, 'execute', recorded)

    assert core.repo_switch_commit(str(tmp_path / 'fixture'), commits[1]) is False
    assert [command for command in ran if 'submodule' in command] == []
