"""Behavioral checks against real v3 modules in an isolated ComfyUI runtime."""

import pytest

from test_install_flags_config import _run_child


PRELUDE = '''
import asyncio, io, logging, pathlib, zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import cnr_utils, manager_util
from comfy.cli_args import args
args.listen = '0.0.0.0'
core = manager_core
core.manager_funcs.is_flagged_install_allowed = lambda: False
config = core.get_config()
config['allow_flagged_nodepack_install'] = False
nodes = pathlib.Path(tmp) / 'custom_nodes'
nodes.mkdir()
core.get_default_custom_nodes_path = lambda: str(nodes)
manager = core.UnifiedManager()
core.unified_manager = manager
terminal = io.StringIO()
logging.getLogger().addHandler(logging.StreamHandler(terminal))
status = 'NodeVersionStatusFlagged'
http = 200
get = Mock(side_effect=lambda *a, **k: SimpleNamespace(status_code=http, json=lambda: {
    'id': 'version-id', 'node_id': 'fixture', 'version': '2.0.0', 'status': status,
    'downloadUrl': 'https://example.invalid/fixture.zip',
}))
cnr_utils.requests.get = get
def download(url, directory, name):
    with zipfile.ZipFile(pathlib.Path(directory) / name, 'w') as archive:
        archive.writestr('__init__.py', 'VERSION = "2.0.0"')
        archive.writestr('pyproject.toml', '[project]\\nname = "fixture"\\nversion = "2.0.0"\\n')
core.manager_downloader.download_url = Mock(side_effect=download)
core.manager_downloader.basic_download_url = core.manager_downloader.download_url
manager.execute_install_script = Mock(return_value=True)
'''


def run(body):
    stub = '''
comfy = types.ModuleType('comfy')
cli_args = types.ModuleType('comfy.cli_args')
cli_args.args = types.SimpleNamespace(listen='127.0.0.1')
sys.modules['comfy'] = comfy
sys.modules['comfy.cli_args'] = cli_args
'''
    return _run_child(stub + PRELUDE + body)


@pytest.mark.parametrize('permission,allowed', [(None, True), ('true', True), ('false', False)])
def test_cli_install_uses_only_parent_permission(permission, allowed):
    data = run(f'''
permission = {permission!r}
os.environ.pop('_COMFYUI_MANAGER_CNR_ALLOW_FLAGGED', None)
if permission is not None:
    os.environ['_COMFYUI_MANAGER_CNR_ALLOW_FLAGGED'] = permission
core.manager_funcs = core.ManagerFuncs()
args.listen = '127.0.0.1' if permission == 'false' else '0.0.0.0'
config['allow_flagged_nodepack_install'] = permission == 'false'
result = asyncio.run(manager.install_by_id('fixture', '2.0.0'))
print(json.dumps({{'ok': result.result, 'queries': get.call_count,
    'downloads': core.manager_downloader.download_url.call_count}}))
''')
    assert data == {'ok': allowed, 'queries': 1, 'downloads': int(allowed)}


@pytest.mark.parametrize('status,permission,allowed', [
    ('Active', False, True), ('Pending', False, True),
    ('Flagged', False, False), ('Flagged', True, True),
])
def test_install_policy_before_download(status, permission, allowed):
    data = run(f'''
status = {'NodeVersionStatus' + status!r}
core.manager_funcs.is_flagged_install_allowed = lambda: {permission!r}
result = asyncio.run(manager.install_by_id('fixture', '2.0.0'))
print(json.dumps({{'ok': result.result, 'message': result.msg,
    'terminal': terminal.getvalue(),
    'queries': get.call_count, 'downloads': core.manager_downloader.download_url.call_count,
    'installed': (nodes / 'fixture/__init__.py').exists()}}))
''')
    assert data['ok'] is allowed, data
    assert data['installed'] is allowed, data
    assert data['downloads'] == int(allowed), data
    assert data['queries'] == 1, data
    if not allowed:
        assert data['message'] == ('This action is not allowed by the current security configuration. '
                                   'See the terminal for details.')
        for detail in ('--listen 127.0.0.1', '--listen ::1', '0.0.0.0', '[default]',
                       'allow_flagged_nodepack_install = true', 'config.ini',
                       'trusted private network', 'Restart ComfyUI'):
            assert detail in data['terminal'], data
    else:
        assert 'allow_flagged_nodepack_install' not in data['terminal']


