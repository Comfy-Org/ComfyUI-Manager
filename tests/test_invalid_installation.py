import ast
import asyncio
import concurrent.futures
import importlib.util
import io
import logging
import os
import re
import shutil
import sys
import threading
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import rich.console
import rich.markup

from _install_flags_testutil import import_reader
from js_lift import NODE, JsSource, line_containing, parse, run_node, slice_braced
from legacy_html_testutil import PACKAGE, load_functions

REGISTRY = [
    {'id': 'comfyui-foo', 'name': 'Foo', 'repository': 'https://github.com/example/ComfyUI-Foo',
     'publisher': {'name': 'example'}, 'description': '', 'latest_version': {'version': '1.0.1'}},
    {'id': 'comfyui-baz', 'name': 'Baz', 'repository': 'https://github.com/example/comfyui-baz',
     'publisher': {'name': 'example'}, 'description': '', 'latest_version': {'version': '2.0.0'}},
]
FOO_URL = 'https://github.com/example/ComfyUI-Foo'
BAR_URL = 'https://github.com/example/ComfyUI-Bar'
NODE_LIST = [
    {'author': 'example', 'title': 'ComfyUI-Foo', 'reference': FOO_URL, 'files': [FOO_URL],
     'install_type': 'git-clone', 'description': ''},
    {'author': 'example', 'title': 'ComfyUI-Bar', 'reference': BAR_URL, 'files': [BAR_URL],
     'install_type': 'git-clone', 'description': ''},
]
INVALID = {'ver': 'unknown', 'aux_id': None, 'invalid_installation': True}
GUIDANCE = ('This nodepack was not installed through ComfyUI-Manager, or its installation is damaged, so the Manager '
            'cannot update it. Reinstalling deletes its folder and installs the nodepack again.')


def pack(path, project_name=None, version='1.0.1', tracking=False, git_url=None):
    path.mkdir(parents=True)
    (path / '__init__.py').write_text('NODE_CLASS_MAPPINGS = {}\n')
    if project_name is not None:
        (path / 'pyproject.toml').write_text(f'[project]\nname = "{project_name}"\nversion = "{version}"\n')
    if tracking:
        (path / '.tracking').write_text('__init__.py\npyproject.toml\n')
    if git_url is not None:
        (path / '.git').mkdir()
        (path / '.git/HEAD').write_text('0123456789abcdef0123456789abcdef01234567\n')
        (path / '.git/config').write_text(f'[remote "origin"]\n\turl = {git_url}\n')
    return path


@pytest.fixture(params=['glob', 'legacy'])
def core(request):
    return import_reader(request.param)


@pytest.fixture
def custom_nodes(core, monkeypatch, tmp_path):
    custom_nodes = tmp_path / 'custom_nodes'
    custom_nodes.mkdir()
    monkeypatch.setattr(sys.modules['folder_paths'], 'get_folder_paths', lambda name: [str(custom_nodes)], raising=False)
    monkeypatch.setattr(core, 'get_default_custom_nodes_path', lambda: str(custom_nodes))
    config = {'network_mode': 'public', 'channel_url': core.DEFAULT_CHANNEL, 'http_channel_enabled': False,
              'allow_flagged_nodepack_install': False}
    monkeypatch.setattr(core, 'get_config', lambda: config)

    async def get_cnr_data(*args, **kwargs):
        return REGISTRY

    async def get_data_by_mode(mode, filename, channel_url=None):
        return {'custom_nodes': [dict(item) for item in NODE_LIST]}

    monkeypatch.setattr(core.cnr_utils, 'get_cnr_data', get_cnr_data)
    monkeypatch.setattr(core, 'get_data_by_mode', get_data_by_mode)
    manager = core.UnifiedManager()
    manager.execute_install_script = Mock(return_value=True)
    monkeypatch.setattr(core, 'unified_manager', manager)
    return custom_nodes


def reload(core):
    asyncio.run(core.unified_manager.reload('cache'))
    return core.unified_manager


def flagged_rows(core):
    rows = asyncio.run(core.get_unified_total_nodes(core.DEFAULT_CHANNEL, 'cache'))
    return {key: row['state'] for key, row in rows.items() if row.get('invalid-installation')}


def archive_of_foo(url, directory, name):
    with zipfile.ZipFile(Path(directory) / name, 'w') as archive:
        archive.writestr('__init__.py', 'NODE_CLASS_MAPPINGS = {}  # 1.0.1\n')
        archive.writestr('pyproject.toml', '[project]\nname = "comfyui-foo"\nversion = "1.0.1"\n')


def refused(url, directory, name):
    raise urllib.error.URLError(ConnectionRefusedError(111, 'Connection refused'))


def block_page(url, directory, name):
    (Path(directory) / name).write_text('<html><body>Access blocked</body></html>')


def registry_api(monkeypatch, core, status='NodeVersionStatusActive', download=archive_of_foo):
    monkeypatch.setattr(core.cnr_utils.requests, 'get', Mock(return_value=SimpleNamespace(
        status_code=200, json=lambda: {
            'id': 'version-id', 'node_id': 'comfyui-foo', 'version': '1.0.1', 'status': status,
            'downloadUrl': 'https://example.invalid/comfyui-foo.zip'})))
    monkeypatch.setattr(core.manager_funcs, 'is_flagged_install_allowed', lambda node_id: False)
    monkeypatch.setattr(core.manager_downloader, 'download_url', Mock(side_effect=download))


def files(path):
    return {x.relative_to(path).as_posix(): x.read_text() for x in sorted(Path(path).rglob('*')) if x.is_file()}


def listing(custom_nodes):
    names = sorted(x.name for x in custom_nodes.iterdir() if x.name != '.disabled')
    disabled = custom_nodes / '.disabled'
    return names + (sorted(f'.disabled/{x.name}' for x in disabled.iterdir()) if disabled.exists() else [])


def git_clone_stand_in(monkeypatch, core, fails=False):
    def clone(url, path, **kwargs):
        if fails:
            Path(path, '.git').mkdir(parents=True)
            raise OSError('the remote end hung up unexpectedly')
        pack(Path(path), git_url=url)
        return SimpleNamespace(clear_cache=lambda: None, close=lambda: None, git=SimpleNamespace(clear_cache=lambda: None))

    run_script = core.manager_funcs.run_script

    def helper_process(cmd, *args, **kwargs):
        if '--clone' not in cmd:
            return run_script(cmd, *args, **kwargs)
        try:
            clone(cmd[-2], cmd[-1])
        except OSError:
            return 1
        return 0

    monkeypatch.setattr(core.manager_funcs, 'run_script', helper_process)
    if hasattr(core, 'clone_repo'):
        monkeypatch.setattr(core, 'clone_repo', clone)
    else:
        monkeypatch.setattr(core.git.Repo, 'clone_from', staticmethod(clone))


@pytest.mark.parametrize('folder, project_name, cnr_id, row', [
    ('comfyui-foo', 'comfyui-foo', 'comfyui-foo', 'comfyui-foo'),
    ('ComfyUI-Foo-main', 'ComfyUI-Foo', 'comfyui-foo', 'comfyui-foo'),
    ('comfyui-baz', 'comfyui-foo', 'comfyui-foo', 'comfyui-foo'),
    ('comfyui-baz', 'not-in-the-registry', 'comfyui-baz', 'comfyui-baz'),
    ('ComfyUI-Baz', None, 'comfyui-baz', 'comfyui-baz'),
    ('ComfyUI-Bar', None, '', 'ComfyUI-Bar'),
    ('Something-Else', None, '', None),
], ids=['no-tracking', 'github-zip', 'project-name-first', 'folder-name', 'folder-name-case', 'non-registry', 'no-row'])
def test_the_pack_of_an_invalid_installation(core, custom_nodes, folder, project_name, cnr_id, row):
    pack(custom_nodes / folder, project_name)
    reload(core)

    assert core.get_installed_node_packs() == {folder: {**INVALID, 'cnr_id': cnr_id, 'enabled': True}}
    assert flagged_rows(core) == ({row: 'enabled'} if row else {})


@pytest.mark.parametrize('folder, project_name, before, after', [
    ('comfyui-foo', 'comfyui-foo', 'comfyui-foo', 'comfyui-foo'),
    ('ComfyUI-Foo-main', 'ComfyUI-Foo', 'comfyui-foo', 'comfyui-foo'),
    ('comfyui-baz', 'not-in-the-registry', 'not-in-the-registry', 'comfyui-baz'),
    ('Something-Else', 'something-else', 'something-else', 'something-else'),
    ('comfyui-baz', None, '', 'comfyui-baz'),
    ('ComfyUI-Bar', None, '', ''),
], ids=['no-tracking', 'github-zip', 'folder-name', 'not-in-the-registry', 'no-pyproject', 'non-registry'])
def test_the_installed_map_tells_the_pack_before_the_registry_list_is_loaded(core, custom_nodes, folder, project_name,
                                                                            before, after):
    pack(custom_nodes / folder, project_name)

    assert not core.unified_manager.cnr_map
    assert core.get_installed_node_packs() == {folder: {**INVALID, 'cnr_id': before, 'enabled': True}}
    reload(core)
    assert core.get_installed_node_packs() == {folder: {**INVALID, 'cnr_id': after, 'enabled': True}}


def load_the_registry_list(manager):
    for cnr in REGISTRY:
        manager.cnr_map[cnr['id']] = cnr
        manager.repo_cnr_map[cnr['repository']] = cnr


