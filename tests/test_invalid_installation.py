import re
from pathlib import Path

import pytest

from js_lift import NODE, JsSource, line_containing, parse, run_node, slice_braced
from test_install_flags_config import _run_child

PRELUDE = '''
import ast, asyncio, logging, pathlib, zipfile
from types import SimpleNamespace
from unittest.mock import Mock
import cnr_utils
core = manager_core
nodes = pathlib.Path(tmp) / 'custom_nodes'
nodes.mkdir()
sys.modules['folder_paths'].get_folder_paths = lambda name: [str(nodes)]
core.get_default_custom_nodes_path = lambda: str(nodes)
config = {'network_mode': 'public', 'channel_url': core.DEFAULT_CHANNEL, 'http_channel_enabled': False,
          'allow_flagged_nodepack_install': False}
core.get_config = lambda: config
core.valid_channels.add(core.DEFAULT_CHANNEL)
FOO_URL = 'https://github.com/example/ComfyUI-Foo'
BAR_URL = 'https://github.com/example/ComfyUI-Bar'
REGISTRY = [
    {'id': 'comfyui-foo', 'name': 'Foo', 'repository': FOO_URL, 'publisher': {'name': 'example'},
     'description': '', 'latest_version': {'version': '1.0.1'}},
    {'id': 'comfyui-baz', 'name': 'Baz', 'repository': 'https://github.com/example/comfyui-baz',
     'publisher': {'name': 'example'}, 'description': '', 'latest_version': {'version': '2.0.0'}},
]
NODE_LIST = [
    {'author': 'example', 'title': 'ComfyUI-Foo', 'reference': FOO_URL, 'files': [FOO_URL],
     'install_type': 'git-clone', 'description': ''},
    {'author': 'example', 'title': 'ComfyUI-Bar', 'reference': BAR_URL, 'files': [BAR_URL],
     'install_type': 'git-clone', 'description': ''},
]

async def get_cnr_data(*args, **kwargs):
    return REGISTRY

async def get_data_by_mode(mode, filename, channel_url=None):
    return {'custom_nodes': [dict(item) for item in NODE_LIST]}

cnr_utils.get_cnr_data = get_cnr_data
core.get_data_by_mode = get_data_by_mode
manager = core.UnifiedManager()
core.unified_manager = manager
manager.execute_install_script = Mock(return_value=True)

def pack(name, project_name=None, version='1.0.1', tracking=False, git_url=None):
    path = nodes / name
    path.mkdir(parents=True)
    (path / '__init__.py').write_text('NODE_CLASS_MAPPINGS = {}\\n')
    if project_name is not None:
        (path / 'pyproject.toml').write_text(f'[project]\\nname = "{project_name}"\\nversion = "{version}"\\n')
    if tracking:
        (path / '.tracking').write_text('__init__.py\\npyproject.toml\\n')
    if git_url is not None:
        (path / '.git').mkdir()
        (path / '.git/HEAD').write_text('0123456789abcdef0123456789abcdef01234567\\n')
        (path / '.git/config').write_text(f'[remote "origin"]\\n\\turl = {git_url}\\n')
    return path

def reload():
    asyncio.run(manager.reload('cache'))

def flagged_rows():
    rows = asyncio.run(core.get_unified_total_nodes(core.DEFAULT_CHANNEL, 'cache'))
    return {key: row['state'] for key, row in rows.items() if row.get('invalid-installation')}

def run_update_all():
    queued = []

    async def save_snapshot_with_postfix(postfix):
        pass

    async def body():
        return {'mode': 'cache'}

    core.save_snapshot_with_postfix = save_snapshot_with_postfix
    update_all = server_function(
        'update_all', core=core, os=os, logging=logging, task_worker_thread=None,
        task_worker_lock=Mock(__enter__=Mock(), __exit__=Mock(return_value=False)),
        _reject_non_json_content_type=lambda request: None, is_allowed_security_level=lambda level: True,
        task_queue=SimpleNamespace(put=lambda item: queued.append(item[1][1])),
        web=SimpleNamespace(Response=lambda status: status))
    assert asyncio.run(update_all(SimpleNamespace(json=body))) == 200
    return sorted(queued)

def left():
    return sorted(path.name for path in nodes.iterdir())

def archive_of_foo(url, directory, name):
    with zipfile.ZipFile(pathlib.Path(directory) / name, 'w') as archive:
        archive.writestr('__init__.py', 'NODE_CLASS_MAPPINGS = {}  # 1.0.1\\n')
        archive.writestr('pyproject.toml', '[project]\\nname = "comfyui-foo"\\nversion = "1.0.1"\\n')

def refused(url, directory, name):
    import urllib.error
    raise urllib.error.URLError(ConnectionRefusedError(111, 'Connection refused'))

def block_page(url, directory, name):
    (pathlib.Path(directory) / name).write_text('<html><body>Access blocked</body></html>')

def registry_api(status='NodeVersionStatusActive', download=archive_of_foo):
    cnr_utils.requests.get = Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {
        'id': 'version-id', 'node_id': 'comfyui-foo', 'version': '1.0.1', 'status': status,
        'downloadUrl': 'https://example.invalid/comfyui-foo.zip'}))
    core.manager_funcs.is_flagged_install_allowed = lambda *args: False
    core.manager_downloader.download_url = Mock(side_effect=download)

def files(path):
    return {x.relative_to(path).as_posix(): x.read_text() for x in sorted(pathlib.Path(path).rglob('*')) if x.is_file()}

def listing():
    names = sorted(x.name for x in nodes.iterdir() if x.name != '.disabled')
    disabled = nodes / '.disabled'
    return names + (sorted(f'.disabled/{x.name}' for x in disabled.iterdir()) if disabled.exists() else [])

def a_users_folder(name, project_name='comfyui-foo'):
    folder = pack(name, project_name)
    (folder / 'my_settings.json').write_text('{"user": "added this"}\\n')
    return folder

def load_the_registry_list():
    for cnr in REGISTRY:
        manager.cnr_map[cnr['id']] = cnr
        manager.repo_cnr_map[cnr['repository']] = cnr

def clone_stand_in(fails=False):
    def clone(url, path, **kwargs):
        path = pathlib.Path(path)
        (path / '.git').mkdir(parents=True)
        if fails:
            raise OSError('the remote end hung up unexpectedly')
        (path / '.git/config').write_text(f'[remote "origin"]\\n\\turl = {url}\\n')
        return SimpleNamespace(git=SimpleNamespace(clear_cache=lambda: None), close=lambda: None)

    run_script = core.manager_funcs.run_script

    def helper_process(cmd, *args, **kwargs):
        if '--clone' not in cmd:
            return run_script(cmd, *args, **kwargs)
        try:
            clone(cmd[-2], cmd[-1])
        except OSError:
            return 1
        return 0

    core.manager_funcs.run_script = helper_process
    core.git.Repo.clone_from = staticmethod(clone)

def a_clone_at_the_install_path():
    folder = pack('comfyui-foo', git_url='https://github.com/someone/ComfyUI-Foo-fork')
    (folder / 'my_settings.json').write_text('{"user": "added this"}\\n')
    return folder

def an_install_of_foo(version, fails=False):
    if version == 'nightly':
        clone_stand_in(fails=fails)
    else:
        registry_api(download=refused if fails else archive_of_foo)

def a_clone_of_a_fork_named_like_foo():
    folder = pack('foo-fork', git_url='https://github.com/someone/comfyui-foo')
    (folder / 'my_settings.json').write_text('{"user": "added this"}\\n')
    return folder

def folders_in_the_maps():
    return [*(x[1] for x in manager.active_nodes.values()), *(x[1] for x in manager.unknown_active_nodes.values()),
            *(x[1] for x in manager.unknown_inactive_nodes.values()), *manager.nightly_inactive_nodes.values(),
            *(x for versions in manager.cnr_inactive_nodes.values() for x in versions.values()),
            *manager.invalid_installations]

def cm_cli_function(name, namespace, class_name=None):
    path = pathlib.Path(manager_core.__file__).parent.parent / 'cm-cli.py'
    body = ast.parse(path.read_text(encoding='utf-8')).body
    if class_name is not None:
        body = next(node for node in body if isinstance(node, ast.ClassDef) and node.name == class_name).body
    found = [node for node in body if isinstance(node, ast.FunctionDef) and node.name == name]
    exec(compile(ast.Module(found, []), str(path), 'exec'), namespace)
    return namespace[name]

def cm_cli_reinstall_node(out=None):
    import io, rich.console, rich.markup
    console = rich.console.Console(file=out if out is not None else io.StringIO(), width=1000, color_system=None)
    return cm_cli_function('reinstall_node', {
        'asyncio': asyncio, 'os': os, 'core': core, 'unified_manager': manager, 'print': console.print,
        'escape': rich.markup.escape, 'cmd_ctx': SimpleNamespace(channel='default', mode='cache', no_deps=False)})

def notice():
    import contextlib, io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        core.check_invalid_nodes()
    return out.getvalue()

def server_function(name, **namespace):
    path = pathlib.Path(manager_core.__file__).parent / 'manager_server.py'
    found = [node for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
             if isinstance(node, ast.AsyncFunctionDef) and node.name == name]
    for node in found:
        node.decorator_list = []
    namespace = dict(namespace)
    exec(compile(ast.Module(found, []), str(path), 'exec'), namespace)
    return namespace[name]

def cannot_delete(locked, schedule_fails=False, movable=False):
    import shutil
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

    core.shutil.rmtree = held_open
    os.rename = move
    core.time.sleep = lambda seconds: None
    core.reserve_script = reserve_script
    return scheduled

def read_only_files_as_on_windows():
    # Windows refuses to delete a read-only file, such as a pack file of a git clone, until `attrib -R`, which rmtree
    # runs there, clears the attribute
    import shutil
    core.platform.system = lambda: 'Windows'
    delete, run_script = shutil.rmtree, core.manager_funcs.run_script

    def refuses_read_only(path, *args, **kwargs):
        read_only = [x for x in pathlib.Path(path).rglob('*') if x.is_file() and not x.stat().st_mode & 0o200]
        if read_only:
            raise PermissionError(13, 'Access is denied', str(read_only[0]))
        return delete(path, *args, **kwargs)

    def attrib(cmd, *args, **kwargs):
        if cmd[:2] != ['attrib', '-R']:
            return run_script(cmd, *args, **kwargs)
        for x in pathlib.Path(cmd[2].removesuffix('\\\\*')).rglob('*'):
            x.chmod(x.stat().st_mode | 0o200)
        return 0

    core.shutil.rmtree = refuses_read_only
    core.manager_funcs.run_script = attrib

def the_new_installation(path):
    init = pathlib.Path(path, '__init__.py')
    return init.is_file() and '# 1.0.1' in init.read_text()

def warnings():
    found = []
    handler = logging.Handler()
    handler.emit = lambda record: found.append(record.getMessage()) if record.levelno == logging.WARNING else None
    logging.getLogger().addHandler(handler)
    return found

def emit(value):
    print()
    print(json.dumps(value))
'''
INVALID = {'ver': 'unknown', 'aux_id': None, 'invalid_installation': True}
GUIDANCE = ('This nodepack was not installed through ComfyUI-Manager, or its installation is damaged, so the Manager '
            'cannot update it. Reinstalling deletes its folder and installs the nodepack again.')


