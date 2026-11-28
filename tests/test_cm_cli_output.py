import ast
import asyncio
import concurrent.futures
import inspect
import io
import json
import os
import sys
import threading
import traceback
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, Mock

import pytest
import rich
import typer
import typer.testing
from rich.console import Console
from typing_extensions import Annotated, List

from legacy_html_testutil import ROOT, load_functions
from test_snapshot_restore_pins import core, manager  # noqa: F401

REASON = 'cannot move [the folder]'


def binds_print(node):
    if isinstance(node, ast.Assign):
        return any(isinstance(target, ast.Name) and target.id == 'print' for target in node.targets)
    return isinstance(node, ast.ImportFrom) and any((name.asname or name.name) == 'print' for name in node.names)


@pytest.fixture
def cm_cli(manager, core, monkeypatch):  # noqa: F811
    out = io.StringIO()
    path = ROOT / 'cm_cli/__main__.py'
    its_print = [node for node in ast.parse(path.read_text(encoding='utf-8')).body if binds_print(node)]

    def cm_cli(*names, width=1000, color_system=None, **more):
        console = Console(file=out, width=width, color_system=color_system, no_color=False)
        monkeypatch.setattr(rich, 'get_console', lambda: console)
        scope = {
            'app': SimpleNamespace(command=lambda *args, **kwargs: lambda function: function),
            'typer': typer, 'Annotated': Annotated, 'List': List, 'Optional': Optional, 'asyncio': asyncio, 'os': os, 'sys': sys,
            'json': json, 'threading': threading, 'concurrent': concurrent,
            'traceback': traceback, 'core': core,
            'NodeInstallError': type('NodeInstallError', (Exception,), {}),
            'cmd_ctx': Mock(no_deps=False, channel='default', mode='cache'), 'unified_manager': manager, 'auto_save_snapshot': AsyncMock(),
            'manager_util': Mock(), 'context': Mock(), 'comfy_path': '', '_finalize_resolve': Mock(), **more,
        }
        exec(compile(ast.Module(its_print, []), str(path), 'exec'), scope)
        return load_functions(path, set(names), scope)

    cm_cli.said = lambda: [' '.join(line.split()) for line in out.getvalue().splitlines() if line.strip()]
    return cm_cli


def command(scope, name, **given):
    try:
        scope[name](**{**dict.fromkeys(inspect.signature(scope[name]).parameters), **given})
    except (SystemExit, typer.Exit):
        pass


@pytest.fixture
def folder(tmp_path):
    (tmp_path / '[my] files').mkdir()
    return str(tmp_path / '[my] files')


@pytest.fixture
def git_pack(tmp_path):
    return 'https://example.invalid/git-pack', str(tmp_path / 'git-pack')


@pytest.mark.parametrize('name, label', [('git-pack', '[unknown]'), ('git-pack@nightly', '[nightly]')], ids=['unknown', 'nightly'])
def test_fix_names_the_version_of_a_git_nodepack(cm_cli, manager, core, git_pack, monkeypatch, name, label):  # noqa: F811
    if label == '[unknown]':
        manager.unknown_active_nodes['git-pack'] = git_pack
    else:
        manager.active_nodes['git-pack'] = ('nightly', git_pack[1])
    monkeypatch.setattr(manager, 'unified_fix', lambda node_id, version_spec, **kwargs: core.ManagedResult('fix'))

    cm_cli('fix_node')['fix_node'](name, cnt_msg='1/1')

    assert cm_cli.said() == [f'1/1 [ FIXING ]: git-pack {label}']


def test_fix_that_fails_says_why(cm_cli, manager, core, git_pack, monkeypatch):  # noqa: F811
    manager.unknown_active_nodes['git-pack'] = git_pack
    monkeypatch.setattr(manager, 'unified_fix', lambda node_id, version_spec, **kwargs: core.ManagedResult('fix').fail('cannot fix [the reason]'))

    cm_cli('fix_node')['fix_node']('git-pack', cnt_msg='1/1')

    assert cm_cli.said()[1:] == ['ERROR: cannot fix [the reason]']


