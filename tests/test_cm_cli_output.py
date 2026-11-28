import os

import pytest

from test_snapshot_restore_pins import run

CLI = '''
import ast, inspect, io, sys, threading, concurrent.futures, traceback
from typing import Optional
from typing_extensions import Annotated, List
import rich, typer, typer.testing

def binds_print(node):
    if isinstance(node, ast.Assign):
        return any(isinstance(target, ast.Name) and target.id == 'print' for target in node.targets)
    return isinstance(node, ast.ImportFrom) and any((name.asname or name.name) == 'print' for name in node.names)

def cm_cli(*names, width=1000, color_system=None, **more):
    found = [node for node in ast.parse(pathlib.Path('cm-cli.py').read_text(encoding='utf-8')).body
             if isinstance(node, ast.FunctionDef) and node.name in names or binds_print(node)]
    if 'app' not in more:
        for node in found:
            node.decorator_list = []
    out = io.StringIO()
    rich.reconfigure(file=out, width=width, color_system=color_system, no_color=False)
    scope = {'typer': typer, 'List': List, 'Annotated': Annotated, 'Optional': Optional, 'asyncio': asyncio, 'traceback': traceback,
             'os': os, 'sys': sys, 'json': json, 'threading': threading, 'concurrent': concurrent,
             'core': core, 'cnr_utils': cnr_utils,
             'cmd_ctx': Mock(no_deps=False, channel='default', mode='cache'), 'unified_manager': manager,
             'auto_save_snapshot': AsyncMock(), 'manager_util': Mock(), 'comfy_path': tmp, **more}
    exec(compile(ast.Module(body=found, type_ignores=[]), 'cm-cli.py', 'exec'), scope)
    return scope, lambda: [' '.join(line.split()) for line in out.getvalue().splitlines() if line.strip()]

def command(scope, name, **given):
    try:
        scope[name](**{**dict.fromkeys(inspect.signature(scope[name]).parameters), **given})
    except (SystemExit, typer.Exit):
        pass

GIT_PACK = ('https://example.invalid/git-pack', str(nodes / 'git-pack'))
folder = os.path.join(tmp, '[my] files')
os.mkdir(folder)
'''


def said(body):
    return run(CLI + body + '\nprint(json.dumps(lines()))\n')


@pytest.mark.parametrize('installed, name, label', [
    ("manager.unknown_active_nodes['git-pack'] = GIT_PACK", 'git-pack', '[unknown]'),
    ("manager.active_nodes['git-pack'] = ('nightly', GIT_PACK[1])", 'git-pack@nightly', '[nightly]'),
], ids=['unknown', 'nightly'])
def test_fix_names_the_version_of_a_git_nodepack(installed, name, label):
    assert said(f'''
{installed}
manager.unified_fix = lambda node_id, version_spec, **kwargs: core.ManagedResult('fix')
scope, lines = cm_cli('fix_node')
scope['fix_node']({name!r}, cnt_msg='1/1')
''') == [f'1/1 [ FIXING ]: git-pack {label}']


def test_fix_that_fails_says_why():
    assert said('''
manager.unknown_active_nodes['git-pack'] = GIT_PACK
manager.unified_fix = lambda node_id, version_spec, **kwargs: core.ManagedResult('fix').fail('cannot fix [the reason]')
scope, lines = cm_cli('fix_node')
scope['fix_node']('git-pack', cnt_msg='1/1')
''')[1:] == ['ERROR: cannot fix [the reason]']


def test_fix_all_has_a_line_for_each_nodepack_it_counts():
    assert said('''
manager.unknown_active_nodes['git-pack'] = GIT_PACK
manager.unknown_inactive_nodes['old-pack'] = ('https://example.invalid/old-pack', str(nodes / '.disabled/old-pack'))
manager.unified_fix = lambda node_id, version_spec, **kwargs: core.ManagedResult('fix')
scope, lines = cm_cli('fix', 'for_each_nodes', 'get_all_installed_node_specs', 'fix_node')
command(scope, 'fix', nodes=['all'])
''') == ['1/2 [ FIXING ]: git-pack [unknown]', '2/2 [ SKIPPED ]: old-pack@unknown => Disabled']


def test_url_that_is_not_installed_says_why():
    assert said('''
core.gitclone_install = AsyncMock(return_value=core.ManagedResult('install-git').fail('cannot clone [the reason]'))
scope, lines = cm_cli('install_node')
scope['install_node'](GIT_PACK[0], cnt_msg='1/1')
''') == ['cannot clone [the reason]', "ERROR: An error occurred while installing 'https://example.invalid/git-pack'."]


