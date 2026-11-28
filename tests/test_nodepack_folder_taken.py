import ast
import asyncio
import io
import logging
import shutil
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from legacy_html_testutil import PACKAGE
from test_invalid_installation import (BAR_URL, FOO_URL, NodeInstallError, cm_cli_function, core, custom_nodes,  # noqa: F401
                                       data_models, pack, registry_api, reload, run_glob_worker)

UNKNOWN, VERSION, NIGHTLY = {'git_url': BAR_URL}, {'project_name': 'comfyui-foo', 'tracking': True}, {'project_name': 'comfyui-foo', 'git_url': FOO_URL}
KINDS = pytest.mark.parametrize('name, made_with, disabled, version', [
    ('ComfyUI-Bar', UNKNOWN, '.disabled/ComfyUI-Bar', 'unknown'),
    ('comfyui-foo', VERSION, '.disabled/comfyui-foo@1_0_1', '1.0.1'),
    ('comfyui-foo', NIGHTLY, '.disabled/comfyui-foo@nightly', 'nightly'),
], ids=['git_clone_that_no_list_knows', 'registry_version', 'nightly_clone'])


def folders(path):
    return sorted(folder.relative_to(path).as_posix() for folder in path.rglob('*')
                  if (folder.is_dir() or folder.is_symlink()) and folder.name != '.git')


def broken_link(path):
    path.parent.mkdir(exist_ok=True)
    path.symlink_to(path.parent / 'gone')


def stand_ins(module, monkeypatch):
    def clone(url, folder, **options):
        Path(folder).mkdir()
        return module.ManagedResult('install-git')

    registry_api(monkeypatch, module)
    monkeypatch.setattr(module.manager_downloader, 'basic_download_url', module.manager_downloader.download_url)
    manager = reload(module)
    manager.repo_install = Mock(side_effect=clone)
    return manager


def install(module, path, version):
    manager = module.unified_manager
    result = asyncio.run(manager.install_by_id('comfyui-foo', version, module.DEFAULT_CHANNEL, 'cache', instant_execution=True))
    return [result.result, module.manager_downloader.download_url.call_count + manager.repo_install.call_count, folders(path)]


def legacy_task(name, **names):
    path = PACKAGE / 'legacy/manager_server.py'
    found = [node for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
             if isinstance(node, ast.AsyncFunctionDef) and node.name == name]
    exec(compile(ast.Module(found, []), str(path), 'exec'), names)
    return names[name]


@KINDS
@pytest.mark.parametrize('taken_by', ['a_disabled_copy', 'a_broken_link'])
def test_disable_fails_when_its_destination_is_taken(core, custom_nodes, taken_by, name, made_with, disabled, version):  # noqa: F811
    pack(custom_nodes / name, **made_with)
    if taken_by == 'a_disabled_copy':
        pack(custom_nodes / disabled, **made_with)
    else:
        broken_link(custom_nodes / disabled)
    manager = reload(core)

    assert [manager.unified_disable(name, version == 'unknown').result, folders(custom_nodes)] == [False, ['.disabled', disabled, name]]


@KINDS
@pytest.mark.parametrize('taken_by', ['a_folder_made_since_the_last_scan', 'a_broken_link'])
def test_enable_fails_when_its_destination_is_taken(core, custom_nodes, taken_by, name, made_with, disabled, version):  # noqa: F811
    pack(custom_nodes / disabled, **made_with)
    manager = reload(core)
    if taken_by == 'a_folder_made_since_the_last_scan':
        (custom_nodes / name).mkdir()
    else:
        broken_link(custom_nodes / name)

    assert [manager.unified_enable(name, version).result, folders(custom_nodes)] == [False, ['.disabled', disabled, name]]


def test_git_clone_that_no_list_knows_is_not_enabled_over_the_enabled_version_of_its_name(core, custom_nodes):  # noqa: F811
    pack(custom_nodes / 'comfyui-foo', **VERSION)
    pack(custom_nodes / '.disabled/comfyui-foo', git_url='https://github.com/someone/comfyui-foo')
    manager = reload(core)

    assert [manager.unified_enable('comfyui-foo', 'unknown').result, folders(custom_nodes)] == [
        False, ['.disabled', '.disabled/comfyui-foo', 'comfyui-foo']]