def run(body):
    return _run_child(PRELUDE + body)


def moved_to_the_archive(folder, archived, node_id='comfyui-foo'):
    return f"[ComfyUI-Manager] '{folder}' was in the way of the reinstall of '{node_id}' and was moved to '{archived}'."


@pytest.mark.parametrize('folder, project_name, cnr_id, row', [
    ('comfyui-foo', 'comfyui-foo', 'comfyui-foo', 'comfyui-foo'),
    ('ComfyUI-Foo-main', 'ComfyUI-Foo', 'comfyui-foo', 'comfyui-foo'),
    ('comfyui-baz', 'comfyui-foo', 'comfyui-foo', 'comfyui-foo'),
    ('comfyui-baz', 'not-in-the-registry', 'comfyui-baz', 'comfyui-baz'),
    ('ComfyUI-Baz', None, 'comfyui-baz', 'comfyui-baz'),
    ('ComfyUI-Bar', None, '', 'ComfyUI-Bar'),
    ('Something-Else', None, '', None),
], ids=['no-tracking', 'github-zip', 'project-name-first', 'folder-name', 'folder-name-case', 'non-registry', 'no-row'])
def test_the_pack_of_an_invalid_installation(folder, project_name, cnr_id, row):
    data = run(f'''
pack({folder!r}, {project_name!r})
reload()
emit({{'installed': core.get_installed_node_packs(), 'rows': flagged_rows()}})
''')
    assert data['installed'] == {folder: {**INVALID, 'cnr_id': cnr_id, 'enabled': True}}
    assert data['rows'] == ({row: 'enabled'} if row else {})


@pytest.mark.parametrize('folder, project_name, before, after', [
    ('comfyui-foo', 'comfyui-foo', 'comfyui-foo', 'comfyui-foo'),
    ('ComfyUI-Foo-main', 'ComfyUI-Foo', 'comfyui-foo', 'comfyui-foo'),
    ('comfyui-baz', 'not-in-the-registry', 'not-in-the-registry', 'comfyui-baz'),
    ('Something-Else', 'something-else', 'something-else', 'something-else'),
    ('comfyui-baz', None, '', 'comfyui-baz'),
    ('ComfyUI-Bar', None, '', ''),
], ids=['no-tracking', 'github-zip', 'folder-name', 'not-in-the-registry', 'no-pyproject', 'non-registry'])
def test_the_installed_map_tells_the_pack_before_the_registry_list_is_loaded(folder, project_name, before, after):
    data = run(f'''
pack({folder!r}, {project_name!r})
assert not manager.cnr_map
before = core.get_installed_node_packs()
reload()
emit({{'before': before, 'after': core.get_installed_node_packs()}})
''')
    assert data['before'] == {folder: {**INVALID, 'cnr_id': before, 'enabled': True}}
    assert data['after'] == {folder: {**INVALID, 'cnr_id': after, 'enabled': True}}


@pytest.mark.parametrize('folder, project_name, cnr_id, row', [
    ('ComfyUI-Bar', None, '', 'ComfyUI-Bar'), ('ComfyUI-Foo-main', 'comfyui-foo', 'comfyui-foo', 'comfyui-foo'),
], ids=['non-registry', 'registry'])
def test_a_disabled_invalid_installation(folder, project_name, cnr_id, row):
    data = run(f'''
pack('.disabled/' + {folder!r}, {project_name!r})
reload()
emit({{'installed': core.get_installed_node_packs(), 'rows': flagged_rows()}})
''')
    assert data['installed'] == {folder: {**INVALID, 'cnr_id': cnr_id, 'enabled': False}}
    assert data['rows'] == {row: 'disabled'}


def test_what_is_never_an_invalid_installation():
    data = run('''
import contextlib, io
pack('comfyui-foo', 'comfyui-foo', tracking=True)
pack('ComfyUI-Bar', git_url=BAR_URL)
pack('not-in-the-registry', 'not-in-the-registry', version='3.0.0', tracking=True)
pack('tracking-without-pyproject', tracking=True)
pack('comfyui-manager', 'comfyui-manager')
(nodes / '__pycache__').mkdir()
(nodes / '.disabled').mkdir()
(nodes / 'single_file_node.py').write_text('')
(nodes / '.ipynb_checkpoints').mkdir()
(nodes / '.git').mkdir()
(nodes / '__MACOSX').mkdir()
(nodes / '.disabled/__pycache__').mkdir()
reload()
out = io.StringIO()
with contextlib.redirect_stdout(out):
    core.check_invalid_nodes()
emit({'installed': core.get_installed_node_packs(), 'rows': flagged_rows(), 'notice': out.getvalue()})
''')
    assert data['installed'] == {
        'comfyui-foo': {'ver': '1.0.1', 'cnr_id': 'comfyui-foo', 'aux_id': None, 'enabled': True},
        'ComfyUI-Bar': {'ver': '0123456789abcdef0123456789abcdef01234567', 'cnr_id': '',
                        'aux_id': 'example/ComfyUI-Bar', 'enabled': True},
        'not-in-the-registry': {'ver': '3.0.0', 'cnr_id': 'not-in-the-registry', 'aux_id': None, 'enabled': True},
    }
    assert data['rows'] == {}
    assert data['notice'] == ''


def test_a_symbolic_link_is_never_an_invalid_installation():
    data = run('''
elsewhere = pathlib.Path(tmp) / 'elsewhere'
(elsewhere / 'comfyui-baz').mkdir(parents=True)
(elsewhere / 'comfyui-baz/pyproject.toml').write_text('[project]\\nname = "comfyui-baz"\\nversion = "2.0.0"\\n')
(elsewhere / 'ComfyUI-Qux-main').mkdir()
try:
    (nodes / 'comfyui-baz').symlink_to(elsewhere / 'comfyui-baz', target_is_directory=True)
    (nodes / 'ComfyUI-Qux-main').symlink_to(elsewhere / 'ComfyUI-Qux-main', target_is_directory=True)
    links = True
except OSError:  # Windows without Developer Mode or the privilege to create a symbolic link
    links = False
reload()
emit({'links': links, 'installed': core.get_installed_node_packs(), 'rows': flagged_rows(), 'notice': notice()})
''')
    if not data['links']:
        pytest.skip('the platform refuses to create a symbolic link')
    assert (data['installed'], data['rows'], data['notice']) == ({}, {}, '')


