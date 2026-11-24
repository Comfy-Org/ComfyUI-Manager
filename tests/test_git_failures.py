import pytest

from test_install_flags_config import _run_child


PRELUDE = '''
import asyncio, os, pathlib, subprocess, time
from unittest.mock import AsyncMock, Mock
core = manager_core
tmp = pathlib.Path(tmp)
os.environ.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='protocol.file.allow', GIT_CONFIG_VALUE_0='always')
(tmp / 'folder_paths.py').touch()
os.environ['COMFYUI_PATH'] = str(tmp)
nodes = tmp / 'custom_nodes'
nodes.mkdir()
core.get_default_custom_nodes_path = lambda: str(nodes)
core.get_custom_nodes_paths = lambda: [str(nodes)]
core.is_valid_url = lambda url: True
manager = core.UnifiedManager()
manager.reload = AsyncMock()
manager.get_custom_nodes = AsyncMock(return_value={})
manager.get_cnr_by_repo = Mock(return_value=None)
manager.execute_install_script = Mock(return_value=True)
core.unified_manager = manager
core.execute_install_script = Mock(return_value=True)

def git(path, *args):
    subprocess.run(['git', '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', *args], cwd=path, check=True, capture_output=True)

def head(path):
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=path, check=True, capture_output=True, text=True).stdout.strip()

def failed(call, *args, **options):
    try:
        call(*args, **options)
    except Exception:
        return True
    return False

asset, library, origin, pack = tmp / 'asset', tmp / 'library', tmp / 'origin', tmp / 'pack'
for repository in (asset, library, origin):
    repository.mkdir()
    git(repository, 'init', '-q')
commits = []
for version in (1, 2):
    for submodule in (asset, library):
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
        git(tmp, 'clone', '-q', '--recursive', str(origin), 'pack')
away = tmp / 'library.away'
library.rename(away)
'''

PULL_TWICE = '''
first = failed(core.git_pull, str(pack))
after_first = head(pack) == commits[0]
asset_after_first = (pack / 'asset/__init__.py').read_text()
away.rename(library)
second = failed(core.git_pull, str(pack))
print(json.dumps({'first failed': first, 'at its commit': after_first, 'asset at its commit': asset_after_first, 'second failed': second,
                  'updated': head(pack) == commits[1], 'library': (pack / 'library/__init__.py').read_text()}))
'''
PULLED = {'first failed': True, 'at its commit': True, 'asset at its commit': 'VERSION = 1', 'second failed': False, 'updated': True, 'library': 'VERSION = 2'}


def run(body):
    return _run_child(PRELUDE + body)


def test_pull_that_fails_at_the_submodules_leaves_the_pack_at_its_commit():
    assert run(PULL_TWICE) == PULLED


def test_pull_of_the_git_helper_that_fails_is_a_failure():
    assert run("core.platform.system = lambda: 'Windows'\n" + PULL_TWICE) == PULLED


WHERE = pytest.mark.parametrize('where', ['', "core.platform.system = lambda: 'Windows'\n"], ids=['in the server process', 'in the git helper'])


@WHERE
def test_a_check_of_a_pack_with_an_update_does_not_ask_for_its_install_script(where):
    assert run(where + '''
away.rename(library)
os.environ['GIT_COMMITTER_DATE'] = '@%d +0000' % (time.time() + 86400)
git(origin, 'commit', '-q', '--allow-empty', '-m', 'a commit dated a day later')
del os.environ['GIT_COMMITTER_DATE']
state = core.git_repo_update_check_with(str(pack))
print()
print(json.dumps({'state': list(state), 'install scripts': core.execute_install_script.call_count, 'updated': head(pack) == head(origin)}))
''') == {'state': [True, True], 'install scripts': 0, 'updated': False}


LIBRARY_NOT_CLONED = '''
git(pack, 'submodule', 'deinit', '-q', '-f', 'library')
# moved, as git makes files read-only that Windows does not remove
(pack / '.git/modules/library').rename(tmp / 'library.modules')
'''


