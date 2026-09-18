"""Exercise the real CNR client and both install implementations."""

import asyncio
import ast
import json
import logging
import os
import socket
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from _install_flags_testutil import import_context, import_reader


@pytest.fixture
def cnr_client(monkeypatch):
    import_context()
    from comfy.cli_args import args
    from comfyui_manager.common import cnr_utils

    monkeypatch.setattr(args, 'listen', '0.0.0.0')
    return cnr_utils


@pytest.fixture(params=['glob', 'legacy'])
def core(request, cnr_client, monkeypatch, tmp_path):
    core = import_reader(request.param)
    monkeypatch.setattr(core.manager_funcs, 'is_flagged_install_allowed', lambda: False)
    monkeypatch.setattr(core, 'get_config', lambda: {'allow_flagged_nodepack_install': False})
    monkeypatch.setattr(core, 'get_default_custom_nodes_path', lambda: str(tmp_path))
    return core


def api_response(status='NodeVersionStatusFlagged', http=200):
    return SimpleNamespace(status_code=http, json=lambda: {
        'id': 'version-id', 'node_id': 'fixture', 'version': '2.0.0',
        'status': status, 'downloadUrl': 'https://example.invalid/fixture.zip',
    })


@pytest.mark.parametrize('permission,allowed', [(None, True), ('true', True), ('false', False)])
def test_cli_install_uses_only_parent_permission(core, monkeypatch, permission, allowed, tmp_path):
    from comfy.cli_args import args

    monkeypatch.delenv('_COMFYUI_MANAGER_CNR_ALLOW_FLAGGED', raising=False)
    if permission is not None:
        monkeypatch.setenv('_COMFYUI_MANAGER_CNR_ALLOW_FLAGGED', permission)
    monkeypatch.setattr(core, 'manager_funcs', core.ManagerFuncs())
    monkeypatch.setattr(args, 'listen', '127.0.0.1' if permission == 'false' else '0.0.0.0')
    monkeypatch.setattr(core, 'get_config', lambda: {'allow_flagged_nodepack_install': permission == 'false'})
    get = Mock(return_value=api_response())
    monkeypatch.setattr(core.cnr_utils.requests, 'get', get)
    download = Mock(side_effect=lambda url, directory, name: (tmp_path / name).write_bytes(b'fixture'))
    monkeypatch.setattr(core.manager_downloader, 'download_url', download)
    monkeypatch.setattr(core.manager_util, 'extract_package_as_zip', lambda *a: ['__init__.py'])
    manager = core.UnifiedManager()
    manager.execute_install_script = Mock(return_value=True)

    result = asyncio.run(manager.install_by_id('fixture', '2.0.0'))

    assert result.result is allowed, result.msg
    assert get.call_count == 1
    assert download.call_count == int(allowed)


@pytest.mark.parametrize('listen,allowed', [
    ('127.0.0.1', True), ('127.2.3.4', True), ('::1', True),
    ('127.0.0.1,::1', True), ('0.0.0.0', False), ('::', False),
    ('192.168.1.2', False), ('127.0.0.1,0.0.0.0', False),
    ('0.0.0.0,::', False), ('', False), ('127.0.0.1,', False),
])
def test_listener_policy(cnr_client, listen, allowed):
    from comfyui_manager.common.manager_security import is_cnr_install_allowed

    assert is_cnr_install_allowed('NodeVersionStatusFlagged', False, listen) is allowed
    assert is_cnr_install_allowed('NodeVersionStatusFlagged', True, listen) is True


def test_hostname_requires_all_resolved_addresses_to_be_loopback(cnr_client, monkeypatch):
    from comfyui_manager.common.manager_security import is_loopback_listener

    def addresses(*hosts):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (host, 0)) for host in hosts]

    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: addresses('127.0.0.1', '::1'))
    assert is_loopback_listener('localhost')
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: addresses('127.0.0.1', '192.168.1.2'))
    assert not is_loopback_listener('localhost')
    monkeypatch.setattr(socket, 'getaddrinfo', Mock(side_effect=socket.gaierror))
    assert not is_loopback_listener('invalid.invalid')