def test_a_junction_is_never_an_invalid_installation():
    data = run('''
junction = pack('comfyui-foo', 'comfyui-foo')
before = files(junction)

from node_package import IO_REPARSE_TAG_MOUNT_POINT

class JunctionStat:
    st_reparse_tag = IO_REPARSE_TAG_MOUNT_POINT

    def __init__(self, result):
        self._result = result

    def __getattr__(self, name):
        return getattr(self._result, name)

lstat = os.lstat
os.lstat = lambda path, *args, **kwargs: (
    JunctionStat(lstat(path, *args, **kwargs)) if os.fspath(path) == str(junction) else lstat(path, *args, **kwargs))
if hasattr(os.path, 'isjunction'):
    del os.path.isjunction
registry_api()
reload()
installed, rows, told = core.get_installed_node_packs(), flagged_rows(), notice()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
emit({'installed': installed, 'rows': rows, 'notice': told, 'ok': result.result, 'same': before == files(junction)})
''')
    assert (data['installed'], data['rows']) == ({}, {})
    assert 'Nodes requiring reinstallation' not in data['notice']
    assert data['ok'] is False
    assert data['same'] is True


def test_a_reload_forgets_a_folder_that_is_gone():
    data = run('''
folder = pack('comfyui-foo', 'comfyui-foo')
before = flagged_rows()
(folder / '.tracking').write_text('__init__.py\\n')
emit({'before': before, 'after': flagged_rows()})
''')
    assert data == {'before': {'comfyui-foo': 'enabled'}, 'after': {}}


@pytest.mark.parametrize('folder, project_name', [('ComfyUI-Foo-main', 'comfyui-foo'), ('ComfyUI-Bar', None)],
                         ids=['of-a-registry-nodepack', 'of-another'])
def test_by_its_folder_name_an_invalid_installation_is_disabled_enabled_and_uninstalled(folder, project_name):
    data = run(f'''
pack({folder!r}, {project_name!r})
reload()
steps = []
manager.unified_disable({folder!r}, True)
steps.append([listing(), core.get_installed_node_packs()])
manager.unified_enable({folder!r}, 'unknown')
steps.append([listing(), core.get_installed_node_packs()])
manager.unified_uninstall({folder!r}, True)
steps.append([listing(), core.get_installed_node_packs()])
emit(steps)
''')
    entry = {**INVALID, 'cnr_id': project_name or ''}
    assert data == [[[f'.disabled/{folder}'], {folder: {**entry, 'enabled': False}}],
                    [[folder], {folder: {**entry, 'enabled': True}}],
                    [[], {}]]


@pytest.mark.parametrize('move', ['disable', 'enable'])
def test_a_reinstall_finds_an_invalid_installation_that_disable_or_enable_moved(move):
    data = run(f'''
disabled = {move!r} == 'enable'
pack('.disabled/ComfyUI-Foo-main' if disabled else 'ComfyUI-Foo-main', 'comfyui-foo')
registry_api()
reload()
if disabled:
    manager.unified_enable('ComfyUI-Foo-main', 'unknown')
else:
    manager.unified_disable('ComfyUI-Foo-main', True)
moved = nodes / ('ComfyUI-Foo-main' if disabled else '.disabled/ComfyUI-Foo-main')
told = notice()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
emit({{'moved': str(moved), 'notice': told, 'ok': result.result, 'msg': result.msg, 'left': listing()}})
''')
    assert f"{data['moved']} (nodepack: comfyui-foo)" in data['notice'].splitlines()
    assert data['ok'] is True, data['msg']
    assert data['left'] == ['comfyui-foo']


def test_the_notice_lists_the_invalid_folders_that_a_reload_found():
    data = run('''
bar = pack('ComfyUI-Bar')
foo = pack('.disabled/ComfyUI-Foo-main', 'comfyui-foo')
reload()
emit({'bar': str(bar), 'foo': str(foo), 'out': notice()})
''')
    assert 'Nodes requiring reinstallation have been detected' in data['out']
    assert 'not installed through ComfyUI-Manager, or their installation is damaged' in data['out']
    assert f"{data['bar']} (nodepack: ComfyUI-Bar)" in data['out'].splitlines()
    assert f"{data['foo']} (nodepack: comfyui-foo)" in data['out'].splitlines()
    assert 'unfinished reinstall notice' not in data['out']


def test_two_reloads_that_interleave_tell_a_folder_once():
    data = run('''
folder = pack('ComfyUI-Foo-main', 'comfyui-foo')

async def loading(*args, **kwargs):
    await asyncio.sleep(0)
    return REGISTRY

cnr_utils.get_cnr_data = loading

async def both():
    await asyncio.gather(manager.reload('remote'), manager.reload('cache'))

asyncio.run(both())
emit({'folder': str(folder), 'notice': notice()})
''')
    assert data['notice'].count(data['folder']) == 1


@pytest.mark.parametrize('reader', ['uninstall-by-id', 'notice'])
def test_a_folder_recorded_while_the_records_are_read_does_not_stop_the_reader(reader):
    data = run(f'''
folder = pack('ComfyUI-Foo-main', 'comfyui-foo')
reload()
late = pack('ComfyUI-Foo-copy', 'comfyui-foo')
pack_id, recorded = manager.invalid_pack_id, []

def recording_one_more(installation):
    if not recorded:
        recorded.append(str(late))
        manager.update_cache_at_path(str(late))
    return pack_id(installation)

manager.invalid_pack_id = recording_one_more
if {reader!r} == 'notice':
    out = {{'notice': notice().splitlines()}}
else:
    out = {{'ok': manager.unified_uninstall('comfyui-foo', False).result, 'gone': not folder.exists()}}
emit({{**out, 'folder': str(folder), 'late': str(late), 'recorded': recorded}})
''')
    if reader == 'notice':
        assert f"{data['folder']} (nodepack: comfyui-foo)" in data['notice']
    else:
        assert (data['ok'], data['gone']) == (True, True)
    assert data['recorded'] == [data['late']]


@pytest.mark.parametrize('network_mode', ['public', 'private', 'offline'])
def test_the_startup_notice_does_not_depend_on_the_network_mode(network_mode):
    data = run(f'''
import contextlib, io, traceback
folder = pack('ComfyUI-Foo-main', 'comfyui-foo')
config.update(network_mode={network_mode!r}, default_cache_as_channel_url=False)
core.refresh_channel_dict = lambda: None

async def no_channel(uri, silent=False):
    raise OSError('no network in this test')

startup = server_function('default_cache_update', core=core, os=os, logging=logging, asyncio=asyncio,
                          traceback=SimpleNamespace(print_exc=lambda: None),
                          manager_util=SimpleNamespace(get_data=no_channel, simple_hash=core.manager_util.simple_hash,
                                                       cache_dir='', write_cache_file=lambda *args: False))
out = io.StringIO()
with contextlib.redirect_stdout(out):
    asyncio.run(startup())
emit({{'folder': str(folder), 'out': out.getvalue()}})
''')
    assert 'Nodes requiring reinstallation have been detected' in data['out']
    assert data['folder'] in data['out']


@pytest.mark.parametrize('network_mode', ['private', 'offline'])
def test_a_private_or_offline_start_tells_the_invalid_installations_and_nothing_of_the_registry_cache(network_mode):
    data = run(f'''
import contextlib, importlib, io
folder = pack('ComfyUI-Foo-main', 'comfyui-foo')
config.update(network_mode={network_mode!r}, default_cache_as_channel_url=False)
core.refresh_channel_dict = lambda: None
importlib.reload(cnr_utils)
core.manager_util.cache_dir = str(pathlib.Path(tmp) / 'cache')
os.makedirs(core.manager_util.cache_dir)
core.manager_util.save_to_cache(f'{{cnr_utils.base_url}}/nodes', {{'nodes': REGISTRY}}, silent=True)

async def no_channel(uri, silent=False):
    raise OSError('no network in this test')

startup = server_function('default_cache_update', core=core, os=os, logging=logging, asyncio=asyncio,
                          traceback=SimpleNamespace(print_exc=lambda: None),
                          manager_util=SimpleNamespace(get_data=no_channel, simple_hash=core.manager_util.simple_hash,
                                                       cache_dir='', write_cache_file=lambda *args: False))
start, listed = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(start):
    asyncio.run(startup())
with contextlib.redirect_stdout(listed):
    reload()
emit({{'folder': str(folder), 'start': start.getvalue().splitlines(), 'listed': listed.getvalue().splitlines()}})
''')
    registry_line = '[ComfyUI-Manager] The ComfyRegistry cache update is still in progress, so an outdated cache is being used.'
    assert f"{data['folder']} (nodepack: comfyui-foo)" in data['start']
    assert registry_line not in data['start']
    assert registry_line in data['listed']


