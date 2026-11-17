"""The summary of a snapshot restore lists a step that failed as failed.

The restore runs in the isolated child of tests/test_install_flags_config.py, against the
real glob/manager_core. What the restore asks the manager to do is replaced, and answers
with a success or a failure.
"""

import subprocess

import pytest

from test_snapshot_restore_pins import run

URL = 'https://github.com/owner/fixture'
HASH = '0123456789abcdef0123456789abcdef01234567'
SUMMARY = '''
import contextlib, io

HASH = '0123456789abcdef0123456789abcdef01234567'

def summary(**snapshot):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        restore(**snapshot)
    return [line.strip() for line in out.getvalue().splitlines() if line.startswith('[ ')]

def pinned(url):
    return {'git_custom_nodes': {url: {'hash': HASH, 'disabled': False}}}

def git_pack(name, url):
    """A directory whose .git/config names `url`, as a git node pack the registry does not know."""
    path = nodes / name
    (path / '.git').mkdir(parents=True)
    (path / '.git/config').write_text('[remote "origin"]\\n\\turl = %s\\n' % url)
    return url, str(path)

def answer(action, ok):
    result = core.ManagedResult(action)
    return Mock(return_value=result if ok else result.fail('failed'))

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

def head(path):
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=path, check=True, capture_output=True, text=True).stdout.strip()
'''


def lines(body):
    return run(SUMMARY + body + '\nprint(json.dumps(result))\n')


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
async def install(pack_id, version_spec, **options):
    subprocess.run(['git', 'clone', '-q', str(pathlib.Path(tmp) / 'origin'), nodes / pack_id], check=True, capture_output=True)
    manager.active_nodes[pack_id] = (version_spec, str(nodes / pack_id))
    return core.ManagedResult('install-git')
manager.repo_cnr_map['{URL}'] = {{'id': 'fixture'}}
manager.install_by_id = install
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
result = summary(**pinned('{URL}'))
''') == [line]


def test_installed_git_pack_the_registry_does_not_know_is_checked_out_at_the_pinned_commit():
    assert lines(f'''
commits = repository(nodes / 'fixture')
subprocess.run(['git', 'remote', 'add', 'origin', '{URL}'], cwd=nodes / 'fixture', check=True)
manager.unknown_active_nodes['fixture'] = ('{URL}', str(nodes / 'fixture'))
result = summary(git_custom_nodes={{'{URL}': {{'hash': commits[0], 'disabled': False}}}})
result = [line.replace(commits[0], 'PINNED') for line in result] + [head(nodes / 'fixture') == commits[0]]
''') == ['[  CHECKOUT ] fixture@PINNED', True]


def test_checkout_that_fails_is_reported_as_failed():
    assert lines(f'''
manager.unknown_active_nodes['fixture'] = git_pack('fixture', '{URL}')
result = summary(**pinned('{URL}'))
''') == [f'[  FAILED   ] fixture@{HASH}']


def test_pack_without_a_commit_in_the_snapshot_is_left_where_it_is():
    assert lines(f'''
commits = repository(nodes / 'fixture')
subprocess.run(['git', 'remote', 'add', 'origin', '{URL}'], cwd=nodes / 'fixture', check=True)
manager.unknown_active_nodes['fixture'] = ('{URL}', str(nodes / 'fixture'))
result = summary(git_custom_nodes={{'{URL}': {{'hash': 'unknown', 'disabled': False}}}}) + [head(nodes / 'fixture') == commits[1]]
''') == ['[  SKIPPED  ] fixture', True]


def test_cloned_pack_without_a_commit_in_the_snapshot_is_installed():
    assert lines(f'''
manager.repo_install = answer('install-git', True)
result = summary(git_custom_nodes={{'{URL}': {{'hash': 'unknown', 'disabled': False}}}})
''') == ['[ INSTALLED ] fixture']


@pytest.mark.parametrize('installed, line', [(True, '[ INSTALLED ] fixture'), (False, '[  FAILED   ] fixture')])
def test_install_script_of_a_cloned_pack_runs_at_the_pinned_commit(installed, line):
    assert lines(f'''
commits = repository(pathlib.Path(tmp) / 'origin')
ran_at = []
def clone(url, path, return_postinstall=False, **options):
    subprocess.run(['git', 'clone', '-q', str(pathlib.Path(tmp) / 'origin'), path], check=True, capture_output=True)
    def postinstall():
        ran_at.append(head(path))
        return {installed}
    result = core.ManagedResult('install-git')
    return result.with_postinstall(postinstall) if return_postinstall else (result if postinstall() else result.fail('install script'))
manager.repo_install = clone
result = summary(git_custom_nodes={{'{URL}': {{'hash': commits[0], 'disabled': False}}}}) + [ran_at == [commits[0]]]
''') == [line, True]


def test_install_script_that_raises_is_reported_as_failed_and_the_restore_goes_on():
    assert lines(f'''
def clone(url, path, return_postinstall=False, **options):
    def postinstall():
        raise subprocess.CalledProcessError(1, ['python', 'install.py'])
    return core.ManagedResult('install-git').with_postinstall(postinstall)
manager.repo_install = clone
core.repo_switch_commit = Mock(return_value=True)
result = summary(git_custom_nodes={{'{URL}': {{'hash': HASH, 'disabled': False}}, '{URL}-other': {{'hash': HASH, 'disabled': False}}}})
''') == ['[  FAILED   ] fixture', '[  FAILED   ] fixture-other']


def test_install_script_of_a_cloned_pack_runs_also_when_the_commit_cannot_be_checked_out():
    """The clone stays where it is, and a later restore only checks it out."""
    assert lines(f'''
