import ast
import asyncio
import os
import pathlib
import shutil
import subprocess
import traceback
from types import SimpleNamespace
from typing import Annotated, Optional
from unittest.mock import AsyncMock, Mock

import pytest

from _install_flags_testutil import GIT_LOCATION
from test_snapshot_restore_pins import COMMIT, REPO_URL, core, manager, restore  # noqa: F401

CM_CLI = pathlib.Path(__file__).resolve().parent.parent / 'cm_cli/__main__.py'


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
    (path / '.git').mkdir(parents=True)
    (path / '.git/config').write_text('[remote "origin"]\n\turl = %s\n' % url)
    return url, str(path)


def in_registry(manager):  # noqa: F811
    manager.repo_cnr_map[REPO_URL] = {'id': 'fixture'}
    manager.get_custom_nodes.return_value = {'fixture': {'repository': REPO_URL}}


@pytest.fixture
def clones(manager, tmp_path):  # noqa: F811
    def clones(kind, clone):
        if kind == 'registry':
            in_registry(manager)
        manager.repo_install = lambda url, path, return_postinstall=False, **options: clone(path, return_postinstall)

    return clones


@pytest.fixture
def steps(core, manager, monkeypatch):  # noqa: F811
    done = []
    manager.unified_disable = lambda name, is_unknown: done.append('disable ' + name) or core.ManagedResult('disable')
    manager.unified_enable = lambda name, version: done.append('enable %s@%s' % (name, version)) or core.ManagedResult('enable')
    manager.repo_install = lambda url, path, **options: done.append('clone %s into %s' % (url, os.path.basename(path))) or core.ManagedResult('install-git')
    manager._cnr_install = lambda name, version, *args: done.append('install %s@%s' % (name, version.version)) or core.ManagedResult('install-cnr')
    monkeypatch.setattr(core.cnr_utils, 'install_node', lambda name, version: SimpleNamespace(version=version, download_url='https://registry.invalid/' + name, status='NodeVersionStatusActive'))
    monkeypatch.setattr(core, 'repo_switch_commit', Mock(return_value=True))
    return done


def errors(caplog):
    return [record.getMessage() for record in caplog.records if record.levelname == 'ERROR']


CLONES = pytest.mark.parametrize('kind', ['registry', 'url'])


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