@pytest.mark.parametrize('invalid', [True, False], ids=['after-the-invalid-installations', 'alone'])
def test_the_notice_tells_the_folders_that_a_reinstall_which_did_not_finish_kept(invalid):
    data = run(f'''
other = pathlib.Path(tmp) / 'other_custom_nodes'
other.mkdir()
sys.modules['folder_paths'].get_folder_paths = lambda name: [str(nodes), str(other)]
held = [a_users_folder('.disabled/.reinstall/0f1e2d3c/ComfyUI-Foo-main'),
        a_users_folder(other / '.disabled/.reinstall/9a8b7c6d/ComfyUI-Bar', None)]
if {invalid!r}:
    pack('ComfyUI-Baz-main', 'comfyui-baz')
before = files(tmp)
reload()
out = notice()
emit({{'held': [str(x) for x in held], 'out': out, 'same': before == files(tmp)}})
''')
    out = data['out']
    assert ('-------------------- ComfyUI-Manager unfinished reinstall notice ---------\n'
            '\n'
            'A reinstall set these nodepack folders aside, and either did not finish or could not delete them.\n'
            'To get one back, stop ComfyUI and move it into custom_nodes, in place of what the reinstall left there. '
            'Otherwise delete it.\n'
            '\n'
            f"{data['held'][0]}\n"
            f"{data['held'][1]}\n"
            '\n'
            '---------------------------------------------------------------------------\n') in out
    assert ('invalid nodes notice' in out) is invalid
    if invalid:
        assert out.index('invalid nodes notice') < out.index('unfinished reinstall notice')
    assert data['same'] is True


@pytest.mark.parametrize('asked', ['before the registry list has loaded', 'after it has loaded'])
def test_which_nodepack_a_folder_is_does_not_depend_on_when_the_scan_ran(asked):
    data = run(f'''
folder = pack('ComfyUI-Foo-main', 'ComfyUI-Foo')
registry_api()

async def not_loaded_yet(*args, **kwargs):
    return []

cnr_utils.get_cnr_data = not_loaded_yet
reload()
if {asked!r} == 'after it has loaded':
    load_the_registry_list()
installed = core.get_installed_node_packs()
reason = manager.unified_update('comfyui-foo').msg
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
emit({{'installed': installed, 'reason': reason, 'folder': str(folder), 'ok': result.result, 'msg': result.msg,
       'left': listing()}})
''')
    assert data['installed'] == {'ComfyUI-Foo-main': {**INVALID, 'cnr_id': 'comfyui-foo', 'enabled': True}}
    assert f"Reinstalling deletes its folder ({data['folder']})" in data['reason']
    assert data['ok'] is True, data['msg']
    assert data['left'] == ['comfyui-foo']


def test_uninstall_by_id_after_the_registry_list_has_loaded_removes_what_the_scan_found_before():
    data = run('''
pack('ComfyUI-Foo-main', 'ComfyUI-Foo')

async def not_loaded_yet(*args, **kwargs):
    return []

cnr_utils.get_cnr_data = not_loaded_yet
reload()
load_the_registry_list()
emit({'ok': manager.unified_uninstall('comfyui-foo', False).result, 'left': listing()})
''')
    assert data == {'ok': True, 'left': []}


@pytest.mark.parametrize('valid, row, state', [
    ('comfyui-foo', 'comfyui-foo', 'enabled'),
    ('.disabled/comfyui-foo@1_0_1', 'comfyui-foo', 'disabled'),
    ('bar-clone', 'ComfyUI-Bar', 'enabled'),
], ids=['registry-enabled', 'registry-disabled', 'git'])
def test_a_valid_installation_beside_a_stray_copy_keeps_its_row(valid, row, state):
    data = run(f'''
if {row!r} == 'comfyui-foo':
    pack({valid!r}, 'comfyui-foo', tracking=True)
    stray = pack('ComfyUI-Foo-main', 'comfyui-foo')
else:
    pack({valid!r}, git_url=BAR_URL)
    stray = pack('.disabled/ComfyUI-Bar')
reload()
rows = asyncio.run(core.get_unified_total_nodes(core.DEFAULT_CHANNEL, 'cache'))
emit({{'row': rows[{row!r}], 'stray': str(stray), 'installed': core.get_installed_node_packs()[stray.name],
       'notice': notice()}})
''')
    assert data['row']['state'] == state
    assert 'invalid-installation' not in data['row']
    assert data['installed']['invalid_installation'] is True
    assert data['stray'] in data['notice']


def test_a_valid_installation_and_its_stray_copy_go_together():
    data = run('''
pack('comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
pack('ComfyUI-Foo-main', 'comfyui-foo')
registry_api()
reload()
ok = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1')).result
emit({'ok': ok, 'left': listing(), 'files': files(nodes)})
''')
    assert data['ok'] is True
    assert data['left'] == ['comfyui-foo']
    assert '# 1.0.1' in data['files']['comfyui-foo/__init__.py']


@pytest.mark.parametrize('order', [['bar-clone', 'ComfyUI-Bar'], ['ComfyUI-Bar', 'bar-clone']],
                         ids=['clone-read-first', 'invalid-read-first'])
def test_a_valid_clone_keeps_its_key_whichever_folder_is_read_first(order):
    data = run(f'''
pack('bar-clone', git_url=BAR_URL)
invalid = pack('ComfyUI-Bar')
listdir = os.listdir
os.listdir = lambda path='.': list({order!r}) if str(path) == str(nodes) else listdir(path)
reload()
emit({{'rows': flagged_rows(), 'queued': run_update_all(), 'invalid': str(invalid), 'notice': notice()}})
''')
    assert data['rows'] == {}
    assert data['queued'] == ['ComfyUI-Bar']
    assert f"{data['invalid']} (nodepack: ComfyUI-Bar)" in data['notice'].splitlines()


@pytest.mark.parametrize('stray', ['disabled', 'in-another-custom-nodes-path'])
def test_the_installed_map_lists_the_valid_installation_of_a_name_that_a_stray_copy_has(stray):
    data = run(f'''
pack('comfyui-foo', 'comfyui-foo', tracking=True)
if {stray!r} == 'disabled':
    pack('.disabled/comfyui-foo', 'comfyui-foo')
else:
    other = pathlib.Path(tmp) / 'other_custom_nodes'
    pack(other / 'comfyui-foo', 'comfyui-foo')
    sys.modules['folder_paths'].get_folder_paths = lambda name: [str(nodes), str(other)]
reload()
emit(core.get_installed_node_packs())
''')
    assert data == {'comfyui-foo': {'ver': '1.0.1', 'cnr_id': 'comfyui-foo', 'aux_id': None, 'enabled': True}}


def test_update_all_queues_no_update_for_an_invalid_installation():
    data = run('''
pack('ComfyUI-Bar')
pack('ComfyUI-Foo-main', 'comfyui-foo')
pack('comfyui-baz', 'comfyui-baz', version='2.0.0', tracking=True)
pack('ComfyUI-Qux', git_url='https://github.com/example/ComfyUI-Qux')
emit(run_update_all())
''')
    assert data == ['ComfyUI-Qux', 'comfyui-baz']


def test_update_all_updates_a_git_pack_whose_id_a_stray_invalid_folder_shares():
    data = run('''
pack('bar-clone', git_url=BAR_URL)
pack('.disabled/ComfyUI-Bar')
emit(run_update_all())
''')
    assert data == ['ComfyUI-Bar']


def test_updating_an_invalid_installation_says_why_it_fails():
    data = run('''
folder = pack('ComfyUI-Bar')
reload()
result = manager.unified_update('ComfyUI-Bar', 'unknown')
emit({'ok': result.result, 'msg': result.msg, 'folder': str(folder)})
''')
    assert data['ok'] is False
    assert data['msg'] == (f"Cannot update 'ComfyUI-Bar': this nodepack was not installed through ComfyUI-Manager, or "
                           f"its installation is damaged, so the Manager cannot update it. Reinstalling deletes its "
                           f"folder ({data['folder']}) and installs the nodepack again.")


@pytest.mark.parametrize('version', [None, 'unknown', 'nightly', '1.0.1'])
def test_updating_an_invalid_installation_fails_the_same_whatever_version_is_asked(version):
    data = run(f'''
folder = pack('ComfyUI-Foo-main', 'comfyui-foo')
reload()
result = manager.unified_update('comfyui-foo', {version!r})
emit({{'ok': result.result, 'msg': result.msg, 'folder': str(folder)}})
''')
    assert data['ok'] is False
    assert data['msg'].startswith("Cannot update 'comfyui-foo': this nodepack was not installed through ComfyUI-Manager")
    assert f"Reinstalling deletes its folder ({data['folder']})" in data['msg']