def test_install_of_an_id_that_no_list_has_says_where_it_was_looked_for():
    assert said('''
scope, lines = cm_cli('install_node')
scope['install_node']('no-such-pack', cnt_msg='1/1')
''') == ["ERROR: An error occurred while installing 'no-such-pack'.", "Node 'no-such-pack@unknown' not found in [default, cache]"]


@pytest.mark.parametrize('installed, act, line', [
    ("manager.unknown_inactive_nodes['git-pack'] = GIT_PACK; manager.unified_enable = lambda *args: core.ManagedResult('enable').fail(REASON)",
     'enable_node', '1/1 [ FAIL ] git-pack => cannot move [the folder]'),
    ("manager.unknown_inactive_nodes['git-pack'] = GIT_PACK; manager.unified_enable = lambda *args: core.ManagedResult('skip').with_msg(REASON)",
     'enable_node', '1/1 [ SKIP ] git-pack => cannot move [the folder]'),
    ("manager.unknown_active_nodes['git-pack'] = GIT_PACK; manager.unified_disable = lambda *args: core.ManagedResult('disable').fail(REASON)",
     'disable_node', '1/1 [ FAIL ] git-pack => cannot move [the folder]'),
    ("manager.unknown_active_nodes['git-pack'] = GIT_PACK; manager.unified_disable = lambda *args: core.ManagedResult('skip').with_msg(REASON)",
     'disable_node', '1/1 [ SKIP ] git-pack => cannot move [the folder]'),
    ("manager.unknown_active_nodes['git-pack'] = GIT_PACK; manager.unified_update = lambda *args, **kwargs: core.ManagedResult('skip').with_msg(REASON)",
     'update_node', '1/1 [ SKIPPED ]: git-pack => cannot move [the folder]'),
], ids=['enable_fails', 'enable_is_skipped', 'disable_fails', 'disable_is_skipped', 'update_is_skipped'])
def test_reason_in_square_brackets_is_printed_whole(installed, act, line):
    assert said(f'''
REASON = 'cannot move [the folder]'
{installed}
scope, lines = cm_cli({act!r})
scope[{act!r}]('git-pack', cnt_msg='1/1')
''') == [line]


@pytest.mark.parametrize('name, installed, act, line', [
    ('git-pack[old]', "manager.unknown_inactive_nodes[NAME] = PACK; manager.unified_enable = lambda *args: core.ManagedResult('enable')",
     'enable_node', '1/1 [ENABLED] git-pack[old]'),
    ('git-pack[old]', "manager.unknown_active_nodes[NAME] = PACK; manager.unified_disable = lambda *args: core.ManagedResult('disable')",
     'disable_node', '1/1 [DISABLED] git-pack[old]'),
    ('comfyui-manager[old]', "manager.unknown_active_nodes[NAME] = PACK",
     'disable_node', "1/1 [ SKIP ] comfyui-manager[old] => Not disabled: its name has 'comfyui-manager'"),
    ('git-pack[old]', "manager.unknown_inactive_nodes[NAME] = PACK", 'fix_node', '1/1 [ SKIPPED ]: git-pack[old] => Disabled'),
    ('git-pack[old]', "", 'fix_node', '1/1 [ SKIPPED ]: git-pack[old] => Not installed'),
    ('git-pack[old]', "", 'update_node', '1/1 [ SKIPPED ]: git-pack[old] => Not installed'),
], ids=['enable', 'disable', 'disable_of_the_manager', 'fix_of_a_disabled_one', 'fix_of_one_that_is_not_installed',
        'update_of_one_that_is_not_installed'])
def test_name_in_square_brackets_is_printed_whole(name, installed, act, line):
    assert said(f'''
NAME = {name!r}
PACK = ('https://example.invalid/git-pack', str(nodes / NAME))
{installed}
scope, lines = cm_cli({act!r})
scope[{act!r}](NAME, cnt_msg='1/1')
''') == [line]


def test_line_longer_than_the_console_is_wide_is_written_as_one_line():
    assert said('''
manager.unknown_active_nodes['git-pack'] = GIT_PACK
scope, lines = cm_cli('enable_node', width=80)
scope['enable_node']('git-pack', cnt_msg='1/1')
''') == ['1/1 [ SKIP ] git-pack => Already enabled']