@pytest.mark.parametrize('asked', ['before the registry list has loaded', 'after it has loaded'])
def test_which_nodepack_a_folder_is_does_not_depend_on_when_the_scan_ran(core, custom_nodes, monkeypatch, asked):
    folder = pack(custom_nodes / 'ComfyUI-Foo-main', 'ComfyUI-Foo')
    registry_api(monkeypatch, core)

    async def not_loaded_yet(*args, **kwargs):
        return []

    monkeypatch.setattr(core.cnr_utils, 'get_cnr_data', not_loaded_yet)
    manager = reload(core)
    if asked == 'after it has loaded':
        load_the_registry_list(manager)

    assert core.get_installed_node_packs() == {'ComfyUI-Foo-main': {**INVALID, 'cnr_id': 'comfyui-foo', 'enabled': True}}
    assert f'Reinstalling deletes its folder ({folder})' in manager.unified_update('comfyui-foo').msg

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is True, result.msg
    assert listing(custom_nodes) == ['comfyui-foo']


def test_uninstall_by_id_after_the_registry_list_has_loaded_removes_what_the_scan_found_before(core, custom_nodes,
                                                                                              monkeypatch):
    pack(custom_nodes / 'ComfyUI-Foo-main', 'ComfyUI-Foo')

    async def not_loaded_yet(*args, **kwargs):
        return []

    monkeypatch.setattr(core.cnr_utils, 'get_cnr_data', not_loaded_yet)
    manager = reload(core)
    load_the_registry_list(manager)

    assert manager.unified_uninstall('comfyui-foo', False).result is True
    assert listing(custom_nodes) == []


@pytest.mark.parametrize('valid, row, state', [
    ('comfyui-foo', 'comfyui-foo', 'enabled'),
    ('.disabled/comfyui-foo@1_0_1', 'comfyui-foo', 'disabled'),
    ('bar-clone', 'ComfyUI-Bar', 'enabled'),
], ids=['registry-enabled', 'registry-disabled', 'git'])
def test_a_valid_installation_beside_a_stray_copy_keeps_its_row(core, custom_nodes, capsys, valid, row, state):
    if row == 'comfyui-foo':
        pack(custom_nodes / valid, 'comfyui-foo', tracking=True)
        stray = pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    else:
        pack(custom_nodes / valid, git_url=BAR_URL)
        stray = pack(custom_nodes / '.disabled/ComfyUI-Bar')
    reload(core)

    rows = asyncio.run(core.get_unified_total_nodes(core.DEFAULT_CHANNEL, 'cache'))

    assert rows[row]['state'] == state
    assert 'invalid-installation' not in rows[row]
    assert core.get_installed_node_packs()[stray.name]['invalid_installation'] is True
    core.check_invalid_nodes()
    assert str(stray) in capsys.readouterr().out


def test_a_valid_installation_and_its_stray_copy_go_together(core, custom_nodes, monkeypatch):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
    pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    registry_api(monkeypatch, core)
    manager = reload(core)

    assert asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1')).result is True
    assert listing(custom_nodes) == ['comfyui-foo']
    assert '# 1.0.1' in (custom_nodes / 'comfyui-foo/__init__.py').read_text()


@pytest.mark.parametrize('order', [['bar-clone', 'ComfyUI-Bar'], ['ComfyUI-Bar', 'bar-clone']],
                         ids=['clone-read-first', 'invalid-read-first'])
def test_a_valid_clone_keeps_its_key_whichever_folder_is_read_first(core, custom_nodes, monkeypatch, capsys, order):
    pack(custom_nodes / 'bar-clone', git_url=BAR_URL)
    invalid = pack(custom_nodes / 'ComfyUI-Bar')
    listdir = os.listdir
    monkeypatch.setattr(os, 'listdir', lambda path='.': list(order) if str(path) == str(custom_nodes) else listdir(path))
    reload(core)

    assert flagged_rows(core) == {}
    assert update_all(monkeypatch, core) == ['ComfyUI-Bar']
    core.check_invalid_nodes()
    assert f'{invalid} (nodepack: ComfyUI-Bar)' in capsys.readouterr().out.splitlines()


@pytest.mark.parametrize('stray', ['disabled', 'in-another-custom-nodes-path'])
def test_the_installed_map_lists_the_valid_installation_of_a_name_that_a_stray_copy_has(core, custom_nodes, monkeypatch,
                                                                                        tmp_path, stray):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', tracking=True)
    if stray == 'disabled':
        pack(custom_nodes / '.disabled/comfyui-foo', 'comfyui-foo')
    else:
        other = tmp_path / 'other_custom_nodes'
        pack(other / 'comfyui-foo', 'comfyui-foo')
        monkeypatch.setattr(sys.modules['folder_paths'], 'get_folder_paths', lambda name: [str(custom_nodes), str(other)])
    reload(core)

    assert core.get_installed_node_packs() == {
        'comfyui-foo': {'ver': '1.0.1', 'cnr_id': 'comfyui-foo', 'aux_id': None, 'enabled': True}}


@pytest.mark.parametrize('folder, project_name, cnr_id, row', [
    ('ComfyUI-Bar', None, '', 'ComfyUI-Bar'), ('ComfyUI-Foo-main', 'comfyui-foo', 'comfyui-foo', 'comfyui-foo'),
], ids=['non-registry', 'registry'])
def test_a_disabled_invalid_installation(core, custom_nodes, folder, project_name, cnr_id, row):
    pack(custom_nodes / '.disabled' / folder, project_name)
    reload(core)

    assert core.get_installed_node_packs() == {folder: {**INVALID, 'cnr_id': cnr_id, 'enabled': False}}
    assert flagged_rows(core) == {row: 'disabled'}


def test_what_is_never_an_invalid_installation(core, custom_nodes, capsys):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', tracking=True)
    pack(custom_nodes / 'ComfyUI-Bar', git_url=BAR_URL)
    pack(custom_nodes / 'not-in-the-registry', 'not-in-the-registry', version='3.0.0', tracking=True)
    pack(custom_nodes / 'tracking-without-pyproject', tracking=True)
    pack(custom_nodes / 'comfyui-manager', 'comfyui-manager')
    (custom_nodes / '__pycache__').mkdir()
    (custom_nodes / '.disabled/.trash').mkdir(parents=True)
    (custom_nodes / 'single_file_node.py').write_text('')
    (custom_nodes / '.ipynb_checkpoints').mkdir()
    (custom_nodes / '.git').mkdir()
    (custom_nodes / '__MACOSX').mkdir()
    (custom_nodes / '.disabled/__pycache__').mkdir()
    reload(core)

    assert core.get_installed_node_packs() == {
        'comfyui-foo': {'ver': '1.0.1', 'cnr_id': 'comfyui-foo', 'aux_id': None, 'enabled': True},
        'ComfyUI-Bar': {'ver': '0123456789abcdef0123456789abcdef01234567', 'cnr_id': '',
                        'aux_id': 'example/ComfyUI-Bar', 'enabled': True},
        'not-in-the-registry': {'ver': '3.0.0', 'cnr_id': 'not-in-the-registry', 'aux_id': None, 'enabled': True},
    }
    assert flagged_rows(core) == {}
    core.check_invalid_nodes()
    assert 'Nodes requiring reinstallation' not in capsys.readouterr().out


def test_a_symbolic_link_is_never_an_invalid_installation(core, custom_nodes, capsys, tmp_path):
    try:
        (custom_nodes / 'comfyui-baz').symlink_to(pack(tmp_path / 'elsewhere/comfyui-baz', 'comfyui-baz'),
                                                  target_is_directory=True)
        (custom_nodes / 'ComfyUI-Qux-main').symlink_to(pack(tmp_path / 'elsewhere/ComfyUI-Qux-main', 'comfyui-foo'),
                                                       target_is_directory=True)
    except OSError:  # Windows without Developer Mode or the privilege to create a symbolic link
        pytest.skip('the platform refuses to create a symbolic link')
    reload(core)

    assert core.get_installed_node_packs() == {}
    assert flagged_rows(core) == {}
    core.check_invalid_nodes()
    assert capsys.readouterr().out == ''


def test_a_junction_is_never_an_invalid_installation(core, custom_nodes, monkeypatch, capsys):
    from comfyui_manager.common.node_package import IO_REPARSE_TAG_MOUNT_POINT

    class JunctionStat:
        st_reparse_tag = IO_REPARSE_TAG_MOUNT_POINT

        def __init__(self, result):
            self._result = result

        def __getattr__(self, name):
            return getattr(self._result, name)

    junction = pack(custom_nodes / 'comfyui-foo', 'comfyui-foo')
    before = files(junction)
    lstat = os.lstat
    monkeypatch.setattr(os, 'lstat', lambda path, *args, **kwargs: (
        JunctionStat(lstat(path, *args, **kwargs)) if os.fspath(path) == str(junction) else lstat(path, *args, **kwargs)))
    monkeypatch.delattr(os.path, 'isjunction', raising=False)
    registry_api(monkeypatch, core)
    manager = reload(core)

    assert core.get_installed_node_packs() == {}
    assert flagged_rows(core) == {}
    core.check_invalid_nodes()
    assert 'Nodes requiring reinstallation' not in capsys.readouterr().out
    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
    assert result.result is False
    assert files(junction) == before


def test_a_reload_forgets_a_folder_that_is_gone(core, custom_nodes):
    folder = pack(custom_nodes / 'comfyui-foo', 'comfyui-foo')
    assert flagged_rows(core) == {'comfyui-foo': 'enabled'}

    (folder / '.tracking').write_text('__init__.py\n')

    assert flagged_rows(core) == {}


@pytest.mark.parametrize('folder, project_name', [('ComfyUI-Foo-main', 'comfyui-foo'), ('ComfyUI-Bar', None)],
                         ids=['of-a-registry-nodepack', 'of-another'])