def test_a_registry_install_beside_a_stray_invalid_folder_is_updated_as_before():
    data = run('''
pack('comfyui-foo', 'comfyui-foo', tracking=True)
pack('ComfyUI-Foo-main', 'comfyui-foo')
registry_api()
reload()
result = manager.unified_update('comfyui-foo')
emit([result.result, result.action, result.msg])
''')
    assert data == [True, 'skip', 'Up to date']


def test_the_console_line_of_a_failed_update_says_why():
    data = run('''
pack('ComfyUI-Bar')
reload()
errors = []
handler = logging.Handler()
handler.emit = lambda record: errors.append(record.getMessage()) if record.levelno == logging.ERROR else None
logging.getLogger().addHandler(handler)
import traceback
do_update = server_function('do_update', core=core, os=os, logging=logging, traceback=traceback,
                            manager_util=SimpleNamespace(clear_pip_cache=lambda: None))
asyncio.run(do_update(('ui', 'ComfyUI-Bar', 'unknown')))
emit(errors)
''')
    assert len(data) == 1
    assert "An error occurred while updating 'ComfyUI-Bar'" in data[0]
    assert 'not installed through ComfyUI-Manager, or its installation is damaged' in data[0]


@pytest.mark.parametrize('node_id, is_unknown, left', [
    ('comfyui-foo', False, ['ComfyUI-Bar-backup', 'ComfyUI-Foo-main', 'bar-clone', 'comfyui-bar']),
    ('ComfyUI-Bar', True, ['ComfyUI-Bar-backup', 'ComfyUI-Foo-main', 'comfyui-bar', 'comfyui-foo']),
], ids=['registry', 'unknown'])
def test_uninstall_leaves_the_invalid_installations_of_the_nodepack_in_other_folders(node_id, is_unknown, left):
    data = run(f'''
pack('comfyui-foo', 'comfyui-foo', tracking=True)
pack('ComfyUI-Foo-main', 'comfyui-foo')
pack('bar-clone', git_url=BAR_URL)
pack('ComfyUI-Bar-backup', 'ComfyUI-Bar')
pack('comfyui-bar')
reload()
result = manager.unified_uninstall({node_id!r}, {is_unknown!r})
emit({{'ok': result.result, 'left': left()}})
''')
    assert data == {'ok': True, 'left': left}


@pytest.mark.parametrize('folder, project_name, node_id, is_unknown', [
    ('comfyui-foo', 'comfyui-foo', 'comfyui-foo', False),
    ('ComfyUI-Bar', None, 'ComfyUI-Bar', True),
], ids=['by-id', 'by-folder-name'])
def test_an_install_right_after_the_uninstall_of_an_invalid_installation_installs_the_nodepack(folder, project_name,
                                                                                              node_id, is_unknown):
    data = run(f'''
pack({folder!r}, {project_name!r})
registry_api()
clone_stand_in()
reload()
uninstalled = manager.unified_uninstall({node_id!r}, {is_unknown!r}).result
result = asyncio.run(manager.install_by_id({node_id!r}, None, core.DEFAULT_CHANNEL, 'cache'))
emit({{'uninstalled': uninstalled, 'ok': result.result, 'action': result.action, 'msg': result.msg, 'left': listing()}})
''')
    assert data['uninstalled'] is True
    assert data['ok'] is True, data['msg']
    assert data['action'] != 'skip'
    assert data['left'] == [node_id]


@pytest.mark.parametrize('where', ['', '.disabled/'], ids=['enabled', 'disabled'])
def test_after_an_uninstall_by_folder_name_its_nodepack_has_no_invalid_installation_left(where):
    path = where + 'ComfyUI-Foo-main'
    data = run(f'''
folder = pack({path!r}, 'comfyui-foo')
reload()
uninstalled = manager.unified_uninstall('ComfyUI-Foo-main', True).result
update = manager.unified_update('comfyui-foo')
emit({{'uninstalled': uninstalled, 'gone': not folder.exists(), 'msg': update.msg or '', 'folder': str(folder)}})
''')
    assert (data['uninstalled'], data['gone']) == (True, True)
    assert 'not installed through ComfyUI-Manager' not in data['msg']
    assert data['folder'] not in data['msg']


@pytest.mark.parametrize('where', ['', '.disabled/'], ids=['enabled', 'disabled'])
@pytest.mark.parametrize('name, project_name, node_id, is_unknown', [
    ('ComfyUI-Bar', None, 'ComfyUI-Bar', True),
    ('ComfyUI-Foo-main', 'comfyui-foo', 'ComfyUI-Foo-main', True),
    ('ComfyUI-Foo-main', 'comfyui-foo', 'comfyui-foo', False),
], ids=['by-its-nodepack-which-is-its-folder-name', 'by-folder-name', 'by-id'])
def test_uninstall_of_an_invalid_installation_that_cannot_be_deleted_fails(where, name, project_name, node_id, is_unknown):
    data = run(f'''
folder = pack({where + name!r}, {project_name!r})
reload()
scheduled = cannot_delete(lambda path: path == str(folder))
try:
    manager.unified_uninstall({node_id!r}, {is_unknown!r})
    raised = None
except Exception as exc:
    raised = type(exc).__name__
emit({{'raised': raised, 'scheduled': scheduled, 'exists': folder.exists(), 'folder': str(folder), 'notice': notice()}})
''')
    assert data['raised'] == 'PermissionError'
    assert data['scheduled'] == []
    assert data['exists'] is True
    assert f"{data['folder']} (nodepack: {project_name or name})" in data['notice'].splitlines()


@pytest.mark.parametrize('folder', ['comfyui-foo', 'ComfyUI-Foo-main'])
def test_reinstall_makes_a_registry_install(folder):
    data = run(f'''
pack({folder!r}, 'comfyui-foo')
registry_api()
reload()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
after = left()
tracking = (nodes / 'comfyui-foo/.tracking').exists()
reload()
emit({{'ok': result.result, 'msg': result.msg, 'left': after, 'tracking': tracking,
                   'installed': core.get_installed_node_packs(), 'rows': flagged_rows()}})
''')
    assert data['ok'] is True, data['msg']
    assert data['left'] == ['comfyui-foo']
    assert data['tracking'] is True
    assert data['installed'] == {'comfyui-foo': {'ver': '1.0.1', 'cnr_id': 'comfyui-foo', 'aux_id': None, 'enabled': True}}
    assert data['rows'] == {}


def test_reinstall_makes_a_git_install_of_a_non_registry_pack():
    data = run('''
pack('ComfyUI-Bar')
reload()
clone_stand_in()
result = asyncio.run(manager.reinstall_by_id('ComfyUI-Bar', 'unknown', core.DEFAULT_CHANNEL, 'cache'))
emit({'ok': result.result, 'msg': result.msg, 'git': (nodes / 'ComfyUI-Bar/.git').is_dir(),
                  'rows': flagged_rows()})
''')
    assert data['ok'] is True, data['msg']
    assert data['git'] is True
    assert data['rows'] == {}


@pytest.mark.parametrize('folder', ['comfyui-foo', 'ComfyUI-Foo-main', '.disabled/ComfyUI-Foo-main'])
@pytest.mark.parametrize('download, reason', [('refused', 'Connection refused'), ('block_page', 'Empty archive file')],
                         ids=['download-fails', 'extraction-fails'])
def test_a_reinstall_that_cannot_install_keeps_the_folder(folder, download, reason):
    data = run(f'''
a_users_folder({folder!r})
before = files(nodes)
registry_api(download={download})
reload()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
after = files(nodes)
left = listing()
rows = flagged_rows()
registry_api()
again = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1')).result
emit({{'ok': result.result, 'msg': result.msg, 'same': before == after, 'left': left, 'rows': rows, 'again': again,
       'finally': listing()}})
''')
    assert data['ok'] is False
    assert reason in data['msg'] and 'previous installation was kept' in data['msg']
    assert data['same'] is True
    assert data['left'] == [folder]
    assert data['rows'] == {'comfyui-foo': 'disabled' if folder.startswith('.disabled') else 'enabled'}
    assert data['again'] is True
    assert data['finally'] == ['comfyui-foo']


def test_a_reinstall_whose_clone_fails_keeps_the_folder():
    data = run('''
a_users_folder('ComfyUI-Bar', None)
before = files(nodes)
clone_stand_in(fails=True)
reload()
result = asyncio.run(manager.reinstall_by_id('ComfyUI-Bar', 'unknown', core.DEFAULT_CHANNEL, 'cache'))
emit({'ok': result.result, 'msg': result.msg, 'same': before == files(nodes), 'rows': flagged_rows()})
''')
    assert data['ok'] is False
    assert 'https://github.com/example/ComfyUI-Bar' in data['msg'] and 'previous installation was kept' in data['msg']
    assert data['same'] is True
    assert data['rows'] == {'ComfyUI-Bar': 'enabled'}