@pytest.mark.parametrize('status,permission,allowed', [
    ('NodeVersionStatusActive', False, True), ('NodeVersionStatusPending', False, True),
    ('NodeVersionStatusFlagged', False, False), ('NodeVersionStatusFlagged', True, True),
])
def test_install_uses_status_from_one_response(core, monkeypatch, tmp_path, caplog, status, permission, allowed):
    get = Mock(return_value=api_response(status))
    monkeypatch.setattr(core.cnr_utils.requests, 'get', get)
    monkeypatch.setattr(core.manager_funcs, 'is_flagged_install_allowed', lambda: permission)
    download = Mock(side_effect=lambda url, directory, name: (tmp_path / name).write_bytes(b'fixture'))
    monkeypatch.setattr(core.manager_downloader, 'download_url', download)
    monkeypatch.setattr(core.manager_util, 'extract_package_as_zip', lambda *a: ['__init__.py'])
    manager = core.UnifiedManager()
    manager.execute_install_script = Mock(return_value=True)

    result = manager.cnr_install('fixture', '2.0.0')

    assert result.result is allowed, result.msg
    if not allowed:
        assert result.msg == ('This action is not allowed by the current security configuration. '
                              'See the terminal for details.')
        for detail in ('--listen 127.0.0.1', '--listen ::1', '0.0.0.0', '[default]',
                       'allow_flagged_nodepack_install = true', 'config.ini',
                       'trusted private network', 'Restart ComfyUI'):
            assert detail in caplog.text
    else:
        assert 'allow_flagged_nodepack_install' not in caplog.text
    assert get.call_count == 1
    assert download.call_count == int(allowed)


@pytest.mark.parametrize('http', [403, 404, 500])
def test_override_does_not_bypass_registry_refusal(core, monkeypatch, tmp_path, http):
    monkeypatch.setattr(core.manager_funcs, 'is_flagged_install_allowed', lambda: True)
    get = Mock(return_value=api_response(http=http))
    monkeypatch.setattr(core.cnr_utils.requests, 'get', get)
    download = Mock(side_effect=AssertionError('Registry refusal must prevent downloading'))
    monkeypatch.setattr(core.manager_downloader, 'download_url', download)
    manager = core.UnifiedManager()

    result = asyncio.run(manager.install_by_id('fixture', '2.0.0'))

    assert result.result is False
    assert result.msg == 'not available node: fixture@2.0.0'
    assert get.call_count == 1
    assert download.call_count == 0
    assert not (tmp_path / 'fixture').exists()


@pytest.mark.parametrize('operation', ['install', 'lazy', 'instant'])
def test_direct_install_and_switch_reject_before_side_effects(core, monkeypatch, operation):
    get = Mock(return_value=api_response())
    monkeypatch.setattr(core.cnr_utils.requests, 'get', get)
    download = Mock(side_effect=AssertionError('download must not happen'))
    monkeypatch.setattr(core.manager_downloader, 'download_url', download)
    monkeypatch.setattr(core.manager_downloader, 'basic_download_url', download)
    manager = core.UnifiedManager()
    manager.reserve_cnr_switch = Mock(side_effect=AssertionError('reservation must not happen'))
    if operation == 'install':
        result = manager.cnr_install('fixture', '2.0.0')
    else:
        result = manager.cnr_switch_version('fixture', '2.0.0', instant_execution=operation == 'instant')
    assert result.result is False
    assert result.msg == ('This action is not allowed by the current security configuration. '
                          'See the terminal for details.')
    assert get.call_count == 1