def test_fix_all_has_a_line_for_each_nodepack_it_counts(cm_cli, manager, core, git_pack, monkeypatch, tmp_path):  # noqa: F811
    manager.unknown_active_nodes['git-pack'] = git_pack
    manager.unknown_inactive_nodes['old-pack'] = ('https://example.invalid/old-pack', str(tmp_path / '.disabled/old-pack'))
    monkeypatch.setattr(manager, 'unified_fix', lambda node_id, version_spec, **kwargs: core.ManagedResult('fix'))

    command(cm_cli('fix', 'for_each_nodes', 'get_all_installed_node_specs', 'fix_node'), 'fix', nodes=['all'])

    assert cm_cli.said() == ['1/2 [ FIXING ]: git-pack [unknown]', '2/2 [ SKIPPED ]: old-pack@unknown => Disabled']


def test_url_that_is_not_installed_says_why(cm_cli, core, git_pack, monkeypatch):  # noqa: F811
    monkeypatch.setattr(core, 'gitclone_install', AsyncMock(return_value=core.ManagedResult('install-git').fail('cannot clone [the reason]')))

    cm_cli('install_node')['install_node'](git_pack[0], cnt_msg='1/1')

    assert cm_cli.said() == ['cannot clone [the reason]', "ERROR: An error occurred while installing 'https://example.invalid/git-pack'."]


def test_install_of_an_id_that_no_list_has_says_where_it_was_looked_for(cm_cli):
    cm_cli('install_node')['install_node']('no-such-pack', cnt_msg='1/1')

    assert cm_cli.said() == ["ERROR: An error occurred while installing 'no-such-pack'.", "Node 'no-such-pack@unknown' not found in [default, cache]"]


@pytest.mark.parametrize('enabled, method, answer, act, line', [
    (False, 'unified_enable', lambda result: result('enable').fail(REASON), 'enable_node', '1/1 [ FAIL ] git-pack => ' + REASON),
    (False, 'unified_enable', lambda result: result('skip').with_msg(REASON), 'enable_node', '1/1 [ SKIP ] git-pack => ' + REASON),
    (True, 'unified_disable', lambda result: result('disable').fail(REASON), 'disable_node', '1/1 [ FAIL ] git-pack => ' + REASON),
    (True, 'unified_disable', lambda result: result('skip').with_msg(REASON), 'disable_node', '1/1 [ SKIP ] git-pack => ' + REASON),
    (True, 'unified_update', lambda result: result('skip').with_msg(REASON), 'update_node', '1/1 [ SKIPPED ]: git-pack => ' + REASON),
], ids=['enable_fails', 'enable_is_skipped', 'disable_fails', 'disable_is_skipped', 'update_is_skipped'])
def test_reason_in_square_brackets_is_printed_whole(cm_cli, manager, core, git_pack, monkeypatch, enabled, method, answer, act, line):  # noqa: F811
    (manager.unknown_active_nodes if enabled else manager.unknown_inactive_nodes)['git-pack'] = git_pack
    monkeypatch.setattr(manager, method, lambda *args, **kwargs: answer(core.ManagedResult))

    cm_cli(act)[act]('git-pack', cnt_msg='1/1')

    assert cm_cli.said() == [line]


@pytest.mark.parametrize('name, enabled, act, line', [
    ('git-pack[old]', False, 'enable_node', '1/1 [ENABLED] git-pack[old]'),
    ('git-pack[old]', True, 'disable_node', '1/1 [DISABLED] git-pack[old]'),
    ('comfyui-manager[old]', True, 'disable_node', "1/1 [ SKIP ] comfyui-manager[old] => Not disabled: its name has 'comfyui-manager'"),
    ('git-pack[old]', False, 'fix_node', '1/1 [ SKIPPED ]: git-pack[old] => Disabled'),
    ('git-pack[old]', None, 'fix_node', '1/1 [ SKIPPED ]: git-pack[old] => Not installed'),
    ('git-pack[old]', None, 'update_node', '1/1 [ SKIPPED ]: git-pack[old] => Not installed'),
], ids=['enable', 'disable', 'disable_of_the_manager', 'fix_of_a_disabled_one', 'fix_of_one_that_is_not_installed',
        'update_of_one_that_is_not_installed'])