def test_by_its_folder_name_an_invalid_installation_is_disabled_enabled_and_uninstalled(core, custom_nodes, folder,
                                                                                        project_name):
    pack(custom_nodes / folder, project_name)
    manager = reload(core)
    entry = {**INVALID, 'cnr_id': project_name or ''}

    manager.unified_disable(folder, True)
    assert listing(custom_nodes) == [f'.disabled/{folder}']
    assert core.get_installed_node_packs() == {folder: {**entry, 'enabled': False}}

    manager.unified_enable(folder, 'unknown')
    assert listing(custom_nodes) == [folder]
    assert core.get_installed_node_packs() == {folder: {**entry, 'enabled': True}}

    manager.unified_uninstall(folder, True)
    assert listing(custom_nodes) == []


@pytest.mark.parametrize('move', ['disable', 'enable'])
def test_a_reinstall_finds_an_invalid_installation_that_disable_or_enable_moved(core, custom_nodes, monkeypatch, capsys,
                                                                               move):
    folder = pack(custom_nodes / ('ComfyUI-Foo-main' if move == 'disable' else '.disabled/ComfyUI-Foo-main'), 'comfyui-foo')
    registry_api(monkeypatch, core)
    manager = reload(core)

    if move == 'disable':
        manager.unified_disable('ComfyUI-Foo-main', True)
    else:
        manager.unified_enable('ComfyUI-Foo-main', 'unknown')

    [moved] = {custom_nodes / 'ComfyUI-Foo-main', custom_nodes / '.disabled/ComfyUI-Foo-main'} - {folder}
    core.check_invalid_nodes()
    assert f'{moved} (nodepack: comfyui-foo)' in capsys.readouterr().out.splitlines()
    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
    assert result.result is True, result.msg
    assert listing(custom_nodes) == ['comfyui-foo']


@pytest.mark.parametrize('core', ['glob'], indirect=True)
def test_by_its_folder_name_the_v4_queue_disables_enables_and_uninstalls_an_invalid_installation(core, custom_nodes,
                                                                                               monkeypatch):
    pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    models = data_models(monkeypatch)

    def run(kind, params):
        task = models.QueueTaskItem.model_validate({'ui_id': 'ui', 'client_id': 'client', 'kind': kind, 'params': params})
        assert [(kind, msg) for kind, msg, status in run_glob_worker(monkeypatch, core, task)] == [(kind, 'success')]
        return listing(custom_nodes)

    assert run('disable', {'node_name': 'ComfyUI-Foo-main', 'is_unknown': True}) == ['.disabled/ComfyUI-Foo-main']
    assert run('enable', {'cnr_id': 'ComfyUI-Foo-main'}) == ['ComfyUI-Foo-main']
    assert run('uninstall', {'node_name': 'ComfyUI-Foo-main', 'is_unknown': True}) == []


def test_the_notice_lists_the_invalid_folders_that_a_reload_found(core, custom_nodes, capsys):
    bar = pack(custom_nodes / 'ComfyUI-Bar')
    foo = pack(custom_nodes / '.disabled/ComfyUI-Foo-main', 'comfyui-foo')
    reload(core)

    core.check_invalid_nodes()

    out = capsys.readouterr().out
    assert 'Nodes requiring reinstallation have been detected' in out
    assert 'not installed through ComfyUI-Manager, or their installation is damaged' in out
    assert f'{bar} (nodepack: ComfyUI-Bar)' in out.splitlines()
    assert f'{foo} (nodepack: comfyui-foo)' in out.splitlines()
    assert 'unfinished reinstall notice' not in out


def test_two_reloads_that_interleave_tell_a_folder_once(core, custom_nodes, monkeypatch, capsys):
    folder = pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')

    async def loading(*args, **kwargs):
        await asyncio.sleep(0)
        return REGISTRY

    monkeypatch.setattr(core.cnr_utils, 'get_cnr_data', loading)

    async def both():
        await asyncio.gather(core.unified_manager.reload('remote'), core.unified_manager.reload('cache'))

    asyncio.run(both())
    core.check_invalid_nodes()

    assert capsys.readouterr().out.count(str(folder)) == 1


@pytest.mark.parametrize('reader', ['uninstall-by-id', 'notice'])
def test_a_folder_recorded_while_the_records_are_read_does_not_stop_the_reader(core, custom_nodes, monkeypatch, capsys,
                                                                              reader):
    folder = pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    manager = reload(core)
    late = pack(custom_nodes / 'ComfyUI-Foo-copy', 'comfyui-foo')
    pack_id, recorded = manager.invalid_pack_id, []

    def recording_one_more(installation):
        if not recorded:
            recorded.append(late)
            manager.update_cache_at_path(str(late))
        return pack_id(installation)

    monkeypatch.setattr(manager, 'invalid_pack_id', recording_one_more)

    if reader == 'notice':
        core.check_invalid_nodes()
        assert f'{folder} (nodepack: comfyui-foo)' in capsys.readouterr().out.splitlines()
    else:
        assert manager.unified_uninstall('comfyui-foo', False).result is True
        assert not folder.exists()
    assert recorded == [late]


@pytest.mark.parametrize('network_mode', ['public', 'private', 'offline'])
def test_the_startup_notice_does_not_depend_on_the_network_mode(core, custom_nodes, monkeypatch, capsys, network_mode):
    server = core.__name__.split('.')[-2]
    folder = pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    config = dict(core.get_config(), network_mode=network_mode, default_cache_as_channel_url=False)
    monkeypatch.setattr(core, 'get_config', lambda: config)

    async def no_channel(uri, silent=False):
        raise OSError('no network in this test')

    manager_util = SimpleNamespace(get_data=no_channel, simple_hash=core.manager_util.simple_hash, cache_dir='',
                                   write_cache_file=lambda *args: False)
    startup = load_functions(PACKAGE / server / 'manager_server.py', {'default_cache_update'}, {
        'os': os, 'logging': logging, 'traceback': SimpleNamespace(print_exc=lambda: None), 'asyncio': asyncio,
        'manager_util': manager_util, 'core': core, 'ManagerDatabaseSource': data_models(monkeypatch).ManagerDatabaseSource})

    asyncio.run(startup['default_cache_update']())

    out = capsys.readouterr().out
    assert 'Nodes requiring reinstallation have been detected' in out
    assert str(folder) in out


@pytest.mark.parametrize('invalid', [True, False], ids=['after-the-invalid-installations', 'alone'])
def test_the_notice_tells_the_folders_that_a_reinstall_which_did_not_finish_kept(core, custom_nodes, monkeypatch, capsys,
                                                                                 tmp_path, invalid):
    other = tmp_path / 'other_custom_nodes'
    other.mkdir()
    monkeypatch.setattr(sys.modules['folder_paths'], 'get_folder_paths', lambda name: [str(custom_nodes), str(other)])
    held = [a_users_folder(custom_nodes / '.disabled/.reinstall/0f1e2d3c/ComfyUI-Foo-main'),
            a_users_folder(other / '.disabled/.reinstall/9a8b7c6d/ComfyUI-Bar', None)]
    if invalid:
        pack(custom_nodes / 'ComfyUI-Baz-main', 'comfyui-baz')
    before = files(tmp_path)
    reload(core)

    core.check_invalid_nodes()

    out = capsys.readouterr().out
    assert ('-------------------- ComfyUI-Manager unfinished reinstall notice ---------\n'
            '\n'
            'A reinstall set these nodepack folders aside, and either did not finish or could not delete them.\n'
            'To get one back, stop ComfyUI and move it into custom_nodes, in place of what the reinstall left there. '
            'Otherwise delete it.\n'
            '\n'
            f'{held[0]}\n'
            f'{held[1]}\n'
            '\n'
            '---------------------------------------------------------------------------\n') in out
    assert ('invalid nodes notice' in out) is invalid
    if invalid:
        assert out.index('invalid nodes notice') < out.index('unfinished reinstall notice')
    assert files(tmp_path) == before


@pytest.mark.parametrize('core', ['glob'], indirect=True)
def test_fetching_updates_leaves_an_invalid_installation_alone(core, custom_nodes, capsys):
    pack(custom_nodes / 'ComfyUI-Bar')
    manager = reload(core)

    assert manager.fetch_or_pull_git_repo(is_pull=True) == {'updated': [], 'failed': []}
    assert 'Traceback' not in capsys.readouterr().err


@pytest.mark.parametrize('core', ['glob'], indirect=True)
def test_fetching_updates_reaches_a_git_pack_whose_id_a_stray_invalid_folder_shares(core, custom_nodes, monkeypatch):
    clone = pack(custom_nodes / 'bar-clone', git_url=BAR_URL)
    pack(custom_nodes / '.disabled/ComfyUI-Bar')
    manager = reload(core)
    fetched = []
    monkeypatch.setattr(core, 'git_repo_update_check_with', lambda path, **kwargs: fetched.append(path) or (True, True))

    assert manager.fetch_or_pull_git_repo(is_pull=False) == {'updated': ['ComfyUI-Bar@unknown'], 'failed': []}
    assert fetched == [str(clone)]


def update_all(monkeypatch, core):
    models = data_models(monkeypatch)
    queued = []
    server = core.__name__.split('.')[-2]

    async def save_snapshot_with_postfix(postfix):
        pass

    monkeypatch.setattr(core, 'save_snapshot_with_postfix', save_snapshot_with_postfix, raising=False)
    namespace = {name: getattr(models, name) for name in dir(models) if not name.startswith('_')}
    namespace.update(
        core=core, logging=logging, os=os,
        web=SimpleNamespace(Response=lambda status: status),
        security_utils=SimpleNamespace(is_allowed_security_level=lambda level: True),
        is_allowed_security_level=lambda level: True,
        task_queue=SimpleNamespace(put=lambda task: queued.append(task.params.node_name)),
        temp_queue_batch=Mock(append=lambda item: queued.append(item[1][1])),
        task_worker_lock=Mock(__enter__=Mock(), __exit__=Mock(return_value=False)), task_worker_thread=None,
    )
    path = PACKAGE / server / 'manager_server.py'
    nodes = [node for node in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(node, ast.AsyncFunctionDef) and node.name == '_update_all']
    exec(compile(ast.Module(nodes, []), str(path), 'exec'), namespace)
    if server == 'glob':
        params = models.UpdateAllQueryParams(client_id='client', ui_id='ui', mode='cache')
    else:
        params = {'mode': 'cache'}
    assert asyncio.run(namespace['_update_all'](params)) == 200
    return queued


