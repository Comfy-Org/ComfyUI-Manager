"""An update or an install whose git step fails is a failure, and can be done again.

The cases run git on repositories of a temporary directory. The node pack has a submodule, and
the repository of the submodule is moved away to make the step fail after the node pack itself
was pulled or cloned.
"""

import asyncio
import os
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from _install_flags_testutil import GIT_LOCATION
from test_snapshot_restore_pins import core, manager  # noqa: F401


def git(path, *args):
    subprocess.run(['git', '-c', 'protocol.file.allow=always', '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', *args],
                   cwd=path, check=True, capture_output=True)


def head(path):
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def git_of_the_case(monkeypatch, tmp_path):
    for name in GIT_LOCATION:
        monkeypatch.delenv(name, raising=False)
    # the git that Manager runs is to clone a submodule from a directory
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'protocol.file.allow')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'always')
    # on Windows a pull runs in the git helper, which looks for this file where ComfyUI is said to be
    (tmp_path / 'folder_paths.py').touch()
    monkeypatch.setenv('COMFYUI_PATH', str(tmp_path))


@pytest.fixture
def origin(tmp_path):
    """A repository with the submodules `asset` and `library`; its two commits name the two commits of each.

    `pack` is a clone made at the first commit: it is one commit behind, and so are its submodules.
    """
    submodules = tmp_path / 'asset', tmp_path / 'library'
    origin = tmp_path / 'origin'
    for repository in (*submodules, origin):
        repository.mkdir()
        git(repository, 'init', '-q')
    commits = []
    for version in (1, 2):
        for submodule in submodules:
            (submodule / '__init__.py').write_text('VERSION = %d' % version)
            git(submodule, 'add', '.')
            git(submodule, 'commit', '-q', '-m', 'version %d' % version)
            if version == 1:
                git(origin, 'submodule', 'add', '-q', str(submodule), submodule.name)
            else:
                git(origin / submodule.name, 'pull', '-q')
        git(origin, 'commit', '-q', '-a', '-m', 'library %d' % version)
        commits.append(head(origin))
        if version == 1:
            git(tmp_path, 'clone', '-q', '--recursive', str(origin), 'pack')
    return commits


@pytest.fixture
def pack(tmp_path, origin):
    """The clone that is behind, with the repository of its submodule `library` away: `asset` is updated before it fails."""
    (tmp_path / 'library').rename(tmp_path / 'library.away')
    return tmp_path / 'pack'


def test_pull_that_fails_at_the_submodules_leaves_the_pack_at_its_commit(core, tmp_path, origin, pack):  # noqa: F811
    """At the new commit the next update finds nothing to do, and the install script of the update is never run."""
    with pytest.raises(Exception):
        core.git_pull(str(pack))

    assert head(pack) == origin[0]
    # the submodule that was updated before the one that failed is back at the commit that the pack names
    assert (pack / 'asset/__init__.py').read_text() == 'VERSION = 1'

    (tmp_path / 'library.away').rename(tmp_path / 'library')
    core.git_pull(str(pack))

    assert head(pack) == origin[1]
    assert (pack / 'library/__init__.py').read_text() == 'VERSION = 2'
    assert (pack / 'asset/__init__.py').read_text() == 'VERSION = 2'


def test_pull_of_the_git_helper_that_fails_is_a_failure(core, monkeypatch, tmp_path, origin, pack):  # noqa: F811
    """On Windows the pull runs in the git helper, which ends with 0 and says in its output that it failed."""
    monkeypatch.setattr(core.platform, 'system', lambda: 'Windows')

    with pytest.raises(Exception):
        core.git_pull(str(pack))

    assert head(pack) == origin[0]
    assert (pack / 'asset/__init__.py').read_text() == 'VERSION = 1'

    (tmp_path / 'library.away').rename(tmp_path / 'library')
    core.git_pull(str(pack))

    assert head(pack) == origin[1]


def library_not_cloned(pack):
    """So that the fetch of the git helper passes it, and the update of the submodules is what fails."""
    git(pack, 'submodule', 'deinit', '-q', '-f', 'library')
    # moved, as git makes files read-only that Windows does not remove
    (pack / '.git/modules/library').rename(pack.parent / 'library.modules')