@pytest.mark.parametrize('operation', ['install', 'lazy', 'instant'])
@pytest.mark.parametrize('return_postinstall', [False, True])
def test_direct_cnr_execution_and_postinstall(core, monkeypatch, tmp_path, operation, return_postinstall):
    get = Mock(return_value=api_response('NodeVersionStatusActive'))
    monkeypatch.setattr(core.cnr_utils.requests, 'get', get)

    def download(url, directory, name):
        with zipfile.ZipFile(Path(directory) / name, 'w') as archive:
            archive.writestr('__init__.py', 'VERSION = "2.0.0"')

    downloader = Mock(side_effect=download)
    monkeypatch.setattr(core.manager_downloader, 'download_url', downloader)
    monkeypatch.setattr(core.manager_downloader, 'basic_download_url', downloader)
    manager = core.UnifiedManager()
    installed = tmp_path / 'fixture'
    if operation != 'install':
        installed.mkdir()
        (installed / '__init__.py').write_text('original')
        (installed / '.tracking').write_text('__init__.py')
        manager.active_nodes['fixture'] = ('1.0.0', str(installed))
    manager.reserve_cnr_switch = Mock(return_value=True)
    manager.execute_install_script = Mock(return_value=True)

    if operation == 'install':
        result = manager.cnr_install('fixture', instant_execution=True,
                                     no_deps=True, return_postinstall=return_postinstall)
    else:
        result = manager.cnr_switch_version('fixture', instant_execution=operation == 'instant',
                                            no_deps=True, return_postinstall=return_postinstall)

    assert result.result is True, result.msg
    assert result.target == ('2.0.0' if operation == 'instant' else None)
    effect = manager.reserve_cnr_switch if operation == 'lazy' else manager.execute_install_script
    assert effect.call_count == int(not return_postinstall)
    if return_postinstall:
        assert result.postinstall()
    assert effect.call_count == 1
    assert get.call_count == 1
    assert downloader.call_count == int(operation != 'lazy')
    assert (installed / '__init__.py').read_text() == (
        'original' if operation == 'lazy' else 'VERSION = "2.0.0"')
    if operation == 'lazy':
        assert effect.call_args.args[1] == 'https://example.invalid/fixture.zip'
        assert effect.call_args.args[-2:] == (True, 'NodeVersionStatusActive')
    else:
        assert effect.call_args.kwargs == {'instant_execution': True, 'no_deps': True}


@pytest.mark.parametrize('installed', ['nightly', 'disabled-cnr', 'new'])
def test_rejection_preserves_existing_install_state(core, monkeypatch, installed):
    get = Mock(return_value=api_response())
    monkeypatch.setattr(core.cnr_utils.requests, 'get', get)
    manager = core.UnifiedManager()
    manager.is_enabled = lambda node, version=None: installed == 'nightly' and version == 'nightly'
    manager.is_disabled = lambda node, version=None: installed == 'disabled-cnr' and version == 'cnr'
    manager.unified_disable = Mock(side_effect=AssertionError('must not disable'))
    manager.unified_enable = Mock(side_effect=AssertionError('must not enable'))
    result = asyncio.run(manager.install_by_id('fixture', '2.0.0'))
    assert result.result is False
    assert result.msg == ('This action is not allowed by the current security configuration. '
                          'See the terminal for details.')
    assert get.call_count == 1


@pytest.mark.parametrize('installed', ['new', 'cnr', 'disabled-cnr'])
@pytest.mark.parametrize('instant', [False, True])
def test_preflight_response_is_reused(core, monkeypatch, installed, instant, tmp_path):
    get = Mock(return_value=api_response('NodeVersionStatusActive'))
    monkeypatch.setattr(core.cnr_utils.requests, 'get', get)
    manager = core.UnifiedManager()
    manager.is_enabled = lambda node, version=None: installed == 'cnr' and version == 'cnr'
    manager.is_disabled = lambda node, version=None: installed == 'disabled-cnr' and version == 'cnr'
    manager.unified_enable = Mock()
    manager.active_nodes['fixture'] = ('1.0.0', str(tmp_path / 'fixture'))
    manager.reserve_cnr_switch = Mock(return_value=True)
    manager.execute_install_script = Mock(return_value=True)
    marker = tmp_path / 'fixture/__init__.py'
    if installed != 'new':
        marker.parent.mkdir()
        marker.write_text('original')
        (marker.parent / '.tracking').write_text('__init__.py')

    def download(url, directory, name):
        (tmp_path / name).write_bytes(b'fixture')

    def extract(archive, directory):
        (Path(directory) / '__init__.py').write_text('replacement')
        return ['__init__.py']

    monkeypatch.setattr(core.manager_downloader, 'download_url', download)
    monkeypatch.setattr(core.manager_downloader, 'basic_download_url', download)
    monkeypatch.setattr(core.manager_util, 'extract_package_as_zip', extract)
    result = asyncio.run(manager.install_by_id('fixture', '2.0.0', instant_execution=instant))
    assert result.result is True
    assert get.call_count == 1
    if installed == 'new' or instant:
        assert marker.read_text() == 'replacement'
        manager.reserve_cnr_switch.assert_not_called()
        manager.execute_install_script.assert_called_once()
        assert manager.execute_install_script.call_args.kwargs['instant_execution'] is instant
    else:
        assert marker.read_text() == 'original'
        manager.reserve_cnr_switch.assert_called_once()
        manager.execute_install_script.assert_not_called()