def test_update_all_queues_no_update_for_an_invalid_installation(core, custom_nodes, monkeypatch):
    pack(custom_nodes / 'ComfyUI-Bar')
    pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    pack(custom_nodes / 'comfyui-baz', 'comfyui-baz', version='2.0.0', tracking=True)
    pack(custom_nodes / 'ComfyUI-Qux', git_url='https://github.com/example/ComfyUI-Qux')

    assert sorted(update_all(monkeypatch, core)) == ['ComfyUI-Qux', 'comfyui-baz']


def test_update_all_updates_a_git_pack_whose_id_a_stray_invalid_folder_shares(core, custom_nodes, monkeypatch):
    pack(custom_nodes / 'bar-clone', git_url=BAR_URL)
    pack(custom_nodes / '.disabled/ComfyUI-Bar')

    assert update_all(monkeypatch, core) == ['ComfyUI-Bar']


def test_updating_an_invalid_installation_says_why_it_fails(core, custom_nodes):
    folder = pack(custom_nodes / 'ComfyUI-Bar')
    manager = reload(core)

    result = manager.unified_update('ComfyUI-Bar', 'unknown')

    assert result.result is False
    assert result.msg == (f"Cannot update 'ComfyUI-Bar': this nodepack was not installed through ComfyUI-Manager, or its "
                          f"installation is damaged, so the Manager cannot update it. Reinstalling deletes its folder "
                          f"({folder}) and installs the nodepack again.")


@pytest.mark.parametrize('version', [None, 'unknown', 'nightly', '1.0.1'])
def test_updating_an_invalid_installation_fails_the_same_whatever_version_is_asked(core, custom_nodes, version):
    folder = pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    manager = reload(core)

    result = manager.unified_update('comfyui-foo', version)

    assert result.result is False
    assert result.msg.startswith("Cannot update 'comfyui-foo': this nodepack was not installed through ComfyUI-Manager")
    assert f'Reinstalling deletes its folder ({folder})' in result.msg


def test_a_registry_install_beside_a_stray_invalid_folder_is_updated_as_before(core, custom_nodes, monkeypatch):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', tracking=True)
    pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    registry_api(monkeypatch, core)
    manager = reload(core)

    result = manager.unified_update('comfyui-foo')

    assert (result.result, result.action, result.msg) == (True, 'skip', 'Up to date')


@pytest.mark.parametrize('node_id, is_unknown, left', [
    ('comfyui-foo', False, ['ComfyUI-Bar-backup', 'ComfyUI-Foo-main', 'bar-clone', 'comfyui-bar']),
    ('ComfyUI-Bar', True, ['ComfyUI-Bar-backup', 'ComfyUI-Foo-main', 'comfyui-bar', 'comfyui-foo']),
], ids=['registry', 'unknown'])
def test_uninstall_leaves_the_invalid_installations_of_the_nodepack_in_other_folders(core, custom_nodes, node_id,
                                                                                     is_unknown, left):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', tracking=True)
    pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    pack(custom_nodes / 'bar-clone', git_url=BAR_URL)
    pack(custom_nodes / 'ComfyUI-Bar-backup', 'ComfyUI-Bar')
    pack(custom_nodes / 'comfyui-bar')
    manager = reload(core)

    result = manager.unified_uninstall(node_id, is_unknown)

    assert result.result is True
    assert listing(custom_nodes) == left


@pytest.mark.parametrize('folder, project_name, node_id, is_unknown', [
    ('comfyui-foo', 'comfyui-foo', 'comfyui-foo', False),
    ('ComfyUI-Bar', None, 'ComfyUI-Bar', True),
], ids=['by-id', 'by-folder-name'])
def test_an_install_right_after_the_uninstall_of_an_invalid_installation_installs_the_nodepack(core, custom_nodes,
                                                                                              monkeypatch, folder,
                                                                                              project_name, node_id,
                                                                                              is_unknown):
    pack(custom_nodes / folder, project_name)
    registry_api(monkeypatch, core)
    git_clone_stand_in(monkeypatch, core)
    manager = reload(core)

    assert manager.unified_uninstall(node_id, is_unknown).result is True
    result = asyncio.run(manager.install_by_id(node_id, None, core.DEFAULT_CHANNEL, 'cache'))

    assert result.result is True, result.msg
    assert result.action != 'skip'
    assert listing(custom_nodes) == [node_id]


@pytest.mark.parametrize('where', ['', '.disabled/'], ids=['enabled', 'disabled'])
def test_after_an_uninstall_by_folder_name_its_nodepack_has_no_invalid_installation_left(core, custom_nodes, where):
    folder = pack(custom_nodes / (where + 'ComfyUI-Foo-main'), 'comfyui-foo')
    manager = reload(core)

    assert manager.unified_uninstall('ComfyUI-Foo-main', True).result is True
    assert not folder.exists()
    msg = manager.unified_update('comfyui-foo').msg or ''
    assert 'not installed through ComfyUI-Manager' not in msg
    assert str(folder) not in msg