@pytest.mark.parametrize('linked, taken', [
    (False, lambda path: (path / 'comfyui-foo').mkdir()),
    (False, lambda path: (path / 'comfyui-foo').symlink_to(path / 'foo')),
    (True, lambda path: (path / 'comfyui-foo').symlink_to(path.parent / 'checkout')),
], ids=['by_another_folder', 'by_a_link_to_the_enabled_folder', 'by_a_second_link_to_the_folder_of_the_enabled_link'])
def test_enable_whose_folder_is_taken_leaves_the_enabled_version_enabled(core, custom_nodes, linked, taken):  # noqa: F811
    pack(custom_nodes.parent / 'checkout' if linked else custom_nodes / 'foo', **NIGHTLY)
    if linked:
        (custom_nodes / 'foo').symlink_to(custom_nodes.parent / 'checkout')
    pack(custom_nodes / '.disabled/comfyui-foo@1_0_1', **VERSION)
    manager = reload(core)
    taken(custom_nodes)

    assert [manager.unified_enable('comfyui-foo', '1.0.1').result, folders(custom_nodes)] == [
        False, ['.disabled', '.disabled/comfyui-foo@1_0_1', 'comfyui-foo', 'foo']]


def test_enable_whose_folder_is_taken_fails_when_the_folder_of_the_enabled_version_is_gone(core, custom_nodes):  # noqa: F811
    pack(custom_nodes / 'foo', **NIGHTLY)
    pack(custom_nodes / '.disabled/comfyui-foo@1_0_1', **VERSION)
    manager = reload(core)
    shutil.rmtree(custom_nodes / 'foo')
    (custom_nodes / 'comfyui-foo').mkdir()

    assert [manager.unified_enable('comfyui-foo', '1.0.1').result, folders(custom_nodes)] == [
        False, ['.disabled', '.disabled/comfyui-foo@1_0_1', 'comfyui-foo']]


@pytest.mark.parametrize('folder', ['comfyui-foo', 'ComfyUI-Foo'], ids=['in_the_folder_of_its_id', 'in_a_folder_of_another_spelling'])
def test_version_takes_the_folder_of_the_enabled_nightly_clone(core, custom_nodes, folder):  # noqa: F811
    pack(custom_nodes / folder, **NIGHTLY)
    pack(custom_nodes / '.disabled/comfyui-foo@1_0_1', **VERSION)
    manager = reload(core)

    assert [manager.unified_enable('comfyui-foo', '1.0.1').result, folders(custom_nodes)] == [
        True, ['.disabled', '.disabled/comfyui-foo@nightly', 'comfyui-foo']]


@pytest.mark.parametrize('enabled, taken, disabled, made_with, act, refused', [
    (NIGHTLY, '.disabled/comfyui-foo@nightly', '.disabled/comfyui-foo@1_0_1', VERSION,
     lambda module, path: module.unified_manager.unified_enable('comfyui-foo', '1.0.1').result, False),
    (VERSION, '.disabled/comfyui-foo@1_0_1', '.disabled/comfyui-foo@nightly', NIGHTLY,
     lambda module, path: module.unified_manager.unified_enable('comfyui-foo', 'nightly').result, False),
    (NIGHTLY, '.disabled/comfyui-foo@nightly', None, None, lambda module, path: install(module, path, '1.0.1')[:2], [False, 0]),
    (VERSION, '.disabled/comfyui-foo@1_0_1', None, None, lambda module, path: install(module, path, 'nightly')[:2], [False, 0]),
], ids=['enable_of_a_version', 'enable_of_the_nightly_clone', 'install_of_a_version', 'install_of_the_nightly_clone'])
def test_nodepack_does_not_take_the_place_of_an_enabled_one_that_cannot_be_disabled(core, custom_nodes, monkeypatch, enabled, taken,  # noqa: F811
                                                                                    disabled, made_with, act, refused):
    for folder in ('ComfyUI-Foo', taken):
        pack(custom_nodes / folder, **enabled)
    if disabled is not None:
        pack(custom_nodes / disabled, **made_with)
    stand_ins(core, monkeypatch)
    before = folders(custom_nodes)

    assert [act(core, custom_nodes), folders(custom_nodes)] == [refused, before]