def test_exact_installed_version_enables_without_registry_lookup(core, monkeypatch, tmp_path):
    manager = core.UnifiedManager()
    installed = tmp_path / '.disabled/fixture@2_0_0'
    installed.mkdir(parents=True)
    (installed / '__init__.py').write_text('already installed')
    manager.cnr_inactive_nodes['fixture'] = {'2.0.0': str(installed)}
    query = Mock(side_effect=AssertionError('activation must not query the Registry'))
    monkeypatch.setattr(core.cnr_utils.requests, 'get', query)
    manager.execute_install_script = Mock(side_effect=AssertionError('activation must not install'))

    result = asyncio.run(manager.install_by_id('fixture', '2.0.0'))

    assert result.result is True
    assert (tmp_path / 'fixture/__init__.py').read_text() == 'already installed'
    assert not installed.exists()
    assert manager.active_nodes['fixture'] == ('2.0.0', str(tmp_path / 'fixture'))
    assert asyncio.run(manager.install_by_id('fixture', '2.0.0')).action == 'skip'
    query.assert_not_called()
    manager.execute_install_script.assert_not_called()


def test_snapshot_denial_preserves_existing_pack_without_retry(core, monkeypatch, tmp_path):
    manager = core.UnifiedManager()
    monkeypatch.setattr(core, 'unified_manager', manager)
    installed = tmp_path / 'fixture'
    installed.mkdir()
    marker = installed / '__init__.py'
    marker.write_text('original')
    (installed / '.tracking').write_text('__init__.py')
    manager.active_nodes['fixture'] = ('1.0.0', str(installed))
    manager.reload = AsyncMock()
    manager.get_custom_nodes = AsyncMock(return_value={})
    monkeypatch.setattr(core.manager_util, 'restore_pip_snapshot', Mock())
    get = Mock(return_value=api_response())
    monkeypatch.setattr(core.cnr_utils.requests, 'get', get)
    download = Mock(side_effect=AssertionError('denied target must not download'))
    monkeypatch.setattr(core.manager_downloader, 'download_url', download)
    monkeypatch.setattr(core.manager_downloader, 'basic_download_url', download)
    snapshot = tmp_path / 'snapshot.json'
    snapshot.write_text(json.dumps({'cnr_custom_nodes': {'fixture': '2.0.0'},
                                    'git_custom_nodes': {}, 'file_custom_nodes': []}))

    asyncio.run(core.restore_snapshot(str(snapshot)))

    assert marker.read_text() == 'original'
    assert manager.active_nodes['fixture'] == ('1.0.0', str(installed))
    assert download.call_count == 0
    assert get.call_count == 1


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_reinstall_stops_when_removal_fails(core, monkeypatch):
    get = Mock(return_value=api_response('NodeVersionStatusActive'))
    monkeypatch.setattr(core.cnr_utils.requests, 'get', get)
    download = Mock(side_effect=AssertionError('failed removal must prevent downloading'))
    monkeypatch.setattr(core.manager_downloader, 'download_url', download)
    manager = core.UnifiedManager()
    manager.unified_uninstall = Mock(return_value=core.ManagedResult('uninstall').fail('cannot remove'))

    result = asyncio.run(manager.reinstall_by_id('fixture', '2.0.0'))

    assert result.result is False
    assert result.msg == 'cannot remove'
    assert get.call_count == 1
    assert download.call_count == 0


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
@pytest.mark.parametrize('version,source', [
    ('nightly', 'manifest'), ('unknown', 'manifest'),
    ('nightly', 'cnr'), ('nightly', 'system-repository'),
])
def test_git_reinstall_replaces_existing_pack(core, monkeypatch, tmp_path, version, source):
    manager = core.UnifiedManager()
    directory = 'repository-name' if source == 'system-repository' else 'fixture'
    installed = tmp_path / directory
    installed.mkdir()
    marker = installed / 'original.txt'
    marker.write_text('original')
    repo_url = f'https://example.invalid/{directory}'
    if version == 'nightly':
        manager.active_nodes['fixture'] = ('nightly', str(installed))
    else:
        manager.unknown_active_nodes['fixture'] = (repo_url, str(installed))
    manager.get_custom_nodes = AsyncMock(return_value={
        'fixture': {'repository': repo_url, 'files': [repo_url]},
    } if source == 'manifest' else {})
    if source != 'manifest':
        manager.cnr_map['fixture'] = {
            'repository': repo_url, 'publisher': None if source == 'system-repository' else {'id': 'fixture'},
        }
    manager.processed_install.add(str(installed / 'install.py'))
    execute = Mock(return_value=True)
    monkeypatch.setattr(core, 'try_install_script', execute)
    monkeypatch.setattr(core.cnr_utils.requests, 'get', Mock(side_effect=AssertionError('Git needs no CNR install query')))

    def clone(url, path, **kwargs):
        assert url == repo_url
        assert not Path(path).exists()
        Path(path).mkdir()
        (Path(path) / 'replacement.txt').write_text('installed')
        (Path(path) / 'install.py').write_text('')
        assert manager.execute_install_script(url, path)
        return core.ManagedResult('install-git')

    manager.repo_install = Mock(side_effect=clone)
    result = asyncio.run(manager.reinstall_by_id('fixture', version))

    assert result.result is True
    assert not marker.exists()
    assert (installed / 'replacement.txt').read_text() == 'installed'
    assert manager.repo_install.call_count == 1
    assert execute.call_count == 1
    assert execute.call_args.args[1] == str(installed)