@pytest.mark.parametrize('http', [403, 404, 500])
def test_override_does_not_bypass_registry_refusal(http):
    data = run(f'''
http = {http}
core.manager_funcs.is_flagged_install_allowed = lambda: True
result = asyncio.run(manager.install_by_id('fixture', '2.0.0'))
print(json.dumps({{'ok': result.result, 'queries': get.call_count,
    'downloads': core.manager_downloader.download_url.call_count}}))
''')
    assert data == {'ok': False, 'queries': 1, 'downloads': 0}


@pytest.mark.parametrize('operation', ['install', 'lazy', 'instant'])
@pytest.mark.parametrize('return_postinstall', [False, True])
def test_direct_cnr_execution_and_postinstall(operation, return_postinstall):
    data = run(f'''
status = 'NodeVersionStatusActive'
operation = {operation!r}
return_postinstall = {return_postinstall!r}
installed = nodes / 'fixture'
if operation != 'install':
    installed.mkdir()
    (installed / '__init__.py').write_text('original')
    (installed / '.tracking').write_text('__init__.py')
    manager.active_nodes['fixture'] = ('1.0.0', str(installed))
manager.reserve_cnr_switch = Mock(return_value=True)
if operation == 'install':
    result = manager.cnr_install('fixture', instant_execution=True,
                                 no_deps=True, return_postinstall=return_postinstall)
else:
    result = manager.cnr_switch_version('fixture', instant_execution=operation == 'instant',
                                        no_deps=True, return_postinstall=return_postinstall)
assert result.result, result.msg
assert result.target == ('2.0.0' if operation == 'instant' else None)
effect = manager.reserve_cnr_switch if operation == 'lazy' else manager.execute_install_script
before = effect.call_count
if return_postinstall:
    assert result.postinstall()
if operation == 'lazy':
    assert effect.call_args.args[1] == 'https://example.invalid/fixture.zip'
    assert effect.call_args.args[-2:] == (True, 'NodeVersionStatusActive')
else:
    assert effect.call_args.kwargs == {{'instant_execution': True, 'no_deps': True}}
print(json.dumps({{'queries': get.call_count,
    'downloads': core.manager_downloader.download_url.call_count,
    'before': before, 'after': effect.call_count,
    'content': (installed / '__init__.py').read_text()}}))
''')
    assert data == {'queries': 1, 'downloads': int(operation != 'lazy'),
                    'before': int(not return_postinstall), 'after': 1,
                    'content': 'original' if operation == 'lazy' else 'VERSION = "2.0.0"'}


@pytest.mark.parametrize('operation', ['install', 'reinstall', 'lazy', 'instant', 'snapshot'])
def test_denial_preserves_installed_version(operation):
    data = run(f'''
installed = nodes / 'fixture'
installed.mkdir()
(installed / '__init__.py').write_text('VERSION = "1.0.0"')
(installed / '.tracking').write_text('__init__.py')
manager.active_nodes['fixture'] = ('1.0.0', str(installed))
manager.reserve_cnr_switch = Mock(return_value=True)
operation = {operation!r}
if operation == 'snapshot':
    manager.reload = AsyncMock()
    manager.get_custom_nodes = AsyncMock(return_value={{}})
    core.manager_util.restore_pip_snapshot = Mock()
    snapshot = pathlib.Path(tmp) / 'snapshot.json'
    snapshot.write_text(json.dumps({{'cnr_custom_nodes': {{'fixture': '2.0.0'}},
        'git_custom_nodes': {{}}, 'file_custom_nodes': []}}))
    asyncio.run(core.restore_snapshot(str(snapshot)))
elif operation in ('lazy', 'instant'):
    result = manager.cnr_switch_version('fixture', '2.0.0', instant_execution=operation == 'instant')
    assert not result.result, result.msg
elif operation == 'reinstall':
    result = asyncio.run(manager.reinstall_by_id('fixture', '2.0.0'))
    assert not result.result, result.msg
else:
    result = asyncio.run(manager.install_by_id('fixture', '2.0.0'))
    assert not result.result, result.msg
print(json.dumps({{'files': (installed / '__init__.py').read_text(),
    'queries': get.call_count, 'downloads': core.manager_downloader.download_url.call_count,
    'reservations': manager.reserve_cnr_switch.call_count}}))
''')
    assert data == {'files': 'VERSION = "1.0.0"', 'queries': 1, 'downloads': 0, 'reservations': 0}


