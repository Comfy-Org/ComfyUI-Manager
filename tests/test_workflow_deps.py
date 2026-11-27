import asyncio
import io
import json
import os
from types import SimpleNamespace
from typing import Optional

import pytest
import rich.console
import typer
from typing_extensions import Annotated

from test_invalid_installation import (BAR_URL, FOO_URL, NODE_LIST, cm_cli_function, core, custom_nodes,  # noqa: F401 -- fixtures
                                       listing, pack, reload)


@pytest.fixture
def cm_cli(core, custom_nodes, monkeypatch, tmp_path):  # noqa: F811
    async def get_data_by_mode(mode, filename, channel_url=None):
        if filename == 'extension-node-map.json':
            return {FOO_URL: [['FooNode'], {}], BAR_URL: [['BarNode'], {}]}
        return {'custom_nodes': [dict(item) for item in NODE_LIST]}

    async def auto_save_snapshot():
        pass

    monkeypatch.setattr(core, 'get_data_by_mode', get_data_by_mode)
    out = io.StringIO()
    namespace = {
        'asyncio': asyncio, 'os': os, 'json': json, 'core': core, 'unified_manager': core.unified_manager, 'typer': typer,
        'Annotated': Annotated, 'Optional': Optional, 'app': SimpleNamespace(command=lambda *args, **kwargs: lambda f: f),
        'print': rich.console.Console(file=out, width=1000, color_system=None).print,
        'auto_save_snapshot': auto_save_snapshot, 'comfy_path': str(tmp_path),
        'context': SimpleNamespace(manager_files_path=str(tmp_path)),
        'manager_util': SimpleNamespace(get_installed_packages=dict,
                                        PIPFixer=lambda *args: SimpleNamespace(fix_broken=lambda: None)),
        'cmd_ctx': SimpleNamespace(set_user_directory=lambda path: None, set_channel_mode=lambda channel, mode: reload(core),
                                   set_no_deps=lambda no_deps: None, mode='cache', channel='default'),
        'out': out}
    for name in ('enable_node', '_finalize_resolve', 'deps_in_workflow', 'install_deps'):
        cm_cli_function(name, namespace)
    return namespace


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
@pytest.mark.parametrize('folder, kwargs, foo, bar', [
    ('comfyui-foo', {'project_name': 'comfyui-foo', 'tracking': True}, 'installed', 'not-installed'),
    ('.disabled/comfyui-foo@1_0_1', {'project_name': 'comfyui-foo', 'tracking': True}, 'disabled', 'not-installed'),
    ('.disabled/comfyui-foo@nightly', {'git_url': FOO_URL}, 'disabled', 'not-installed'),
    ('ComfyUI-Bar', {'git_url': BAR_URL}, 'not-installed', 'installed'),
    ('.disabled/ComfyUI-Bar', {'git_url': BAR_URL}, 'not-installed', 'disabled'),
    ('ComfyUI-Bar.disabled', {'git_url': BAR_URL}, 'not-installed', 'disabled'),
], ids=['registry', 'registry-disabled', 'nightly-disabled', 'git', 'git-disabled', 'git-disabled-old-style'])
def test_deps_in_workflow_writes_the_state_of_each_nodepack(core, custom_nodes, cm_cli, tmp_path, folder, kwargs, foo, bar):  # noqa: F811
    pack(custom_nodes / folder, **kwargs)
    workflow = tmp_path / 'workflow.json'
    workflow.write_text(json.dumps({'nodes': [{'id': 1, 'type': 'FooNode'}, {'id': 2, 'type': 'BarNode'}]}))

    cm_cli['deps_in_workflow'](workflow=str(workflow), output=str(tmp_path / 'deps.json'), channel=None, mode=None,
                               user_directory=None)

    assert json.loads((tmp_path / 'deps.json').read_text()) == {
        'custom_nodes': {FOO_URL: {'state': foo, 'hash': '-'}, BAR_URL: {'state': bar, 'hash': '-'}}, 'unknown_nodes': []}


@pytest.mark.parametrize('core', ['legacy'], indirect=True)
@pytest.mark.parametrize('folder, kwargs, url, enabled', [
    ('.disabled/comfyui-foo@1_0_1', {'project_name': 'comfyui-foo', 'tracking': True}, FOO_URL, 'comfyui-foo'),
    ('.disabled/ComfyUI-Bar', {'git_url': BAR_URL}, BAR_URL, 'ComfyUI-Bar'),
    ('ComfyUI-Bar.disabled', {'git_url': BAR_URL}, BAR_URL, 'ComfyUI-Bar'),
], ids=['registry', 'git', 'git-old-style'])
def test_install_deps_enables_a_disabled_nodepack(core, custom_nodes, cm_cli, tmp_path, folder, kwargs, url, enabled):  # noqa: F811
    pack(custom_nodes / folder, **kwargs)
    deps = tmp_path / 'deps.json'
    deps.write_text(json.dumps({'custom_nodes': {url: {'state': 'disabled', 'hash': '-'}}, 'unknown_nodes': []}))

    cm_cli['install_deps'](deps=str(deps), channel=None, mode=None, user_directory=None, uv_compile=False)

    assert listing(custom_nodes) == [enabled]
    assert cm_cli['out'].getvalue().splitlines()[-1] == 'Dependency installation and activation complete.'