def test_a_reinstall_whose_install_script_fails_removes_what_it_installed_and_keeps_the_folder():
    data = run('''
a_users_folder('comfyui-foo')
before = files(nodes)
registry_api()
reload()
manager.execute_install_script = Mock(return_value=False)
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
emit({'ok': result.result, 'msg': result.msg, 'same': before == files(nodes)})
''')
    assert data['ok'] is False
    assert 'Failed to execute install script' in data['msg'] and 'previous installation was kept' in data['msg']
    assert data['same'] is True


def test_a_reinstall_stops_before_anything_changes_when_a_folder_cannot_be_moved():
    data = run('''
pack('comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
stray = a_users_folder('ComfyUI-Foo-main')
before = files(nodes)
registry_api()
reload()
rename = os.rename

def locked(src, dst):
    if src == str(stray):
        raise PermissionError(13, 'Permission denied', src)
    return rename(src, dst)

os.rename = locked
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
os.rename = rename
emit({'ok': result.result, 'msg': result.msg, 'downloads': core.manager_downloader.download_url.call_count,
      'same': before == files(nodes), 'left': listing()})
''')
    assert data['ok'] is False
    assert 'Permission denied' in data['msg'] and 'previous installation was kept' in data['msg']
    assert data['downloads'] == 0
    assert data['same'] is True
    assert data['left'] == ['ComfyUI-Foo-main', 'comfyui-foo']


@pytest.mark.parametrize('movable', [True, False], ids=['can-be-moved', 'cannot-be-moved'])
def test_a_reinstall_whose_install_fails_leaves_what_it_cannot_delete_where_it_is(movable):
    data = run(f'''
folder = a_users_folder('comfyui-foo')
before = files(folder)
registry_api()
reload()
manager.execute_install_script = Mock(return_value=False)
scheduled = cannot_delete(the_new_installation, movable={movable!r})
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
held = [str(x) for x in (nodes / '.disabled/.reinstall').glob('*/*')]
emit({{'ok': result.result, 'msg': result.msg, 'held': held, 'kept': [before == files(x) for x in held],
       'left': the_new_installation(folder), 'scheduled': scheduled, 'notice': notice()}})
''')
    [held] = data['held']
    assert data['ok'] is False
    assert data['msg'] == ("Failed to reinstall 'comfyui-foo': Failed to execute install script: comfyui-foo@1.0.1. "
                           f"Its previous installation could not be put back and is kept in {held}")
    assert data['kept'] == [True]
    assert data['left'] is True
    assert data['scheduled'] == []
    assert held in data['notice'].splitlines()


@pytest.mark.parametrize('went_back', [False, True], ids=['previous-installation-held', 'all-went-back'])
def test_after_a_failed_reinstall_only_a_folder_that_went_back_is_installed(went_back):
    data = run(f'''
pack('comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
registry_api()
reload()
manager.execute_install_script = Mock(return_value=False)
if not {went_back!r}:
    cannot_delete(the_new_installation)
reinstall = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
install = asyncio.run(manager.install_by_id('comfyui-foo', None, core.DEFAULT_CHANNEL, 'cache'))
emit({{'msg': reinstall.msg, 'install': install.action}})
''')
    assert ('could not be put back' in data['msg']) is not went_back
    assert (data['install'] == 'skip') is went_back


def test_a_reinstall_that_cannot_delete_a_folder_it_set_aside_leaves_it_to_the_notice():
    data = run('''
folder = a_users_folder('comfyui-foo')
before = files(folder)
registry_api()
reload()
scheduled = cannot_delete(lambda path: '.reinstall' in pathlib.Path(path).parts)
warned = warnings()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
[held] = (nodes / '.disabled/.reinstall').glob('*/comfyui-foo')
emit({'ok': result.result, 'msg': result.msg, 'scheduled': scheduled, 'new': the_new_installation(folder),
      'held': str(held), 'kept': before == files(held), 'warned': warned, 'notice': notice()})
''')
    assert data['ok'] is True, data['msg']
    assert data['scheduled'] == []
    assert data['new'] is True
    assert data['kept'] is True
    assert any(str(Path(data['held']).parent) in x for x in data['warned'])
    assert data['held'] in data['notice'].splitlines()


def test_a_reinstall_whose_install_fails_schedules_no_deletion_of_its_install_path():
    data = run('''
folder = a_users_folder('comfyui-foo')
registry_api()
reload()
manager.execute_install_script = Mock(return_value=False)
locked = [True]
scheduled = cannot_delete(lambda path: locked[0] and the_new_installation(path), schedule_fails=True)
warned = warnings()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
[held] = (nodes / '.disabled/.reinstall').glob('*/comfyui-foo')
first = {'ok': result.result, 'msg': result.msg, 'held': str(held), 'scheduled': list(scheduled), 'warned': warned}
locked[0] = False
manager.execute_install_script = Mock(return_value=True)
again = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1')).result
emit({**first, 'folder': str(folder), 'again': again, 'new': the_new_installation(folder), 'finally': scheduled})
''')
    assert data['ok'] is False
    assert data['msg'].endswith(f"Its previous installation could not be put back and is kept in {data['held']}")
    assert data['scheduled'] == []
    assert any(data['folder'] in x for x in data['warned'])
    assert data['again'] is True
    assert data['new'] is True
    assert data['finally'] == []


def test_a_reinstall_deletes_the_read_only_files_of_the_clone_it_replaced():
    data = run('''
clone = pack('comfyui-foo', git_url=FOO_URL)
(clone / '.git/objects/pack').mkdir(parents=True)
for name in ('pack-0123.idx', 'pack-0123.pack'):
    (clone / '.git/objects/pack' / name).write_text('')
    (clone / '.git/objects/pack' / name).chmod(0o444)
read_only_files_as_on_windows()
registry_api()
reload()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
emit({'ok': result.result, 'msg': result.msg, 'new': the_new_installation(clone), 'left': listing(), 'notice': notice()})
''')
    assert data['ok'] is True, data['msg']
    assert data['new'] is True
    assert data['left'] == ['comfyui-foo']
    assert 'unfinished reinstall notice' not in data['notice']


@pytest.mark.parametrize('movable', [True, False], ids=['can-be-moved', 'cannot-be-moved'])
def test_a_reinstall_whose_extraction_fails_schedules_no_deletion_of_its_install_path(movable):
    data = run(f'''
folder = a_users_folder('comfyui-foo')
before = files(folder)
registry_api()
reload()

def fails_midway(archive, to):
    pathlib.Path(to, 'half_written.py').write_text('')
    raise OSError(28, 'No space left on device')

core.manager_util.extract_package_as_zip = fails_midway
scheduled = cannot_delete(lambda path: path == str(folder) and (folder / 'half_written.py').exists(), movable={movable!r})
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
emit({{'ok': result.result, 'msg': result.msg, 'scheduled': scheduled, 'back': before == files(folder)}})
''')
    assert data['ok'] is False
    assert 'No space left on device' in data['msg']
    assert data['scheduled'] == []
    assert data['back'] is False


def test_a_reinstall_puts_every_folder_back_when_an_empty_holding_place_cannot_be_removed():
    data = run('''
pack('comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
pack('.disabled/comfyui-foo@0_9_0', 'comfyui-foo', version='0.9.0', tracking=True)
before = files(nodes)
registry_api(download=refused)
reload()
rmdir, refused_once = os.rmdir, []

def busy_once(path, *args, **kwargs):
    if not refused_once:
        refused_once.append(path)
        raise PermissionError(13, 'Permission denied', os.fspath(path))
    return rmdir(path, *args, **kwargs)

os.rmdir = busy_once
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
os.rmdir = rmdir
emit({'ok': result.result, 'msg': result.msg, 'refused': len(refused_once), 'back': before == files(nodes)})
''')
    assert data['ok'] is False
    assert "Failed to reinstall 'comfyui-foo', so its previous installation was kept: " in data['msg']
    assert data['refused'] == 1
    assert data['back'] is True


def test_a_reinstall_that_cannot_move_a_folder_aside_nor_put_one_back_says_where_it_is_kept():
    data = run('''
folder = pack('comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
before = files(folder)
stray = a_users_folder('ComfyUI-Foo-main')
registry_api()
reload()
rename = os.rename

def locked(src, dst):
    if src == str(stray) or '.reinstall' in pathlib.Path(src).parts:
        raise PermissionError(13, 'Permission denied', src)
    return rename(src, dst)

os.rename = locked
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
os.rename = rename
[held] = (nodes / '.disabled/.reinstall').glob('*/comfyui-foo')
emit({'ok': result.result, 'msg': result.msg, 'held': str(held), 'stray': str(stray), 'kept': before == files(held),
      'downloads': core.manager_downloader.download_url.call_count, 'left': stray.exists()})
''')
    assert data['ok'] is False
    # an OSError gives its path as Python writes it, which doubles a backslash
    assert data['msg'] == (f"Failed to reinstall 'comfyui-foo': [Errno 13] Permission denied: {data['stray']!r}. "
                           f"Its previous installation could not be put back and is kept in {data['held']}")
    assert data['downloads'] == 0
    assert data['kept'] is True
    assert data['left'] is True


