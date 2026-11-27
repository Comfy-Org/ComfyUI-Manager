import pytest

from manager_test_utils import load_manager_util
from test_install_flags_config import _run_child

COMFY_ORG = 'https://raw.githubusercontent.com/Comfy-Org/ComfyUI-Manager/main'
LTDRDATA = 'https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main'
MIRROR = 'https://example.invalid/mirror'
FILES = ['custom-node-list.json', 'extension-node-map.json', 'model-list.json', 'github-stats.json']
SPELLINGS = [pytest.param(COMFY_ORG, id='Comfy-Org'), pytest.param(LTDRDATA, id='ltdrdata')]
CONFIGS = [pytest.param(None, id='no channel_url')] + SPELLINGS
CACHED = [pytest.param((), id='DEFAULT_CHANNEL'), pytest.param(('default_cache_as_channel_url = True',), id='channel_url')]

PRELUDE = '''
import ast, asyncio, logging, pathlib, traceback
from types import SimpleNamespace
from aiohttp import web
import cnr_utils
import manager_util
core = manager_core
user = pathlib.Path(tmp)
nodes = user / 'custom_nodes'
nodes.mkdir()
sys.modules['folder_paths'].get_folder_paths = lambda name: [str(nodes)]
core.manager_channel_list_path = str(user / 'channels.list')
manager_util.cache_dir = str(user / 'cache')
manager_util.comfyui_manager_path = str(user / 'manager')
os.makedirs(manager_util.cache_dir)
os.makedirs(manager_util.comfyui_manager_path)
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
for name, data in BUNDLED.items():
    (pathlib.Path(manager_util.comfyui_manager_path) / name).write_text(json.dumps(data))
REGISTRY = [{'id': 'comfyui-foo', 'name': 'Foo', 'repository': 'https://github.com/example/ComfyUI-Foo',
             'publisher': {'name': 'example'}, 'description': '', 'latest_version': {'version': '1.0.1'}}]
requests = []
get_data = manager_util.get_data

async def from_the_channel(uri, silent=False):
    if uri.startswith('https://'):
        requests.append(uri)
        return json.loads(json.dumps(SERVED[os.path.basename(uri)]))
    return await get_data(uri, silent)

async def get_cnr_data(*args, **kwargs):
    return REGISTRY

manager_util.get_data = from_the_channel
cnr_utils.get_cnr_data = get_cnr_data
core.unified_manager = core.UnifiedManager()
SERVER = pathlib.Path(core.__file__).with_name('manager_server.py')
route = lambda path: lambda handler: handler

def server(*names):
    functions = [node for node in ast.parse(SERVER.read_text(encoding='utf-8')).body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    scope = {'core': core, 'manager_util': manager_util, 'os': os, 'logging': logging, 'traceback': traceback, 'asyncio': asyncio,
             'web': web, 'routes': SimpleNamespace(get=route, post=route), 'populate_markdown': lambda node_pack: None}
    exec(compile(ast.Module(functions, []), str(SERVER), 'exec'), scope)
    return scope

def configure(channel_url, default_url, *lines):
    config = ['[default]'] + ([f'channel_url = {channel_url}'] if channel_url else []) + list(lines)
    pathlib.Path(CONFIG_PATH).write_text('\\n'.join(config) + '\\n')
    (user / 'channels.list').write_text(f'default::{default_url}\\nrecent::{default_url}/node_db/new\\nmirror::https://example.invalid/mirror\\n')

def start():
    try:
        asyncio.run(server('default_cache_update')['default_cache_update']())
    except Exception as e:
        return repr(e)

def answer(name, **query):
    response = asyncio.run(server(name)[name](SimpleNamespace(rel_url=SimpleNamespace(query=query))))
    return json.loads(response.text)

def emit(value):
    print()
    print(json.dumps(value))
'''


def run(body):
    return _run_child(PRELUDE + body)


@pytest.mark.parametrize('cached', CACHED)
@pytest.mark.parametrize('default_url', SPELLINGS)
@pytest.mark.parametrize('channel_url', CONFIGS)
def test_start_writes_the_lists_every_reader_reads(channel_url, default_url, cached):
    data = run(f'''
configure({channel_url!r}, {default_url!r}, *{cached!r})
failed = start()
started = len(os.listdir(manager_util.cache_dir))
requests.clear()
unread = [[channel, filename] for channel in (None, 'default', {COMFY_ORG!r}, {LTDRDATA!r}) for filename in SERVED
          if asyncio.run(core.get_data_by_mode('cache', filename, channel)) != SERVED[filename]]
level = asyncio.run(server('get_risky_level')['get_risky_level']([BAR_URL], []))
emit({{'failed': failed, 'cache': [started, len(os.listdir(manager_util.cache_dir))], 'unread': unread,
       'fetched': requests, 'level': level}})
''')

    assert data == {'failed': None, 'cache': [len(FILES), len(FILES)], 'unread': [], 'fetched': [], 'level': 'middle'}


@pytest.mark.parametrize('default_url', SPELLINGS)
@pytest.mark.parametrize('channel_url', CONFIGS)
def test_custom_nodes_manager_lists_the_registry_nodepacks_on_the_default_channel(channel_url, default_url):
    data = run(f'''
configure({channel_url!r}, {default_url!r})
start()
listed = answer('fetch_customnode_list', mode='cache')
emit({{'channel': listed['channel'], 'node_packs': {{key: row['reference'] for key, row in listed['node_packs'].items()}}}})
''')

    assert data == {'channel': 'default', 'node_packs': {
        'ComfyUI-Bar': 'https://github.com/example/ComfyUI-Bar', 'comfyui-foo': 'https://registry.comfy.org/nodes/comfyui-foo'}}


@pytest.mark.parametrize('default_url', SPELLINGS)
@pytest.mark.parametrize('channel_url', CONFIGS)
def test_channel_menu_selects_the_default_channel(channel_url, default_url):
    data = run(f'''
configure({channel_url!r}, {default_url!r})
emit(answer('get_channel_url_list')['selected'])
''')

    assert data == 'default'


@pytest.mark.parametrize('default_url', SPELLINGS)
def test_another_channel_keeps_its_own_lists(default_url):
    data = run(f'''
configure({MIRROR!r}, {default_url!r}, 'default_cache_as_channel_url = True')
failed = start()
cache = sorted(os.listdir(manager_util.cache_dir))
listed = answer('fetch_customnode_list', mode='cache')
requests.clear()
emit({{'failed': failed, 'cache': cache,
       'read': {{filename: asyncio.run(core.get_data_by_mode('cache', filename)) == SERVED[filename] for filename in SERVED}},
       'fetched': requests, 'selected': answer('get_channel_url_list')['selected'],
       'listed': [listed['channel'], list(listed['node_packs'])]}})
''')

    simple_hash = load_manager_util().simple_hash
    assert data == {'failed': None, 'cache': sorted(f'{simple_hash(f"{MIRROR}/{filename}")}_{filename}' for filename in FILES),
                    'read': dict.fromkeys(FILES, True), 'fetched': [], 'selected': 'mirror', 'listed': ['mirror', ['ComfyUI-Bar']]}

