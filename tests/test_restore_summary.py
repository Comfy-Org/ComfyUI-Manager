"""The summary of a snapshot restore lists a step that failed as failed.

Both `manager_core` modules are run. What the restore asks the manager to do is replaced,
and answers with a success or a failure.
"""

import os
import subprocess
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from _install_flags_testutil import GIT_LOCATION
from test_snapshot_restore_pins import COMMIT, REPO_URL, core, manager, restore  # noqa: F401


@pytest.fixture(autouse=True)
def git_finds_its_repository_by_the_directory(monkeypatch):
    for name in GIT_LOCATION:
        monkeypatch.delenv(name, raising=False)


def pinned(url, commit=COMMIT):
    return {'git_custom_nodes': {url: {'hash': commit, 'disabled': False}}}


@pytest.fixture
def summary(core, tmp_path, capsys):  # noqa: F811
    def summary(**snapshot):
        restore(core, tmp_path, **snapshot)
        return [line.strip() for line in capsys.readouterr().out.splitlines() if line.startswith('[ ')]

    return summary


@pytest.fixture
def answer(core):  # noqa: F811
    def answer(action, ok):
        result = core.ManagedResult(action)
        return Mock(return_value=result if ok else result.fail('failed'))

    return answer


def git_pack(path, url):
    """A directory whose .git/config names `url`, as a git nodepack the Registry does not know."""
    (path / '.git').mkdir(parents=True)
    (path / '.git/config').write_text('[remote "origin"]\n\turl = %s\n' % url)
    return url, str(path)


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


