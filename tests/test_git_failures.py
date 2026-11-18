import subprocess

import pytest

from _install_flags_testutil import GIT_LOCATION
from test_snapshot_restore_pins import core  # noqa: F401


def git(path, *args):
    subprocess.run(['git', '-c', 'protocol.file.allow=always', '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', *args],
                   cwd=path, check=True, capture_output=True)


def head(path):
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(autouse=True)
def git_of_the_case(monkeypatch, tmp_path):
    for name in GIT_LOCATION:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'protocol.file.allow')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'always')
    (tmp_path / 'folder_paths.py').touch()
    monkeypatch.setenv('COMFYUI_PATH', str(tmp_path))


@pytest.fixture
def origin(tmp_path):
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
    (tmp_path / 'library').rename(tmp_path / 'library.away')
    return tmp_path / 'pack'


def test_pull_that_fails_at_the_submodules_leaves_the_pack_at_its_commit(core, tmp_path, origin, pack):  # noqa: F811
    with pytest.raises(Exception):
        core.git_pull(str(pack))

    assert head(pack) == origin[0]
    assert (pack / 'asset/__init__.py').read_text() == 'VERSION = 1'

    (tmp_path / 'library.away').rename(tmp_path / 'library')
    core.git_pull(str(pack))

    assert head(pack) == origin[1]
    assert (pack / 'library/__init__.py').read_text() == 'VERSION = 2'
    assert (pack / 'asset/__init__.py').read_text() == 'VERSION = 2'


def test_pull_of_the_git_helper_that_fails_is_a_failure(core, monkeypatch, tmp_path, origin, pack):  # noqa: F811
    monkeypatch.setattr(core.platform, 'system', lambda: 'Windows')

    with pytest.raises(Exception):
        core.git_pull(str(pack))

    assert head(pack) == origin[0]
    assert (pack / 'asset/__init__.py').read_text() == 'VERSION = 1'

    (tmp_path / 'library.away').rename(tmp_path / 'library')
    core.git_pull(str(pack))

    assert head(pack) == origin[1]


def library_not_cloned(pack):
    git(pack, 'submodule', 'deinit', '-q', '-f', 'library')
    # moved, as git makes files read-only that Windows does not remove
    (pack / '.git/modules/library').rename(pack.parent / 'library.modules')


@pytest.fixture
def helper(core, monkeypatch):  # noqa: F811
    monkeypatch.setattr(core.platform, 'system', lambda: 'Windows')


def test_pull_of_the_git_helper_that_fails_at_the_submodules_puts_them_back(core, helper, tmp_path, origin):  # noqa: F811
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
def test_pull_of_a_pack_whose_branch_is_ahead_of_its_remote_is_no_failure(core, request, tmp_path, origin, where):  # noqa: F811
    pack = tmp_path / 'pack'
    git(pack, 'pull', '-q', '--recurse-submodules')
    git(pack, 'commit', '-q', '--allow-empty', '-m', 'a commit of the pack alone')
    tip = head(pack)
    if where == 'in the git helper':
        request.getfixturevalue('helper')

    core.git_pull(str(pack))

    assert head(pack) == tip


def library_at_a_commit_away(tmp_path):
    library = tmp_path / 'library'
    (library / '__init__.py').write_text('VERSION = 3')
    git(library, 'commit', '-q', '-a', '-m', 'version 3')
    git(tmp_path / 'origin/library', 'pull', '-q')
    git(tmp_path / 'origin', 'commit', '-q', '-a', '-m', 'library 3')
    version_3 = head(library)
    library.rename(tmp_path / 'library.away')
    return version_3


@pytest.mark.parametrize('where', ['in the server process', 'in the git helper'])
def test_pull_that_fails_puts_back_the_branch_of_a_pack_that_was_not_on_it(core, request, tmp_path, origin, where):  # noqa: F811
    pack = tmp_path / 'pack'
    git(pack, 'pull', '-q', '--recurse-submodules')
    git(pack, 'checkout', '-q', origin[0])
    git(pack, 'submodule', 'update', '-q', '--recursive')
    library_not_cloned(pack)
    library_at_a_commit_away(tmp_path)
    if where == 'in the git helper':
        request.getfixturevalue('helper')

    with pytest.raises(Exception):
        core.git_pull(str(pack))

    assert head(pack) == origin[1]


def test_pull_whose_submodules_cannot_be_put_back_either_fails_with_the_error_of_the_update(core, monkeypatch, capfd, tmp_path, origin):  # noqa: F811
    pack = tmp_path / 'pack'
    git(pack, 'pull', '-q', '--no-recurse-submodules')
    version_3 = library_at_a_commit_away(tmp_path)

    monkeypatch.setattr(core.platform, 'system', lambda: 'Linux')
    with pytest.raises(Exception) as failure:
        core.git_pull(str(pack))

    assert version_3 in str(failure.value)

    monkeypatch.setattr(core.platform, 'system', lambda: 'Windows')
    capfd.readouterr()
    with pytest.raises(Exception):
        core.git_pull(str(pack))

    assert version_3 in capfd.readouterr().out


@pytest.mark.parametrize('where', ['in the server process', 'in the git helper'])
def test_pull_that_fails_leaves_a_submodule_that_was_never_fetched_alone(core, request, tmp_path, where):  # noqa: F811
    for name in ('asset', 'library', 'extra', 'origin'):
        (tmp_path / name).mkdir()
        git(tmp_path / name, 'init', '-q')
    for name in ('asset', 'library', 'extra'):
        (tmp_path / name / '__init__.py').write_text('VERSION = 1')
        git(tmp_path / name, 'add', '.')
        git(tmp_path / name, 'commit', '-q', '-m', 'version 1')
    origin, plain = tmp_path / 'origin', tmp_path / 'plain'
    for name in ('asset', 'library'):
        git(origin, 'submodule', 'add', '-q', str(tmp_path / name), name)
    git(origin, 'commit', '-q', '-m', 'two submodules')
    git(tmp_path, 'clone', '-q', str(origin), 'plain')
    git(plain, 'submodule', 'update', '-q', '--init', 'asset')
    git(origin, 'rm', '-q', 'library')
    git(origin, 'submodule', 'add', '-q', str(tmp_path / 'extra'), 'extra')
    git(origin, 'commit', '-q', '-m', 'library removed, extra added')
    (tmp_path / 'extra').rename(tmp_path / 'extra.away')
    before = head(plain)
    if where == 'in the git helper':
        request.getfixturevalue('helper')

    with pytest.raises(Exception):
        core.git_pull(str(plain))

    assert head(plain) == before
    assert list((plain / 'library').iterdir()) == []
