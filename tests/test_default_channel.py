import asyncio
import json
import logging
import os
import sys
import traceback
from types import SimpleNamespace

import pytest
from aiohttp import web

from _install_flags_testutil import import_context, import_glob_security_utils, import_reader
from legacy_html_testutil import PACKAGE, ROOT, load_functions

COMFY_ORG = 'https://raw.githubusercontent.com/Comfy-Org/ComfyUI-Manager/main'
LTDRDATA = 'https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main'
MIRROR = 'https://example.invalid/mirror'
BAR_URL = 'https://github.com/example/ComfyUI-Bar'
SERVED = {
    'custom-node-list.json': {'custom_nodes': [{'author': 'example', 'title': 'ComfyUI-Bar', 'reference': BAR_URL, 'files': [BAR_URL],
                                                'install_type': 'git-clone', 'description': ''}]},
    'extension-node-map.json': {BAR_URL: [['BarNode'], {'title_aux': 'ComfyUI-Bar'}]},
    'model-list.json': {'models': [{'name': 'served by the channel'}]},
    'github-stats.json': {BAR_URL: {'stars': 7, 'last_update': '2026-11-01 00:00:00', 'author_account_age_days': 900}},
}
BUNDLED = {'custom-node-list.json': {'custom_nodes': []}, 'extension-node-map.json': {}, 'model-list.json': {'models': []},
           'github-stats.json': {}, 'extras.json': {'favorites': []}}
REGISTRY = [{'id': 'comfyui-foo', 'name': 'Foo', 'repository': 'https://github.com/example/ComfyUI-Foo',
             'publisher': {'name': 'example'}, 'description': '', 'latest_version': {'version': '1.0.1'}}]
SPELLINGS = [pytest.param(COMFY_ORG, id='Comfy-Org'), pytest.param(LTDRDATA, id='ltdrdata')]
CONFIGS = [pytest.param(None, id='no channel_url')] + SPELLINGS
WRITERS = ['glob start', 'legacy start', 'cm-cli update-cache']
CACHED = [pytest.param((), id='DEFAULT_CHANNEL'), pytest.param(('default_cache_as_channel_url = True',), id='channel_url')]
route = lambda path: lambda handler: handler  # noqa: E731


@pytest.fixture
def user(tmp_path, monkeypatch):
    context = import_context()
    from comfyui_manager.common import manager_util

    cores = {'glob': import_reader('glob'), 'legacy': import_reader('legacy')}
    for core in cores.values():
        monkeypatch.setattr(core, 'cached_config', None)
        monkeypatch.setattr(core, 'channel_dict', None)
        monkeypatch.setattr(core, 'channel_list', None)
        monkeypatch.setattr(core, 'valid_channels', set(core.valid_channels))
    monkeypatch.setattr(context, 'manager_config_path', str(tmp_path / 'config.ini'))
    monkeypatch.setattr(context, 'manager_channel_list_path', str(tmp_path / 'channels.list'))
    monkeypatch.setattr(manager_util, 'cache_dir', str(tmp_path / 'cache'))
    monkeypatch.setattr(manager_util, 'comfyui_manager_path', str(tmp_path / 'manager'))
    os.makedirs(manager_util.cache_dir)
    os.makedirs(manager_util.comfyui_manager_path)
    for name, data in BUNDLED.items():
        with open(os.path.join(manager_util.comfyui_manager_path, name), 'w', encoding='utf-8') as f:
            json.dump(data, f)

    get_data = manager_util.get_data

    async def from_the_channel(uri, silent=False):
        if uri.startswith('https://'):
            return json.loads(json.dumps(SERVED[os.path.basename(uri)]))
        return await get_data(uri, silent)

    monkeypatch.setattr(manager_util, 'get_data', from_the_channel)
    return SimpleNamespace(cores=cores, util=manager_util, path=tmp_path, monkeypatch=monkeypatch)


def configure(user, channel_url, default_url, *lines):
    config = ['[default]'] + ([f'channel_url = {channel_url}'] if channel_url else []) + list(lines)
    (user.path / 'config.ini').write_text('\n'.join(config) + '\n')
    (user.path / 'channels.list').write_text(f'default::{default_url}\nrecent::{default_url}/node_db/new\nmirror::{MIRROR}\n')


async def idle(*args, **kwargs):
    pass


def write(user, writer):
    core = user.cores['glob' if writer == 'glob start' else 'legacy']
    with user.monkeypatch.context() as m:
        m.setattr(core, 'unified_manager', SimpleNamespace(reload=idle, get_custom_nodes=idle))
        m.setattr(core, 'check_invalid_nodes', lambda: None)
        if writer == 'cm-cli update-cache':
            cli = load_functions(ROOT / 'cm_cli/__main__.py', {'_force_update_cache'}, {
                'os': os, 'sys': sys, 'asyncio': asyncio, 'print': lambda *args, **kwargs: None, 'core': core,
                'manager_util': user.util, 'unified_manager': SimpleNamespace(reload=idle, load_nightly=idle)})
            asyncio.run(cli['_force_update_cache']('default'))
        else:
            server = load_functions(PACKAGE / writer.split()[0] / 'manager_server.py', {'default_cache_update'}, {
                'os': os, 'logging': logging, 'traceback': traceback, 'asyncio': asyncio, 'manager_util': user.util,
                'core': core, 'ManagerDatabaseSource': SimpleNamespace(remote=SimpleNamespace(value='remote'))})
            asyncio.run(server['default_cache_update']())