def cannot_delete(monkeypatch, core, locked, schedule_fails=False, movable=False):
    rmtree, rename = shutil.rmtree, os.rename

    def held_open(path, *args, **kwargs):
        if not locked(os.fspath(path)):
            return rmtree(path, *args, **kwargs)
        if not kwargs.get('ignore_errors'):
            raise PermissionError(13, 'The process cannot access the file because another process uses it', os.fspath(path))

    def move(src, dst):
        if locked(os.fspath(src)) and not movable:
            raise PermissionError(13, 'The process cannot access the file because another process uses it', os.fspath(src))
        return rename(src, dst)

    scheduled = []

    def reserve_script(title, cmd):
        scheduled.append(cmd)
        if schedule_fails:
            raise PermissionError(13, 'Permission denied', 'install-scripts.txt')

    monkeypatch.setattr(core.shutil, 'rmtree', held_open)
    monkeypatch.setattr(os, 'rename', move)
    monkeypatch.setattr(core.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(core, 'reserve_script', reserve_script)
    return scheduled


@pytest.mark.parametrize('where', ['', '.disabled/'], ids=['enabled', 'disabled'])
@pytest.mark.parametrize('name, project_name, node_id, is_unknown', [
    ('ComfyUI-Bar', None, 'ComfyUI-Bar', True),
    ('ComfyUI-Foo-main', 'comfyui-foo', 'ComfyUI-Foo-main', True),
    ('ComfyUI-Foo-main', 'comfyui-foo', 'comfyui-foo', False),
], ids=['by-its-nodepack-which-is-its-folder-name', 'by-folder-name', 'by-id'])
def test_uninstall_of_an_invalid_installation_that_cannot_be_deleted_fails(core, custom_nodes, monkeypatch, capsys, where,
                                                                          name, project_name, node_id, is_unknown):
    folder = pack(custom_nodes / (where + name), project_name)
    manager = reload(core)
    scheduled = cannot_delete(monkeypatch, core, lambda path: path == str(folder))

    with pytest.raises(PermissionError):
        manager.unified_uninstall(node_id, is_unknown)

    assert scheduled == []
    assert folder.exists()
    core.check_invalid_nodes()
    assert f'{folder} (nodepack: {project_name or name})' in capsys.readouterr().out.splitlines()


@pytest.mark.parametrize('folder', ['comfyui-foo', 'ComfyUI-Foo-main'])
def test_reinstall_makes_a_registry_install(core, custom_nodes, monkeypatch, folder):
    pack(custom_nodes / folder, 'comfyui-foo')
    registry_api(monkeypatch, core)
    manager = reload(core)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is True, result.msg
    assert [path.name for path in custom_nodes.iterdir()] == ['comfyui-foo']
    assert (custom_nodes / 'comfyui-foo/.tracking').exists()
    reload(core)
    assert core.get_installed_node_packs() == {
        'comfyui-foo': {'ver': '1.0.1', 'cnr_id': 'comfyui-foo', 'aux_id': None, 'enabled': True}}
    assert flagged_rows(core) == {}


def test_reinstall_makes_a_git_install_of_a_non_registry_pack(core, custom_nodes, monkeypatch):
    pack(custom_nodes / 'ComfyUI-Bar')
    git_clone_stand_in(monkeypatch, core)
    manager = reload(core)

    result = asyncio.run(manager.reinstall_by_id('ComfyUI-Bar', 'unknown', core.DEFAULT_CHANNEL, 'cache'))

    assert result.result is True, result.msg
    assert (custom_nodes / 'ComfyUI-Bar/.git').is_dir()
    assert flagged_rows(core) == {}


def test_reinstall_refused_by_the_flagged_policy_keeps_the_folder(core, custom_nodes, monkeypatch):
    folder = pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    registry_api(monkeypatch, core, status='NodeVersionStatusFlagged')
    manager = reload(core)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is False
    assert folder.exists()


def a_users_folder(path, project_name='comfyui-foo'):
    folder = pack(path, project_name)
    (folder / 'my_settings.json').write_text('{"user": "added this"}\n')
    return folder


@pytest.mark.parametrize('folder', ['comfyui-foo', 'ComfyUI-Foo-main', '.disabled/ComfyUI-Foo-main'])
@pytest.mark.parametrize('download, reason', [(refused, 'Connection refused'), (block_page, 'Empty archive file')],
                         ids=['download-fails', 'extraction-fails'])
def test_a_reinstall_that_cannot_install_keeps_the_folder(core, custom_nodes, monkeypatch, folder, download, reason):
    a_users_folder(custom_nodes / folder)
    before = files(custom_nodes)
    registry_api(monkeypatch, core, download=download)
    manager = reload(core)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is False
    assert reason in result.msg and 'previous installation was kept' in result.msg
    assert files(custom_nodes) == before
    assert listing(custom_nodes) == [folder]
    assert flagged_rows(core) == {'comfyui-foo': 'disabled' if folder.startswith('.disabled') else 'enabled'}
    registry_api(monkeypatch, core)
    assert asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1')).result is True
    assert listing(custom_nodes) == ['comfyui-foo']


def test_a_reinstall_whose_clone_fails_keeps_the_folder(core, custom_nodes, monkeypatch):
    a_users_folder(custom_nodes / 'ComfyUI-Bar', None)
    before = files(custom_nodes)
    git_clone_stand_in(monkeypatch, core, fails=True)
    manager = reload(core)

    result = asyncio.run(manager.reinstall_by_id('ComfyUI-Bar', 'unknown', core.DEFAULT_CHANNEL, 'cache'))

    assert result.result is False
    assert BAR_URL in result.msg and 'previous installation was kept' in result.msg
    assert files(custom_nodes) == before
    assert flagged_rows(core) == {'ComfyUI-Bar': 'enabled'}


def test_a_reinstall_whose_install_script_fails_removes_what_it_installed_and_keeps_the_folder(core, custom_nodes,
                                                                                               monkeypatch):
    a_users_folder(custom_nodes / 'comfyui-foo')
    before = files(custom_nodes)
    registry_api(monkeypatch, core)
    manager = reload(core)
    manager.execute_install_script = Mock(return_value=False)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is False
    assert 'Failed to execute install script' in result.msg and 'previous installation was kept' in result.msg
    assert files(custom_nodes) == before


def test_a_reinstall_stops_before_anything_changes_when_a_folder_cannot_be_moved(core, custom_nodes, monkeypatch):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
    stray = a_users_folder(custom_nodes / 'ComfyUI-Foo-main')
    before = files(custom_nodes)
    registry_api(monkeypatch, core)
    manager = reload(core)
    rename = os.rename

    def locked(src, dst):
        if src == str(stray):
            raise PermissionError(13, 'Permission denied', src)
        return rename(src, dst)

    monkeypatch.setattr(os, 'rename', locked)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is False
    assert 'Permission denied' in result.msg and 'previous installation was kept' in result.msg
    assert core.manager_downloader.download_url.call_count == 0
    assert files(custom_nodes) == before
    assert listing(custom_nodes) == ['ComfyUI-Foo-main', 'comfyui-foo']


def the_new_installation(path):
    init = Path(path, '__init__.py')
    return init.is_file() and '# 1.0.1' in init.read_text()


@pytest.mark.parametrize('movable', [True, False], ids=['can-be-moved', 'cannot-be-moved'])
def test_a_reinstall_whose_install_fails_leaves_what_it_cannot_delete_where_it_is(core, custom_nodes, monkeypatch,
                                                                                   capsys, movable):
    folder = a_users_folder(custom_nodes / 'comfyui-foo')
    before = files(folder)
    registry_api(monkeypatch, core)
    manager = reload(core)
    manager.execute_install_script = Mock(return_value=False)
    scheduled = cannot_delete(monkeypatch, core, the_new_installation, movable=movable)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    [held] = (custom_nodes / '.disabled/.reinstall').glob('*/*')
    assert result.result is False
    assert result.msg == ("Failed to reinstall 'comfyui-foo': Failed to execute install script: comfyui-foo@1.0.1. "
                          f"Its previous installation could not be put back and is kept in {held}")
    assert files(held) == before
    assert the_new_installation(folder)
    assert scheduled == []
    core.check_invalid_nodes()
    assert str(held) in capsys.readouterr().out.splitlines()


@pytest.mark.parametrize('went_back', [False, True], ids=['previous-installation-held', 'all-went-back'])
def test_after_a_failed_reinstall_only_a_folder_that_went_back_is_installed(core, custom_nodes, monkeypatch, went_back):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
    registry_api(monkeypatch, core)
    manager = reload(core)
    manager.execute_install_script = Mock(return_value=False)
    if not went_back:
        cannot_delete(monkeypatch, core, the_new_installation)

    reinstall = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
    install = asyncio.run(manager.install_by_id('comfyui-foo', None, core.DEFAULT_CHANNEL, 'cache'))

    assert ('could not be put back' in reinstall.msg) is not went_back
    assert (install.action == 'skip') is went_back


def test_a_reinstall_that_cannot_delete_a_folder_it_set_aside_leaves_it_to_the_notice(core, custom_nodes, monkeypatch,
                                                                                      caplog, capsys):
    folder = a_users_folder(custom_nodes / 'comfyui-foo')
    before = files(folder)
    registry_api(monkeypatch, core)
    manager = reload(core)
    scheduled = cannot_delete(monkeypatch, core, lambda path: '.reinstall' in Path(path).parts)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is True, result.msg
    assert scheduled == []
    assert the_new_installation(folder)
    [held] = (custom_nodes / '.disabled/.reinstall').glob('*/comfyui-foo')
    assert files(held) == before
    assert any(str(held.parent) in x.getMessage() for x in caplog.records if x.levelno == logging.WARNING)
    core.check_invalid_nodes()
    assert str(held) in capsys.readouterr().out.splitlines()


def test_a_reinstall_whose_install_fails_schedules_no_deletion_of_its_install_path(core, custom_nodes, monkeypatch,
                                                                                    caplog):
    folder = a_users_folder(custom_nodes / 'comfyui-foo')
    registry_api(monkeypatch, core)
    manager = reload(core)
    manager.execute_install_script = Mock(return_value=False)
    locked = [True]
    scheduled = cannot_delete(monkeypatch, core, lambda path: locked[0] and the_new_installation(path), schedule_fails=True)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    [held] = (custom_nodes / '.disabled/.reinstall').glob('*/comfyui-foo')
    assert result.result is False
    assert result.msg.endswith(f'Its previous installation could not be put back and is kept in {held}')
    assert scheduled == []
    assert any(str(folder) in x.getMessage() for x in caplog.records if x.levelno == logging.WARNING)
    locked[0] = False
    manager.execute_install_script = Mock(return_value=True)
    assert asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1')).result is True
    assert the_new_installation(folder)
    assert scheduled == []


def read_only_files_as_on_windows(monkeypatch, core):
    """
    Windows refuses to delete a read-only file, such as a pack file of a git clone, until `attrib -R`, which rmtree
    runs there, clears the attribute.
    """
    delete, run_script = shutil.rmtree, core.manager_funcs.run_script

    def refuses_read_only(path, *args, **kwargs):
        read_only = [x for x in Path(path).rglob('*') if x.is_file() and not x.stat().st_mode & 0o200]
        if read_only:
            raise PermissionError(13, 'Access is denied', str(read_only[0]))
        return delete(path, *args, **kwargs)

    def attrib(cmd, *args, **kwargs):
        if cmd[:2] != ['attrib', '-R']:
            return run_script(cmd, *args, **kwargs)
        for x in Path(cmd[2].removesuffix('\\*')).rglob('*'):
            x.chmod(x.stat().st_mode | 0o200)
        return 0

    monkeypatch.setattr(core.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(core.shutil, 'rmtree', refuses_read_only)
    monkeypatch.setattr(core.manager_funcs, 'run_script', attrib)


def test_a_reinstall_deletes_the_read_only_files_of_the_clone_it_replaced(core, custom_nodes, monkeypatch, capsys):
    clone = pack(custom_nodes / 'comfyui-foo', git_url=FOO_URL)
    (clone / '.git/objects/pack').mkdir(parents=True)
    for name in ('pack-0123.idx', 'pack-0123.pack'):
        (clone / '.git/objects/pack' / name).write_text('')
        (clone / '.git/objects/pack' / name).chmod(0o444)
    read_only_files_as_on_windows(monkeypatch, core)
    registry_api(monkeypatch, core)
    manager = reload(core)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is True, result.msg
    assert the_new_installation(clone)
    assert listing(custom_nodes) == ['comfyui-foo']
    core.check_invalid_nodes()
    assert 'unfinished reinstall notice' not in capsys.readouterr().out


@pytest.mark.parametrize('movable', [True, False], ids=['can-be-moved', 'cannot-be-moved'])
def test_a_reinstall_whose_extraction_fails_schedules_no_deletion_of_its_install_path(core, custom_nodes, monkeypatch,
                                                                                     movable):
    folder = a_users_folder(custom_nodes / 'comfyui-foo')
    before = files(folder)
    registry_api(monkeypatch, core)
    manager = reload(core)

    def fails_midway(archive, to):
        Path(to, 'half_written.py').write_text('')
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(core.manager_util, 'extract_package_as_zip', fails_midway)
    scheduled = cannot_delete(monkeypatch, core, lambda path: path == str(folder) and (folder / 'half_written.py').exists(),
                              movable=movable)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is False
    assert 'No space left on device' in result.msg
    assert scheduled == []
    assert files(folder) != before


def test_a_reinstall_puts_every_folder_back_when_an_empty_holding_place_cannot_be_removed(core, custom_nodes,
                                                                                         monkeypatch):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
    pack(custom_nodes / '.disabled/comfyui-foo@0_9_0', 'comfyui-foo', version='0.9.0', tracking=True)
    before = files(custom_nodes)
    registry_api(monkeypatch, core, download=refused)
    manager = reload(core)
    rmdir, refused_once = os.rmdir, []

    def busy_once(path, *args, **kwargs):
        if not refused_once:
            refused_once.append(path)
            raise PermissionError(13, 'Permission denied', os.fspath(path))
        return rmdir(path, *args, **kwargs)

    monkeypatch.setattr(os, 'rmdir', busy_once)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is False
    assert "Failed to reinstall 'comfyui-foo', so its previous installation was kept: " in result.msg
    assert len(refused_once) == 1
    assert files(custom_nodes) == before


def test_a_reinstall_that_cannot_move_a_folder_aside_nor_put_one_back_says_where_it_is_kept(core, custom_nodes,
                                                                                           monkeypatch):
    folder = pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
    before = files(folder)
    stray = a_users_folder(custom_nodes / 'ComfyUI-Foo-main')
    registry_api(monkeypatch, core)
    manager = reload(core)
    rename = os.rename

    def locked(src, dst):
        if src == str(stray) or '.reinstall' in Path(src).parts:
            raise PermissionError(13, 'Permission denied', src)
        return rename(src, dst)

    monkeypatch.setattr(os, 'rename', locked)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    [held] = (custom_nodes / '.disabled/.reinstall').glob('*/comfyui-foo')
    assert result.result is False
    # an OSError gives its path as Python writes it, which doubles a backslash
    assert result.msg == (f"Failed to reinstall 'comfyui-foo': [Errno 13] Permission denied: {str(stray)!r}. "
                          f"Its previous installation could not be put back and is kept in {held}")
    assert core.manager_downloader.download_url.call_count == 0
    assert files(held) == before
    assert stray.exists()


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='the crash is a child process that dies')
def test_a_crash_in_the_middle_of_a_reinstall_leaves_the_folder_on_disk(core, custom_nodes, monkeypatch):
    folder = a_users_folder(custom_nodes / 'ComfyUI-Foo-main')
    before = files(folder)
    registry_api(monkeypatch, core, download=lambda *args: os._exit(0))
    manager = reload(core)

    child = os.fork()
    if child == 0:
        asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
        os._exit(1)
    assert os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]) == 0

    [held] = (custom_nodes / '.disabled/.reinstall').glob('*/ComfyUI-Foo-main')
    assert files(held) == before
    reload(core)
    assert len(manager.invalid_installations) == 0
    assert core.get_installed_node_packs() == {}
    assert flagged_rows(core) == {}
    manager.unified_enable('.reinstall', 'unknown')
    assert list((custom_nodes / '.disabled/.reinstall').glob('*/ComfyUI-Foo-main')) == [held]