def test_error_of_a_nodepack_in_a_run_over_several_is_printed_whole():
    assert said('''
def act(name, **kwargs):
    raise RuntimeError('no such [thing] for ' + name)

scope, lines = cm_cli('for_each_nodes', traceback=Mock())
scope['for_each_nodes'](['git-pack'], act)
''') == ['ERROR: no such [thing] for git-pack']


def test_error_of_an_update_in_a_run_over_several_is_printed_whole():
    assert said('''
scope, lines = cm_cli('update_parallel', update_node=Mock(side_effect=RuntimeError('no such [thing]')), traceback=Mock())
scope['update_parallel'](['git-pack'])
''') == ['ERROR: no such [thing]']


def test_show_versions_prints_a_changelog_with_square_brackets():
    assert said('''
cnr_utils.all_versions_of_node = lambda name: [{'createdAt': '2026-01-02T03:04:05', 'version': '1.0.1', 'changelog': '[fix] a crash'}]
scope, lines = cm_cli('show_versions')
scope['show_versions']('git-pack')
''') == ['[2026-01-02] 1.0.1 -- [fix] a crash']


def test_show_prints_a_title_and_an_author_with_square_brackets():
    assert said('''
manager.get_custom_nodes = AsyncMock(return_value={
    'listed-pack': {'title': 'Listed [gist-wrapper] Pack', 'author': 'some[one]', 'files': ['https://github.com/someone/listed-pack']},
})
manager.cnr_map['registry-pack'] = {'id': 'registry-pack', 'name': 'Registry[official] Pack', 'publisher': {'name': 'someone'},
                                    'latest_version': {'version': '1.0.0'}}
manager.active_nodes['registry-pack'] = ('1.0.0', str(nodes / 'registry-pack'))
manager.unknown_active_nodes['listed-pack'] = ('https://github.com/someone/listed-pack', str(nodes / 'listed-pack'))
scope, lines = cm_cli('show', 'simple_show', 'show_list')
scope['show']('installed', None, None, None)
scope['simple_show']('installed', None, None, None)
''') == ['[ ENABLED ] Registry[official] Pack registry-pack (author: someone ) [1.0.0]',
         '[ ENABLED ] Listed [gist-wrapper] Pack listed-pack (author: some[one] ) [UNKNOWN]',
         'Registry[official] Pack@1.0.0', 'Listed [gist-wrapper] Pack@unknown']


def test_show_of_a_word_that_is_no_list_is_refused_in_plain_words():
    assert said('''
sys.stderr = refusal = io.StringIO()
scope, lines = cm_cli('simple_show')
command(scope, 'simple_show', arg='[nodes]')
lines = lambda: refusal.getvalue().split()
''') == ['Invalid', 'command:', '`show', '[nodes]`']


def test_names_of_snapshots_are_listed_whole():
    assert said('''
open(os.path.join(folder, 'before [the update].json'), 'w').close()
scope, lines = cm_cli('show_snapshot_list')
scope['cmd_ctx'].get_snapshot_path.return_value = folder
scope['show_snapshot_list']()
''') == ['before [the update].json']


PATHS = {
    'restore-snapshot of a file that is not there': (
        "scope['cmd_ctx'].get_snapshot_path.return_value = folder; command(scope, 'restore_snapshot', snapshot_name='gone.json')",
        f'ERROR: `{{folder}}{os.sep}gone.json` is not exists.'),
    'save-snapshot into a folder that is not there': (
        "command(scope, 'save_snapshot', output=folder + '/gone/snapshot.json')", 'ERROR: {folder}/gone/snapshot.json path not exists.'),
    'save-snapshot': (
        "core.save_snapshot_with_postfix = AsyncMock(return_value=folder + '/snapshot.json'); command(scope, 'save_snapshot', output=folder + '/snapshot.json')",
        'Current snapshot is saved as `{folder}/snapshot.json`'),
    'deps-in-workflow of a file that is not there': (
        "command(scope, 'deps_in_workflow', workflow=folder + '/gone.json', output='deps.json')", 'File not found: {folder}/gone.json'),
    'deps-in-workflow': (
        "open(folder + '/workflow.json', 'w').close(); core.extract_nodes_from_workflow = AsyncMock(return_value=({}, []));"
        " command(scope, 'deps_in_workflow', workflow=folder + '/workflow.json', output=folder + '/deps.json')",
        'Workflow dependencies are being saved into {folder}/deps.json.'),
    'install-deps of a file that is not there': ("command(scope, 'install_deps', deps=folder + '/gone.json')", 'File not found: {folder}/gone.json'),
    'install-deps of a file that is not JSON': (
        "open(folder + '/deps.json', 'w').close(); command(scope, 'install_deps', deps=folder + '/deps.json')", 'Invalid json file: {folder}/deps.json'),
}