@pytest.mark.parametrize('status', ['', 'NodeVersionStatusActive', 'NodeVersionStatusFlagged'])
@pytest.mark.parametrize('override', [False, True])
@pytest.mark.parametrize('listen', ['127.0.0.1', '0.0.0.0'])
def test_deferred_switch_reuses_status_with_current_policy(cnr_client, monkeypatch, tmp_path, caplog, status, override, listen):
    from comfy.cli_args import args as server_args
    from comfyui_manager.common import manager_downloader, manager_util

    monkeypatch.setattr(server_args, 'listen', listen)
    # Execute the real function without running prestartup's module-level startup.
    source = Path(cnr_client.__file__).parents[1] / 'prestartup_script.py'
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'execute_lazy_cnr_switch')
    scope = {'__package__': 'comfyui_manager', 'os': os, 'logging': logging,
             'manager_downloader': manager_downloader, 'manager_util': manager_util,
             'default_conf': {'allow_flagged_nodepack_install': str(override)}}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
    from_path, to_path = tmp_path / 'fixture@1.0.0', tmp_path / 'fixture'
    from_path.mkdir()
    (from_path / '.tracking').write_text('__init__.py')
    (from_path / '__init__.py').write_text('')

    def download(url, directory, name):
        (Path(directory) / name).write_bytes(b'fixture')

    downloader = Mock(side_effect=download)
    monkeypatch.setattr(manager_downloader, 'download_url', downloader)
    monkeypatch.setattr(manager_util, 'extract_package_as_zip', lambda *a: {'__init__.py'})
    monkeypatch.setattr(cnr_client.requests, 'get', Mock(side_effect=AssertionError('no CNR query')))
    args = ('fixture', 'https://example.invalid/archive.zip', str(from_path), str(to_path), False, str(tmp_path))
    # Omit the added argument for the old on-disk reservation format.
    result = scope['execute_lazy_cnr_switch'](*args, *([status] if status else []))
    allowed = status == 'NodeVersionStatusActive' or override or listen == '127.0.0.1'
    assert result is allowed
    assert downloader.call_count == int(allowed)
    assert to_path.exists() is allowed
    assert from_path.exists() is not allowed
    if not allowed and not status:
        assert 'stored Registry status is missing' in caplog.text
        assert 'Request the installation again' in caplog.text
    elif not allowed:
        for detail in ('--listen 127.0.0.1', '--listen ::1', '[default]',
                       'allow_flagged_nodepack_install = true', 'Restart ComfyUI'):
            assert detail in caplog.text
    else:
        assert 'allow_flagged_nodepack_install' not in caplog.text
