from test_snapshot_restore_pins import run

PACKS = '''
import ast, io, traceback
from typing_extensions import Annotated, List
import typer
from rich.console import Console

def cm_cli(*names):
    found = [node for node in ast.parse(pathlib.Path('cm-cli.py').read_text(encoding='utf-8')).body if isinstance(node, ast.FunctionDef)
             and node.name in names]
    for node in found:
        node.decorator_list = []
    out = io.StringIO()
    scope = {'typer': typer, 'List': List, 'Annotated': Annotated, 'asyncio': asyncio, 'traceback': traceback,
             'print': Console(file=out, width=1000, color_system=None).print,
             'cmd_ctx': Mock(no_deps=False), 'unified_manager': manager, 'auto_save_snapshot': AsyncMock()}
    exec(compile(ast.Module(body=found, type_ignores=[]), 'cm-cli.py', 'exec'), scope)
    return scope, lambda: [' '.join(line.split()) for line in out.getvalue().splitlines() if 'pack' in line]

def command(name):
    scope, said = cm_cli(name, 'for_each_nodes', 'get_all_installed_node_specs', 'enable_node', 'disable_node')
    scope[name](['all'], None, None, None)
    return [line.split('=>')[-1].strip() for line in said()]

for name in ('enabled-pack', '.disabled/registry-pack@1_0_0', '.disabled/rc-pack@1_0_0-rc1', '.disabled/git-pack'):
    (nodes / name).mkdir(parents=True)
manager.active_nodes['enabled-pack'] = ('2.0.0', str(nodes / 'enabled-pack'))
manager.cnr_inactive_nodes['registry-pack'] = {'1.0.0': str(nodes / '.disabled/registry-pack@1_0_0')}
manager.cnr_inactive_nodes['rc-pack'] = {'1.0.0-rc1': str(nodes / '.disabled/rc-pack@1_0_0-rc1')}
manager.unknown_inactive_nodes['git-pack'] = ('https://github.com/owner/git-pack', str(nodes / '.disabled/git-pack'))
'''


def all_of(name):
    return run(PACKS + f'''
said = command({name!r})
print(json.dumps({{'said': said, 'enabled': sorted(os.listdir(nodes)), 'disabled': sorted(os.listdir(nodes / '.disabled'))}}))
''')


def test_enable_all_enables_every_disabled_nodepack():
    result = all_of('enable')

    assert result['enabled'] == ['.disabled', 'enabled-pack', 'git-pack', 'rc-pack', 'registry-pack']
    assert result['disabled'] == []
    assert result['said'][0] == 'Already enabled'


def test_disable_all_disables_every_enabled_nodepack_and_leaves_the_disabled_ones():
    result = all_of('disable')

    assert result['enabled'] == ['.disabled']
    assert result['disabled'] == ['enabled-pack@2_0_0', 'git-pack', 'rc-pack@1_0_0-rc1', 'registry-pack@1_0_0']
    assert result['said'][1:] == ['Already disabled', 'Already disabled', 'Already disabled']


def test_latest_names_the_installed_nodepack_as_a_bare_id_does():
    result = run(PACKS + '''
for name, latest in (('enabled-pack', '3.0.0'), ('registry-pack', '1.5.0')):
    manager.cnr_map[name] = {'id': name, 'latest_version': {'version': latest}}
manager.unified_update = lambda node_id, version_spec=None, **kwargs: core.ManagedResult('update').with_target('3.0.0')
manager.unified_fix = lambda node_id, version_spec, **kwargs: core.ManagedResult('fix')
scope, said = cm_cli('update_node', 'fix_node', 'disable_node', 'enable_node')
for act, name in (('update_node', 'enabled-pack'), ('fix_node', 'enabled-pack'), ('disable_node', 'enabled-pack'), ('enable_node', 'registry-pack')):
    scope[act](name + '@latest')
print(json.dumps({'said': said(), 'enabled': sorted(os.listdir(nodes)), 'disabled': sorted(os.listdir(nodes / '.disabled'))}))
''')

    assert result['said'] == ['[ UPDATED ]: enabled-pack => (2.0.0 -> 3.0.0)', '[ FIXING ]: enabled-pack [2.0.0]', '[DISABLED] enabled-pack',
                              '[ENABLED] registry-pack']
    assert result['enabled'] == ['.disabled', 'registry-pack']
    assert 'enabled-pack@2_0_0' in result['disabled']


def test_a_registry_nodepack_that_is_not_installed_is_not_called_disabled():
    result = run(PACKS + '''
manager.cnr_map['absent-pack'] = {'id': 'absent-pack', 'latest_version': {'version': '1.0.0'}}
scope, said = cm_cli('update_node', 'fix_node', 'disable_node', 'enable_node')
for name in ('absent-pack', 'absent-pack@latest'):
    for act in ('update_node', 'fix_node', 'disable_node', 'enable_node'):
        scope[act](name)
print(json.dumps({'said': [line.split('=>')[-1].strip() for line in said()]}))
''')

    assert result['said'] == ['Not installed', 'Not installed', 'Not found', 'Not found'] * 2
