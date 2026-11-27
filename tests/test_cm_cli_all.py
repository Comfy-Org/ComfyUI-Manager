import asyncio
import io
import os
import sys
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import typer
from rich.console import Console
from typing_extensions import Annotated, List

from legacy_html_testutil import ROOT, load_functions
from test_snapshot_restore_pins import core, manager  # noqa: F401


@pytest.fixture
def cm_cli(manager, tmp_path):  # noqa: F811
    for name in ('enabled-pack', '.disabled/registry-pack@1_0_0', '.disabled/rc-pack@1_0_0-rc1', '.disabled/git-pack'):
        (tmp_path / name).mkdir(parents=True)
    manager.active_nodes['enabled-pack'] = ('2.0.0', str(tmp_path / 'enabled-pack'))
    manager.cnr_inactive_nodes['registry-pack'] = {'1.0.0': str(tmp_path / '.disabled/registry-pack@1_0_0')}
    manager.cnr_inactive_nodes['rc-pack'] = {'1.0.0-rc1': str(tmp_path / '.disabled/rc-pack@1_0_0-rc1')}
    manager.unknown_inactive_nodes['git-pack'] = ('https://github.com/owner/git-pack', str(tmp_path / '.disabled/git-pack'))
    out = io.StringIO()

    def cm_cli(*names):
        return load_functions(ROOT / 'cm_cli/__main__.py', set(names), {
            'app': SimpleNamespace(command=lambda *args, **kwargs: lambda function: function),
            'typer': typer, 'Annotated': Annotated, 'List': List, 'asyncio': asyncio, 'sys': sys, 'traceback': traceback,
            'print': Console(file=out, width=1000, color_system=None).print, 'NodeInstallError': type('NodeInstallError', (Exception,), {}),
            'cmd_ctx': Mock(no_deps=False), 'unified_manager': manager, 'auto_save_snapshot': AsyncMock(),
        })

    cm_cli.said = lambda: [' '.join(line.split()) for line in out.getvalue().splitlines() if 'pack' in line]
    cm_cli.folders = lambda: (sorted(os.listdir(tmp_path)), sorted(os.listdir(tmp_path / '.disabled')))
    return cm_cli


def all_of(cm_cli, name):
    cm_cli(name, 'for_each_nodes', 'get_all_installed_node_specs', 'enable_node', 'disable_node')[name](['all'], None, None, None)
    return [line.split('=>')[-1].strip() for line in cm_cli.said()], *cm_cli.folders()


def test_enable_all_enables_every_disabled_nodepack(cm_cli):
    said, enabled, disabled = all_of(cm_cli, 'enable')

    assert enabled == ['.disabled', 'enabled-pack', 'git-pack', 'rc-pack', 'registry-pack']
    assert disabled == []
    assert said[0] == 'Already enabled'


def test_disable_all_disables_every_enabled_nodepack_and_leaves_the_disabled_ones(cm_cli):
    said, enabled, disabled = all_of(cm_cli, 'disable')

    assert enabled == ['.disabled']
    assert disabled == ['enabled-pack@2_0_0', 'git-pack', 'rc-pack@1_0_0-rc1', 'registry-pack@1_0_0']
    assert said[1:] == ['Already disabled', 'Already disabled', 'Already disabled']


def test_latest_names_the_installed_nodepack_as_a_bare_id_does(cm_cli, manager, core, monkeypatch):  # noqa: F811
    for name, latest in (('enabled-pack', '3.0.0'), ('registry-pack', '1.5.0')):
        manager.cnr_map[name] = {'id': name, 'latest_version': {'version': latest}}
    monkeypatch.setattr(manager, 'unified_update', lambda node_id, version_spec=None, **kwargs: core.ManagedResult('update').with_target('3.0.0'))
    monkeypatch.setattr(manager, 'unified_fix', lambda node_id, version_spec, **kwargs: core.ManagedResult('fix'))
    acts = cm_cli('update_node', 'fix_node', 'disable_node', 'enable_node')

    for act, name in (('update_node', 'enabled-pack'), ('fix_node', 'enabled-pack'), ('disable_node', 'enabled-pack'), ('enable_node', 'registry-pack')):
        acts[act](name + '@latest')

    assert cm_cli.said() == ['[ UPDATED ]: enabled-pack => (2.0.0 -> 3.0.0)', '[ FIXING ]: enabled-pack [2.0.0]', '[DISABLED] enabled-pack',
                             '[ENABLED] registry-pack']
    assert cm_cli.folders() == (['.disabled', 'registry-pack'], ['enabled-pack@2_0_0', 'git-pack', 'rc-pack@1_0_0-rc1'])


def test_a_registry_nodepack_that_is_not_installed_is_not_called_disabled(cm_cli, manager):  # noqa: F811
    manager.cnr_map['absent-pack'] = {'id': 'absent-pack', 'latest_version': {'version': '1.0.0'}}
    acts = cm_cli('update_node', 'fix_node', 'disable_node', 'enable_node')

    for name in ('absent-pack', 'absent-pack@latest'):
        for act in ('update_node', 'fix_node', 'disable_node', 'enable_node'):
            acts[act](name)

    assert [line.split('=>')[-1].strip() for line in cm_cli.said()] == ['Not installed', 'Not installed', 'Not found', 'Not found'] * 2