@pytest.fixture
def helper(core, monkeypatch):  # noqa: F811
    """On Windows the pull runs in the git helper."""
    monkeypatch.setattr(core.platform, 'system', lambda: 'Windows')


def test_pull_of_the_git_helper_that_fails_at_the_submodules_puts_them_back(core, helper, tmp_path, origin):  # noqa: F811
    """The next commit of `asset` has a submodule of its own, whose repository is away: `asset` is checked out before that one fails."""
    asset, nested, pack = tmp_path / 'asset', tmp_path / 'nested', tmp_path / 'pack'
    nested.mkdir()
    git(nested, 'init', '-q')
    git(nested, 'commit', '-q', '--allow-empty', '-m', 'nested')
    git(asset, 'submodule', 'add', '-q', str(nested), 'nested')
    git(asset, 'commit', '-q', '-m', 'a submodule')
    git(tmp_path / 'origin/asset', 'pull', '-q')
    git(tmp_path / 'origin', 'commit', '-q', '-a', '-m', 'asset with a submodule')
    nested.rename(tmp_path / 'nested.away')

    with pytest.raises(Exception):
        core.git_pull(str(pack))

    assert head(pack) == origin[0]
    assert not (pack / 'asset/.gitmodules').exists()


@pytest.mark.parametrize('where', ['in the server process', 'in the git helper'])
def test_pull_that_fails_leaves_a_pack_that_was_not_on_its_branch_as_it_was(core, request, tmp_path, origin, where):  # noqa: F811
    """The pack is at an older commit than its branch, which has a commit of its own: both are where they were."""
    pack = tmp_path / 'pack'
    branch = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=pack, check=True, capture_output=True, text=True).stdout.strip()
    git(pack, 'pull', '-q')
    git(pack, 'commit', '-q', '--allow-empty', '-m', 'a commit of the pack alone')
    tip = head(pack)
    git(pack, 'checkout', '-q', '--detach', origin[0])
    library_not_cloned(pack)
    (tmp_path / 'library').rename(tmp_path / 'library.away')
    if where == 'in the git helper':
        request.getfixturevalue('helper')

    with pytest.raises(Exception):
        core.git_pull(str(pack))

    assert subprocess.run(['git', 'rev-parse', branch], cwd=pack, check=True, capture_output=True, text=True).stdout.strip() == tip
    assert head(pack) == origin[0]
    assert (pack / 'asset/__init__.py').read_text() == 'VERSION = 1'


def test_install_that_fails_at_the_submodules_leaves_no_directory(core, manager, monkeypatch, tmp_path, origin):  # noqa: F811
    """What is left of the clone is in the way of the next install, which is answered with `Already exists`."""
    (tmp_path / 'library').rename(tmp_path / 'library.away')
    monkeypatch.setattr(core, 'is_valid_url', lambda url: True)
    manager.execute_install_script = Mock(return_value=True)
    url, path = str(tmp_path / 'origin'), tmp_path / 'installed'

    assert manager.repo_install(url, str(path), instant_execution=True).result is False

    assert not path.exists()
    manager.execute_install_script.assert_not_called()

    (tmp_path / 'library.away').rename(tmp_path / 'library')

    assert manager.repo_install(url, str(path), instant_execution=True).result is True
    assert (path / 'library/__init__.py').read_text() == 'VERSION = 2'


# the runner of the server returns the exit code of the git helper, and the default one, which cm-cli has, raises for it
RUNNER_FAILURES = ['returns', 'raises']


def packs(custom_nodes):
    # the files of the claims of installs are in `.disabled`
    return [name for name in os.listdir(custom_nodes) if name != '.disabled']


def failed_clone(failure):
    def clone_that_fails(command, cwd):
        os.makedirs(command[-1], exist_ok=True)
        # as git leaves the files of its objects
        (Path(command[-1]) / 'object').touch(stat.S_IREAD)
        if failure == 'raises':
            raise subprocess.CalledProcessError(1, command)
        return 1

    return clone_that_fails


