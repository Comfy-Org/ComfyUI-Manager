import pytest

from test_install_flags_config import _run_child
from test_invalid_installation import PRELUDE

TAKEN = PRELUDE + '''
import io, shutil, traceback, zipfile

def folders():
    return sorted(path.relative_to(nodes).as_posix() for path in nodes.rglob('*')
                  if (path.is_dir() or path.is_symlink()) and path.name != '.git')

def broken_link(folder):
    (nodes / '.disabled').mkdir(exist_ok=True)
    os.symlink(nodes / 'gone', nodes / folder)

def download(url, directory, name):
    with zipfile.ZipFile(pathlib.Path(directory) / name, 'w') as archive:
        archive.writestr('__init__.py', '')
        archive.writestr('pyproject.toml', '[project]\\nname = "comfyui-foo"\\nversion = "1.0.1"\\n')

cnr_utils.install_node = lambda name, version: SimpleNamespace(version=version, download_url='https://registry.invalid/' + name,
                                                               status='NodeVersionStatusActive')
core.manager_downloader.download_url = core.manager_downloader.basic_download_url = Mock(side_effect=download)

def clone(url, path, **options):
    pathlib.Path(path).mkdir()
    return core.ManagedResult('install-git')

manager.repo_install = Mock(side_effect=clone)

def install(version):
    installed = asyncio.run(manager.install_by_id('comfyui-foo', version, core.DEFAULT_CHANNEL, 'cache', instant_execution=True))
    return [installed.result, core.manager_downloader.download_url.call_count + manager.repo_install.call_count, folders()]
'''

UNKNOWN, VERSION, NIGHTLY = 'git_url=BAR_URL', "'comfyui-foo', tracking=True", "'comfyui-foo', git_url=FOO_URL"
KINDS = pytest.mark.parametrize('name, made_with, disabled, version', [
    ('ComfyUI-Bar', UNKNOWN, '.disabled/ComfyUI-Bar', 'unknown'),
    ('comfyui-foo', VERSION, '.disabled/comfyui-foo@1_0_1', '1.0.1'),
    ('comfyui-foo', NIGHTLY, '.disabled/comfyui-foo@nightly', 'nightly'),
], ids=['git_clone_that_no_list_knows', 'registry_version', 'nightly_clone'])


def run(body):
    return _run_child(TAKEN + body + '\nprint(json.dumps(result))\n')


@KINDS
@pytest.mark.parametrize('taken_by', ['pack({disabled!r}, {made_with})', 'broken_link({disabled!r})'], ids=['a_disabled_copy', 'a_broken_link'])
def test_disable_fails_when_its_destination_is_taken(taken_by, name, made_with, disabled, version):
    assert run(f'''
pack({name!r}, {made_with})
{taken_by.format(disabled=disabled, made_with=made_with)}
reload()
result = [manager.unified_disable({name!r}, {version == 'unknown'}).result, folders()]
''') == [False, ['.disabled', disabled, name]]


@KINDS
@pytest.mark.parametrize('taken_by', ['(nodes / {name!r}).mkdir()', 'broken_link({name!r})'],
                         ids=['a_folder_made_since_the_last_scan', 'a_broken_link'])
def test_enable_fails_when_its_destination_is_taken(taken_by, name, made_with, disabled, version):
    assert run(f'''
pack({disabled!r}, {made_with})
reload()
{taken_by.format(name=name)}
result = [manager.unified_enable({name!r}, {version!r}).result, folders()]
''') == [False, ['.disabled', disabled, name]]


def test_git_clone_that_no_list_knows_is_not_enabled_over_the_enabled_version_of_its_name():
    assert run(f'''
pack('comfyui-foo', {VERSION})
pack('.disabled/comfyui-foo', git_url='https://github.com/someone/comfyui-foo')
reload()
result = [manager.unified_enable('comfyui-foo', 'unknown').result, folders()]
''') == [False, ['.disabled', '.disabled/comfyui-foo', 'comfyui-foo']]