def test_name_in_square_brackets_is_printed_whole(cm_cli, manager, core, tmp_path, monkeypatch, name, enabled, act, line):  # noqa: F811
    if enabled is not None:
        (manager.unknown_active_nodes if enabled else manager.unknown_inactive_nodes)[name] = ('https://example.invalid/git-pack', str(tmp_path / name))
    monkeypatch.setattr(manager, 'unified_enable', lambda *args, **kwargs: core.ManagedResult('enable'))
    monkeypatch.setattr(manager, 'unified_disable', lambda *args, **kwargs: core.ManagedResult('disable'))

    cm_cli(act)[act](name, cnt_msg='1/1')

    assert cm_cli.said() == [line]


def test_line_longer_than_the_console_is_wide_is_written_as_one_line(cm_cli, manager, git_pack):  # noqa: F811
    manager.unknown_active_nodes['git-pack'] = git_pack

    cm_cli('enable_node', width=80)['enable_node']('git-pack', cnt_msg='1/1')

    assert cm_cli.said() == ['1/1 [ SKIP ] git-pack => Already enabled']


def test_error_of_a_nodepack_in_a_run_over_several_is_printed_whole(cm_cli):
    def act(name, **kwargs):
        raise RuntimeError('no such [thing] for ' + name)

    with pytest.raises(SystemExit):
        cm_cli('for_each_nodes', traceback=Mock())['for_each_nodes'](['git-pack'], act)

    assert cm_cli.said()[0] == 'ERROR: no such [thing] for git-pack'


def test_error_of_an_update_in_a_run_over_several_is_printed_whole(cm_cli):
    cm_cli('update_parallel', update_node=Mock(side_effect=RuntimeError('no such [thing]')), traceback=Mock())['update_parallel'](['git-pack'])

    assert cm_cli.said() == ['ERROR: no such [thing]']


def test_show_versions_prints_a_changelog_with_square_brackets(cm_cli):
    versions = [{'createdAt': '2026-01-02T03:04:05', 'version': '1.0.1', 'changelog': '[fix] a crash'}]

    cm_cli('show_versions', cnr_utils=SimpleNamespace(all_versions_of_node=lambda name: versions))['show_versions']('git-pack')

    assert cm_cli.said() == ['[2026-01-02] 1.0.1 -- [fix] a crash']


def test_show_prints_a_title_and_an_author_with_square_brackets(cm_cli, manager, tmp_path):  # noqa: F811
    manager.get_custom_nodes = AsyncMock(return_value={
        'listed-pack': {'title': 'Listed [gist-wrapper] Pack', 'author': 'some[one]', 'files': ['https://github.com/someone/listed-pack']},
    })
    manager.cnr_map['registry-pack'] = {'id': 'registry-pack', 'name': 'Registry[official] Pack', 'publisher': {'name': 'someone'},
                                        'latest_version': {'version': '1.0.0'}}
    manager.active_nodes['registry-pack'] = ('1.0.0', str(tmp_path / 'registry-pack'))
    manager.unknown_active_nodes['listed-pack'] = ('https://github.com/someone/listed-pack', str(tmp_path / 'listed-pack'))
    scope = cm_cli('show', 'simple_show', 'show_list')

    scope['show']('installed', None, None, None)
    scope['simple_show']('installed', None, None, None)

    assert cm_cli.said() == ['[ ENABLED ] Registry[official] Pack registry-pack (author: someone ) [1.0.0]',
                             '[ ENABLED ] Listed [gist-wrapper] Pack listed-pack (author: some[one] ) [UNKNOWN]',
                             'Registry[official] Pack@1.0.0', 'Listed [gist-wrapper] Pack@unknown']


def test_show_of_a_word_that_is_no_list_is_refused_in_plain_words(cm_cli, capsys):
    command(cm_cli('simple_show'), 'simple_show', arg='[nodes]')

    assert capsys.readouterr().err.split() == ['Invalid', 'command:', '`show', '[nodes]`']