def a_clone_at_the_install_path(custom_nodes):
    folder = pack(custom_nodes / 'comfyui-foo', git_url='https://github.com/someone/ComfyUI-Foo-fork')
    (folder / 'my_settings.json').write_text('{"user": "added this"}\n')
    return folder


def an_install_of_foo(monkeypatch, core, version, fails=False):
    if version == 'nightly':
        git_clone_stand_in(monkeypatch, core, fails=fails)
    else:
        registry_api(monkeypatch, core, download=refused if fails else archive_of_foo)


def a_clone_of_a_fork_named_like_foo(custom_nodes):
    folder = pack(custom_nodes / 'foo-fork', git_url='https://github.com/someone/comfyui-foo')
    (folder / 'my_settings.json').write_text('{"user": "added this"}\n')
    return folder


def folders_in_the_maps(manager):
    return {*(x[1] for x in manager.active_nodes.values()), *(x[1] for x in manager.unknown_active_nodes.values()),
            *(x[1] for x in manager.unknown_inactive_nodes.values()), *manager.nightly_inactive_nodes.values(),
            *(x for versions in manager.cnr_inactive_nodes.values() for x in versions.values()),
            *manager.invalid_installations}


def moved_to_the_archive(folder, archived, node_id='comfyui-foo'):
    return f"[ComfyUI-Manager] '{folder}' was in the way of the reinstall of '{node_id}' and was moved to '{archived}'."


def warned(caplog):
    return [x.getMessage() for x in caplog.records if x.levelno == logging.WARNING]


@pytest.mark.parametrize('version', ['nightly', '1.0.1'])
def test_a_reinstall_archives_what_sits_at_its_install_path_under_another_key(core, custom_nodes, monkeypatch, caplog,
                                                                              version):
    clone = a_clone_at_the_install_path(custom_nodes)
    before = files(clone)
    an_install_of_foo(monkeypatch, core, version)
    manager = reload(core)
    assert core.get_installed_node_packs()['comfyui-foo']['cnr_id'] == ''

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', version, core.DEFAULT_CHANNEL, 'cache'))

    [archived] = (custom_nodes / '.disabled/.archived').glob('*/comfyui-foo')
    assert result.result is True, result.msg
    assert files(archived) == before
    assert listing(custom_nodes) == ['comfyui-foo', '.disabled/.archived']
    assert moved_to_the_archive(clone, archived) in warned(caplog)
    reload(core)
    assert core.get_installed_node_packs()['comfyui-foo']['cnr_id'] == 'comfyui-foo'


@pytest.mark.parametrize('version, reason', [('nightly', FOO_URL), ('1.0.1', 'Connection refused')])
def test_a_reinstall_that_cannot_install_keeps_what_sits_at_its_install_path(core, custom_nodes, monkeypatch, version,
                                                                             reason):
    a_clone_at_the_install_path(custom_nodes)
    before = files(custom_nodes)
    an_install_of_foo(monkeypatch, core, version, fails=True)
    manager = reload(core)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', version, core.DEFAULT_CHANNEL, 'cache'))

    assert result.result is False
    assert reason in result.msg and 'previous installation was kept' in result.msg
    assert files(custom_nodes) == before
    assert listing(custom_nodes) == ['comfyui-foo']


@pytest.mark.parametrize('fails', [False, True], ids=['installed', 'install-fails'])
@pytest.mark.parametrize('version', ['nightly', '1.0.1'])
def test_by_the_key_of_the_folder_in_its_way_a_reinstall_leaves_nothing_to_uninstall(core, custom_nodes, monkeypatch,
                                                                                    version, fails):
    a_clone_at_the_install_path(custom_nodes)
    an_install_of_foo(monkeypatch, core, version, fails=fails)
    manager = reload(core)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', version, core.DEFAULT_CHANNEL, 'cache'))
    assert result.result is not fails, result.msg
    manager.unified_uninstall('ComfyUI-Foo-fork', True)

    assert listing(custom_nodes) == ([] if fails else ['comfyui-foo', '.disabled/.archived'])


def test_a_reinstall_archives_a_clone_of_a_fork_that_has_the_name_of_the_nodepack(core, custom_nodes, monkeypatch,
                                                                                    caplog):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
    fork = a_clone_of_a_fork_named_like_foo(custom_nodes)
    before = files(fork)
    registry_api(monkeypatch, core)
    manager = reload(core)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    [archived] = (custom_nodes / '.disabled/.archived').glob('*/foo-fork')
    assert result.result is True, result.msg
    assert the_new_installation(custom_nodes / 'comfyui-foo')
    assert files(archived) == before
    assert listing(custom_nodes) == ['comfyui-foo', '.disabled/.archived']
    assert not {str(fork), str(archived)} & folders_in_the_maps(manager)
    assert moved_to_the_archive(fork, archived) in warned(caplog)


def test_a_reinstall_that_fails_puts_back_the_clone_of_a_fork_that_has_the_name_of_the_nodepack(core, custom_nodes,
                                                                                                 monkeypatch, caplog):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
    fork = a_clone_of_a_fork_named_like_foo(custom_nodes)
    before = files(fork)
    registry_api(monkeypatch, core, download=refused)
    manager = reload(core)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is False
    assert "Failed to reinstall 'comfyui-foo', so its previous installation was kept: " in result.msg
    assert files(fork) == before
    assert list((custom_nodes / '.disabled/.archived').glob('*')) == []
    assert not [x for x in warned(caplog) if 'was in the way' in x]


def test_after_a_reload_an_archived_folder_is_in_no_map_no_notice_and_not_in_the_installed_map(core, custom_nodes,
                                                                                                monkeypatch, capsys):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
    a_clone_of_a_fork_named_like_foo(custom_nodes)
    registry_api(monkeypatch, core)
    manager = reload(core)
    assert asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1')).result is True
    archive = custom_nodes / '.disabled/.archived'
    assert list(archive.glob('*/foo-fork'))

    manager = reload(core)

    assert [x for x in folders_in_the_maps(manager) if Path(x).is_relative_to(archive)] == []
    core.check_invalid_nodes()
    assert str(archive) not in capsys.readouterr().out
    assert list(core.get_installed_node_packs()) == ['comfyui-foo']


def test_a_reload_in_the_middle_of_a_reinstall_leaves_nothing_set_aside(core, custom_nodes, monkeypatch):
    pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    registry_api(monkeypatch, core)
    manager = reload(core)
    rename = os.rename

    def rename_then_reload(src, dst):
        rename(src, dst)
        if '.reinstall' in Path(dst).parts:
            monkeypatch.setattr(os, 'rename', rename)
            reloading = threading.Thread(target=reload, args=(core,))
            reloading.start()
            reloading.join()

    monkeypatch.setattr(os, 'rename', rename_then_reload)

    result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))

    assert result.result is True, result.msg
    assert listing(custom_nodes) == ['comfyui-foo']


def data_models(monkeypatch):
    spec = importlib.util.spec_from_file_location('_generated_models', PACKAGE / 'data_models/generated_models.py')
    models = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, models)
    spec.loader.exec_module(models)
    return models