@pytest.mark.parametrize('cloned, line', [(True, '[ INSTALLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_clone_follows_its_result(core, manager, summary, answer, monkeypatch, tmp_path, cloned, line):  # noqa: F811
    manager.repo_install = answer('install-git', cloned)
    monkeypatch.setattr(core, 'repo_switch_commit', Mock(return_value=True))

    assert summary(**pinned(REPO_URL + '.git')) == [line]
    assert manager.repo_install.call_args.args[1] == str(tmp_path / 'fixture')


def test_url_that_is_not_cloned_is_reported_as_failed(manager, summary, tmp_path):  # noqa: F811
    assert summary(**pinned('/home/someone/repos/fixture')) == ['[  FAILED   ] fixture']
    assert not (tmp_path / 'fixture').exists()


def test_pack_of_the_registry_that_the_node_list_does_not_have_is_cloned(manager, summary, steps):  # noqa: F811
    registered = {'id': 'fixture-of-the-registry', 'repository': REPO_URL, 'publisher': {'name': 'owner'}}
    manager.repo_cnr_map[REPO_URL] = manager.cnr_map['fixture-of-the-registry'] = registered

    assert summary(**pinned(REPO_URL + '.git')) == ['[ INSTALLED ] fixture-of-the-registry']
    assert steps == [f'clone {REPO_URL} into fixture-of-the-registry']


def test_pack_of_the_registry_is_cloned_from_the_url_of_the_snapshot_when_the_node_list_has_another_one_under_its_name(manager, summary, steps):  # noqa: F811
    manager.repo_cnr_map[REPO_URL] = {'id': 'fixture'}
    manager.get_custom_nodes.return_value = {'fixture': {'repository': 'https://github.com/another-owner/fixture'}}

    assert summary(**pinned(REPO_URL)) == ['[ INSTALLED ] fixture']
    assert steps == [f'clone {REPO_URL} into fixture']


@pytest.mark.parametrize('in_node_list', [True, False])
def test_enabled_version_of_the_registry_is_disabled_before_the_clone_of_a_snapshot_that_names_no_version(manager, summary, steps, tmp_path, in_node_list):  # noqa: F811
    """A snapshot from before the registry has no `cnr_custom_nodes`, so nothing else disables that version."""
    registered = {'id': 'fixture', 'repository': REPO_URL, 'publisher': {'name': 'owner'}}
    manager.repo_cnr_map[REPO_URL] = manager.cnr_map['fixture'] = registered
    manager.get_custom_nodes.return_value = {'fixture': {'repository': REPO_URL}} if in_node_list else {}
    manager.active_nodes['fixture'] = ('1.0.0', str(tmp_path / 'fixture'))

    assert summary(cnr_custom_nodes=None, **pinned(REPO_URL)) == ['[ INSTALLED ] fixture']
    assert steps == ['disable fixture', f'clone {REPO_URL} into fixture']


@pytest.mark.parametrize('machine, lines, done', [
    ('that saved it', ['[  SKIPPED  ] fixture'], []),
    ('with no node pack', ['[ INSTALLED ] fixture@1.0.0'], ['install fixture@1.0.0']),
], ids=['that saved it', 'with no node pack'])
def test_pack_saved_at_a_version_of_the_registry_with_its_clone_disabled_is_restored_at_that_version(core, manager, summary, steps, monkeypatch, tmp_path, machine, lines, done):  # noqa: F811
    """A switch from the clone to a version of the registry keeps the clone, disabled, and a snapshot saves both."""
    manager.repo_cnr_map[REPO_URL] = manager.cnr_map['fixture'] = {'id': 'fixture', 'repository': REPO_URL, 'publisher': {'name': 'owner'}}
    version, clone = tmp_path / 'fixture', tmp_path / '.disabled/fixture@nightly'
    version.mkdir()
    (version / '.tracking').write_text('')
    (version / 'pyproject.toml').write_text('[project]\nname = "fixture"\nversion = "1.0.0"\n')
    repository(clone)
    subprocess.run(['git', 'remote', 'add', 'origin', REPO_URL + '.git'], cwd=clone, check=True)
    monkeypatch.setattr(core, 'get_custom_nodes_paths', lambda: [str(tmp_path)])
    saved = asyncio.run(core.get_current_snapshot(custom_nodes_only=True))
    if machine == 'that saved it':
        manager.active_nodes['fixture'] = ('1.0.0', str(version))
        manager.nightly_inactive_nodes['fixture'] = str(clone)
    else:
        shutil.rmtree(version)
        shutil.rmtree(clone)

    assert summary(cnr_custom_nodes=saved['cnr_custom_nodes'], git_custom_nodes=saved['git_custom_nodes']) == lines
    assert steps == done


def test_clone_that_is_enabled_is_left_to_the_install_of_the_version_that_the_snapshot_names(manager, summary, steps, tmp_path):  # noqa: F811
    manager.repo_cnr_map[REPO_URL] = manager.cnr_map['fixture'] = {'id': 'fixture', 'repository': REPO_URL, 'publisher': {'name': 'owner'}}
    manager.active_nodes['fixture'] = ('nightly', str(tmp_path / 'fixture'))

    assert summary(cnr_custom_nodes={'fixture': '1.0.0'}, git_custom_nodes={REPO_URL: {'hash': COMMIT, 'disabled': True}}) == ['[ INSTALLED ] fixture@1.0.0']
    assert steps == ['disable fixture', 'install fixture@1.0.0']


@pytest.mark.parametrize('failure, lines, done', [
    ('the registry does not have it', [f'[  CHECKOUT ] fixture@{COMMIT}', '[  FAILED   ] fixture@1.0.0'], []),
    ('its download fails', [f'[  CHECKOUT ] fixture@{COMMIT}', '[  FAILED   ] fixture@1.0.0'], ['disable fixture', 'enable fixture@nightly']),
    ('its download fails after another version was enabled', [f'[  CHECKOUT ] fixture@{COMMIT}', '[  FAILED   ] fixture@1.0.0'], ['disable fixture', 'enable fixture@cnr', 'enable fixture@nightly']),
], ids=['the registry does not have it', 'its download fails', 'its download fails after another version was enabled'])
def test_clone_of_the_snapshot_is_restored_when_the_version_that_the_snapshot_names_cannot_be_installed(core, manager, summary, steps, monkeypatch, tmp_path, failure, lines, done):  # noqa: F811
    manager.repo_cnr_map[REPO_URL] = manager.cnr_map['fixture'] = {'id': 'fixture', 'repository': REPO_URL, 'publisher': {'name': 'owner'}}
    manager.active_nodes['fixture'] = ('nightly', str(tmp_path / 'fixture'))

    def disable(name, is_unknown):
        steps.append('disable ' + name)
        manager.nightly_inactive_nodes[name] = manager.active_nodes.pop(name)[1]
        return core.ManagedResult('disable')

    def enable(name, version):
        steps.append('enable %s@%s' % (name, version))
        if version == 'cnr':
            manager.active_nodes[name] = ('2.0.0', manager.cnr_inactive_nodes[name].pop('2.0.0'))
        return core.ManagedResult('enable').with_target(str(tmp_path / name))

    manager.unified_disable, manager.unified_enable = disable, enable
    if failure == 'the registry does not have it':
        monkeypatch.setattr(core.cnr_utils, 'install_node', lambda name, version: None)
    elif failure == 'its download fails':
        manager._cnr_install = lambda name, version, *args: core.ManagedResult('install-cnr').fail('the download failed')
    else:
        manager.cnr_inactive_nodes['fixture'] = {'2.0.0': str(tmp_path / '.disabled/fixture@2_0_0')}
        manager._cnr_switch_version = lambda name, version, *args: core.ManagedResult('switch-cnr').fail('the download failed')

    assert summary(cnr_custom_nodes={'fixture': '1.0.0'}, git_custom_nodes={REPO_URL: {'hash': COMMIT, 'disabled': True}}) == lines
    assert steps == done
    assert [x.args for x in core.repo_switch_commit.call_args_list] == [(str(tmp_path / 'fixture'), COMMIT)]


def test_pack_of_the_registry_with_the_name_of_the_manager_in_its_id_is_not_cloned(manager, summary, steps):  # noqa: F811
    manager.repo_cnr_map[REPO_URL] = {'id': 'comfyui-manager-fixture'}

    assert summary(**pinned(REPO_URL)) == ['[  SKIPPED  ] comfyui-manager-fixture']
    assert steps == []


@CLONES
def test_clone_that_is_refused_tells_why(core, manager, clones, tmp_path, caplog, kind):  # noqa: F811
    clones(kind, lambda path, return_postinstall: core.ManagedResult('install-git').fail('the clone was refused'))

    restore(core, tmp_path, **pinned(REPO_URL))

    assert errors(caplog) == ['the clone was refused']


def test_url_that_is_not_cloned_tells_why(core, manager, tmp_path, caplog):  # noqa: F811
    restore(core, tmp_path, **pinned('/home/someone/repos/fixture'))

    assert errors(caplog) == ['Invalid git url: /home/someone/repos/fixture']


def test_clone_of_a_pack_of_the_registry_that_raises_is_logged_once(core, manager, tmp_path, caplog):  # noqa: F811
    in_registry(manager)
    manager.repo_install = Mock(side_effect=RuntimeError('the disk is full'))

    restore(core, tmp_path, **pinned(REPO_URL))

    assert errors(caplog) == ['[ComfyUI-Manager] the disk is full']


def test_url_that_cannot_be_parsed_is_reported_as_failed_and_the_restore_goes_on(manager, summary):  # noqa: F811
    entry = {'hash': COMMIT, 'disabled': False}

    assert summary(git_custom_nodes={'https://[not-a-host/first': dict(entry), '/home/someone/repos/second': dict(entry)}) == [
        '[  FAILED   ] first', '[  FAILED   ] second']


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

    def clone(url, path, **options):
        subprocess.run(['git', 'clone', '-q', str(tmp_path / 'origin'), path], check=True, capture_output=True)
        return core.ManagedResult('install-git')

    in_registry(manager)
    manager.repo_install = clone

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
def test_enabling_a_git_pack_of_the_snapshot_follows_its_result(core, manager, summary, answer, tmp_path, monkeypatch, enabled, line):  # noqa: F811
    manager.unknown_inactive_nodes['fixture'] = git_pack(tmp_path / '.disabled/fixture', REPO_URL)
    manager.unified_enable = answer('enable', enabled)
    manager.unified_enable.return_value.target = str(tmp_path / 'fixture') if enabled else None
    checkout = Mock(return_value=False)
    monkeypatch.setattr(core, 'repo_switch_commit', checkout)

    assert summary(**pinned(REPO_URL)) == [line]
    assert [x.args for x in checkout.call_args_list] == ([(str(tmp_path / 'fixture'), COMMIT)] if enabled else [])


def test_installed_git_pack_the_registry_does_not_know_is_checked_out_at_the_pinned_commit(manager, summary, tmp_path):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    subprocess.run(['git', 'remote', 'add', 'origin', REPO_URL], cwd=tmp_path / 'fixture', check=True)
    manager.unknown_active_nodes['fixture'] = (REPO_URL, str(tmp_path / 'fixture'))

    assert summary(**pinned(REPO_URL, commits[0])) == [f'[  CHECKOUT ] fixture@{commits[0]}']
    assert head(tmp_path / 'fixture') == commits[0]


NO_COMMIT = pytest.mark.parametrize('entry', [{'hash': 'unknown', 'disabled': False}, {'disabled': False}], ids=['unknown', 'no hash'])


@NO_COMMIT
def test_pack_without_a_commit_in_the_snapshot_is_left_where_it_is(manager, summary, tmp_path, entry):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    subprocess.run(['git', 'remote', 'add', 'origin', REPO_URL], cwd=tmp_path / 'fixture', check=True)
    manager.unknown_active_nodes['fixture'] = (REPO_URL, str(tmp_path / 'fixture'))

    assert summary(git_custom_nodes={REPO_URL: entry}) == ['[  SKIPPED  ] fixture']
    assert head(tmp_path / 'fixture') == commits[1]


@CLONES
@NO_COMMIT
def test_cloned_pack_without_a_commit_in_the_snapshot_is_installed(core, summary, clones, tmp_path, kind, entry):  # noqa: F811
    ran = []
    clones(kind, lambda path, return_postinstall: core.ManagedResult('install-git').with_postinstall(lambda: ran.append(path) or True))

    assert summary(git_custom_nodes={REPO_URL: entry}) == ['[ INSTALLED ] fixture']
    assert ran == [str(tmp_path / 'fixture')]


@CLONES
@pytest.mark.parametrize('installed, line', [(True, '[ INSTALLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_install_script_of_a_cloned_pack_runs_at_the_pinned_commit(core, summary, clones, tmp_path, kind, installed, line):  # noqa: F811
    commits = repository(tmp_path / 'origin')
    ran_at = []

    def clone(path, return_postinstall):
        subprocess.run(['git', 'clone', '-q', str(tmp_path / 'origin'), path], check=True, capture_output=True)

        def postinstall():
            ran_at.append(head(path))
            return installed

        result = core.ManagedResult('install-git')
        return result.with_postinstall(postinstall) if return_postinstall else (result if postinstall() else result.fail('install script'))

    clones(kind, clone)

    assert summary(**pinned(REPO_URL, commits[0])) == [line]
    assert ran_at == [commits[0]]


@CLONES
def test_install_script_that_raises_is_reported_as_failed_and_the_restore_goes_on(core, manager, summary, clones, monkeypatch, kind):  # noqa: F811
    def clone(path, return_postinstall):
        def postinstall():
            raise subprocess.CalledProcessError(1, ['python', 'install.py'])

        return core.ManagedResult('install-git').with_postinstall(postinstall)

    manager.repo_install = lambda url, path, **options: clone(path, True)
    clones(kind, clone)
    monkeypatch.setattr(core, 'repo_switch_commit', Mock(return_value=True))

    assert summary(git_custom_nodes={REPO_URL: {'hash': COMMIT, 'disabled': False},
                                     REPO_URL + '-other': {'hash': COMMIT, 'disabled': False}}) == ['[  FAILED   ] fixture', '[  FAILED   ] fixture-other']


def test_install_script_of_a_cloned_pack_runs_also_when_the_commit_cannot_be_checked_out(core, manager, summary, tmp_path):  # noqa: F811
    ran = []
    manager.repo_install = lambda url, path, **options: core.ManagedResult('install-git').with_postinstall(lambda: ran.append(path) or True)

    assert summary(**pinned(REPO_URL)) == [f'[  FAILED   ] fixture@{COMMIT}']
    assert ran == [str(tmp_path / 'fixture')]


def test_install_script_of_a_cloned_registry_pack_runs_also_when_the_commit_cannot_be_checked_out(core, manager, summary, tmp_path):  # noqa: F811
    ran = []

    in_registry(manager)
    manager.repo_install = lambda url, path, **options: core.ManagedResult('install-git').with_postinstall(lambda: ran.append(os.path.basename(path)) or True)

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



def test_registry_pack_whose_install_raises_is_reported_as_failed_and_the_restore_goes_on(core, manager, summary):  # noqa: F811
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


def registry_pack(manager, path, name='fixture', url=REPO_URL):  # noqa: F811
    manager.active_nodes[name] = ('1.0.0', str(path / name))


def registry_git_pack(manager, path, name='fixture', url=REPO_URL):  # noqa: F811
    manager.active_nodes[name] = ('nightly', str(path / name))
    manager.repo_cnr_map[url] = {'id': name}


def disabled_registry_git_pack(manager, path, name='fixture', url=REPO_URL):  # noqa: F811
    manager.nightly_inactive_nodes[name] = git_pack(path / '.disabled' / name, url)[1]
    manager.repo_cnr_map[url] = {'id': name}


def unknown_git_pack(manager, path, name='fixture', url=REPO_URL):  # noqa: F811
    manager.unknown_active_nodes[name] = git_pack(path / name, url)


def disabled_unknown_git_pack(manager, path, name='fixture', url=REPO_URL):  # noqa: F811
    manager.unknown_inactive_nodes[name] = git_pack(path / '.disabled' / name, url)


@pytest.mark.parametrize('installed, step, in_snapshot', [
    (registry_pack, 'unified_disable', False),
    (registry_git_pack, 'unified_disable', False),
    (unknown_git_pack, 'unified_disable', False),
    (disabled_registry_git_pack, 'unified_enable', True),
    (disabled_unknown_git_pack, 'unified_enable', True),
])
def test_pack_whose_directory_cannot_be_moved_is_reported_as_failed_and_the_restore_goes_on(manager, summary, tmp_path, installed, step, in_snapshot):  # noqa: F811
    """The second nodepack is the proof that the restore goes on."""
    packs = {'fixture': REPO_URL, 'second': REPO_URL + '-2'}
    for name, url in packs.items():
        installed(manager, tmp_path, name, url)
    setattr(manager, step, Mock(side_effect=PermissionError(13, 'Permission denied')))
    snapshot = {url: {'hash': COMMIT, 'disabled': False} for url in packs.values()} if in_snapshot else {}

    assert summary(git_custom_nodes=snapshot) == ['[  FAILED   ] fixture', '[  FAILED   ] second']
    assert getattr(manager, step).call_count == 2


@pytest.mark.parametrize('installed', [unknown_git_pack, disabled_unknown_git_pack, registry_git_pack, disabled_registry_git_pack])
def test_checkout_that_fails_is_reported_as_failed(manager, summary, tmp_path, installed):  # noqa: F811
    installed(manager, tmp_path)

    assert summary(**pinned(REPO_URL)) == [f'[  FAILED   ] fixture@{COMMIT}']


def test_pack_that_fails_at_two_steps_is_listed_once(core, manager, summary, answer, tmp_path):  # noqa: F811
    manager.active_nodes['fixture'] = ('1.0.0', str(tmp_path / 'fixture'))
    in_registry(manager)
    manager.unified_disable = answer('disable', False)
    manager.repo_install = answer('install-git', False)

    assert summary(cnr_custom_nodes={}, **pinned(REPO_URL)) == ['[  FAILED   ] fixture']


@pytest.mark.parametrize('pinned_at, line', [(0, '[  CHECKOUT ] fixture@{pinned}'), (1, '[  ENABLED  ] fixture')])
def test_registry_git_pack_that_is_enabled_is_listed_once(manager, summary, tmp_path, pinned_at, line):  # noqa: F811
    commits = repository(tmp_path / '.disabled/fixture')
    manager.nightly_inactive_nodes['fixture'] = str(tmp_path / '.disabled/fixture')
    in_registry(manager)

    assert summary(**pinned(REPO_URL, commits[pinned_at])) == [line.format(pinned=commits[0])]
    assert head(tmp_path / 'fixture') == commits[pinned_at]


@pytest.mark.parametrize('pinned_at, line', [(0, '[  CHECKOUT ] fixture@{pinned}'), (1, '[  SKIPPED  ] fixture')])
def test_registry_git_pack_that_is_installed_is_listed_once(manager, summary, tmp_path, pinned_at, line):  # noqa: F811
    commits = repository(tmp_path / 'fixture')
    manager.active_nodes['fixture'] = ('nightly', str(tmp_path / 'fixture'))
    in_registry(manager)

    assert summary(**pinned(REPO_URL, commits[pinned_at])) == [line.format(pinned=commits[0])]
    assert head(tmp_path / 'fixture') == commits[pinned_at]


def packs_that_name(tmp_path, **files):
    for name in ('first', 'second'):
        (tmp_path / name).mkdir()
        for file, text in files.items():
            (tmp_path / name / file).write_text(text)
    return str(tmp_path / 'first'), str(tmp_path / 'second')


@pytest.fixture
def installs(core, monkeypatch):  # noqa: F811
    def installs(*answers):
        answers, ran = list(answers), []

        def try_install_script(url, repo_path, install_cmd, instant_execution=False):
            ran.append(os.path.basename(repo_path) + ' ' + install_cmd[-1])
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
    assert ran == ['first shareddep==1', 'second shareddep==1']


def test_requirement_after_one_that_failed_is_tried_for_the_next_pack(manager, installs, tmp_path):  # noqa: F811
    first, second = packs_that_name(tmp_path, **{'requirements.txt': 'fails==1\nshareddep==1\n'})
    ran = installs(False, True, True)

    assert not manager.execute_install_script(None, first)
    assert manager.execute_install_script(None, second)
    assert ran == ['first fails==1', 'second fails==1', 'second shareddep==1']


def test_requirement_that_was_installed_is_not_installed_twice(manager, installs, tmp_path):  # noqa: F811
    first, second = packs_that_name(tmp_path, **{'requirements.txt': 'shareddep==1\n'})
    ran = installs(True)

    assert manager.execute_install_script(None, first)
    assert manager.execute_install_script(None, second)
    assert ran == ['first shareddep==1']


def test_install_script_that_failed_is_run_when_asked_again(manager, installs, tmp_path):  # noqa: F811
    first, _ = packs_that_name(tmp_path, **{'install.py': ''})
    ran = installs(False, True)

    assert not manager.execute_install_script(None, first)
    assert manager.execute_install_script(None, first)
    assert ran == ['first install.py', 'first install.py']


def test_install_script_not_run_after_a_requirement_failed_is_run_when_asked_again(manager, installs, tmp_path):  # noqa: F811
    first, _ = packs_that_name(tmp_path, **{'requirements.txt': 'fails==1\n', 'install.py': ''})
    ran = installs(False, True, True)

    assert not manager.execute_install_script(None, first)
    assert manager.execute_install_script(None, first)
    assert ran == ['first fails==1', 'first fails==1', 'first install.py']


def test_install_script_of_a_pack_that_is_cloned_where_another_was_installed_is_run(manager, installs, tmp_path, monkeypatch):  # noqa: F811
    first, _ = packs_that_name(tmp_path, **{'install.py': ''})
    ran = installs(True, True)
    assert manager.execute_install_script(None, first)
    os.rename(first, tmp_path / '.disabled')
    origin = tmp_path / 'origin'
    origin.mkdir()
    (origin / 'install.py').write_text('')
    for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '-q', '-m', 'a pack']):
        subprocess.run(['git', *args], cwd=origin, check=True, capture_output=True)
    for name, value in {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': f'url.{origin}.insteadOf', 'GIT_CONFIG_VALUE_0': REPO_URL}.items():
        monkeypatch.setenv(name, value)

    assert manager.repo_install(REPO_URL, first, instant_execution=True).result
    assert ran == ['first install.py', 'first install.py']


@pytest.mark.parametrize('cloned', [True, False])
def test_restore_tells_whether_every_step_was_done(core, manager, answer, tmp_path, monkeypatch, cloned):  # noqa: F811
    manager.repo_install = answer('install-git', cloned)
    monkeypatch.setattr(core, 'repo_switch_commit', Mock(return_value=True))

    assert restore(core, tmp_path, **pinned(REPO_URL)) is cloned


@pytest.mark.parametrize('not_installed, restored', [([], True), (['alpha==1.0'], False)])
def test_restore_tells_whether_every_pip_package_was_installed(core, manager, tmp_path, monkeypatch, not_installed, restored):  # noqa: F811
    monkeypatch.setattr(core.manager_util, 'restore_pip_snapshot', Mock(return_value=not_installed))

    assert restore(core, tmp_path) is restored


class Exit(Exception):
    def __init__(self, code=0):
        self.code = code


@pytest.mark.parametrize('restored, code', [(True, None), (False, 1)])
def test_cm_cli_ends_with_1_when_a_step_of_the_restore_failed(tmp_path, restored, code):
    command = next(node for node in ast.parse(CM_CLI.read_text(encoding='utf-8')).body
                   if isinstance(node, ast.FunctionDef) and node.name == 'restore_snapshot')
    command.decorator_list = []
    finalize = Mock()
    scope = {'typer': SimpleNamespace(Option=Mock(), Exit=Exit), 'Optional': Optional, 'Annotated': Annotated, 'os': os, 'asyncio': asyncio,
             'traceback': traceback, 'cmd_ctx': Mock(), 'comfy_path': '', 'context': Mock(), '_finalize_resolve': finalize,
             'manager_util': SimpleNamespace(PIPFixer=Mock(), get_installed_packages=Mock()),
             'core': SimpleNamespace(restore_snapshot=AsyncMock(return_value=restored))}
    exec(compile(ast.Module(body=[command], type_ignores=[]), str(CM_CLI), 'exec'), scope)
    snapshot = tmp_path / 'snapshot.json'
    snapshot.touch()

    ended = None
    try:
        scope['restore_snapshot'](str(snapshot), **{arg.arg: None for arg in command.args.args[1:]})
    except Exit as e:
        ended = e.code

    assert ended == code
    finalize.assert_called_once()
