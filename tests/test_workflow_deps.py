import pytest

from test_invalid_installation import run

CM_CLI = '''
import io, typer, rich.console
from typing_extensions import Annotated

async def get_data_by_mode(mode, filename, channel_url=None):
    if filename == 'extension-node-map.json':
        return {FOO_URL: [['FooNode'], {}], BAR_URL: [['BarNode'], {}]}
    return {'custom_nodes': [dict(item) for item in NODE_LIST]}

async def auto_save_snapshot():
    pass

core.get_data_by_mode = get_data_by_mode
out = io.StringIO()
cm_cli = {'asyncio': asyncio, 'os': os, 'json': json, 'core': core, 'unified_manager': manager, 'typer': typer,
          'Annotated': Annotated, 'app': SimpleNamespace(command=lambda *args, **kwargs: lambda f: f),
          'print': rich.console.Console(file=out, width=1000, color_system=None).print,
          'auto_save_snapshot': auto_save_snapshot, 'comfy_path': tmp,
          'manager_util': SimpleNamespace(get_installed_packages=dict,
                                          PIPFixer=lambda *args: SimpleNamespace(fix_broken=lambda: None)),
          'cmd_ctx': SimpleNamespace(set_user_directory=lambda path: None, set_channel_mode=lambda channel, mode: reload(),
                                     mode='cache', channel='default')}
for name in ('enable_node', 'deps_in_workflow', 'install_deps'):
    cm_cli_function(name, cm_cli)
workflow = pathlib.Path(tmp) / 'workflow.json'
workflow.write_text(json.dumps({'nodes': [{'id': 1, 'type': 'FooNode'}, {'id': 2, 'type': 'BarNode'}]}))
deps = pathlib.Path(tmp) / 'deps.json'
'''

FOO_URL = 'https://github.com/example/ComfyUI-Foo'
BAR_URL = 'https://github.com/example/ComfyUI-Bar'


@pytest.mark.parametrize('folder, kwargs, foo, bar', [
    ('comfyui-foo', "'comfyui-foo', tracking=True", 'installed', 'not-installed'),
    ('.disabled/comfyui-foo@1_0_1', "'comfyui-foo', tracking=True", 'disabled', 'not-installed'),
    ('.disabled/comfyui-foo@nightly', 'git_url=FOO_URL', 'disabled', 'not-installed'),
    ('ComfyUI-Bar', 'git_url=BAR_URL', 'not-installed', 'installed'),
    ('.disabled/ComfyUI-Bar', 'git_url=BAR_URL', 'not-installed', 'disabled'),
    ('ComfyUI-Bar.disabled', 'git_url=BAR_URL', 'not-installed', 'disabled'),
], ids=['registry', 'registry-disabled', 'nightly-disabled', 'git', 'git-disabled', 'git-disabled-old-style'])
def test_deps_in_workflow_writes_the_state_of_each_nodepack(folder, kwargs, foo, bar):
    data = run(CM_CLI + f'''
pack({folder!r}, {kwargs})
cm_cli['deps_in_workflow'](workflow=str(workflow), output=str(deps), channel=None, mode=None, user_directory=None)
emit(json.loads(deps.read_text()))
''')

    assert data == {'custom_nodes': {FOO_URL: {'state': foo, 'hash': '-'}, BAR_URL: {'state': bar, 'hash': '-'}},
                    'unknown_nodes': []}


@pytest.mark.parametrize('folder, kwargs, enabled', [
    ('.disabled/comfyui-foo@1_0_1', "'comfyui-foo', tracking=True", 'comfyui-foo'),
    ('.disabled/ComfyUI-Bar', 'git_url=BAR_URL', 'ComfyUI-Bar'),
    ('ComfyUI-Bar.disabled', 'git_url=BAR_URL', 'ComfyUI-Bar'),
], ids=['registry', 'git', 'git-old-style'])
def test_install_deps_enables_a_disabled_nodepack(folder, kwargs, enabled):
    data = run(CM_CLI + f'''
pack({folder!r}, {kwargs})
url = FOO_URL if {enabled!r} == 'comfyui-foo' else BAR_URL
deps.write_text(json.dumps({{'custom_nodes': {{url: {{'state': 'disabled', 'hash': '-'}}}}, 'unknown_nodes': []}}))
cm_cli['install_deps'](deps=str(deps), channel=None, mode=None, user_directory=None)
emit({{'left': listing(), 'out': out.getvalue().splitlines()}})
''')

    assert data['left'] == [enabled]
    assert data['out'][-1] == 'Dependency installation and activation complete.'