@pytest.mark.parametrize('cloned, line', [(True, '[ INSTALLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_clone_follows_its_result(core, manager, summary, answer, monkeypatch, tmp_path, cloned, line):  # noqa: F811
    manager.repo_install = answer('install-git', cloned)
    monkeypatch.setattr(core, 'repo_switch_commit', Mock(return_value=True))

    assert summary(**pinned(REPO_URL + '.git')) == [line]
    assert manager.repo_install.call_args.args[1] == str(tmp_path / 'fixture')


def test_url_that_is_not_cloned_is_reported_as_failed(manager, summary, tmp_path):  # noqa: F811
    assert summary(**pinned('/home/someone/repos/fixture')) == ['[  FAILED   ] fixture']
    assert not (tmp_path / 'fixture').exists()


def test_cloned_pack_is_checked_out_at_the_pinned_commit(core, manager, summary, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'origin')

    def clone(url, path, **options):
        subprocess.run(['git', 'clone', '-q', str(tmp_path / 'origin'), path], check=True, capture_output=True)
        return core.ManagedResult('install-git')

    manager.repo_install = clone

    assert summary(**pinned(REPO_URL, commits[0])) == ['[ INSTALLED ] fixture']
    assert head(tmp_path / 'fixture') == commits[0]
    assert (tmp_path / 'fixture/__init__.py').read_text() == 'VERSION = 1'


def test_cloned_registry_pack_is_checked_out_at_the_pinned_commit(core, manager, summary, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'origin')

    async def install(pack_id, version_spec, **options):
        subprocess.run(['git', 'clone', '-q', str(tmp_path / 'origin'), tmp_path / pack_id], check=True, capture_output=True)
        manager.active_nodes[pack_id] = (version_spec, str(tmp_path / pack_id))
        return core.ManagedResult('install-git')

    manager.repo_cnr_map[REPO_URL] = {'id': 'fixture'}
    manager.install_by_id = AsyncMock(side_effect=install)

    assert summary(**pinned(REPO_URL, commits[0])) == ['[ INSTALLED ] fixture']
    assert head(tmp_path / 'fixture') == commits[0]


def test_cloned_pack_that_cannot_be_checked_out_is_reported_as_failed(manager, summary, answer):  # noqa: F811
    manager.repo_install = answer('install-git', True)

    assert summary(**pinned(REPO_URL)) == [f'[  FAILED   ] fixture@{COMMIT}']


@pytest.mark.parametrize('disabled, line', [(True, '[  DISABLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_disabling_a_git_pack_that_is_not_in_the_snapshot_follows_its_result(manager, summary, answer, tmp_path, disabled, line):  # noqa: F811
    manager.unknown_active_nodes['fixture'] = git_pack(tmp_path / 'fixture', REPO_URL)
    manager.unified_disable = answer('disable', disabled)

    assert summary() == [line]


@pytest.mark.parametrize('disabled, line', [(True, '[  DISABLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_disabling_a_registry_pack_that_is_not_in_the_snapshot_follows_its_result(manager, summary, answer, tmp_path, disabled, line):  # noqa: F811
    manager.active_nodes['fixture'] = ('1.0.0', str(tmp_path / 'fixture'))
    manager.unified_disable = answer('disable', disabled)

    assert summary() == [line]


@pytest.mark.parametrize('name', ['ComfyUI-Manager', 'comfyui-manager'])
def test_the_manager_itself_is_not_listed(manager, summary, answer, tmp_path, name):  # noqa: F811
    manager.unknown_active_nodes[name] = git_pack(tmp_path / name, 'https://github.com/ltdrdata/ComfyUI-Manager')
    manager.unified_disable = answer('disable', True)

    assert summary() == []
    assert manager.unified_disable.call_count == 0


@pytest.mark.parametrize('enabled, line', [(True, '[  ENABLED  ] fixture'), (False, '[  FAILED   ] fixture')])
def test_enabling_a_git_pack_of_the_snapshot_follows_its_result(manager, summary, answer, tmp_path, enabled, line):  # noqa: F811
    manager.unknown_inactive_nodes['fixture'] = git_pack(tmp_path / '.disabled/fixture', REPO_URL)
    manager.unified_enable = answer('enable', enabled)

    assert summary(**pinned(REPO_URL)) == [line]


def test_installed_git_pack_the_registry_does_not_know_is_checked_out_at_the_pinned_commit(manager, summary, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    subprocess.run(['git', 'remote', 'add', 'origin', REPO_URL], cwd=tmp_path / 'fixture', check=True)
    manager.unknown_active_nodes['fixture'] = (REPO_URL, str(tmp_path / 'fixture'))

    assert summary(**pinned(REPO_URL, commits[0])) == [f'[  CHECKOUT ] fixture@{commits[0]}']
    assert head(tmp_path / 'fixture') == commits[0]


def test_checkout_that_fails_is_reported_as_failed(manager, summary, tmp_path):  # noqa: F811
    manager.unknown_active_nodes['fixture'] = git_pack(tmp_path / 'fixture', REPO_URL)

    assert summary(**pinned(REPO_URL)) == [f'[  FAILED   ] fixture@{COMMIT}']


def test_pack_without_a_commit_in_the_snapshot_is_left_where_it_is(manager, summary, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    subprocess.run(['git', 'remote', 'add', 'origin', REPO_URL], cwd=tmp_path / 'fixture', check=True)
    manager.unknown_active_nodes['fixture'] = (REPO_URL, str(tmp_path / 'fixture'))

    assert summary(**pinned(REPO_URL, 'unknown')) == ['[  SKIPPED  ] fixture']
    assert head(tmp_path / 'fixture') == commits[1]


def test_cloned_pack_without_a_commit_in_the_snapshot_is_installed(manager, summary, answer):  # noqa: F811
    manager.repo_install = answer('install-git', True)

    assert summary(**pinned(REPO_URL, 'unknown')) == ['[ INSTALLED ] fixture']


@pytest.mark.parametrize('installed, line', [(True, '[ INSTALLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_install_script_of_a_cloned_pack_runs_at_the_pinned_commit(core, manager, summary, tmp_path, installed, line):  # noqa: F811
    commits = repository(tmp_path / 'origin')
    ran_at = []

    def clone(url, path, return_postinstall=False, **options):
        subprocess.run(['git', 'clone', '-q', str(tmp_path / 'origin'), path], check=True, capture_output=True)

        def postinstall():
            ran_at.append(head(path))
            return installed

        result = core.ManagedResult('install-git')
        return result.with_postinstall(postinstall) if return_postinstall else (result if postinstall() else result.fail('install script'))

    manager.repo_install = clone

    assert summary(**pinned(REPO_URL, commits[0])) == [line]
    assert ran_at == [commits[0]]


def test_install_script_that_raises_is_reported_as_failed_and_the_restore_goes_on(core, manager, summary, monkeypatch):  # noqa: F811
    def clone(url, path, return_postinstall=False, **options):
        def postinstall():
            raise subprocess.CalledProcessError(1, ['python', 'install.py'])

        return core.ManagedResult('install-git').with_postinstall(postinstall)

    manager.repo_install = clone
    monkeypatch.setattr(core, 'repo_switch_commit', Mock(return_value=True))

    assert summary(git_custom_nodes={REPO_URL: {'hash': COMMIT, 'disabled': False},
                                     REPO_URL + '-other': {'hash': COMMIT, 'disabled': False}}) == ['[  FAILED   ] fixture', '[  FAILED   ] fixture-other']


def test_install_script_of_a_cloned_pack_runs_also_when_the_commit_cannot_be_checked_out(core, manager, summary, tmp_path):  # noqa: F811
    """The clone stays where it is, and a later restore only checks it out."""
    ran = []
    manager.repo_install = lambda url, path, **options: core.ManagedResult('install-git').with_postinstall(lambda: ran.append(path) or True)

    assert summary(**pinned(REPO_URL)) == [f'[  FAILED   ] fixture@{COMMIT}']
    assert ran == [str(tmp_path / 'fixture')]


def test_install_script_of_a_cloned_registry_pack_runs_also_when_the_commit_cannot_be_checked_out(core, manager, summary, tmp_path):  # noqa: F811
    ran = []

    async def install(pack_id, version_spec, **options):
        manager.active_nodes[pack_id] = (version_spec, str(tmp_path / pack_id))
        return core.ManagedResult('install-git').with_postinstall(lambda: ran.append(pack_id) or True)

    manager.repo_cnr_map[REPO_URL] = {'id': 'fixture'}
    manager.install_by_id = AsyncMock(side_effect=install)

    assert summary(**pinned(REPO_URL)) == [f'[  FAILED   ] fixture@{COMMIT}']
    assert ran == ['fixture']


@pytest.mark.parametrize('outcome, line', [(True, '[ INSTALLED ] fixture@1.0.0'), (False, '[  FAILED   ] fixture@1.0.0'),
                                           (subprocess.CalledProcessError(1, ['python', 'install.py']), '[  FAILED   ] fixture@1.0.0')])
def test_install_script_of_a_registry_pack_is_run(core, manager, summary, outcome, line):  # noqa: F811
    ran = []

    def postinstall():
        ran.append('fixture')
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    manager.install_by_id = AsyncMock(return_value=core.ManagedResult('install-cnr').with_postinstall(postinstall))

    assert summary(cnr_custom_nodes={'fixture': '1.0.0'}) == [line]
    assert ran == ['fixture']
    assert manager.install_by_id.await_args.kwargs['return_postinstall'] is True


def test_git_of_a_case_does_not_inherit_a_repository():
    """Run from a git hook, the tests inherit variables such as GIT_DIR, which point git at the repository of the hook."""
    names = subprocess.run(['git', 'rev-parse', '--local-env-vars'], check=True, capture_output=True, text=True).stdout.split()
    case = f'{__file__}::test_cloned_pack_is_checked_out_at_the_pinned_commit'
    child = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', case],
                           env={**os.environ, **dict.fromkeys(names, 'elsewhere')}, capture_output=True, text=True)

    assert child.returncode == 0, child.stdout


def test_registry_pack_whose_install_raises_is_reported_as_failed_and_the_restore_goes_on(core, manager, summary):  # noqa: F811
    """Without a connection the request to the Registry raises."""
    async def install(pack_id, **options):
        if pack_id == 'fixture':
            raise ConnectionError('the Registry cannot be reached')
        return core.ManagedResult('install-cnr')

    manager.install_by_id = AsyncMock(side_effect=install)

    assert summary(cnr_custom_nodes={'fixture': '1.0.0', 'other': '1.0.0'}) == ['[ INSTALLED ] other@1.0.0', '[  FAILED   ] fixture@1.0.0']


def test_registry_pack_whose_switch_raises_is_reported_as_failed_and_the_restore_goes_on(core, manager, summary, tmp_path):  # noqa: F811
    manager.active_nodes['fixture'] = ('1.0.0', str(tmp_path / 'fixture'))
    manager.cnr_switch_version = Mock(side_effect=ConnectionError('the Registry cannot be reached'))
    manager.install_by_id = AsyncMock(return_value=core.ManagedResult('install-cnr'))

    assert summary(cnr_custom_nodes={'fixture': '2.0.0', 'other': '1.0.0'}) == ['[ INSTALLED ] other@1.0.0', '[  FAILED   ] fixture@2.0.0']


def registry_pack(manager, path):  # noqa: F811
    manager.active_nodes['fixture'] = ('1.0.0', str(path / 'fixture'))


def registry_git_pack(manager, path):  # noqa: F811
    manager.active_nodes['fixture'] = ('nightly', str(path / 'fixture'))
    manager.repo_cnr_map[REPO_URL] = {'id': 'fixture'}


def disabled_registry_git_pack(manager, path):  # noqa: F811
    manager.nightly_inactive_nodes['fixture'] = str(path / '.disabled/fixture')
    manager.repo_cnr_map[REPO_URL] = {'id': 'fixture'}


def unknown_git_pack(manager, path):  # noqa: F811
    manager.unknown_active_nodes['fixture'] = git_pack(path / 'fixture', REPO_URL)


def disabled_unknown_git_pack(manager, path):  # noqa: F811
    manager.unknown_inactive_nodes['fixture'] = git_pack(path / '.disabled/fixture', REPO_URL)


@pytest.mark.parametrize('installed, step, snapshot', [
    (registry_pack, 'unified_disable', {}),
    (registry_git_pack, 'unified_disable', {}),
    (unknown_git_pack, 'unified_disable', {}),
    (disabled_registry_git_pack, 'unified_enable', pinned(REPO_URL)),
    (disabled_unknown_git_pack, 'unified_enable', pinned(REPO_URL)),
])
def test_pack_whose_directory_cannot_be_moved_is_reported_as_failed_and_the_restore_goes_on(manager, summary, tmp_path, installed, step, snapshot):  # noqa: F811
    """Disabling and enabling move the directory of the pack."""
    installed(manager, tmp_path)
    setattr(manager, step, Mock(side_effect=PermissionError(13, 'Permission denied')))

    assert summary(**snapshot) == ['[  FAILED   ] fixture']
    assert getattr(manager, step).call_count == 1


def test_registry_git_pack_that_cannot_be_enabled_is_listed_once(manager, summary, tmp_path):  # noqa: F811
    """The install that follows for a pack of the snapshot enables it as well, and raises for the same reason."""
    disabled_registry_git_pack(manager, tmp_path)
    manager.unified_enable = Mock(side_effect=PermissionError(13, 'Permission denied'))
    manager.install_by_id = AsyncMock(side_effect=PermissionError(13, 'Permission denied'))

    assert summary(**pinned(REPO_URL)) == ['[  FAILED   ] fixture']


def packs_that_name(tmp_path, **files):
    for name in ('first', 'second'):
        (tmp_path / name).mkdir()
        for file, text in files.items():
            (tmp_path / name / file).write_text(text)
    return str(tmp_path / 'first'), str(tmp_path / 'second')


@pytest.fixture
def installs(core, monkeypatch):  # noqa: F811
    """Replace what runs an install command; the answers are given in turn, and the directories it ran in are returned."""
    def installs(*answers):
        answers, ran = list(answers), []

        def try_install_script(url, repo_path, install_cmd, instant_execution=False):
            ran.append(os.path.basename(repo_path))
            return answers.pop(0)

        monkeypatch.setattr(core, 'try_install_script', try_install_script)
        monkeypatch.setattr(core.manager_util, 'PIPFixer', Mock())
        monkeypatch.setattr(core.manager_util, 'get_installed_packages', Mock(return_value={}))
        monkeypatch.setattr(core.cm_global, 'pip_overrides', {}, raising=False)
        return ran

    return installs


def test_requirement_that_was_not_installed_is_tried_for_the_next_pack(manager, installs, tmp_path):  # noqa: F811
    first, second = packs_that_name(tmp_path, **{'requirements.txt': 'shareddep==1\n'})
    ran = installs(False, True)

    assert not manager.execute_install_script(None, first)
    assert manager.execute_install_script(None, second)
    assert ran == ['first', 'second']


def test_requirement_after_one_that_failed_is_tried_for_the_next_pack(manager, installs, tmp_path):  # noqa: F811
    first, second = packs_that_name(tmp_path, **{'requirements.txt': 'fails==1\nshareddep==1\n'})
    ran = installs(False, True, True)

    assert not manager.execute_install_script(None, first)
    assert manager.execute_install_script(None, second)
    assert ran == ['first', 'second', 'second']


def test_requirement_that_was_installed_is_not_installed_twice(manager, installs, tmp_path):  # noqa: F811
    first, second = packs_that_name(tmp_path, **{'requirements.txt': 'shareddep==1\n'})
    ran = installs(True)

    assert manager.execute_install_script(None, first)
    assert manager.execute_install_script(None, second)
    assert ran == ['first']


def test_install_script_that_failed_is_run_when_asked_again(manager, installs, tmp_path):  # noqa: F811
    first, _ = packs_that_name(tmp_path, **{'install.py': ''})
    ran = installs(False, True)

    assert not manager.execute_install_script(None, first)
    assert manager.execute_install_script(None, first)
    assert ran == ['first', 'first']


def test_install_script_not_run_after_a_requirement_failed_is_run_when_asked_again(manager, installs, tmp_path):  # noqa: F811
    first, _ = packs_that_name(tmp_path, **{'requirements.txt': 'fails==1\n', 'install.py': ''})
    ran = installs(False, True, True)

    assert not manager.execute_install_script(None, first)
    assert manager.execute_install_script(None, first)
    assert ran == ['first', 'first', 'first']