@pytest.mark.parametrize('listen,allowed', [
    ('127.0.0.1', True), ('::1', True), ('127.0.0.1,::1', True),
    ('0.0.0.0', False), ('::', False), ('0.0.0.0,::', False),
    ('192.168.1.2', False), ('127.0.0.1,0.0.0.0', False), ('', False),
])
def test_all_listener_addresses_must_be_loopback(listen, allowed):
    data = run(f'''
print(json.dumps(manager_util.is_cnr_install_allowed('NodeVersionStatusFlagged', False, {listen!r})))
''')
    assert data is allowed


@pytest.mark.parametrize('addresses,allowed', [
    (['127.0.0.1', '::1'], True), (['127.0.0.1', '192.168.1.2'], False),
    ([], False), (None, False),
])
def test_hostname_must_resolve_exclusively_to_loopback(addresses, allowed):
    data = run(f'''
addresses = {addresses!r}
if addresses is None:
    manager_util.socket.getaddrinfo = Mock(side_effect=OSError('unresolvable'))
else:
    manager_util.socket.getaddrinfo = Mock(return_value=[
        (0, 0, 0, '', (ip, 0)) for ip in addresses])
print(json.dumps(manager_util.is_cnr_install_allowed('NodeVersionStatusFlagged', False, 'host.test')))
''')
    assert data is allowed


@pytest.mark.parametrize('state', ['nightly', 'disabled'])
def test_denial_preserves_enabled_state(state):
    data = run(f'''
state = {state!r}
installed = nodes / ('fixture' if state == 'nightly' else '.disabled/fixture@1_0_0')
installed.mkdir(parents=True)
(installed / '__init__.py').write_text('original')
if state == 'nightly':
    manager.active_nodes['fixture'] = ('nightly', str(installed))
else:
    manager.cnr_inactive_nodes['fixture'] = {{'1.0.0': str(installed)}}
before = repr((manager.active_nodes, manager.cnr_inactive_nodes))
result = asyncio.run(manager.install_by_id('fixture', '2.0.0'))
print(json.dumps({{'ok': result.result, 'original': (installed / '__init__.py').read_text(),
    'unchanged': before == repr((manager.active_nodes, manager.cnr_inactive_nodes)),
    'queries': get.call_count, 'downloads': core.manager_downloader.download_url.call_count}}))
''')
    assert data == {'ok': False, 'original': 'original', 'unchanged': True, 'queries': 1, 'downloads': 0}


def test_exact_installed_version_enables_without_registry_lookup():
    data = run('''
installed = nodes / '.disabled/fixture@2_0_0'
installed.mkdir(parents=True)
(installed / '__init__.py').write_text('already installed')
manager.cnr_inactive_nodes['fixture'] = {'2.0.0': str(installed)}
result = asyncio.run(manager.install_by_id('fixture', '2.0.0'))
assert manager.active_nodes['fixture'] == ('2.0.0', str(nodes / 'fixture'))
assert asyncio.run(manager.install_by_id('fixture', '2.0.0')).action == 'skip'
print(json.dumps({'ok': result.result, 'old_path': installed.exists(),
    'content': (nodes / 'fixture/__init__.py').read_text(), 'queries': get.call_count,
    'downloads': core.manager_downloader.download_url.call_count,
    'scripts': manager.execute_install_script.call_count}))
''')
    assert data == {'ok': True, 'old_path': False, 'content': 'already installed',
                    'queries': 0, 'downloads': 0, 'scripts': 0}


