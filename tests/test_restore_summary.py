import ast
import asyncio
import os
import pathlib
import traceback
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, Mock

import pytest

from test_snapshot_restore_pins import run

CM_CLI = pathlib.Path(__file__).resolve().parent.parent / 'cm-cli.py'

URL = 'https://github.com/owner/fixture'
HASH = '0123456789abcdef0123456789abcdef01234567'
SUMMARY = '''
import contextlib, io, logging, os, shutil
from types import SimpleNamespace

URL = 'https://github.com/owner/fixture'
HASH = '0123456789abcdef0123456789abcdef01234567'

def summary(**snapshot):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        restore(**snapshot)
    return [line.strip() for line in out.getvalue().splitlines() if line.startswith('[ ')]

def errors(**snapshot):
    seen = []
    handler = logging.Handler(logging.ERROR)
    handler.emit = lambda record: seen.append(record.getMessage())
    logging.getLogger().addHandler(handler)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        restore(**snapshot)
    return seen

def pinned(url):
    return {'git_custom_nodes': {url: {'hash': HASH, 'disabled': False}}}

def git_pack(name, url):
    path = nodes / name
    (path / '.git').mkdir(parents=True)
    (path / '.git/config').write_text('[remote "origin"]\\n\\turl = %s\\n' % url)
    return url, str(path)

def in_registry():
    manager.repo_cnr_map[URL] = {'id': 'fixture'}
    manager.get_custom_nodes.return_value = {'fixture': {'repository': URL}}

def clones(kind, clone):
    if kind == 'registry':
        in_registry()
    manager.repo_install = lambda url, path, return_postinstall=False, **options: clone(path, return_postinstall)

def steps():
    done = []
    manager.unified_disable = lambda name, is_unknown: done.append('disable ' + name) or core.ManagedResult('disable')
    manager.unified_enable = lambda name, version: done.append('enable %s@%s' % (name, version)) or core.ManagedResult('enable')
    manager.repo_install = lambda url, path, **options: done.append('clone %s into %s' % (url, os.path.basename(path))) or core.ManagedResult('install-git')
    manager._cnr_install = lambda name, version, *args: done.append('install %s@%s' % (name, version.version)) or core.ManagedResult('install-cnr')
    cnr_utils.install_node = lambda name, version: SimpleNamespace(version=version, download_url='https://registry.invalid/' + name, status='NodeVersionStatusActive')
    core.repo_switch_commit = Mock(return_value=True)
    return done

def answer(action, ok):
    result = core.ManagedResult(action)
    return Mock(return_value=result if ok else result.fail('failed'))

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

def head(path):
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=path, check=True, capture_output=True, text=True).stdout.strip()
'''


def lines(body):
    return run(SUMMARY + body + '\nprint(json.dumps(result))\n')


CLONES = pytest.mark.parametrize('kind', ['registry', 'url'])