def run_glob_worker(monkeypatch, core, task, allowed_levels=('middle', 'middle+')):
    models = data_models(monkeypatch)
    done = []

    class Queue:
        tasks = [(task, 0)]
        running_tasks = {}

        def get(self, timeout):
            return self.tasks.pop() if self.tasks else None

        def total_count(self):
            return len(self.tasks)

        def done_count(self):
            return len(done)

        def finalize(self):
            pass

        async def task_done(self, item, index, msg, status):
            done.append((item.kind, msg, status.status_str))

    namespace = {name: getattr(models, name) for name in dir(models) if not name.startswith('_')}
    namespace.update(
        core=core, logging=logging, traceback=traceback_module(), os=os, task_queue=Queue(),
        manager_util=SimpleNamespace(clear_pip_cache=lambda: None),
        security_utils=SimpleNamespace(is_allowed_security_level=lambda level: level in allowed_levels),
        SECURITY_MESSAGE_MIDDLE='', SECURITY_MESSAGE_MIDDLE_P='', replaces_cnr_with_nightly=lambda cnr_id: False,
        PromptServer=SimpleNamespace(instance=SimpleNamespace(send_sync=lambda *args: None)),
    )
    path = PACKAGE / 'glob/manager_server.py'
    nodes = [node for node in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(node, ast.AsyncFunctionDef) and node.name == 'task_worker']
    exec(compile(ast.Module(nodes, []), str(path), 'exec'), namespace)
    asyncio.run(namespace['task_worker']())
    return done


def traceback_module():
    import traceback
    return traceback


def reinstall_task(monkeypatch):
    models = data_models(monkeypatch)
    return models.QueueTaskItem.model_validate({
        'ui_id': 'ui', 'client_id': 'client', 'kind': 'reinstall',
        'params': {'id': 'comfyui-foo', 'version': '1.0.1', 'selected_version': 'latest',
                   'mode': 'cache', 'channel': 'default'}})


@pytest.mark.parametrize('core', ['glob'], indirect=True)
def test_the_v4_queue_reinstalls(core, custom_nodes, monkeypatch):
    pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    registry_api(monkeypatch, core)

    done = run_glob_worker(monkeypatch, core, reinstall_task(monkeypatch))

    assert [(kind, msg) for kind, msg, status in done] == [('reinstall', 'success')]
    assert [path.name for path in custom_nodes.iterdir()] == ['comfyui-foo']
    assert (custom_nodes / 'comfyui-foo/.tracking').exists()


@pytest.mark.parametrize('core', ['glob'], indirect=True)
def test_the_v4_queue_checks_a_reinstall_as_an_install(core, custom_nodes, monkeypatch):
    folder = pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    registry_api(monkeypatch, core)

    done = run_glob_worker(monkeypatch, core, reinstall_task(monkeypatch), allowed_levels=())

    assert [(kind, msg) for kind, msg, status in done] == [('reinstall', 'failed')]
    assert folder.exists()


@pytest.mark.parametrize('core', ['glob'], indirect=True)
def test_the_v4_queue_says_why_an_update_of_an_invalid_installation_fails(core, custom_nodes, monkeypatch):
    folder = pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    models = data_models(monkeypatch)
    task = models.QueueTaskItem.model_validate({
        'ui_id': 'ui', 'client_id': 'client', 'kind': 'update',
        'params': {'node_name': 'comfyui-foo', 'node_ver': 'nightly'}})

    done = run_glob_worker(monkeypatch, core, task)

    assert len(done) == 1
    kind, msg, status = done[0]
    assert (kind, status) == ('update', 'error')
    assert "Cannot update 'comfyui-foo': this nodepack was not installed through ComfyUI-Manager" in msg
    assert f'Reinstalling deletes its folder ({folder})' in msg


@pytest.mark.parametrize('core', ['glob'], indirect=True)
def test_the_v4_installed_map_carries_the_flag(core, custom_nodes, monkeypatch):
    pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    pack(custom_nodes / 'comfyui-baz', 'comfyui-baz', version='2.0.0', tracking=True)
    reload(core)
    models = data_models(monkeypatch)

    state = models.TaskStateMessage(history={}, running_queue=[], pending_queue=[],
                                    installed_packs=core.get_installed_node_packs())

    packs = state.model_dump(mode='json')['installed_packs']
    assert packs['ComfyUI-Foo-main']['invalid_installation'] is True
    assert packs['ComfyUI-Foo-main']['cnr_id'] == 'comfyui-foo'
    assert not packs['comfyui-baz']['invalid_installation']