@pytest.mark.parametrize('enabled, taken', [
    (f"pack('foo', {NIGHTLY})", "(nodes / 'comfyui-foo').mkdir()"),
    (f"pack('foo', {NIGHTLY})", "os.symlink(nodes / 'foo', nodes / 'comfyui-foo')"),
    (f"pack('../checkout', {NIGHTLY}); os.symlink(nodes.parent / 'checkout', nodes / 'foo')",
     "os.symlink(nodes.parent / 'checkout', nodes / 'comfyui-foo')"),
], ids=['by_another_folder', 'by_a_link_to_the_enabled_folder', 'by_a_second_link_to_the_folder_of_the_enabled_link'])
def test_enable_whose_folder_is_taken_leaves_the_enabled_version_enabled(enabled, taken):
    assert run(f'''
{enabled}
pack('.disabled/comfyui-foo@1_0_1', {VERSION})
reload()
{taken}
result = [manager.unified_enable('comfyui-foo', '1.0.1').result, folders()]
''') == [False, ['.disabled', '.disabled/comfyui-foo@1_0_1', 'comfyui-foo', 'foo']]


def test_enable_whose_folder_is_taken_fails_when_the_folder_of_the_enabled_version_is_gone():
    assert run(f'''
pack('foo', {NIGHTLY})
pack('.disabled/comfyui-foo@1_0_1', {VERSION})
reload()
shutil.rmtree(nodes / 'foo')
(nodes / 'comfyui-foo').mkdir()
result = [manager.unified_enable('comfyui-foo', '1.0.1').result, folders()]
''') == [False, ['.disabled', '.disabled/comfyui-foo@1_0_1', 'comfyui-foo']]


@pytest.mark.parametrize('folder', ['comfyui-foo', 'ComfyUI-Foo'], ids=['in_the_folder_of_its_id', 'in_a_folder_of_another_spelling'])
def test_version_takes_the_folder_of_the_enabled_nightly_clone(folder):
    assert run(f'''
pack({folder!r}, {NIGHTLY})
pack('.disabled/comfyui-foo@1_0_1', {VERSION})
reload()
result = [manager.unified_enable('comfyui-foo', '1.0.1').result, folders()]
''') == [True, ['.disabled', '.disabled/comfyui-foo@nightly', 'comfyui-foo']]


@pytest.mark.parametrize('enabled, taken, disabled, act, refused', [
    (NIGHTLY, '.disabled/comfyui-foo@nightly', f"'.disabled/comfyui-foo@1_0_1', {VERSION}", "manager.unified_enable('comfyui-foo', '1.0.1').result", False),
    (VERSION, '.disabled/comfyui-foo@1_0_1', f"'.disabled/comfyui-foo@nightly', {NIGHTLY}", "manager.unified_enable('comfyui-foo', 'nightly').result", False),
    (NIGHTLY, '.disabled/comfyui-foo@nightly', None, "install('1.0.1')[:2]", [False, 0]),
    (VERSION, '.disabled/comfyui-foo@1_0_1', None, "install('nightly')[:2]", [False, 0]),
], ids=['enable_of_a_version', 'enable_of_the_nightly_clone', 'install_of_a_version', 'install_of_the_nightly_clone'])
def test_nodepack_does_not_take_the_place_of_an_enabled_one_that_cannot_be_disabled(enabled, taken, disabled, act, refused):
    done, before, after = run(f'''
for folder in ('ComfyUI-Foo', {taken!r}):
    pack(folder, {enabled})
if {disabled is not None}:
    pack({disabled})
reload()
before = folders()
result = [{act}, before, folders()]
''')
    assert [done, after] == [refused, before]


@pytest.mark.parametrize('enabled, disabled, act, done', [
    (NIGHTLY, f"'.disabled/comfyui-foo@1_0_1', {VERSION}", "manager.unified_enable('comfyui-foo', '1.0.1').result", [True, ['.disabled', 'comfyui-foo']]),
    (VERSION, f"'.disabled/comfyui-foo@nightly', {NIGHTLY}", "manager.unified_enable('comfyui-foo', 'nightly').result", [True, ['.disabled', 'comfyui-foo']]),
    (NIGHTLY, None, "install('1.0.1')[:2]", [[True, 1], ['comfyui-foo']]),
    (VERSION, None, "install('nightly')[:2]", [[True, 1], ['comfyui-foo']]),
], ids=['enable_of_a_version', 'enable_of_the_nightly_clone', 'install_of_a_version', 'install_of_the_nightly_clone'])
def test_nodepack_takes_the_place_of_an_enabled_one_whose_folder_is_gone(enabled, disabled, act, done):
    assert run(f'''
pack('ComfyUI-Foo', {enabled})
if {disabled is not None}:
    pack({disabled})
reload()
shutil.rmtree(nodes / 'ComfyUI-Foo')
result = [{act}, folders()]
''') == done