@pytest.mark.parametrize('enabled, disabled, made_with, act, done', [
    (NIGHTLY, '.disabled/comfyui-foo@1_0_1', VERSION, lambda module, path: module.unified_manager.unified_enable('comfyui-foo', '1.0.1').result,
     [True, ['.disabled', 'comfyui-foo']]),
    (VERSION, '.disabled/comfyui-foo@nightly', NIGHTLY, lambda module, path: module.unified_manager.unified_enable('comfyui-foo', 'nightly').result,
     [True, ['.disabled', 'comfyui-foo']]),
    (NIGHTLY, None, None, lambda module, path: install(module, path, '1.0.1')[:2], [[True, 1], ['comfyui-foo']]),
    (VERSION, None, None, lambda module, path: install(module, path, 'nightly')[:2], [[True, 1], ['comfyui-foo']]),
], ids=['enable_of_a_version', 'enable_of_the_nightly_clone', 'install_of_a_version', 'install_of_the_nightly_clone'])
def test_nodepack_takes_the_place_of_an_enabled_one_whose_folder_is_gone(core, custom_nodes, monkeypatch, enabled, disabled,  # noqa: F811
                                                                         made_with, act, done):
    pack(custom_nodes / 'ComfyUI-Foo', **enabled)
    if disabled is not None:
        pack(custom_nodes / disabled, **made_with)
    stand_ins(core, monkeypatch)
    shutil.rmtree(custom_nodes / 'ComfyUI-Foo')

    assert [act(core, custom_nodes), folders(custom_nodes)] == done


@pytest.mark.parametrize('enabled, disabled, version', [
    (NIGHTLY, '.disabled/comfyui-foo@1_0_0', '1.0.1'),
    (NIGHTLY, None, '1.0.1'),
    (VERSION, None, 'nightly'),
], ids=['of_a_version_that_enables_a_disabled_one', 'of_a_version_that_is_downloaded', 'of_the_nightly_clone'])
def test_install_whose_folder_is_taken_leaves_the_enabled_one_enabled(core, custom_nodes, monkeypatch, enabled, disabled,  # noqa: F811
                                                                      version):
    pack(custom_nodes / 'foo', **enabled)
    if disabled is not None:
        pack(custom_nodes / disabled, 'comfyui-foo', version='1.0.0', tracking=True)
    stand_ins(core, monkeypatch)
    (custom_nodes / 'comfyui-foo').mkdir()
    before = folders(custom_nodes)

    assert install(core, custom_nodes, version) == [False, 0, before]


def test_version_is_not_switched_when_the_disabled_one_cannot_be_enabled(core, custom_nodes, monkeypatch):  # noqa: F811
    pack(custom_nodes / 'comfyui-foo', git_url='https://github.com/someone/comfyui-foo')
    pack(custom_nodes / '.disabled/comfyui-foo@1_0_0', 'comfyui-foo', version='1.0.0', tracking=True)

    stand_ins(core, monkeypatch)

    assert install(core, custom_nodes, '1.0.1') == [False, 0, ['.disabled', '.disabled/comfyui-foo@1_0_0', 'comfyui-foo']]