@pytest.mark.parametrize('cloned, line', [(True, '[ INSTALLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_clone_follows_its_result(cloned, line):
    assert lines(f'''
manager.repo_install = answer('install-git', {cloned})
core.repo_switch_commit = Mock(return_value=True)
result = summary(**pinned('{URL}.git')) + [manager.repo_install.call_args.args[1] == str(nodes / 'fixture')]
''') == [line, True]


def test_url_that_is_not_cloned_is_reported_as_failed():
    assert lines('''
result = summary(**pinned('/home/someone/repos/fixture')) + [(nodes / 'fixture').exists()]
''') == ['[  FAILED   ] fixture', False]


def test_pack_of_the_registry_that_the_node_list_does_not_have_is_cloned():
    assert lines(f'''
manager.repo_cnr_map['{URL}'] = {{'id': 'fixture-of-the-registry'}}
done = steps()
result = summary(**pinned('{URL}.git')) + [done]
''') == ['[ INSTALLED ] fixture-of-the-registry', [f'clone {URL} into fixture-of-the-registry']]


def test_pack_of_the_registry_is_cloned_from_the_url_of_the_snapshot_when_the_node_list_has_another_one_under_its_name():
    assert lines(f'''
manager.repo_cnr_map['{URL}'] = {{'id': 'fixture'}}
manager.get_custom_nodes.return_value = {{'fixture': {{'repository': 'https://github.com/another-owner/fixture'}}}}
done = steps()
result = summary(**pinned('{URL}')) + [done]
''') == ['[ INSTALLED ] fixture', [f'clone {URL} into fixture']]


@pytest.mark.parametrize('in_node_list', [True, False])
def test_enabled_version_of_the_registry_is_disabled_before_the_clone_of_a_snapshot_that_names_no_version(in_node_list):
    """A snapshot from before the registry has no `cnr_custom_nodes`, so nothing else disables that version."""
    assert lines(f'''
manager.repo_cnr_map['{URL}'] = {{'id': 'fixture'}}
manager.get_custom_nodes.return_value = {{'fixture': {{'repository': '{URL}'}}}} if {in_node_list} else {{}}
manager.active_nodes['fixture'] = ('1.0.0', str(nodes / 'fixture'))
done = steps()
result = summary(cnr_custom_nodes=None, **pinned('{URL}')) + [done]
''') == ['[ INSTALLED ] fixture', ['disable fixture', f'clone {URL} into fixture']]


@pytest.mark.parametrize('machine, state', [
    ('that saved it', ['[  SKIPPED  ] fixture', []]),
    ('with no node pack', ['[ INSTALLED ] fixture@1.0.0', ['install fixture@1.0.0']]),
], ids=['that saved it', 'with no node pack'])
def test_pack_saved_at_a_version_of_the_registry_with_its_clone_disabled_is_restored_at_that_version(machine, state):
    """A switch from the clone to a version of the registry keeps the clone, disabled, and a snapshot saves both."""
    assert lines(f'''
manager.repo_cnr_map[URL] = manager.cnr_map['fixture'] = {{'id': 'fixture', 'repository': URL, 'publisher': {{'name': 'owner'}}}}
version, clone = nodes / 'fixture', nodes / '.disabled/fixture@nightly'
version.mkdir()
(version / '.tracking').write_text('')
(version / 'pyproject.toml').write_text('[project]\\nname = "fixture"\\nversion = "1.0.0"\\n')
repository(clone)
subprocess.run(['git', 'remote', 'add', 'origin', URL + '.git'], cwd=clone, check=True)
core.get_custom_nodes_paths = lambda: [str(nodes)]
saved = asyncio.run(core.get_current_snapshot(custom_nodes_only=True))
if '{machine}' == 'that saved it':
    manager.active_nodes['fixture'] = ('1.0.0', str(version))
    manager.nightly_inactive_nodes['fixture'] = str(clone)
else:
    shutil.rmtree(version)
    shutil.rmtree(clone)
done = steps()
result = summary(cnr_custom_nodes=saved['cnr_custom_nodes'], git_custom_nodes=saved['git_custom_nodes']) + [done]
''') == state


def test_clone_that_is_enabled_is_left_to_the_install_of_the_version_that_the_snapshot_names():
    assert lines('''
manager.repo_cnr_map[URL] = {'id': 'fixture'}
manager.active_nodes['fixture'] = ('nightly', str(nodes / 'fixture'))
done = steps()
result = summary(cnr_custom_nodes={'fixture': '1.0.0'}, git_custom_nodes={URL: {'hash': HASH, 'disabled': True}}) + [done]
''') == ['[ INSTALLED ] fixture@1.0.0', ['disable fixture', 'install fixture@1.0.0']]


@pytest.mark.parametrize('failure, state', [
    ('cnr_utils.install_node = lambda name, version: None', [f'[  CHECKOUT ] fixture@{HASH}', '[  FAILED   ] fixture@1.0.0', []]),
    ("manager._cnr_install = lambda name, version, *args: core.ManagedResult('install-cnr').fail('the download failed')",
     [f'[  CHECKOUT ] fixture@{HASH}', '[  FAILED   ] fixture@1.0.0', ['disable fixture', 'enable fixture@nightly']]),
    ("manager.cnr_inactive_nodes['fixture'] = {'2.0.0': str(nodes / '.disabled/fixture@2_0_0')}; "
     "manager._cnr_switch_version = lambda name, version, *args: core.ManagedResult('switch-cnr').fail('the download failed')",
     [f'[  CHECKOUT ] fixture@{HASH}', '[  FAILED   ] fixture@1.0.0', ['disable fixture', 'enable fixture@cnr', 'enable fixture@nightly']]),
], ids=['the registry does not have it', 'its download fails', 'its download fails after another version was enabled'])
def test_clone_of_the_snapshot_is_restored_when_the_version_that_the_snapshot_names_cannot_be_installed(failure, state):
    assert lines(f'''
manager.repo_cnr_map[URL] = {{'id': 'fixture'}}
manager.active_nodes['fixture'] = ('nightly', str(nodes / 'fixture'))
done = steps()
def disable(name, is_unknown):
    done.append('disable ' + name)
    manager.nightly_inactive_nodes[name] = manager.active_nodes.pop(name)[1]
    return core.ManagedResult('disable')
def enable(name, version):
    done.append('enable %s@%s' % (name, version))
    if version == 'cnr':
        manager.active_nodes[name] = ('2.0.0', manager.cnr_inactive_nodes[name].pop('2.0.0'))
    return core.ManagedResult('enable').with_target(str(nodes / name))
manager.unified_disable, manager.unified_enable = disable, enable
{failure}
result = summary(cnr_custom_nodes={{'fixture': '1.0.0'}}, git_custom_nodes={{URL: {{'hash': HASH, 'disabled': True}}}}) + [done]
result += [[x.args for x in core.repo_switch_commit.call_args_list] == [(str(nodes / 'fixture'), HASH)]]
''') == state + [True]


def test_pack_of_the_registry_with_the_name_of_the_manager_in_its_id_is_not_cloned():
    assert lines(f'''
manager.repo_cnr_map['{URL}'] = {{'id': 'comfyui-manager-fixture'}}
done = steps()
result = summary(**pinned('{URL}')) + [done]
''') == ['[  SKIPPED  ] comfyui-manager-fixture', []]


@CLONES
def test_clone_that_is_refused_tells_why(kind):
    assert lines(f'''
clones('{kind}', lambda path, return_postinstall: core.ManagedResult('install-git').fail('the clone was refused'))
result = errors(**pinned('{URL}'))
''') == ['the clone was refused']


def test_url_that_is_not_cloned_tells_why():
    assert lines('''
result = errors(**pinned('/home/someone/repos/fixture'))
''') == ['Invalid git url: /home/someone/repos/fixture']


def test_clone_of_a_pack_of_the_registry_that_raises_is_logged_once():
    assert lines(f'''
in_registry()
manager.repo_install = Mock(side_effect=RuntimeError('the disk is full'))
result = errors(**pinned('{URL}'))
''') == ['[ComfyUI-Manager] the disk is full']


def test_url_that_cannot_be_parsed_is_reported_as_failed_and_the_restore_goes_on():
    assert lines('''
entry = {'hash': HASH, 'disabled': False}
result = summary(git_custom_nodes={'https://[not-a-host/first': dict(entry), '/home/someone/repos/second': dict(entry)})
''') == ['[  FAILED   ] first', '[  FAILED   ] second']


def test_cloned_pack_is_checked_out_at_the_pinned_commit():
    assert lines(f'''
commits = repository(pathlib.Path(tmp) / 'origin')
def clone(url, path, **options):
    subprocess.run(['git', 'clone', '-q', str(pathlib.Path(tmp) / 'origin'), path], check=True, capture_output=True)
    return core.ManagedResult('install-git')
manager.repo_install = clone
result = summary(git_custom_nodes={{'{URL}': {{'hash': commits[0], 'disabled': False}}}})
result += [head(nodes / 'fixture') == commits[0], (nodes / 'fixture/__init__.py').read_text()]
''') == ['[ INSTALLED ] fixture', True, 'VERSION = 1']


def test_cloned_registry_pack_is_checked_out_at_the_pinned_commit():
    assert lines(f'''
commits = repository(pathlib.Path(tmp) / 'origin')
def clone(url, path, **options):
    subprocess.run(['git', 'clone', '-q', str(pathlib.Path(tmp) / 'origin'), path], check=True, capture_output=True)
    return core.ManagedResult('install-git')
in_registry()
manager.repo_install = clone
result = summary(git_custom_nodes={{'{URL}': {{'hash': commits[0], 'disabled': False}}}})
result += [head(nodes / 'fixture') == commits[0]]
''') == ['[ INSTALLED ] fixture', True]


def test_cloned_pack_that_cannot_be_checked_out_is_reported_as_failed():
    assert lines(f'''
manager.repo_install = answer('install-git', True)
result = summary(**pinned('{URL}'))
''') == [f'[  FAILED   ] fixture@{HASH}']


@pytest.mark.parametrize('disabled, line', [(True, '[  DISABLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_disabling_a_git_pack_that_is_not_in_the_snapshot_follows_its_result(disabled, line):
    assert lines(f'''
manager.unknown_active_nodes['fixture'] = git_pack('fixture', '{URL}')
manager.unified_disable = answer('disable', {disabled})
result = summary()
''') == [line]


@pytest.mark.parametrize('disabled, line', [(True, '[  DISABLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_disabling_a_registry_pack_that_is_not_in_the_snapshot_follows_its_result(disabled, line):
    assert lines(f'''
manager.active_nodes['fixture'] = ('1.0.0', str(nodes / 'fixture'))
manager.unified_disable = answer('disable', {disabled})
result = summary()
''') == [line]


@pytest.mark.parametrize('name', ['ComfyUI-Manager', 'comfyui-manager'])
def test_the_manager_itself_is_not_listed(name):
    assert lines(f'''
manager.unknown_active_nodes['{name}'] = git_pack('{name}', 'https://github.com/ltdrdata/ComfyUI-Manager')
manager.unified_disable = answer('disable', True)
result = summary() + [manager.unified_disable.call_count]
''') == [0]


@pytest.mark.parametrize('enabled, line', [(True, '[  ENABLED  ] fixture'), (False, '[  FAILED   ] fixture')])
def test_enabling_a_git_pack_of_the_snapshot_follows_its_result(enabled, line):
    assert lines(f'''
manager.unknown_inactive_nodes['fixture'] = git_pack('.disabled/fixture', '{URL}')
manager.unified_enable = answer('enable', {enabled})
manager.unified_enable.return_value.target = str(nodes / 'fixture') if {enabled} else None
core.repo_switch_commit = Mock(return_value=False)
result = summary(**pinned('{URL}')) + [[x.args for x in core.repo_switch_commit.call_args_list] == ([(str(nodes / 'fixture'), HASH)] if {enabled} else [])]
''') == [line, True]


def test_installed_git_pack_the_registry_does_not_know_is_checked_out_at_the_pinned_commit():
    assert lines(f'''
commits = repository(nodes / 'fixture')
subprocess.run(['git', 'remote', 'add', 'origin', '{URL}'], cwd=nodes / 'fixture', check=True)
manager.unknown_active_nodes['fixture'] = ('{URL}', str(nodes / 'fixture'))
result = summary(git_custom_nodes={{'{URL}': {{'hash': commits[0], 'disabled': False}}}})
result = [line.replace(commits[0], 'PINNED') for line in result] + [head(nodes / 'fixture') == commits[0]]
''') == ['[  CHECKOUT ] fixture@PINNED', True]


@pytest.mark.parametrize('installed', ['unknown_git_pack', 'disabled_unknown_git_pack', 'registry_git_pack', 'disabled_registry_git_pack'])
def test_checkout_that_fails_is_reported_as_failed(installed):
    assert lines(f'''
name, url = 'fixture', URL
{MOVED[installed][0]}
result = summary(**pinned(URL))
''') == [f'[  FAILED   ] fixture@{HASH}']


NO_COMMIT = pytest.mark.parametrize('entry', [{'hash': 'unknown', 'disabled': False}, {'disabled': False}], ids=['unknown', 'no hash'])


@NO_COMMIT
def test_pack_without_a_commit_in_the_snapshot_is_left_where_it_is(entry):
    assert lines(f'''
commits = repository(nodes / 'fixture')
subprocess.run(['git', 'remote', 'add', 'origin', '{URL}'], cwd=nodes / 'fixture', check=True)
manager.unknown_active_nodes['fixture'] = ('{URL}', str(nodes / 'fixture'))
result = summary(git_custom_nodes={{'{URL}': {entry!r}}}) + [head(nodes / 'fixture') == commits[1]]
''') == ['[  SKIPPED  ] fixture', True]


@CLONES
@NO_COMMIT
def test_cloned_pack_without_a_commit_in_the_snapshot_is_installed(kind, entry):
    assert lines(f'''
ran = []
clones('{kind}', lambda path, return_postinstall: core.ManagedResult('install-git').with_postinstall(lambda: ran.append(path) or True))
result = summary(git_custom_nodes={{'{URL}': {entry!r}}}) + [ran == [str(nodes / 'fixture')]]
''') == ['[ INSTALLED ] fixture', True]


@CLONES
@pytest.mark.parametrize('installed, line', [(True, '[ INSTALLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_install_script_of_a_cloned_pack_runs_at_the_pinned_commit(kind, installed, line):
    assert lines(f'''
commits = repository(pathlib.Path(tmp) / 'origin')
ran_at = []
def clone(path, return_postinstall):
    subprocess.run(['git', 'clone', '-q', str(pathlib.Path(tmp) / 'origin'), path], check=True, capture_output=True)
    def postinstall():
        ran_at.append(head(path))
        return {installed}
    result = core.ManagedResult('install-git')
    return result.with_postinstall(postinstall) if return_postinstall else (result if postinstall() else result.fail('install script'))
clones('{kind}', clone)
result = summary(git_custom_nodes={{'{URL}': {{'hash': commits[0], 'disabled': False}}}}) + [ran_at == [commits[0]]]
''') == [line, True]


@CLONES
def test_install_script_that_raises_is_reported_as_failed_and_the_restore_goes_on(kind):
    assert lines(f'''
def clone(path, return_postinstall):
    def postinstall():
        raise subprocess.CalledProcessError(1, ['python', 'install.py'])
    return core.ManagedResult('install-git').with_postinstall(postinstall)
manager.repo_install = lambda url, path, **options: clone(path, True)
clones('{kind}', clone)
core.repo_switch_commit = Mock(return_value=True)
result = summary(git_custom_nodes={{'{URL}': {{'hash': HASH, 'disabled': False}}, '{URL}-other': {{'hash': HASH, 'disabled': False}}}})
''') == ['[  FAILED   ] fixture', '[  FAILED   ] fixture-other']


def test_install_script_of_a_cloned_pack_runs_also_when_the_commit_cannot_be_checked_out():
    assert lines(f'''
ran = []
manager.repo_install = lambda url, path, **options: core.ManagedResult('install-git').with_postinstall(lambda: ran.append(path) or True)
result = summary(**pinned('{URL}')) + [ran == [str(nodes / 'fixture')]]
''') == [f'[  FAILED   ] fixture@{HASH}', True]


def test_install_script_of_a_cloned_registry_pack_runs_also_when_the_commit_cannot_be_checked_out():
    assert lines(f'''
ran = []
in_registry()
manager.repo_install = lambda url, path, **options: core.ManagedResult('install-git').with_postinstall(lambda: ran.append(os.path.basename(path)) or True)
result = summary(**pinned('{URL}')) + [ran]
''') == [f'[  FAILED   ] fixture@{HASH}', ['fixture']]


@pytest.mark.parametrize('outcome, line', [('return True', '[ INSTALLED ] fixture@1.0.0'), ('return False', '[  FAILED   ] fixture@1.0.0'),
                                           ("raise subprocess.CalledProcessError(1, ['python', 'install.py'])", '[  FAILED   ] fixture@1.0.0')])
def test_install_script_of_a_registry_pack_is_run(outcome, line):
    assert lines(f'''
ran = []
def postinstall():
    ran.append('fixture')
    {outcome}
async def install(pack_id, **options):
    ran.append(options['return_postinstall'])
    return core.ManagedResult('install-cnr').with_postinstall(postinstall)
manager.install_by_id = install
result = summary(cnr_custom_nodes={{'fixture': '1.0.0'}}) + [ran]
''') == [line, [True, 'fixture']]



def test_registry_pack_whose_install_raises_is_reported_as_failed_and_the_restore_goes_on():
    assert lines('''
async def install(pack_id, **options):
    if pack_id == 'fixture':
        raise ConnectionError('the registry cannot be reached')
    return core.ManagedResult('install-cnr')
manager.install_by_id = install
result = summary(cnr_custom_nodes={'fixture': '1.0.0', 'other': '1.0.0'})
''') == ['[ INSTALLED ] other@1.0.0', '[  FAILED   ] fixture@1.0.0']


def test_registry_pack_whose_switch_raises_is_reported_as_failed_and_the_restore_goes_on():
    assert lines('''
async def install(pack_id, **options):
    return core.ManagedResult('install-cnr')
manager.active_nodes['fixture'] = ('1.0.0', str(nodes / 'fixture'))
manager.cnr_switch_version = Mock(side_effect=ConnectionError('the registry cannot be reached'))
manager.install_by_id = install
result = summary(cnr_custom_nodes={'fixture': '2.0.0', 'other': '1.0.0'})
''') == ['[ INSTALLED ] other@1.0.0', '[  FAILED   ] fixture@2.0.0']


MOVED = {
    'registry_pack': ("manager.active_nodes[name] = ('1.0.0', str(nodes / name))", 'unified_disable', False),
    'registry_git_pack': ("manager.active_nodes[name] = ('nightly', str(nodes / name)); manager.repo_cnr_map[url] = {'id': name}", 'unified_disable', False),
    'unknown_git_pack': ("manager.unknown_active_nodes[name] = git_pack(name, url)", 'unified_disable', False),
    'disabled_registry_git_pack': ("manager.nightly_inactive_nodes[name] = git_pack('.disabled/' + name, url)[1]; manager.repo_cnr_map[url] = {'id': name}", 'unified_enable', True),
    'disabled_unknown_git_pack': ("manager.unknown_inactive_nodes[name] = git_pack('.disabled/' + name, url)", 'unified_enable', True),
}


@pytest.mark.parametrize('installed', MOVED)
def test_pack_whose_directory_cannot_be_moved_is_reported_as_failed_and_the_restore_goes_on(installed):
    """The second node pack is the proof that the restore goes on."""
    arrange, step, in_snapshot = MOVED[installed]
    assert lines(f'''
packs = {{'fixture': URL, 'second': URL + '-2'}}
for name, url in packs.items():
    {arrange}
manager.{step} = Mock(side_effect=PermissionError(13, 'Permission denied'))
snapshot = {{url: {{'hash': HASH, 'disabled': False}} for url in packs.values()}} if {in_snapshot} else {{}}
result = summary(git_custom_nodes=snapshot) + [manager.{step}.call_count]
''') == ['[  FAILED   ] fixture', '[  FAILED   ] second', 2]


def test_pack_that_fails_at_two_steps_is_listed_once():
    assert lines(f'''
manager.active_nodes['fixture'] = ('1.0.0', str(nodes / 'fixture'))
in_registry()
manager.unified_disable = answer('disable', False)
manager.repo_install = answer('install-git', False)
result = summary(cnr_custom_nodes={{}}, **pinned('{URL}'))
''') == ['[  FAILED   ] fixture']


@pytest.mark.parametrize('pinned_at, line', [(0, '[  CHECKOUT ] fixture@PINNED'), (1, '[  ENABLED  ] fixture')])
def test_registry_git_pack_that_is_enabled_is_listed_once(pinned_at, line):
    assert lines(f'''
commits = repository(nodes / '.disabled/fixture')
manager.nightly_inactive_nodes['fixture'] = str(nodes / '.disabled/fixture')
in_registry()
result = summary(git_custom_nodes={{'{URL}': {{'hash': commits[{pinned_at}], 'disabled': False}}}})
result = [line.replace(commits[0], 'PINNED') for line in result] + [head(nodes / 'fixture') == commits[{pinned_at}]]
''') == [line, True]


@pytest.mark.parametrize('pinned_at, line', [(0, '[  CHECKOUT ] fixture@PINNED'), (1, '[  SKIPPED  ] fixture')])
def test_registry_git_pack_that_is_installed_is_listed_once(pinned_at, line):
    assert lines(f'''
commits = repository(nodes / 'fixture')
manager.active_nodes['fixture'] = ('nightly', str(nodes / 'fixture'))
in_registry()
result = summary(git_custom_nodes={{'{URL}': {{'hash': commits[{pinned_at}], 'disabled': False}}}})
result = [line.replace(commits[0], 'PINNED') for line in result] + [head(nodes / 'fixture') == commits[{pinned_at}]]
''') == [line, True]


INSTALLS = '''
import os

def packs(**files):
    for name in ('first', 'second'):
        (nodes / name).mkdir()
        for file, text in files.items():
            (nodes / name / file).write_text(text)
    return str(nodes / 'first'), str(nodes / 'second')

def installs(*answers):
    answers, ran = list(answers), []

    def try_install_script(url, repo_path, install_cmd, instant_execution=False):
        ran.append(os.path.basename(repo_path) + ' ' + install_cmd[-1])
        return answers.pop(0)

    core.try_install_script = try_install_script
    core.remap_pip_package = lambda package: package
    manager_util.PIPFixer = Mock()
    manager_util.get_installed_packages = Mock(return_value={})
    return ran
'''


def install_steps(body):
    return lines(INSTALLS + body)


def test_requirement_that_was_not_installed_is_tried_for_the_next_pack():
    assert install_steps('''
first, second = packs(**{'requirements.txt': 'shareddep==1\\n'})
ran = installs(False, True)
result = [manager.execute_install_script(None, first), manager.execute_install_script(None, second), ran]
''') == [False, True, ['first shareddep==1', 'second shareddep==1']]


def test_requirement_after_one_that_failed_is_tried_for_the_next_pack():
    assert install_steps('''
first, second = packs(**{'requirements.txt': 'fails==1\\nshareddep==1\\n'})
ran = installs(False, True, True)
result = [manager.execute_install_script(None, first), manager.execute_install_script(None, second), ran]
''') == [False, True, ['first fails==1', 'second fails==1', 'second shareddep==1']]


def test_requirement_that_was_installed_is_not_installed_twice():
    assert install_steps('''
first, second = packs(**{'requirements.txt': 'shareddep==1\\n'})
ran = installs(True)
result = [manager.execute_install_script(None, first), manager.execute_install_script(None, second), ran]
''') == [True, True, ['first shareddep==1']]


def test_install_script_that_failed_is_run_when_asked_again():
    assert install_steps('''
first, _ = packs(**{'install.py': ''})
ran = installs(False, True)
result = [manager.execute_install_script(None, first), manager.execute_install_script(None, first), ran]
''') == [False, True, ['first install.py', 'first install.py']]


def test_install_script_not_run_after_a_requirement_failed_is_run_when_asked_again():
    assert install_steps('''
first, _ = packs(**{'requirements.txt': 'fails==1\\n', 'install.py': ''})
ran = installs(False, True, True)
result = [manager.execute_install_script(None, first), manager.execute_install_script(None, first), ran]
''') == [False, True, ['first fails==1', 'first fails==1', 'first install.py']]


def test_install_script_of_a_pack_that_is_cloned_where_another_was_installed_is_run():
    assert install_steps(f'''
first, _ = packs(**{{'install.py': ''}})
ran = installs(True, True)
manager.execute_install_script(None, first)
os.rename(first, nodes / '.disabled')

def clone(url, path, **options):
    os.mkdir(path)
    open(os.path.join(path, 'install.py'), 'w').close()
    return Mock()

core.git.Repo.clone_from = clone
result = [manager.repo_install('{URL}', first, instant_execution=True).result, ran]
''') == [True, ['first install.py', 'first install.py']]


@pytest.mark.parametrize('cloned', [True, False])
def test_restore_tells_whether_every_step_was_done(cloned):
    assert lines(f'''
manager.repo_install = answer('install-git', {cloned})
core.repo_switch_commit = Mock(return_value=True)
with contextlib.redirect_stdout(io.StringIO()):
    result = restore(**pinned('{URL}'))
''') is cloned


@pytest.mark.parametrize('not_installed, restored', [([], True), (['alpha==1.0'], False)])
def test_restore_tells_whether_every_pip_package_was_installed(not_installed, restored):
    assert lines(f'''
manager_util.restore_pip_snapshot = Mock(return_value={not_installed})
with contextlib.redirect_stdout(io.StringIO()):
    result = restore()
''') is restored


class Exit(Exception):
    def __init__(self, code=0):
        self.code = code


@pytest.mark.parametrize('restored, code', [(True, None), (False, 1)])
def test_cm_cli_ends_with_1_when_a_step_of_the_restore_failed(tmp_path, restored, code):
    command = next(node for node in ast.parse(CM_CLI.read_text(encoding='utf-8')).body
                   if isinstance(node, ast.FunctionDef) and node.name == 'restore_snapshot')
    command.decorator_list = []
    fixer = Mock()
    scope = {'typer': SimpleNamespace(Option=Mock(), Exit=Exit), 'Optional': Optional, 'os': os, 'asyncio': asyncio, 'traceback': traceback,
             'cmd_ctx': Mock(), 'comfy_path': '', 'manager_util': SimpleNamespace(PIPFixer=Mock(return_value=fixer), get_installed_packages=Mock()),
             'core': SimpleNamespace(restore_snapshot=AsyncMock(return_value=restored), manager_files_path='')}
    exec(compile(ast.Module(body=[command], type_ignores=[]), str(CM_CLI), 'exec'), scope)
    snapshot = tmp_path / 'snapshot.json'
    snapshot.touch()

    ended = None
    try:
        scope['restore_snapshot'](str(snapshot), None, None, None, None, None)
    except Exit as e:
        ended = e.code

    assert ended == code
    fixer.fix_broken.assert_called_once()