@pytest.mark.skipif(not hasattr(__import__('os'), 'fork'), reason='the crash is a child process that dies')
def test_a_crash_in_the_middle_of_a_reinstall_leaves_the_folder_on_disk():
    data = run('''
folder = a_users_folder('ComfyUI-Foo-main')
before = files(folder)
registry_api(download=lambda *args: os._exit(0))
reload()
child = os.fork()
if child == 0:
    asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
    os._exit(1)
died = os.waitstatus_to_exitcode(os.waitpid(child, 0)[1]) == 0
held = [files(x) for x in (nodes / '.disabled/.reinstall').glob('*/ComfyUI-Foo-main')]
reload()
invalid, installed, rows = len(manager.invalid_installations), core.get_installed_node_packs(), flagged_rows()
manager.unified_enable('.reinstall', 'unknown')
still = [files(x) for x in (nodes / '.disabled/.reinstall').glob('*/ComfyUI-Foo-main')]
emit({'died': died, 'held': held, 'before': before, 'invalid': invalid, 'installed': installed, 'rows': rows, 'still': still})
''')
    assert data['died'] is True
    assert data['held'] == [data['before']]
    assert (data['invalid'], data['installed'], data['rows']) == (0, {}, {})
    assert data['still'] == [data['before']]


@pytest.mark.parametrize('version', ['nightly', '1.0.1'])
def test_a_reinstall_archives_what_sits_at_its_install_path_under_another_key(version):
    data = run(f'''
clone = a_clone_at_the_install_path()
before = files(clone)
an_install_of_foo({version!r})
reload()
warned = warnings()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', {version!r}, core.DEFAULT_CHANNEL, 'cache'))
archived = [str(x) for x in (nodes / '.disabled/.archived').glob('*/comfyui-foo')]
kept, left = [before == files(x) for x in archived], listing()
reload()
emit({{'ok': result.result, 'msg': result.msg, 'clone': str(clone), 'archived': archived, 'kept': kept, 'left': left,
       'warned': warned, 'installed': core.get_installed_node_packs()}})
''')
    [archived] = data['archived']
    assert data['ok'] is True, data['msg']
    assert data['kept'] == [True]
    assert data['left'] == ['comfyui-foo', '.disabled/.archived']
    assert moved_to_the_archive(data['clone'], archived) in data['warned']
    assert data['installed']['comfyui-foo']['cnr_id'] == 'comfyui-foo'


@pytest.mark.parametrize('version, reason', [('nightly', 'https://github.com/example/ComfyUI-Foo'),
                                             ('1.0.1', 'Connection refused')])
def test_a_reinstall_that_cannot_install_keeps_what_sits_at_its_install_path(version, reason):
    data = run(f'''
a_clone_at_the_install_path()
before = files(nodes)
an_install_of_foo({version!r}, fails=True)
reload()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', {version!r}, core.DEFAULT_CHANNEL, 'cache'))
emit({{'ok': result.result, 'msg': result.msg, 'same': before == files(nodes), 'left': listing()}})
''')
    assert data['ok'] is False
    assert reason in data['msg'] and 'previous installation was kept' in data['msg']
    assert data['same'] is True
    assert data['left'] == ['comfyui-foo']


def test_a_reinstall_archives_a_clone_of_a_fork_that_has_the_name_of_the_nodepack():
    data = run('''
pack('comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
fork = a_clone_of_a_fork_named_like_foo()
before = files(fork)
registry_api()
reload()
warned = warnings()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
archived = [str(x) for x in (nodes / '.disabled/.archived').glob('*/foo-fork')]
emit({'ok': result.result, 'msg': result.msg, 'new': the_new_installation(nodes / 'comfyui-foo'), 'fork': str(fork),
      'archived': archived, 'kept': [before == files(x) for x in archived], 'left': listing(),
      'maps': folders_in_the_maps(), 'warned': warned})
''')
    [archived] = data['archived']
    assert data['ok'] is True, data['msg']
    assert data['new'] is True
    assert data['kept'] == [True]
    assert data['left'] == ['comfyui-foo', '.disabled/.archived']
    assert not {data['fork'], archived} & set(data['maps'])
    assert moved_to_the_archive(data['fork'], archived) in data['warned']


def test_a_reinstall_that_fails_puts_back_the_clone_of_a_fork_that_has_the_name_of_the_nodepack():
    data = run('''
pack('comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
fork = a_clone_of_a_fork_named_like_foo()
before = files(fork)
registry_api(download=refused)
reload()
warned = warnings()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
emit({'ok': result.result, 'msg': result.msg, 'back': before == files(fork),
      'archive': [str(x) for x in (nodes / '.disabled/.archived').glob('*')], 'warned': warned})
''')
    assert data['ok'] is False
    assert "Failed to reinstall 'comfyui-foo', so its previous installation was kept: " in data['msg']
    assert data['back'] is True
    assert data['archive'] == []
    assert not [x for x in data['warned'] if 'was in the way' in x]


def test_after_a_reload_an_archived_folder_is_in_no_map_no_notice_and_not_in_the_installed_map():
    data = run('''
pack('comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
a_clone_of_a_fork_named_like_foo()
registry_api()
reload()
ok = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1')).result
archive = nodes / '.disabled/.archived'
archived = [str(x) for x in archive.glob('*/foo-fork')]
reload()
emit({'ok': ok, 'archive': str(archive), 'archived': archived, 'maps': folders_in_the_maps(), 'notice': notice(),
      'installed': list(core.get_installed_node_packs())})
''')
    assert data['ok'] is True
    assert data['archived']
    assert [x for x in data['maps'] if Path(x).is_relative_to(data['archive'])] == []
    assert data['archive'] not in data['notice']
    assert data['installed'] == ['comfyui-foo']


def test_a_reload_in_the_middle_of_a_reinstall_leaves_nothing_set_aside():
    data = run('''
import threading
pack('ComfyUI-Foo-main', 'comfyui-foo')
registry_api()
reload()
rename = os.rename

def rename_then_reload(src, dst):
    rename(src, dst)
    if '.reinstall' in pathlib.Path(dst).parts:
        os.rename = rename
        reloading = threading.Thread(target=reload)
        reloading.start()
        reloading.join()

os.rename = rename_then_reload
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
emit({'ok': result.result, 'msg': result.msg, 'left': listing()})
''')
    assert data['ok'] is True, data['msg']
    assert data['left'] == ['comfyui-foo']


def test_cm_cli_prints_no_notice():
    data = run('''
import contextlib, io
pack('ComfyUI-Foo-main', 'comfyui-foo')
set_channel_mode = cm_cli_function('set_channel_mode', {'asyncio': asyncio, 'unified_manager': manager}, 'Ctx')
out = io.StringIO()
with contextlib.redirect_stdout(out):
    set_channel_mode(SimpleNamespace(mode='cache', channel=core.DEFAULT_CHANNEL), None, 'cache')
emit({'out': out.getvalue(), 'invalid': len(manager.invalid_installations)})
''')
    assert 'invalid nodes notice' not in data['out']
    assert data['invalid'] == 1


def test_cm_cli_reinstall_keeps_the_folder_when_the_install_fails():
    data = run('''
a_users_folder('ComfyUI-Foo-main')
before = files(nodes)
registry_api(download=refused)
reload()
reinstall_node = cm_cli_reinstall_node()
reinstall_node('comfyui-foo@1.0.1')
same = before == files(nodes)
registry_api()
reinstall_node('comfyui-foo@1.0.1')
emit({'same': same, 'left': listing()})
''')
    assert data == {'same': True, 'left': ['comfyui-foo']}


@pytest.mark.parametrize('listed', [True, False], ids=['in-the-node-list', 'only-in-the-registry'])
@pytest.mark.parametrize('spec', ['comfyui-foo', 'https://github.com/example/ComfyUI-Foo'], ids=['by-id', 'by-url'])
def test_cm_cli_reinstall_by_a_registered_url_installs_what_reinstall_by_its_id_installs(spec, listed):
    data = run(f'''
import io
if not {listed!r}:
    NODE_LIST[:] = [x for x in NODE_LIST if x['reference'] != FOO_URL]
a_users_folder('ComfyUI-Foo-main')
registry_api()
clone_stand_in()
reload()
out = io.StringIO()
cm_cli_reinstall_node(out)({spec!r})
left = listing()
reload()
emit({{'out': [x.strip() for x in out.getvalue().splitlines()], 'left': left, 'installed': core.get_installed_node_packs()}})
''')
    assert f"[REINSTALLED] {'comfyui-foo':50}[1.0.1]" in data['out']
    assert data['left'] == ['comfyui-foo']
    assert data['installed'] == {'comfyui-foo': {'ver': '1.0.1', 'cnr_id': 'comfyui-foo', 'aux_id': None, 'enabled': True}}