@pytest.mark.parametrize('core', ['glob'], indirect=True)
def test_the_v4_queue_tells_the_page_that_a_disable_failed_and_the_terminal_why(core, custom_nodes, monkeypatch, caplog):  # noqa: F811
    for folder in ('ComfyUI-Bar', '.disabled/ComfyUI-Bar'):
        pack(custom_nodes / folder, **UNKNOWN)
    reload(core)
    task = data_models(monkeypatch).QueueTaskItem.model_validate({
        'ui_id': 'ui', 'client_id': 'client', 'kind': 'disable', 'params': {'node_name': 'ComfyUI-Bar', 'is_unknown': True}})

    assert [run_glob_worker(monkeypatch, core, task), folders(custom_nodes)] == [
        [('disable', "Failed to disable: 'ComfyUI-Bar'", 'error')], ['.disabled', '.disabled/ComfyUI-Bar', 'ComfyUI-Bar']]
    assert str(custom_nodes / '.disabled' / 'ComfyUI-Bar') in caplog.text


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_the_legacy_queue_tells_the_page_that_a_disable_failed_and_the_terminal_why(core, custom_nodes, caplog):  # noqa: F811
    for folder in ('ComfyUI-Bar', '.disabled/ComfyUI-Bar'):
        pack(custom_nodes / folder, **UNKNOWN)
    reload(core)
    disable = legacy_task('do_disable', core=core, logging=logging, traceback=traceback)

    assert [asyncio.run(disable(('the row', 'ComfyUI-Bar', True))), folders(custom_nodes)] == [
        "Failed to disable: 'ComfyUI-Bar'", ['.disabled', '.disabled/ComfyUI-Bar', 'ComfyUI-Bar']]
    assert str(custom_nodes / '.disabled' / 'ComfyUI-Bar') in caplog.text


def a_version_whose_folder_is_taken(module, path):
    pack(path / '.disabled/comfyui-foo@1_0_1', **VERSION)
    reload(module)
    (path / 'comfyui-foo').mkdir()


@pytest.mark.parametrize('core', ['glob'], indirect=True)
def test_the_v4_queue_tells_the_page_that_an_enable_failed_and_the_terminal_why(core, custom_nodes, monkeypatch, caplog):  # noqa: F811
    a_version_whose_folder_is_taken(core, custom_nodes)
    task = data_models(monkeypatch).QueueTaskItem.model_validate({
        'ui_id': 'ui', 'client_id': 'client', 'kind': 'enable', 'params': {'cnr_id': 'comfyui-foo'}})

    assert [run_glob_worker(monkeypatch, core, task), folders(custom_nodes)] == [
        [('enable', "Failed to enable: 'comfyui-foo'", 'error')], ['.disabled', '.disabled/comfyui-foo@1_0_1', 'comfyui-foo']]
    assert str(custom_nodes / 'comfyui-foo') in caplog.text


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_the_legacy_queue_tells_the_page_that_an_enable_failed_and_the_terminal_why(core, custom_nodes, caplog):  # noqa: F811
    a_version_whose_folder_is_taken(core, custom_nodes)
    enable = legacy_task('do_enable', core=core, logging=logging, replaces_cnr_with_nightly=lambda cnr_id: False)

    assert [asyncio.run(enable(('the row', 'comfyui-foo'))), folders(custom_nodes)] == [
        "Failed to enable: 'comfyui-foo'", ['.disabled', '.disabled/comfyui-foo@1_0_1', 'comfyui-foo']]
    assert str(custom_nodes / 'comfyui-foo') in caplog.text


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
def test_cm_cli_install_reports_an_enable_that_failed(core, custom_nodes):  # noqa: F811
    pack(custom_nodes / '.disabled/ComfyUI-Bar', **UNKNOWN)
    manager = reload(core)
    (custom_nodes / 'ComfyUI-Bar').mkdir()
    out = io.StringIO()
    install_node = cm_cli_function('install_node', {
        'asyncio': asyncio, 'core': core, 'unified_manager': manager, 'print': lambda *objects, **kwargs: print(*objects, file=out),
        'cmd_ctx': SimpleNamespace(channel=core.DEFAULT_CHANNEL, mode='cache', no_deps=False), 'NodeInstallError': NodeInstallError})

    with pytest.raises(NodeInstallError):
        install_node('ComfyUI-Bar@unknown', cnt_msg='1/1', raise_on_fail=True)

    assert ['[ ENABLED ]' in out.getvalue(), folders(custom_nodes)] == [False, ['.disabled', '.disabled/ComfyUI-Bar', 'ComfyUI-Bar']]