def test_the_console_line_of_a_failed_update_says_why(monkeypatch, caplog, core, custom_nodes):
    server = core.__name__.split('.')[-2]
    pack(custom_nodes / 'ComfyUI-Bar')
    reload(core)
    models = data_models(monkeypatch)
    namespace = {'core': core, 'logging': logging, 'os': os, 'traceback': traceback_module(),
                 'manager_util': SimpleNamespace(clear_pip_cache=lambda: None),
                 'OperationResult': models.OperationResult, 'UpdatePackParams': models.UpdatePackParams}
    path = PACKAGE / server / 'manager_server.py'
    nodes = [node for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
             if isinstance(node, ast.AsyncFunctionDef) and node.name == 'do_update']
    exec(compile(ast.Module(nodes, []), str(path), 'exec'), namespace)
    item = (models.UpdatePackParams(node_name='ComfyUI-Bar', node_ver='unknown') if server == 'glob'
            else ('ui', 'ComfyUI-Bar', 'unknown'))

    asyncio.run(namespace['do_update'](item))

    errors = [record.getMessage() for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "An error occurred while updating 'ComfyUI-Bar'" in errors[0]
    assert 'not installed through ComfyUI-Manager, or its installation is damaged' in errors[0]


def cm_cli_function(name, namespace, class_name=None):
    path = Path(__file__).resolve().parent.parent / 'cm_cli/__main__.py'
    body = ast.parse(path.read_text(encoding='utf-8')).body
    if class_name is not None:
        body = next(node for node in body if isinstance(node, ast.ClassDef) and node.name == class_name).body
    nodes = [node for node in body if isinstance(node, ast.FunctionDef) and node.name == name]
    exec(compile(ast.Module(nodes, []), str(path), 'exec'), namespace)
    return namespace[name]


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_cm_cli_prints_no_notice(core, custom_nodes, capsys):
    pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    set_channel_mode = cm_cli_function('set_channel_mode', {'asyncio': asyncio, 'core': core,
                                                            'unified_manager': core.unified_manager}, 'Ctx')

    set_channel_mode(SimpleNamespace(mode='cache', channel=core.DEFAULT_CHANNEL), None, 'cache')

    assert 'invalid nodes notice' not in capsys.readouterr().out
    assert core.unified_manager.invalid_installations


class NodeInstallError(Exception):
    pass


def cm_cli_reinstall_node(core, out=None):
    console = rich.console.Console(file=out if out is not None else io.StringIO(), width=1000, color_system=None)
    return cm_cli_function('reinstall_node', {
        'asyncio': asyncio, 'os': os, 'core': core, 'unified_manager': core.unified_manager, 'print': console.print,
        'escape': rich.markup.escape, 'cmd_ctx': SimpleNamespace(channel='default', mode='cache', no_deps=False),
        'NodeInstallError': NodeInstallError})


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_cm_cli_reinstall_keeps_the_folder_when_the_install_fails(core, custom_nodes, monkeypatch):
    a_users_folder(custom_nodes / 'ComfyUI-Foo-main')
    before = files(custom_nodes)
    registry_api(monkeypatch, core, download=refused)
    reload(core)
    reinstall_node = cm_cli_reinstall_node(core)

    with pytest.raises(NodeInstallError):
        reinstall_node('comfyui-foo@1.0.1')

    assert files(custom_nodes) == before
    registry_api(monkeypatch, core)
    reinstall_node('comfyui-foo@1.0.1')
    assert listing(custom_nodes) == ['comfyui-foo']


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
@pytest.mark.parametrize('version', ['nightly', '1.0.1'])
def test_cm_cli_reinstall_archives_what_sits_at_the_install_path_under_another_key(core, custom_nodes, monkeypatch,
                                                                                   version):
    a_clone_at_the_install_path(custom_nodes)
    before = files(custom_nodes)
    an_install_of_foo(monkeypatch, core, version, fails=True)
    reload(core)
    reinstall_node = cm_cli_reinstall_node(core)

    with pytest.raises(NodeInstallError):
        reinstall_node(f'comfyui-foo@{version}')

    assert files(custom_nodes) == before
    an_install_of_foo(monkeypatch, core, version)
    reinstall_node(f'comfyui-foo@{version}')
    assert listing(custom_nodes) == ['comfyui-foo', '.disabled/.archived']
    assert not (custom_nodes / 'comfyui-foo/my_settings.json').exists()
    reload(core)
    assert core.get_installed_node_packs()['comfyui-foo']['cnr_id'] == 'comfyui-foo'


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_cm_cli_reinstall_by_a_registered_url_that_the_node_list_lacks_installs_the_nightly(core, custom_nodes,
                                                                                            monkeypatch):
    monkeypatch.setitem(globals(), 'NODE_LIST', [x for x in NODE_LIST if x['reference'] != FOO_URL])
    a_users_folder(custom_nodes / 'ComfyUI-Foo-main')
    git_clone_stand_in(monkeypatch, core)
    reload(core)

    cm_cli_reinstall_node(core)(FOO_URL)

    assert listing(custom_nodes) == ['comfyui-foo']
    assert f'url = {FOO_URL}' in (custom_nodes / 'comfyui-foo/.git/config').read_text()
    reload(core)
    assert core.get_installed_node_packs()['comfyui-foo']['cnr_id'] == 'comfyui-foo'


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
@pytest.mark.parametrize('url', ['https://github.com/example/ComfyUI.Dot', 'https://github.com/example/ComfyUI.Dot.git'])
def test_cm_cli_reinstall_by_an_unregistered_url_replaces_the_clone_the_scan_names_by_it(core, custom_nodes,
                                                                                         monkeypatch, url):
    clone = pack(custom_nodes / 'ComfyUI.Dot', git_url='https://github.com/example/ComfyUI.Dot')
    (clone / 'my_settings.json').write_text('{"user": "added this"}\n')
    git_clone_stand_in(monkeypatch, core)
    reload(core)

    cm_cli_reinstall_node(core)(url)

    assert listing(custom_nodes) == ['ComfyUI.Dot']
    assert 'my_settings.json' not in files(clone)
    assert 'github.com/example/ComfyUI.Dot' in files(clone)['.git/config']


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_cm_cli_reinstall_by_the_url_of_a_fork_archives_the_registry_nodepack_of_its_name(core, custom_nodes,
                                                                                         monkeypatch, caplog):
    folder = pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
    before = files(folder)
    git_clone_stand_in(monkeypatch, core)
    reload(core)

    cm_cli_reinstall_node(core)('https://github.com/someone/comfyui-foo')

    [archived] = (custom_nodes / '.disabled/.archived').glob('*/comfyui-foo')
    assert files(archived) == before
    assert 'github.com/someone/comfyui-foo' in files(folder)['.git/config']
    assert moved_to_the_archive(folder, archived) in warned(caplog)


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
@pytest.mark.parametrize('spec, line', [
    ('comfyui-foo@nightly', f"[REINSTALLED] {'comfyui-foo':50}[NIGHTLY]"),
    ('ComfyUI-Bar', f"[REINSTALLED] {'ComfyUI-Bar':50}[UNKNOWN]"),
    ('comfyui-foo@1.0.1', f"[REINSTALLED] {'comfyui-foo':50}[1.0.1]"),
], ids=['nightly', 'unknown', 'registry'])
def test_cm_cli_reinstall_says_what_it_installed(core, custom_nodes, monkeypatch, spec, line):
    a_users_folder(custom_nodes / 'ComfyUI-Foo-main')
    pack(custom_nodes / 'ComfyUI-Bar')
    git_clone_stand_in(monkeypatch, core)
    registry_api(monkeypatch, core)
    reload(core)
    out = io.StringIO()

    cm_cli_reinstall_node(core, out)(spec)

    assert line in [x.strip() for x in out.getvalue().splitlines()]


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_cm_cli_reinstall_says_why_it_failed_with_what_is_in_square_brackets(core, custom_nodes):
    reload(core)
    out = io.StringIO()

    with pytest.raises(NodeInstallError):
        cm_cli_reinstall_node(core, out)('Something-Else')

    assert out.getvalue().splitlines() == ["ERROR: An error occurred while reinstalling 'Something-Else'.",
                                           "Node 'Something-Else@unknown' not found in [default, cache]"]


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
@pytest.mark.parametrize('spec', ['ComfyUI-Manager', 'all'])
def test_cm_cli_reinstall_skips_the_manager(core, custom_nodes, spec):
    pack(custom_nodes / 'ComfyUI-Manager', git_url='https://github.com/Comfy-Org/ComfyUI-Manager')
    reload(core)
    out = io.StringIO()
    reinstall_node = cm_cli_reinstall_node(core, out)
    namespace = {'unified_manager': core.unified_manager, 'NodeInstallError': NodeInstallError, 'sys': sys,
                 'traceback': traceback_module(), 'print': reinstall_node.__globals__['print']}
    cm_cli_function('get_all_installed_node_specs', namespace)

    cm_cli_function('for_each_nodes', namespace)([spec], act=reinstall_node)

    lines = out.getvalue().splitlines()
    assert f"1/1 [   SKIP  ] {'ComfyUI-Manager':50} => Already installed" in lines
    assert not [x for x in lines if 'ERROR' in x or 'ignored' in x]


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_cm_cli_update_all_leaves_an_invalid_installation_out(core, custom_nodes, monkeypatch):
    pack(custom_nodes / 'comfyui-foo', 'comfyui-foo', tracking=True)
    pack(custom_nodes / 'ComfyUI-Bar')
    registry_api(monkeypatch, core)
    reload(core)
    outs = []

    for nodes in (['all'], ['ComfyUI-Bar']):
        out = io.StringIO()
        namespace = {'unified_manager': core.unified_manager, 'threading': threading, 'concurrent': concurrent,
                     'traceback': traceback_module(), 'cmd_ctx': SimpleNamespace(no_deps=False),
                     'print': rich.console.Console(file=out, width=1000, color_system=None).print}
        cm_cli_function('update_node', namespace)
        cm_cli_function('update_parallel', namespace)(nodes)
        outs.append([x.strip() for x in out.getvalue().splitlines()])

    every, by_folder_name = outs
    assert every == [f"1/1 [  SKIPPED  ]: {'comfyui-foo':50} => Up to date", '[1/1] Post update: comfyui-foo@None']
    assert by_folder_name == ["ERROR: An error occurred while updating 'ComfyUI-Bar'.", '[1/1] Post update: ComfyUI-Bar@unknown']


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_cm_cli_uninstall_by_name_deletes_the_valid_clone_and_leaves_the_invalid_copies(core, custom_nodes):
    pack(custom_nodes / 'bar-clone', git_url=BAR_URL)
    pack(custom_nodes / 'ComfyUI-Bar-backup', 'ComfyUI-Bar')
    pack(custom_nodes / 'comfyui-bar')
    reload(core)
    out = io.StringIO()
    uninstall_node = cm_cli_function('uninstall_node', {
        'unified_manager': core.unified_manager, 'print': rich.console.Console(file=out, width=1000, color_system=None).print})

    uninstall_node('ComfyUI-Bar')

    assert [x.strip() for x in out.getvalue().splitlines()] == ['[UNINSTALLED] ComfyUI-Bar']
    assert listing(custom_nodes) == ['ComfyUI-Bar-backup', 'comfyui-bar']


def test_what_a_user_reads_does_not_name_git_or_tracking(core, custom_nodes, capsys, monkeypatch):
    pack(custom_nodes / 'ComfyUI-Bar')
    pack(custom_nodes / 'ComfyUI-Foo-main', 'comfyui-foo')
    registry_api(monkeypatch, core, download=refused)
    manager = reload(core)

    reason = manager.unified_update('ComfyUI-Bar', 'unknown').msg
    core.check_invalid_nodes()
    notice = capsys.readouterr().out
    failure = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1')).msg

    for text in (reason, notice, failure):
        assert '.git' not in text and '.tracking' not in text
        assert not re.search(r'node\s+pack', text, re.IGNORECASE)
    assert 'not installed through ComfyUI-Manager' in reason and 'not installed through ComfyUI-Manager' in notice
    assert "Failed to reinstall 'comfyui-foo', so its previous installation was kept: " in failure


def legacy_page():
    js = JsSource(PACKAGE / 'js')
    manager = js.text('custom-nodes-manager.js')
    formatter = js.lift_formatter('custom-nodes-manager.js', "id: 'title',")
    action_buttons = slice_braced(manager, 'getActionButtons(action, rowItem, is_selected_button)')
    reinstall_confirmation = slice_braced(manager, 'if(mode === "reinstall")')
    script = '\n'.join([
        js.lift_declaration('common.js', 'export function sanitizeHTML('),
        line_containing(manager, 'const INVALID_INSTALLATION_GUIDANCE ='),
        'const messages = [], confirmations = [];',
        'const show_message = (msg) => messages.push(msg);',
        'const customConfirm = async (msg) => { confirmations.push(msg); return false; };',
        'const sanitizeUrl = (url) => url;',
        'const self = {};',
        'const document = {createElement: (tag) => ({tag, style: {}, children: [], '
        'appendChild(child) { this.children.push(child); }})};',
        f'const formatter = {formatter};',
        f'function {action_buttons}',
        f'async function confirm(mode, title, list) {{ {reinstall_confirmation} }}',
        "const row = {action: 'invalid-installation', title: 'ComfyUI-Foo', version: 'unknown', "
        "reference: 'https://github.com/example/ComfyUI-Foo', originalData: {id: 'comfyui-foo'}};",
        'const cell = formatter(row.title, row, {});',
        'const marker = cell.children[0];',
        'marker.onclick();',
        "await confirm('reinstall', row.title, ['hash']);",
        "await confirm('reinstall', undefined, ['a', 'b', 'c']);",
        'console.log(JSON.stringify({cell: cell.children.map((child) => child.tag), '
        'marker: {label: marker.innerText, tooltip: marker.title}, dialog: messages, '
        'buttons: getActionButtons(row.action, row), confirmations}));',
    ])
    return run_node(script)


@pytest.mark.skipif(NODE is None, reason='node is required to execute the lifted production JS')
def test_the_legacy_page_explains_an_invalid_installation():
    page = legacy_page()
    buttons = parse(page['buttons'])

    assert page['cell'] == ['button', 'br', 'a']
    assert page['marker'] == {'label': 'INVALID INSTALLATION \u2197', 'tooltip': GUIDANCE}
    [dialog] = page['dialog']
    assert "The 'ComfyUI-Foo' nodepack is an invalid installation." in dialog
    assert GUIDANCE in dialog
    assert buttons.tags == ['button']
    assert dict(buttons.attrs)['title'] == GUIDANCE
    assert page['confirmations'] == ['Reinstall ComfyUI-Foo? This deletes its folder and installs the nodepack again.',
                                     'Reinstall 3 custom nodes? This deletes their folders and installs the nodepacks again.']

    for text in (page['marker']['label'], page['marker']['tooltip'], dialog, page['buttons'], *page['confirmations']):
        assert '.git' not in text and '.tracking' not in text
        assert not re.search(r'node\s+pack', text, re.IGNORECASE)