def test_names_of_snapshots_are_listed_whole(cm_cli, folder):
    open(os.path.join(folder, 'before [the update].json'), 'w').close()
    scope = cm_cli('show_snapshot_list')
    scope['cmd_ctx'].get_snapshot_path.return_value = folder

    scope['show_snapshot_list']()

    assert cm_cli.said() == ['before [the update].json']


def restore_of_a_file_that_is_not_there(scope, folder):
    scope['cmd_ctx'].get_snapshot_path.return_value = folder
    command(scope, 'restore_snapshot', snapshot_name='gone.json')


def save_as(scope, folder):
    scope['core'].save_snapshot_with_postfix = AsyncMock(return_value=folder + '/snapshot.json')
    command(scope, 'save_snapshot', output=folder + '/snapshot.json')


def deps_of_a_workflow(scope, folder):
    open(folder + '/workflow.json', 'w').close()
    scope['core'].extract_nodes_from_workflow = AsyncMock(return_value=({}, []))
    command(scope, 'deps_in_workflow', workflow=folder + '/workflow.json', output=folder + '/deps.json')


def install_deps_of_a_file_that_is_not_json(scope, folder):
    open(folder + '/deps.json', 'w').close()
    command(scope, 'install_deps', deps=folder + '/deps.json')


@pytest.mark.parametrize('call, line', [
    (restore_of_a_file_that_is_not_there, f'ERROR: `{{folder}}{os.sep}gone.json` is not exists.'),
    (lambda scope, folder: command(scope, 'save_snapshot', output=folder + '/gone/snapshot.json'),
     'ERROR: {folder}/gone/snapshot.json path not exists.'),
    (save_as, 'Current snapshot is saved as `{folder}/snapshot.json`'),
    (lambda scope, folder: command(scope, 'deps_in_workflow', workflow=folder + '/gone.json', output='deps.json'),
     'File not found: {folder}/gone.json'),
    (deps_of_a_workflow, 'Workflow dependencies are being saved into {folder}/deps.json.'),
    (lambda scope, folder: command(scope, 'install_deps', deps=folder + '/gone.json'), 'File not found: {folder}/gone.json'),
    (install_deps_of_a_file_that_is_not_json, 'Invalid json file: {folder}/deps.json'),
], ids=['restore-snapshot of a file that is not there', 'save-snapshot into a folder that is not there', 'save-snapshot',
        'deps-in-workflow of a file that is not there', 'deps-in-workflow', 'install-deps of a file that is not there',
        'install-deps of a file that is not JSON'])
def test_path_with_square_brackets_is_printed_whole(cm_cli, core, monkeypatch, folder, call, line):  # noqa: F811
    monkeypatch.setattr(core, 'save_snapshot_with_postfix', None)
    monkeypatch.setattr(core, 'extract_nodes_from_workflow', None)

    call(cm_cli('restore_snapshot', 'save_snapshot', 'deps_in_workflow', 'install_deps'), folder)

    assert cm_cli.said()[-1:] == [line.replace('{folder}', folder)]


@pytest.mark.parametrize('path', [r'C:\ComfyUI\[My] files\deps.json', '/nodes/' + 'long-folder-name/' * 5 + 'deps.json', '/nodes/x:100:y/deps.json'],
                         ids=['a backslash before a bracket', 'longer than the console is wide', 'the code of an emoji'])
@pytest.mark.parametrize('call, line', [
    (lambda scope, path: command(scope, 'install_deps', deps=path), 'File not found: {}'),
    (lambda scope, path: command(scope, 'save_snapshot'), 'Current snapshot is saved as `{}`'),
], ids=['a coloured line', 'a line without a colour'])
def test_line_is_written_as_it_is(cm_cli, core, monkeypatch, call, line, path):  # noqa: F811
    monkeypatch.setattr(core, 'save_snapshot_with_postfix', AsyncMock(return_value=path))

    call(cm_cli('install_deps', 'save_snapshot', width=80), path)

    assert cm_cli.said() == [line.format(path)]


def list_a_snapshot_with_a_quoted_word(scope, folder):
    open(os.path.join(folder, "the 'old' one.json"), 'w').close()
    scope['cmd_ctx'].get_snapshot_path.return_value = folder
    scope['show_snapshot_list']()