def test_pull_of_the_git_helper_that_fails_at_the_submodules_puts_them_back():
    data = run('''
away.rename(library)
nested = tmp / 'nested'
nested.mkdir()
git(nested, 'init', '-q')
git(nested, 'commit', '-q', '--allow-empty', '-m', 'nested')
git(asset, 'submodule', 'add', '-q', str(nested), 'nested')
git(asset, 'commit', '-q', '-m', 'a submodule')
git(origin / 'asset', 'pull', '-q')
git(origin, 'commit', '-q', '-a', '-m', 'asset with a submodule')
nested.rename(tmp / 'nested.away')
core.platform.system = lambda: 'Windows'
first = failed(core.git_pull, str(pack))
print(json.dumps({'failed': first, 'at its commit': head(pack) == commits[0], 'asset at its commit': not (pack / 'asset/.gitmodules').exists()}))
''')
    assert data == {'failed': True, 'at its commit': True, 'asset at its commit': True}


@pytest.mark.parametrize('where', ['', "core.platform.system = lambda: 'Windows'\n"], ids=['in the server process', 'in the git helper'])
def test_pull_of_a_pack_whose_branch_is_ahead_of_its_remote_is_no_failure(where):
    data = run(where + '''
away.rename(library)
git(pack, 'pull', '-q', '--recurse-submodules')
git(pack, 'commit', '-q', '--allow-empty', '-m', 'a commit of the pack alone')
tip = head(pack)
print(json.dumps({'failed': failed(core.git_pull, str(pack)), 'at its commit': head(pack) == tip}))
''')
    assert data == {'failed': False, 'at its commit': True}


LIBRARY_AT_A_COMMIT_AWAY = '''
(library / '__init__.py').write_text('VERSION = 3')
git(library, 'commit', '-q', '-a', '-m', 'version 3')
git(origin / 'library', 'pull', '-q')
git(origin, 'commit', '-q', '-a', '-m', 'library 3')
version_3 = head(library)
library.rename(away)
'''


@pytest.mark.parametrize('where', ['', "core.platform.system = lambda: 'Windows'\n"], ids=['in the server process', 'in the git helper'])
def test_pull_that_fails_puts_back_the_branch_of_a_pack_that_was_not_on_it(where):
    data = run(where + '''
away.rename(library)
git(pack, 'pull', '-q', '--recurse-submodules')
git(pack, 'checkout', '-q', commits[0])
git(pack, 'submodule', 'update', '-q', '--recursive')
''' + LIBRARY_NOT_CLONED + LIBRARY_AT_A_COMMIT_AWAY + '''
print(json.dumps({'failed': failed(core.git_pull, str(pack)), 'at the commit of its branch': head(pack) == commits[1]}))
''')
    assert data == {'failed': True, 'at the commit of its branch': True}


def test_pull_whose_submodules_cannot_be_put_back_either_fails_with_the_error_of_the_update():
    data = run('''
away.rename(library)
git(pack, 'pull', '-q', '--no-recurse-submodules')
''' + LIBRARY_AT_A_COMMIT_AWAY + '''
error = ''
try:
    core.platform.system = lambda: 'Linux'
    core.git_pull(str(pack))
except Exception as e:
    error = str(e)
helper = subprocess.run([sys.executable, core.git_script_path, '--pull', str(pack)], env=core.get_script_env(), cwd=nodes,
                        capture_output=True, text=True)
print(json.dumps({'in the server process': version_3 in error, 'in the git helper': [helper.returncode, version_3 in helper.stdout]}))
''')
    assert data == {'in the server process': True, 'in the git helper': [1, True]}


@pytest.mark.parametrize('where', ['', "core.platform.system = lambda: 'Windows'\n"], ids=['in the server process', 'in the git helper'])
def test_pull_that_fails_leaves_a_submodule_that_was_never_fetched_alone(where):
    data = run(where + '''
away.rename(library)
git(tmp, 'clone', '-q', str(origin), 'plain')
plain = tmp / 'plain'
git(plain, 'submodule', 'update', '-q', '--init', 'asset')
extra = tmp / 'extra'
extra.mkdir()
git(extra, 'init', '-q')
(extra / 'x.py').write_text('x')
git(extra, 'add', '.')
git(extra, 'commit', '-q', '-m', 'x')
git(origin, 'rm', '-q', 'library')
git(origin, 'submodule', 'add', '-q', str(extra), 'extra')
git(origin, 'commit', '-q', '-m', 'library removed, extra added')
extra.rename(tmp / 'extra.away')
before = head(plain)
print(json.dumps({'failed': failed(core.git_pull, str(plain)), 'at its commit': head(plain) == before, 'library': os.listdir(plain / 'library')}))
''')
    assert data == {'failed': True, 'at its commit': True, 'library': []}
