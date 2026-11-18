import logging
import os
import subprocess

import git
import pytest

from _install_flags_testutil import GIT_LOCATION
from test_snapshot_restore_pins import core  # noqa: F401


@pytest.fixture(autouse=True)
def git_finds_its_repository_by_the_directory(monkeypatch):
    for name in GIT_LOCATION:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def manager_clones_from_a_directory(monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'protocol.file.allow')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'always')


def head(path):
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


def repository(path):
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


def test_ref_that_head_names_is_read(core, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    head_file = tmp_path / 'fixture/.git/HEAD'
    branch = head_file.read_text().strip()[5:]

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == commits[1]

    head_file.write_text('ref:' + branch + '\n')
    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == commits[1]

    head_file.write_text('ref: \n')
    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == 'unknown'


def test_commit_of_a_pack_whose_refs_are_packed_is_read(core, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    subprocess.run(['git', 'pack-refs', '--all'], cwd=tmp_path / 'fixture', check=True)
    with open(tmp_path / 'fixture/.git/packed-refs', 'a') as packed:
        packed.write('\n')
    branch = (tmp_path / 'fixture/.git/HEAD').read_text().strip()[5:]

    assert not (tmp_path / 'fixture/.git' / branch).exists()
    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == commits[1]


def test_ref_whose_place_is_a_folder_is_not_read_as_a_file(core, tmp_path):  # noqa: F811
    """git takes a folder there for no ref: after `git pack-refs`, and after `git checkout --orphan feature` beside a branch `feature/x`."""
    commits = repository(tmp_path / 'fixture')
    subprocess.run(['git', 'pack-refs', '--all'], cwd=tmp_path / 'fixture', check=True)
    branch = (tmp_path / 'fixture/.git/HEAD').read_text().strip()[5:]
    (tmp_path / 'fixture/.git' / branch).mkdir(parents=True)

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == commits[1]

    subprocess.run(['git', 'branch', 'feature/x'], cwd=tmp_path / 'fixture', check=True)
    subprocess.run(['git', 'checkout', '-q', '--orphan', 'feature'], cwd=tmp_path / 'fixture', check=True)

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == 'unknown'


def test_commit_that_is_not_ascii_is_read_without_an_error(core, tmp_path):  # noqa: F811
    repository(tmp_path / 'fixture')
    git_dir = tmp_path / 'fixture/.git'
    branch = (git_dir / 'HEAD').read_text().strip()[5:]
    subprocess.run(['git', 'pack-refs', '--all'], cwd=tmp_path / 'fixture', check=True)
    (git_dir / 'packed-refs').write_bytes(b'0123\xff ' + branch.encode() + b'\n')

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == '0123\ufffd'

    (git_dir / branch).write_bytes(b'0123\xff\n')
    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == '0123\ufffd'

    (git_dir / 'HEAD').write_bytes(b'0123\xff\n')
    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == '0123\ufffd'


def test_head_that_cannot_be_opened_has_no_commit(core, tmp_path):  # noqa: F811
    (tmp_path / 'fixture/.git/HEAD').mkdir(parents=True)

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == 'unknown'


def test_files_that_may_not_be_read_have_no_commit(core, tmp_path):  # noqa: F811
    (tmp_path / 'probe').touch()
    (tmp_path / 'probe').chmod(0)
    try:
        open(tmp_path / 'probe').close()
    except OSError:
        pass
    else:
        pytest.skip('a file can be read here whatever its mode, as by root or on Windows')

    commits = repository(tmp_path / 'fixture')
    git_dir = tmp_path / 'fixture/.git'
    subprocess.run(['git', 'pack-refs', '--all'], cwd=tmp_path / 'fixture', check=True)
    branch = (git_dir / 'HEAD').read_text().strip()[5:]

    (git_dir / 'packed-refs').chmod(0)
    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == 'unknown'

    (git_dir / branch).write_text(commits[1])
    (git_dir / branch).chmod(0)
    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == 'unknown'

    (git_dir / 'HEAD').chmod(0)
    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == 'unknown'


def test_commit_is_read_beside_refs_that_are_not_utf8(core, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    subprocess.run(['git', 'pack-refs', '--all'], cwd=tmp_path / 'fixture', check=True)
    packed = tmp_path / 'fixture/.git/packed-refs'
    packed.write_bytes(b'0123456789abcdef0123456789abcdef01234567 refs/heads/\xff\xfe\n' + packed.read_bytes())

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == commits[1]


def test_head_that_is_not_utf8_is_read(core, tmp_path):  # noqa: F811
    heads = tmp_path / 'fixture/.git/refs/heads'
    heads.mkdir(parents=True)
    (tmp_path / 'fixture/.git/HEAD').write_bytes(b'ref: refs/heads/\xff\xfe\n')
    try:
        with open(os.fsencode(heads) + b'/\xff\xfe', 'wb') as ref:
            ref.write(b'0123456789abcdef0123456789abcdef01234567\n')
    except (OSError, ValueError):
        pytest.skip('this file system has no file of such a name, as that of Windows')

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == '0123456789abcdef0123456789abcdef01234567'


# what MinGit 2.56 named the file of a branch that was cloned on Windows
NAMES_OF_GIT_FOR_WINDOWS = [
    (b'rel-\xfe', 'rel-\u00fe'),
    (b'caf\xe9', 'caf\u00e9'),
    (b'rel-\x81', 'rel-81'),
    ('\ud55c\uae00'.encode(), '\ud55c\uae00'),
    ('\ud55c'.encode() + b'\xfe\xe9\xc3', '\ud55c\u00fe\u00e9\u00c3'),
    ('a\U0001f600'.encode(), 'a\U0001f600'),
    (b'\xe0\x80\x80', '\u00e08080'),
    # a surrogate in UTF-8, which `xutftowcsn` of compat/mingw.c of git takes as one
    (b'\xed\xa0\x80', '\ud800'),
]


@pytest.mark.parametrize('name, file_name', NAMES_OF_GIT_FOR_WINDOWS)
def test_file_of_a_ref_is_named_as_git_for_windows_names_it(core, name, file_name):  # noqa: F811
    assert core.git_utils.file_name_of_git_for_windows(name) == file_name


@pytest.mark.skipif(os.name != 'nt', reason='the names that Git for Windows gives its files')
def test_ref_that_git_for_windows_made_is_read(core, tmp_path):  # noqa: F811
    """A name that is not UTF-8 is no name of a file there, and Git for Windows writes the file under another."""
    heads = tmp_path / 'fixture/.git/refs/heads'
    heads.mkdir(parents=True)
    (tmp_path / 'fixture/.git/HEAD').write_bytes(b'ref: refs/heads/rel-\xfe\n')
    (heads / 'rel-\u00fe').write_text('0123456789abcdef0123456789abcdef01234567\n')

    assert core.git_utils.get_commit_hash(str(tmp_path / 'fixture')) == '0123456789abcdef0123456789abcdef01234567'


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


@pytest.mark.parametrize('clone', [['--recursive'], []], ids=['with its submodules', 'without its submodules'])
def test_checkout_brings_the_submodules_to_the_commit(core, manager_clones_from_a_directory, tmp_path, clone):  # noqa: F811
    library, pinned_commits = repository_with_a_submodule(tmp_path)
    git_with_local_submodules(tmp_path, 'clone', '-q', *clone, str(tmp_path / 'origin'), 'fixture')

    assert core.repo_switch_commit(str(tmp_path / 'fixture'), pinned_commits[0]) is True
    assert head(tmp_path / 'fixture') == pinned_commits[0]
    assert head(tmp_path / 'fixture/library') == library[0]


def test_submodules_are_brought_to_the_commit_of_a_pack_that_is_at_it_already(core, tmp_path):  # noqa: F811
    library, pinned_commits = repository_with_a_submodule(tmp_path)
    git_with_local_submodules(tmp_path, 'clone', '-q', '--recursive', str(tmp_path / 'origin'), 'fixture')
    git_with_local_submodules(tmp_path / 'fixture/library', 'checkout', '-q', library[0])

    assert core.repo_switch_commit(str(tmp_path / 'fixture'), pinned_commits[1]) is False
    assert head(tmp_path / 'fixture/library') == library[1]


def test_submodule_that_was_never_fetched_is_left_alone_in_a_pack_cloned_without_its_submodules(core, tmp_path):  # noqa: F811
    """As git does without `--init`: no submodule of such a clone is active."""
    library, pinned_commits = repository_with_a_submodule(tmp_path)
    git_with_local_submodules(tmp_path, 'clone', '-q', str(tmp_path / 'origin'), 'fixture')
    # moved, as git makes files read-only that Windows does not remove
    (tmp_path / 'library').rename(tmp_path / 'library.away')

    assert core.repo_switch_commit(str(tmp_path / 'fixture'), pinned_commits[1]) is False
    assert list((tmp_path / 'fixture/library').iterdir()) == []


@pytest.mark.parametrize('reachable', [True, False], ids=['reachable', 'away'])
def test_submodule_that_was_never_fetched_is_fetched_in_a_pack_cloned_as_manager_clones(core, manager_clones_from_a_directory, tmp_path,  # noqa: F811
                                                                                         caplog, reachable):
    """`clone --recursive` makes every submodule active, also one of a later commit: git updates it without `--init`."""
    repository(tmp_path / 'library')
    plain, pack = tmp_path / 'plain', tmp_path / 'fixture'
    plain.mkdir()
    git_with_local_submodules(plain, 'init', '-q')
    git_with_local_submodules(plain, 'commit', '-q', '--allow-empty', '-m', 'no submodule')
    git_with_local_submodules(tmp_path, 'clone', '-q', '--recursive', str(plain), str(pack))
    git_with_local_submodules(plain, 'submodule', 'add', '-q', str(tmp_path / 'library'), 'library')
    git_with_local_submodules(plain, 'commit', '-q', '-m', 'a submodule')
    git_with_local_submodules(pack, 'pull', '-q')
    if not reachable:
        # moved, as git makes files read-only that Windows does not remove
        (tmp_path / 'library').rename(tmp_path / 'library.away')

    with caplog.at_level(logging.ERROR):
        switched = core.repo_switch_commit(str(pack), head(plain))

    assert (switched, (pack / 'library/__init__.py').exists(), f"'{pack}'" in caplog.text, 'library' in caplog.text) == \
        ((False, True, False, False) if reachable else (None, False, True, True))


def test_git_is_not_run_for_the_submodules_of_a_pack_that_has_none(core, tmp_path, monkeypatch):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    ran = []
    execute = git.Git.execute

    def recorded(self, command, *args, **kwargs):
        ran.append(list(command))
        return execute(self, command, *args, **kwargs)

    monkeypatch.setattr(git.Git, 'execute', recorded)

    assert core.repo_switch_commit(str(tmp_path / 'fixture'), commits[1]) is False
    assert [command for command in ran if 'submodule' in command] == []