@pytest.mark.parametrize('call, line', [
    (lambda scope, folder: command(scope, 'install_deps', deps='deps.json'), '\x1b[1;31mFile not found: deps.json\x1b[0m'),
    (list_a_snapshot_with_a_quoted_word, "the \x1b[32m'old'\x1b[0m one.json"),
], ids=['a line that cm-cli colours', 'a quoted text in another line'])
def test_line_keeps_its_colour(cm_cli, folder, call, line):
    call(cm_cli('install_deps', 'show_snapshot_list', color_system='standard'), folder)

    assert cm_cli.said() == [line]


@pytest.mark.parametrize('app', [typer.Typer, lambda: typer.Typer(rich_markup_mode=None)], ids=['with rich markup', 'without'])
def test_help_names_the_values_that_an_argument_and_an_option_take(cm_cli, app):
    app = cm_cli('show', 'update', app=app())['app']

    def help(name):
        return ' '.join(typer.testing.CliRunner().invoke(app, [name, '--help'], env={'COLUMNS': '200'}).output.split())

    assert 'installed|enabled|not-installed' in help('show') and 'all|List of custom nodes to update' in help('update')
    assert 'remote|local|cache' in help('show') and 'remote|local|cache' in help('update')
    assert '\\' not in help('show') + help('update')


def test_report_of_the_resolver_names_a_requirement_with_its_extra(cm_cli, monkeypatch, tmp_path):
    result = SimpleNamespace(success=False, error='no solution for [the pack]', lockfile=SimpleNamespace(conflicts=['a conflict']),
                             collected=SimpleNamespace(sources={}))
    monkeypatch.setitem(sys.modules, 'comfyui_manager.common.unified_dep_resolver', SimpleNamespace(
        collect_node_pack_paths=lambda paths: [str(tmp_path / 'a-pack')], collect_base_requirements=lambda path: [],
        UnifiedDepResolver=lambda **kwargs: SimpleNamespace(resolve_and_install=lambda: result), UvNotAvailableError=RuntimeError,
        attribute_conflicts=lambda sources, conflicts: {'opencv-python-headless': [(str(tmp_path / 'a-pack'), 'opencv-python-headless[ffmpeg]>=4')]}))

    command(cm_cli('_run_unified_resolve', cm_global=Mock()), '_run_unified_resolve')

    assert cm_cli.said()[1:] == ['Resolution failed: no solution for [the pack]', 'Conflicting packages (by node pack):',
                                 'opencv-python-headless:', 'a-pack → opencv-python-headless[ffmpeg]>=4']


def test_disable_says_why_the_manager_is_not_disabled(cm_cli):
    cm_cli('disable_node')['disable_node']('comfyui-manager', cnt_msg='1/1')

    assert cm_cli.said() == ["1/1 [ SKIP ] comfyui-manager => Not disabled: its name has 'comfyui-manager'"]


def test_disable_all_has_a_line_for_each_nodepack_it_counts(cm_cli, manager, tmp_path):  # noqa: F811
    for name in ('comfyui-manager', 'git-pack'):
        (tmp_path / name).mkdir()
        manager.unknown_active_nodes[name] = ('https://example.invalid/' + name, str(tmp_path / name))

    cm_cli('disable', 'for_each_nodes', 'get_all_installed_node_specs', 'disable_node')['disable'](['all'], None, None, None)

    assert [line.split()[0] for line in cm_cli.said()] == ['1/2', '2/2']


def test_restore_dependencies_runs_for_the_nodepacks_only(cm_cli, manager, folder):  # noqa: F811
    for name in ('a-pack', '__pycache__', 'b-pack.disabled', '.disabled'):
        os.mkdir(os.path.join(folder, name))
    manager.execute_install_script = Mock()
    scope = cm_cli('restore_dependencies')
    scope['cmd_ctx'].get_custom_nodes_paths.return_value = [folder]

    command(scope, 'restore_dependencies', uv_compile=False)

    assert [line for line in cm_cli.said() if line.startswith('Restoring')] == [f'Restoring [1/1]: {folder}{os.sep}a-pack']
    assert [call.args[1] for call in manager.execute_install_script.call_args_list] == [os.path.join(folder, 'a-pack')]