@pytest.fixture
def windows(core, monkeypatch):  # noqa: F811
    """Windows, as far as these cases go: the clone runs in the git helper, and a read-only file is not removed."""
    unlink = os.unlink

    def unlink_a_file_that_may_be_written(path, *, dir_fd=None):
        if not os.stat(path, dir_fd=dir_fd, follow_symlinks=False).st_mode & stat.S_IWRITE:
            raise PermissionError(13, 'Access is denied', str(path))
        unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, 'unlink', unlink_a_file_that_may_be_written)
    monkeypatch.setattr(core.platform, 'system', lambda: 'Windows')


@pytest.mark.parametrize('failure', RUNNER_FAILURES)
def test_install_whose_clone_in_the_git_helper_fails_leaves_no_directory(core, manager, monkeypatch, windows, tmp_path, failure):  # noqa: F811
    """The git helper is replaced by one that fails after it made the directory."""

    monkeypatch.setattr(core.manager_funcs, 'run_script', failed_clone(failure))

    assert manager.repo_install('https://github.com/owner/fixture', str(tmp_path / 'fixture')).result is False

    assert not (tmp_path / 'fixture').exists()


@pytest.mark.parametrize('failure', RUNNER_FAILURES)
def test_install_whose_clone_fails_leaves_a_directory_that_was_there(core, manager, monkeypatch, windows, tmp_path, failure):  # noqa: F811
    (tmp_path / 'fixture').mkdir()
    (tmp_path / 'fixture/kept').write_text('a file that was there')
    monkeypatch.setattr(core.manager_funcs, 'run_script', failed_clone(failure))

    assert manager.repo_install('https://github.com/owner/fixture', str(tmp_path / 'fixture')).result is False

    assert (tmp_path / 'fixture/kept').read_text() == 'a file that was there'


@pytest.mark.parametrize('failure', RUNNER_FAILURES)
def test_install_by_url_whose_clone_in_the_git_helper_fails_leaves_no_directory(core, manager, monkeypatch, windows, tmp_path, failure):  # noqa: F811
    """The git helper is replaced by one that fails after it made the directory."""
    custom_nodes = tmp_path / 'custom_nodes'
    custom_nodes.mkdir()
    monkeypatch.setattr(core.manager_funcs, 'run_script', failed_clone(failure))
    monkeypatch.setattr(core, 'get_default_custom_nodes_path', lambda: str(custom_nodes))
    monkeypatch.setattr(core, 'get_custom_nodes_paths', lambda: [str(custom_nodes)])
    manager.get_cnr_by_repo = Mock(return_value=None)

    assert asyncio.run(core.gitclone_install('https://github.com/owner/fixture')).result is False

    assert packs(custom_nodes) == []


@pytest.fixture
def made_by_another_install(core, monkeypatch, tmp_path):  # noqa: F811
    """A directory that a check does not see: another install can make it after the check, before the clone starts."""
    destination = tmp_path / 'custom_nodes/fixture'
    destination.mkdir(parents=True)
    (destination / 'kept').write_text('of another install')
    exists = os.path.exists
    monkeypatch.setattr(os.path, 'exists', lambda path: False if str(path) == str(destination) else exists(path))
    return destination


@pytest.mark.parametrize('failure', RUNNER_FAILURES)
def test_install_whose_clone_fails_leaves_a_directory_that_another_install_made(core, manager, monkeypatch, windows, made_by_another_install, failure):  # noqa: F811
    monkeypatch.setattr(core.manager_funcs, 'run_script', failed_clone(failure))

    assert manager.repo_install('https://github.com/owner/fixture', str(made_by_another_install)).result is False

    assert (made_by_another_install / 'kept').is_file()


@pytest.mark.parametrize('failure', RUNNER_FAILURES)
def test_install_by_url_whose_clone_fails_leaves_a_directory_that_another_install_made(core, manager, monkeypatch, windows, made_by_another_install, failure):  # noqa: F811
    custom_nodes = made_by_another_install.parent
    monkeypatch.setattr(core.manager_funcs, 'run_script', failed_clone(failure))
    monkeypatch.setattr(core, 'get_default_custom_nodes_path', lambda: str(custom_nodes))
    monkeypatch.setattr(core, 'get_custom_nodes_paths', lambda: [str(custom_nodes)])
    manager.get_cnr_by_repo = Mock(return_value=None)

    assert asyncio.run(core.gitclone_install('https://github.com/owner/fixture')).result is False

    assert (made_by_another_install / 'kept').is_file()