@pytest.mark.parametrize('url', ['https://github.com/example/ComfyUI.Dot', 'https://github.com/example/ComfyUI.Dot.git'])
def test_cm_cli_reinstall_by_an_unregistered_url_replaces_the_clone_the_scan_names_by_it(url):
    data = run(f'''
pack('ComfyUI.Dot', git_url='https://github.com/example/ComfyUI.Dot')
clone_stand_in()
reload()
cm_cli_reinstall_node()({url!r})
emit({{'left': listing(), 'files': files(nodes / 'ComfyUI.Dot')}})
''')
    assert data['left'] == ['ComfyUI.Dot']
    assert list(data['files']) == ['.git/config']
    assert 'github.com/example/ComfyUI.Dot' in data['files']['.git/config']


def test_cm_cli_reinstall_by_the_url_of_a_fork_archives_the_registry_nodepack_of_its_name():
    data = run('''
import io
folder = pack('comfyui-foo', 'comfyui-foo', version='1.0.0', tracking=True)
before = files(folder)
clone_stand_in()
reload()
terminal = io.StringIO()
logging.getLogger().addHandler(logging.StreamHandler(terminal))
cm_cli_reinstall_node()('https://github.com/someone/comfyui-foo')
archived = [str(x) for x in (nodes / '.disabled/.archived').glob('*/comfyui-foo')]
emit({'folder': str(folder), 'archived': archived, 'kept': [before == files(x) for x in archived],
      'clone': files(folder), 'terminal': terminal.getvalue().splitlines()})
''')
    [archived] = data['archived']
    assert data['kept'] == [True]
    assert data['clone'] == {'.git/config': '[remote "origin"]\n\turl = https://github.com/someone/comfyui-foo\n'}
    assert moved_to_the_archive(data['folder'], archived) in data['terminal']


@pytest.mark.parametrize('spec, line', [
    ('comfyui-foo@nightly', f"[REINSTALLED] {'comfyui-foo':50}[NIGHTLY]"),
    ('ComfyUI-Bar', f"[REINSTALLED] {'ComfyUI-Bar':50}[UNKNOWN]"),
    ('comfyui-foo@1.0.1', f"[REINSTALLED] {'comfyui-foo':50}[1.0.1]"),
], ids=['nightly', 'unknown', 'registry'])
def test_cm_cli_reinstall_says_what_it_installed(spec, line):
    data = run(f'''
import io
a_users_folder('ComfyUI-Foo-main')
pack('ComfyUI-Bar')
clone_stand_in()
registry_api()
reload()
out = io.StringIO()
cm_cli_reinstall_node(out)({spec!r})
emit({{'out': [x.strip() for x in out.getvalue().splitlines()]}})
''')
    assert line in data['out']


def test_cm_cli_reinstall_says_why_it_failed_with_what_is_in_square_brackets():
    data = run('''
import io
reload()
out = io.StringIO()
cm_cli_reinstall_node(out)('Something-Else')
emit({'out': out.getvalue().splitlines()})
''')
    assert data['out'] == ["ERROR: An error occurred while reinstalling 'Something-Else'.",
                           "Node 'Something-Else@unknown' not found in [default, cache]"]


@pytest.mark.parametrize('spec', ['ComfyUI-Manager', 'all'])
def test_cm_cli_reinstall_skips_the_manager(spec):
    data = run(f'''
import io, traceback
pack('ComfyUI-Manager', git_url='https://github.com/Comfy-Org/ComfyUI-Manager')
reload()
out = io.StringIO()
reinstall_node = cm_cli_reinstall_node(out)
namespace = {{'unified_manager': manager, 'traceback': traceback, 'print': reinstall_node.__globals__['print']}}
cm_cli_function('get_all_installed_node_specs', namespace)
cm_cli_function('for_each_nodes', namespace)([{spec!r}], act=reinstall_node)
emit({{'out': out.getvalue().splitlines()}})
''')
    assert f"1/1 [   SKIP  ] {'ComfyUI-Manager':50} => Already installed" in data['out']
    assert not [x for x in data['out'] if 'ERROR' in x or 'ignored' in x]


def test_cm_cli_reinstall_of_a_url_with_a_commit_clones_into_the_folder_that_the_url_names():
    data = run('''
clone_stand_in()
reload()
cm_cli_reinstall_node()(BAR_URL + '@0123456789abcdef0123456789abcdef01234567')
emit({'left': listing(), 'files': files(nodes)})
''')
    assert data['left'] == ['ComfyUI-Bar']
    assert data['files'] == {'ComfyUI-Bar/.git/config': '[remote "origin"]\n\turl = https://github.com/example/ComfyUI-Bar\n'}


def test_cm_cli_update_all_leaves_an_invalid_installation_out():
    data = run('''
import io, threading, concurrent.futures, traceback, rich.console
pack('comfyui-foo', 'comfyui-foo', tracking=True)
pack('ComfyUI-Bar')
registry_api()
reload()
outs = []
for nodes in (['all'], ['ComfyUI-Bar']):
    out = io.StringIO()
    namespace = {'unified_manager': manager, 'threading': threading, 'concurrent': concurrent, 'traceback': traceback,
                 'print': rich.console.Console(file=out, width=1000, color_system=None).print,
                 'cmd_ctx': SimpleNamespace(no_deps=False)}
    cm_cli_function('update_node', namespace)
    cm_cli_function('update_parallel', namespace)(nodes)
    outs.append([x.strip() for x in out.getvalue().splitlines()])
emit(outs)
''')
    every, by_folder_name = data
    assert every == [f"1/1 [  SKIPPED  ]: {'comfyui-foo':50} => Up to date", '[1/1] Post update: comfyui-foo@None']
    assert by_folder_name == ["ERROR: An error occurred while updating 'ComfyUI-Bar'.", '[1/1] Post update: ComfyUI-Bar@unknown']


def test_cm_cli_uninstall_by_name_deletes_the_valid_clone_and_leaves_the_invalid_copies():
    data = run('''
import io, rich.console
pack('bar-clone', git_url=BAR_URL)
pack('ComfyUI-Bar-backup', 'ComfyUI-Bar')
pack('comfyui-bar')
reload()
out = io.StringIO()
uninstall_node = cm_cli_function('uninstall_node', {
    'unified_manager': manager, 'print': rich.console.Console(file=out, width=1000, color_system=None).print})
uninstall_node('ComfyUI-Bar')
emit({'out': [x.strip() for x in out.getvalue().splitlines()], 'left': listing()})
''')
    assert data == {'out': ['[UNINSTALLED] ComfyUI-Bar'], 'left': ['ComfyUI-Bar-backup', 'comfyui-bar']}


def test_reinstall_refused_by_the_flagged_policy_keeps_the_folder():
    data = run('''
folder = pack('ComfyUI-Foo-main', 'comfyui-foo')
registry_api(status='NodeVersionStatusFlagged')
reload()
result = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1'))
emit({'ok': result.result, 'left': left()})
''')
    assert data == {'ok': False, 'left': ['ComfyUI-Foo-main']}


def test_the_installed_route_lists_an_invalid_installation():
    data = run('''
pack('ComfyUI-Foo-main', 'comfyui-foo')
reload()
installed_list = server_function('installed_list', core=core, startup_time_installed_node_packs={},
                                 web=SimpleNamespace(json_response=lambda body, content_type: body))
emit(asyncio.run(installed_list(SimpleNamespace(query={}))))
''')
    assert data == {'ComfyUI-Foo-main': {**INVALID, 'cnr_id': 'comfyui-foo', 'enabled': True}}


def test_what_a_user_reads_does_not_name_git_or_tracking():
    data = run('''
pack('ComfyUI-Bar')
pack('ComfyUI-Foo-main', 'comfyui-foo')
registry_api(download=refused)
reload()
reason = manager.unified_update('ComfyUI-Bar', 'unknown').msg
told = notice()
failure = asyncio.run(manager.reinstall_by_id('comfyui-foo', '1.0.1')).msg
emit({'reason': reason, 'notice': told, 'failure': failure})
''')
    for text in (data['reason'], data['notice'], data['failure']):
        assert '.git' not in text and '.tracking' not in text
        assert not re.search(r'node\s+pack', text, re.IGNORECASE)
    assert 'not installed through ComfyUI-Manager' in data['reason'] and 'not installed through ComfyUI-Manager' in data['notice']
    assert "Failed to reinstall 'comfyui-foo', so its previous installation was kept: " in data['failure']


def legacy_page():
    js = JsSource(Path(__file__).resolve().parent.parent / 'js')
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