ran = []
manager.repo_install = lambda url, path, **options: core.ManagedResult('install-git').with_postinstall(lambda: ran.append(path) or True)
result = summary(**pinned('{URL}')) + [ran == [str(nodes / 'fixture')]]
''') == [f'[  FAILED   ] fixture@{HASH}', True]


def test_install_script_of_a_cloned_registry_pack_runs_also_when_the_commit_cannot_be_checked_out():
    assert lines(f'''
ran = []
async def install(pack_id, version_spec, **options):
    manager.active_nodes[pack_id] = (version_spec, str(nodes / pack_id))
    return core.ManagedResult('install-git').with_postinstall(lambda: ran.append(pack_id) or True)
manager.repo_cnr_map['{URL}'] = {{'id': 'fixture'}}
manager.install_by_id = install
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


def test_git_of_a_case_does_not_inherit_a_repository(monkeypatch):
    """Run from a git hook, the tests inherit variables such as GIT_DIR, which point git at the repository of the hook."""
    names = subprocess.run(['git', 'rev-parse', '--local-env-vars'], check=True, capture_output=True, text=True).stdout.split()
    for name in names:
        monkeypatch.setenv(name, 'elsewhere')

    assert run(f'print(json.dumps(sorted(set(os.environ) & set({names}))))') == []


def test_registry_pack_whose_install_raises_is_reported_as_failed_and_the_restore_goes_on():
    """Without a connection the request to the registry raises."""
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
    'registry_pack': ("manager.active_nodes['fixture'] = ('1.0.0', str(nodes / 'fixture'))", 'unified_disable', False),
    'registry_git_pack': (f"manager.active_nodes['fixture'] = ('nightly', str(nodes / 'fixture'))\nmanager.repo_cnr_map['{URL}'] = {{'id': 'fixture'}}",
                          'unified_disable', False),
    'unknown_git_pack': (f"manager.unknown_active_nodes['fixture'] = git_pack('fixture', '{URL}')", 'unified_disable', False),
    'disabled_registry_git_pack': (f"manager.nightly_inactive_nodes['fixture'] = str(nodes / '.disabled/fixture')\nmanager.repo_cnr_map['{URL}'] = {{'id': 'fixture'}}",
                                   'unified_enable', True),
    'disabled_unknown_git_pack': (f"manager.unknown_inactive_nodes['fixture'] = git_pack('.disabled/fixture', '{URL}')", 'unified_enable', True),
}


@pytest.mark.parametrize('installed', MOVED)
def test_pack_whose_directory_cannot_be_moved_is_reported_as_failed_and_the_restore_goes_on(installed):
    """Disabling and enabling move the directory of the node pack."""
    arrange, step, in_snapshot = MOVED[installed]
    snapshot = f"**pinned('{URL}')" if in_snapshot else ''
    assert lines(f'''
{arrange}
manager.{step} = Mock(side_effect=PermissionError(13, 'Permission denied'))
result = summary({snapshot}) + [manager.{step}.call_count]
''') == ['[  FAILED   ] fixture', 1]


def test_registry_git_pack_that_cannot_be_enabled_is_listed_once():
    """The install that follows for a node pack of the snapshot enables it as well, and raises for the same reason."""
    arrange = MOVED['disabled_registry_git_pack'][0]
    assert lines(f'''
{arrange}
async def install(pack_id, version_spec, **options):
    raise PermissionError(13, 'Permission denied')
manager.unified_enable = Mock(side_effect=PermissionError(13, 'Permission denied'))
manager.install_by_id = install
result = summary(**pinned('{URL}'))
''') == ['[  FAILED   ] fixture']


INSTALLS = '''
import os

def packs(**files):
    for name in ('first', 'second'):
        (nodes / name).mkdir()
        for file, text in files.items():
            (nodes / name / file).write_text(text)
    return str(nodes / 'first'), str(nodes / 'second')

def installs(*answers):
    """Replace what runs an install command; the answers are given in turn, and the directories it ran in are returned."""
    answers, ran = list(answers), []

    def try_install_script(url, repo_path, install_cmd, instant_execution=False):
        ran.append(os.path.basename(repo_path))
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
''') == [False, True, ['first', 'second']]


def test_requirement_after_one_that_failed_is_tried_for_the_next_pack():
    assert install_steps('''
first, second = packs(**{'requirements.txt': 'fails==1\\nshareddep==1\\n'})
ran = installs(False, True, True)
result = [manager.execute_install_script(None, first), manager.execute_install_script(None, second), ran]
''') == [False, True, ['first', 'second', 'second']]


def test_requirement_that_was_installed_is_not_installed_twice():
    assert install_steps('''
first, second = packs(**{'requirements.txt': 'shareddep==1\\n'})
ran = installs(True)
result = [manager.execute_install_script(None, first), manager.execute_install_script(None, second), ran]
''') == [True, True, ['first']]


def test_install_script_that_failed_is_run_when_asked_again():
    assert install_steps('''
first, _ = packs(**{'install.py': ''})
ran = installs(False, True)
result = [manager.execute_install_script(None, first), manager.execute_install_script(None, first), ran]
''') == [False, True, ['first', 'first']]


def test_install_script_not_run_after_a_requirement_failed_is_run_when_asked_again():
    assert install_steps('''
first, _ = packs(**{'requirements.txt': 'fails==1\\n', 'install.py': ''})
ran = installs(False, True, True)
result = [manager.execute_install_script(None, first), manager.execute_install_script(None, first), ran]
''') == [False, True, ['first', 'first', 'first']]