@pytest.mark.skipif(os.name != 'posix' or os.geteuid() == 0, reason='the folder can be removed here')
def test_what_a_failed_clone_left_and_cannot_be_removed_is_reported(core, manager, monkeypatch, caplog, tmp_path):  # noqa: F811
    """As a file that another program has open on Windows: here a file in a folder that may not be written."""
    def clone_that_fails(command, cwd):
        held = Path(command[-1]) / 'held'
        held.mkdir(parents=True, exist_ok=True)
        (held / 'file').touch()
        held.chmod(0o555)
        return 1

    monkeypatch.setattr(core.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(core.manager_funcs, 'run_script', clone_that_fails)

    try:
        assert manager.repo_install('https://github.com/owner/fixture', str(tmp_path / 'fixture')).result is False
    finally:
        (tmp_path / 'fixture/held').chmod(0o755)

    assert [record for record in caplog.records if str(tmp_path / 'fixture') in record.getMessage()]


def test_install_into_a_directory_that_was_there_is_left_to_the_git_helper(core, manager, monkeypatch, windows, tmp_path):  # noqa: F811
    """The helper moves what an earlier clone left out of the way, and clones."""
    (tmp_path / 'fixture').mkdir()
    (tmp_path / 'fixture/left').touch()
    monkeypatch.setattr(core.manager_funcs, 'run_script', Mock(return_value=0))
    manager.execute_install_script = Mock(return_value=True)

    assert manager.repo_install('https://github.com/owner/fixture', str(tmp_path / 'fixture')).result is True

    assert core.manager_funcs.run_script.call_args.args[0][-1] == str(tmp_path / 'fixture')


@pytest.mark.parametrize('failure', RUNNER_FAILURES)
def test_file_whose_mode_cannot_be_changed_does_not_hide_the_failed_clone(core, manager, monkeypatch, windows, tmp_path, failure):  # noqa: F811
    """What is left is removed as far as it can be, and the install ends as one whose clone failed."""
    def chmod(path, mode, **options):
        raise PermissionError(13, 'Access is denied', str(path))

    monkeypatch.setattr(core.manager_funcs, 'run_script', failed_clone(failure))
    monkeypatch.setattr(os, 'chmod', chmod)

    result = manager.repo_install('https://github.com/owner/fixture', str(tmp_path / 'fixture'))

    assert (result.result, result.msg) == (False, 'Failed to clone repo: https://github.com/owner/fixture')


def test_install_by_url_that_fails_at_the_submodules_leaves_no_directory(core, manager, monkeypatch, tmp_path, origin):  # noqa: F811
    (tmp_path / 'library').rename(tmp_path / 'library.away')
    custom_nodes = tmp_path / 'custom_nodes'
    custom_nodes.mkdir()
    monkeypatch.setattr(core, 'get_default_custom_nodes_path', lambda: str(custom_nodes))
    monkeypatch.setattr(core, 'get_custom_nodes_paths', lambda: [str(custom_nodes)])
    monkeypatch.setattr(core, 'is_valid_url', lambda url: True)
    monkeypatch.setattr(core, 'execute_install_script', Mock(return_value=True))
    manager.get_cnr_by_repo = Mock(return_value=None)

    assert asyncio.run(core.gitclone_install(str(tmp_path / 'origin'), instant_execution=True)).result is False

    assert packs(custom_nodes) == []
    core.execute_install_script.assert_not_called()


@pytest.fixture
def fixture(core, manager, monkeypatch, windows, tmp_path):  # noqa: F811
    """The destination of two installs of one nodepack at a time. The clone runs in the git helper, which is replaced by one that leaves a file."""
    custom_nodes = tmp_path / 'custom_nodes'
    custom_nodes.mkdir()
    monkeypatch.setattr(core, 'get_default_custom_nodes_path', lambda: str(custom_nodes))
    monkeypatch.setattr(core, 'get_custom_nodes_paths', lambda: [str(custom_nodes)])
    monkeypatch.setattr(core.manager_funcs, 'run_script', cloned)
    manager.get_cnr_by_repo = Mock(return_value=None)
    return custom_nodes / 'fixture'


def cloned(command, cwd):
    os.makedirs(command[-1], exist_ok=True)
    (Path(command[-1]) / 'cloned').touch()
    return 0


@pytest.mark.parametrize('first', ['queued', 'by url'])
def test_install_of_a_nodepack_that_is_being_installed_is_refused(core, manager, monkeypatch, fixture, first):  # noqa: F811
    """Its clone would go into the directory that the first install has made, and be removed with it when the clone of the first fails."""
    url, others = 'https://github.com/owner/fixture', []

    def clone_with_another_install_in_it(command, cwd):
        monkeypatch.setattr(core.manager_funcs, 'run_script', cloned)
        others.append(manager.repo_install(url, str(fixture)).result)
        return 1

    monkeypatch.setattr(core.manager_funcs, 'run_script', clone_with_another_install_in_it)

    if first == 'queued':
        assert manager.repo_install(url, str(fixture)).result is False
    else:
        assert asyncio.run(core.gitclone_install(url)).result is False

    assert others == [False]
    assert packs(fixture.parent) == []
    assert manager.repo_install(url, str(fixture)).result is True
    assert (fixture / 'cloned').exists()


# another process, as `cm-cli` beside the server: it has the install of the nodepack for itself until it is told to go on, or killed
OTHER_PROCESS = """
import json, os, sys
# the tests and the package: not every Python looks in the directory it is run in
sys.path[:0] = [sys.argv[1], os.path.dirname(sys.argv[1])]
from _install_flags_testutil import import_reader
with import_reader(sys.argv[2]).claimed_install(sys.argv[3]) as claimed:
    print('claimed:', json.dumps(claimed), flush=True)
    sys.stdin.read(1)
"""


def test_install_of_a_nodepack_that_another_process_installs_is_refused_until_that_process_is_gone(core, manager, fixture, tmp_path):  # noqa: F811
    """The process is killed, as a container that is stopped in the middle of a clone: what it had is free, whatever file it left."""
    url = 'https://github.com/owner/fixture'
    other = subprocess.Popen([sys.executable, '-c', OTHER_PROCESS, os.path.dirname(__file__), core.__name__.split('.')[1], str(fixture)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        # the module says which git it uses before
        assert next(line for line in iter(other.stdout.readline, '') if line.startswith('claimed:')) == 'claimed: true\n'

        assert manager.repo_install(url, str(fixture)).result is False
        assert packs(fixture.parent) == []
    finally:
        other.kill()
        other.wait()

    assert manager.repo_install(url, str(fixture)).result is True
    assert (fixture / 'cloned').exists()


def test_claim_of_an_install_is_a_file_beside_the_nodepacks(core, manager, monkeypatch, fixture):  # noqa: F811
    """In `.disabled/.locks`, which ComfyUI does not load: where that cannot be written, nothing can be installed either.

    Manager takes the folders in `.disabled` for nodepacks that are disabled, and not this one."""
    assert manager.repo_install('https://github.com/owner/fixture', str(fixture)).result is True

    assert sorted(os.listdir(fixture.parent)) == ['.disabled', 'fixture']
    assert os.listdir(fixture.parent / '.disabled') == ['.locks']
    assert os.listdir(fixture.parent / '.disabled/.locks') == ['fixture.lock']
    assert core.get_installed_node_packs() == {}
    monkeypatch.setattr(sys.modules['folder_paths'], 'get_folder_paths', lambda kind: [str(fixture.parent)], raising=False)
    monkeypatch.setattr(core.cnr_utils, 'get_cnr_data', AsyncMock(return_value=[]))
    found = core.UnifiedManager()
    asyncio.run(found.reload('cache'))
    assert (sorted(found.unknown_active_nodes), sorted(found.unknown_inactive_nodes)) == (['fixture'], [])


def test_install_whose_claim_cannot_be_taken_fails(core, manager, monkeypatch, fixture):  # noqa: F811
    """Without the claim, what it removes after a clone that failed can be the clone of another install."""
    url, clones = 'https://github.com/owner/fixture', []
    monkeypatch.setattr(core.manager_funcs, 'run_script', lambda command, cwd: clones.append(command) or 0)
    # no file can be made in it
    (fixture.parent / '.disabled').touch()

    assert asyncio.run(core.gitclone_install(url)).result is False
    assert manager.repo_install(url, str(fixture)).result is False

    assert clones == []
    assert os.listdir(fixture.parent) == ['.disabled']