def test_failed_uninstall_stops_reinstall():
    data = run('''
status = 'NodeVersionStatusActive'
manager.unified_uninstall = Mock(return_value=core.ManagedResult('uninstall').fail('cannot remove'))
result = asyncio.run(manager.reinstall_by_id('fixture', '2.0.0'))
print(json.dumps({'ok': result.result, 'message': result.msg, 'queries': get.call_count,
    'downloads': core.manager_downloader.download_url.call_count}))
''')
    assert data == {'ok': False, 'message': 'cannot remove', 'queries': 1, 'downloads': 0}


@pytest.mark.parametrize('version', ['nightly', 'unknown'])
def test_git_reinstall_replaces_pack_and_reruns_script(version):
    data = run(f'''
version = {version!r}
installed = nodes / 'fixture'
installed.mkdir()
(installed / 'original.txt').write_text('original')
repo_url = 'https://example.invalid/fixture'
if version == 'nightly':
    manager.active_nodes['fixture'] = ('nightly', str(installed))
else:
    manager.unknown_active_nodes['fixture'] = (repo_url, str(installed))
manager.get_custom_nodes = AsyncMock(return_value={{
    'fixture': {{'repository': repo_url, 'files': [repo_url]}},
}})
get.side_effect = AssertionError('Git needs no CNR install query')
manager.processed_install.add(str(installed / 'install.py'))
manager.execute_install_script = core.UnifiedManager.execute_install_script.__get__(manager)
core.try_install_script = Mock(return_value=True)
def clone(url, path, **kwargs):
    assert url == repo_url
    path = pathlib.Path(path)
    assert not path.exists()
    path.mkdir()
    (path / 'replacement.txt').write_text('installed')
    (path / 'install.py').write_text('')
    assert manager.execute_install_script(url, str(path))
    return core.ManagedResult('install-git')
manager.repo_install = Mock(side_effect=clone)
result = asyncio.run(manager.reinstall_by_id('fixture', version))
print(json.dumps({{'ok': result.result, 'original': (installed / 'original.txt').exists(),
    'replacement': (installed / 'replacement.txt').read_text(),
    'clones': manager.repo_install.call_count, 'scripts': core.try_install_script.call_count}}))
''')
    assert data == {'ok': True, 'original': False, 'replacement': 'installed', 'clones': 1, 'scripts': 1}


def test_config_defaults_and_manual_edits_survive_settings_save():
    data = _run_child('''
write_ini('[default]\\nsecurity_level = normal\\n')
first = fresh_read()['allow_flagged_nodepack_install']
write_ini('[default]\\nsecurity_level = normal\\nallow_flagged_nodepack_install = true\\n')
manager_core.get_config()['db_mode'] = 'local'
manager_core.write_config()
cached = manager_core.get_config()['allow_flagged_nodepack_install']
fresh = fresh_read()['allow_flagged_nodepack_install']
print(json.dumps([first, cached, fresh]))
''')
    assert data == [False, False, True]


@pytest.mark.parametrize('raw,expected', [('TRUE', True), ('false', False), ('garbage', False)])
def test_config_value_roundtrip(raw, expected):
    data = _run_child(f'''
write_ini('[default]\\nallow_flagged_nodepack_install = {raw}\\n')
loaded = fresh_read()['allow_flagged_nodepack_install']
manager_core.get_config()['allow_flagged_nodepack_install'] = not loaded
manager_core.write_config()
print(json.dumps([loaded, fresh_read()['allow_flagged_nodepack_install']]))
''')
    assert data == [expected, not expected]
