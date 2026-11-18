import ast
import asyncio
import os
import pathlib
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
        if kind == 'url':
            manager.repo_install = lambda url, path, return_postinstall=False, **options: clone(path, return_postinstall)
            return

        async def install(pack_id, version_spec, return_postinstall=False, **options):
            manager.active_nodes[pack_id] = (version_spec, str(tmp_path / pack_id))
            return clone(str(tmp_path / pack_id), return_postinstall)

        in_registry(manager)
        manager.install_by_id = AsyncMock(side_effect=install)

    return clones


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

    async def install(pack_id, version_spec, **options):
        return core.ManagedResult('install-git').fail('failed')

    manager.install_by_id = install

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