def handlers(user, server, names):
    return load_functions(PACKAGE / server / 'manager_server.py', names, {
        'core': user.cores[server], 'web': web, 'routes': SimpleNamespace(get=route, post=route),
        'populate_markdown': lambda node_pack: None})


def answer(handler, **query):
    response = asyncio.run(handler(SimpleNamespace(rel_url=SimpleNamespace(query=query))))
    return json.loads(response.text)


def install_levels(user):
    glob = import_glob_security_utils()
    legacy = load_functions(PACKAGE / 'legacy/manager_server.py', {'get_risky_level'}, {'core': user.cores['legacy']})
    return {'glob': asyncio.run(glob.get_risky_level([BAR_URL], [])), 'legacy': asyncio.run(legacy['get_risky_level']([BAR_URL], []))}


def unread(user):
    return {(name, channel, filename): data
            for name, core in user.cores.items() for channel in (None, 'default', COMFY_ORG, LTDRDATA) for filename in SERVED
            if (data := asyncio.run(core.get_data_by_mode('cache', filename, channel))) != SERVED[filename]}


@pytest.mark.parametrize('cached', CACHED)
@pytest.mark.parametrize('default_url', SPELLINGS)
@pytest.mark.parametrize('channel_url', CONFIGS)
@pytest.mark.parametrize('writer', WRITERS)
def test_every_reader_reads_the_lists_that_were_written(user, writer, channel_url, default_url, cached):
    configure(user, channel_url, default_url, *cached)
    write(user, writer)

    assert unread(user) == {}
    assert install_levels(user) == {'glob': 'middle+', 'legacy': 'middle+'}


@pytest.mark.parametrize('cached', CACHED)
@pytest.mark.parametrize('default_url', SPELLINGS)
@pytest.mark.parametrize('channel_url', CONFIGS)
def test_both_servers_and_cm_cli_write_one_set_of_cache_files(user, channel_url, default_url, cached):
    configure(user, channel_url, default_url, *cached)
    for writer in WRITERS:
        write(user, writer)

    assert len(os.listdir(user.util.cache_dir)) == len(SERVED)


@pytest.fixture
def registry(user, monkeypatch):
    custom_nodes = user.path / 'comfyui' / 'custom_nodes'
    custom_nodes.mkdir(parents=True)
    monkeypatch.setattr(sys.modules['folder_paths'], 'get_folder_paths', lambda name: [str(custom_nodes)], raising=False)
    core = user.cores['legacy']

    async def get_cnr_data(*args, **kwargs):
        return REGISTRY

    monkeypatch.setattr(core.cnr_utils, 'get_cnr_data', get_cnr_data)
    monkeypatch.setattr(core, 'unified_manager', core.UnifiedManager())


@pytest.mark.parametrize('default_url', SPELLINGS)
@pytest.mark.parametrize('channel_url', CONFIGS)
def test_custom_nodes_manager_lists_the_registry_nodepacks_on_the_default_channel(user, registry, channel_url, default_url):
    configure(user, channel_url, default_url)
    write(user, 'legacy start')

    listed = answer(handlers(user, 'legacy', {'fetch_customnode_list'})['fetch_customnode_list'], mode='cache')

    assert listed['channel'] == 'default'
    assert {key: row['reference'] for key, row in listed['node_packs'].items()} == {
        'ComfyUI-Bar': BAR_URL, 'comfyui-foo': 'https://registry.comfy.org/nodes/comfyui-foo'}


@pytest.mark.parametrize('server', ['glob', 'legacy'])
@pytest.mark.parametrize('default_url', SPELLINGS)
@pytest.mark.parametrize('channel_url', CONFIGS)
def test_channel_menu_selects_the_default_channel(user, server, channel_url, default_url):
    configure(user, channel_url, default_url)

    assert answer(handlers(user, server, {'channel_url_list'})['channel_url_list'])['selected'] == 'default'


@pytest.mark.parametrize('server', ['glob', 'legacy'])
@pytest.mark.parametrize('default_url', SPELLINGS)
def test_another_channel_keeps_its_own_lists(user, server, default_url):
    configure(user, MIRROR, default_url, 'default_cache_as_channel_url = True')
    write(user, f'{server} start')
    core = user.cores[server]

    assert sorted(os.listdir(user.util.cache_dir)) == sorted(
        f'{user.util.simple_hash(f"{MIRROR}/{filename}")}_{filename}' for filename in SERVED)
    assert {filename: asyncio.run(core.get_data_by_mode('cache', filename)) for filename in SERVED} == SERVED
    assert answer(handlers(user, server, {'channel_url_list'})['channel_url_list'])['selected'] == 'mirror'


@pytest.mark.parametrize('default_url', SPELLINGS)
def test_custom_nodes_manager_on_another_channel_lists_only_its_nodepacks(user, registry, default_url):
    configure(user, MIRROR, default_url, 'default_cache_as_channel_url = True')
    write(user, 'legacy start')

    listed = answer(handlers(user, 'legacy', {'fetch_customnode_list'})['fetch_customnode_list'], mode='cache')

    assert (listed['channel'], list(listed['node_packs'])) == ('mirror', ['ComfyUI-Bar'])