@pytest.mark.parametrize('case', PATHS)
def test_path_with_square_brackets_is_printed_whole(case):
    call, line = PATHS[case]

    assert said(f'''
scope, said = cm_cli('restore_snapshot', 'save_snapshot', 'deps_in_workflow', 'install_deps')
{call}
lines = lambda: [line.replace(folder, '{{folder}}') for line in said()][-1:]
''') == [line]


@pytest.mark.parametrize('path', [r'C:\ComfyUI\[My] files\deps.json', '/nodes/' + 'long-folder-name/' * 5 + 'deps.json', '/nodes/x:100:y/deps.json'],
                         ids=['a backslash before a bracket', 'longer than the console is wide', 'the code of an emoji'])
@pytest.mark.parametrize('call, line', [
    ("command(scope, 'install_deps', deps=path)", 'File not found: {}'),
    ("core.save_snapshot_with_postfix = AsyncMock(return_value=path); command(scope, 'save_snapshot')", 'Current snapshot is saved as `{}`'),
], ids=['a coloured line', 'a line without a colour'])
def test_line_is_written_as_it_is(call, line, path):
    assert said(f'''
path = {path!r}
scope, lines = cm_cli('install_deps', 'save_snapshot', width=80)
{call}
''') == [line.format(path)]


@pytest.mark.parametrize('call, line', [
    ("command(scope, 'install_deps', deps='deps.json')", '\x1b[1;31mFile not found: deps.json\x1b[0m'),
    ("open(os.path.join(folder, \"the 'old' one.json\"), 'w').close(); scope['cmd_ctx'].get_snapshot_path.return_value = folder;"
     " scope['show_snapshot_list']()", "the \x1b[32m'old'\x1b[0m one.json"),
], ids=['a line that cm-cli colours', 'a quoted text in another line'])
def test_line_keeps_its_colour(call, line):
    assert said(f'''
scope, lines = cm_cli('install_deps', 'show_snapshot_list', color_system='standard')
{call}
''') == [line]


@pytest.mark.parametrize('app', ['typer.Typer()', 'typer.Typer(rich_markup_mode=None)'], ids=['with rich markup', 'without'])
def test_help_names_the_values_that_an_argument_and_an_option_take(app):
    assert said(f'''
scope, said = cm_cli('show', 'update', app={app})
help = lambda name: ' '.join(typer.testing.CliRunner().invoke(scope['app'], [name, '--help'], env={{'COLUMNS': '200'}}).output.split())
lines = lambda: [text in help(name) and chr(92) not in help(name) for name, text in (
    ('show', 'installed|enabled|not-installed'), ('show', 'remote|local|cache'),
    ('update', 'all|List of custom nodes to update'), ('update', 'remote|local|cache'))]
''') == [True, True, True, True]


def test_disable_says_why_the_manager_is_not_disabled():
    assert said('''
scope, lines = cm_cli('disable_node')
scope['disable_node']('comfyui-manager', cnt_msg='1/1')
''') == ["1/1 [ SKIP ] comfyui-manager => Not disabled: its name has 'comfyui-manager'"]


def test_disable_all_has_a_line_for_each_nodepack_it_counts():
    assert [line.split()[0] for line in said('''
for name in ('comfyui-manager', 'git-pack'):
    (nodes / name).mkdir()
    manager.unknown_active_nodes[name] = ('https://example.invalid/' + name, str(nodes / name))
scope, lines = cm_cli('disable', 'for_each_nodes', 'get_all_installed_node_specs', 'disable_node')
scope['disable'](['all'], None, None, None)
''')] == ['1/2', '2/2']


def test_restore_dependencies_runs_for_the_nodepacks_only():
    assert said('''
for name in ('a-pack', '__pycache__', 'b-pack.disabled', '.disabled'):
    os.mkdir(os.path.join(folder, name))
manager.execute_install_script = Mock()
scope, said = cm_cli('restore_dependencies')
scope['cmd_ctx'].get_custom_nodes_paths.return_value = [folder]
command(scope, 'restore_dependencies')
lines = lambda: ([line.replace(folder, '{folder}') for line in said() if line.startswith('Restoring')]
                 + [os.path.basename(call.args[1]) for call in manager.execute_install_script.call_args_list])
''') == ['Restoring [1/1]: {folder}' + os.sep + 'a-pack', 'a-pack']