@pytest.mark.parametrize('enabled, disabled, version', [
    (NIGHTLY, "pack('.disabled/comfyui-foo@1_0_0', 'comfyui-foo', version='1.0.0', tracking=True)", '1.0.1'),
    (NIGHTLY, '', '1.0.1'),
    (VERSION, '', 'nightly'),
], ids=['of_a_version_that_enables_a_disabled_one', 'of_a_version_that_is_downloaded', 'of_the_nightly_clone'])
def test_install_whose_folder_is_taken_leaves_the_enabled_one_enabled(enabled, disabled, version):
    done, before = run(f'''
pack('foo', {enabled})
{disabled}
reload()
(nodes / 'comfyui-foo').mkdir()
before = folders()
result = [install({version!r}), before]
''')
    assert done == [False, 0, before]


def test_version_is_not_switched_when_the_disabled_one_cannot_be_enabled():
    assert run('''
pack('comfyui-foo', git_url='https://github.com/someone/comfyui-foo')
pack('.disabled/comfyui-foo@1_0_0', 'comfyui-foo', version='1.0.0', tracking=True)
reload()
result = install('1.0.1')
''') == [False, 0, ['.disabled', '.disabled/comfyui-foo@1_0_0', 'comfyui-foo']]


def test_page_is_told_that_a_disable_failed_and_the_terminal_why():
    assert run(f'''
for folder in ('ComfyUI-Bar', '.disabled/ComfyUI-Bar'):
    pack(folder, {UNKNOWN})
reload()
logged = []
handler = logging.Handler()
handler.emit = lambda record: logged.append(record.getMessage())
logging.getLogger().addHandler(handler)
disable = server_function('do_disable', core=core, logging=logging, traceback=traceback)
result = [asyncio.run(disable(('the row', 'ComfyUI-Bar', True))), any(str(nodes / '.disabled' / 'ComfyUI-Bar') in line for line in logged), folders()]
''') == ["Failed to disable: 'ComfyUI-Bar'", True, ['.disabled', '.disabled/ComfyUI-Bar', 'ComfyUI-Bar']]


def test_page_is_told_why_an_enable_failed_and_the_terminal_too():
    assert run(f'''
pack('.disabled/comfyui-foo@1_0_1', {VERSION})
reload()
(nodes / 'comfyui-foo').mkdir()
sent, logged = [], []
handler = logging.Handler()
handler.emit = lambda record: logged.append(record.getMessage())
logging.getLogger().addHandler(handler)
enable = server_function(
    '_queue_node_install', core=core, logging=logging, _reject_non_json_content_type=lambda request: None,
    is_allowed_security_level=lambda level: True, web=SimpleNamespace(Response=lambda status=200, text=None: [status, text]),
    PromptServer=SimpleNamespace(instance=SimpleNamespace(send_sync=lambda name, data: sent.append(data.get('nodepack_result')))))

async def row():
    return {{'id': 'comfyui-foo', 'version': '1.0.1', 'selected_version': '1.0.1', 'skip_post_install': True, 'ui_id': 'the row'}}

reason = 'Destination already exists: ' + str(nodes / 'comfyui-foo')
result = [asyncio.run(enable(SimpleNamespace(json=row), 'install')) == [400, reason], any(reason in line for line in logged), sent, folders()]
''') == [True, True, [], ['.disabled', '.disabled/comfyui-foo@1_0_1', 'comfyui-foo']]


def test_cm_cli_install_reports_an_enable_that_failed():
    assert run(f'''
pack('.disabled/ComfyUI-Bar', {UNKNOWN})
reload()
(nodes / 'ComfyUI-Bar').mkdir()
out = io.StringIO()
install_node = cm_cli_function('install_node', {{
    'asyncio': asyncio, 'sys': sys, 'core': core, 'unified_manager': manager, 'print': lambda *objects, **kwargs: print(*objects, file=out),
    'cmd_ctx': SimpleNamespace(channel=core.DEFAULT_CHANNEL, mode='cache', no_deps=False)}})
try:
    ended = install_node('ComfyUI-Bar@unknown', cnt_msg='1/1', exit_on_fail=True)
except SystemExit as exit:
    ended = exit.code
result = [ended, '[ ENABLED ]' in out.getvalue(), folders()]
''') == [1, False, ['.disabled', '.disabled/ComfyUI-Bar', 'ComfyUI-Bar']]
