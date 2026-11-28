import asyncio
import sys
import traceback
from types import SimpleNamespace
from typing import Optional
from unittest.mock import Mock

import pytest
import typer
from typing_extensions import Annotated, List

from legacy_html_testutil import ROOT, load_functions


class NodeInstallError(Exception):
    pass


def install(node, exit_on_fail):
    async def install_by_id(*args, **kwargs):
        return SimpleNamespace(action='install', result=False, target=None, msg=f"Node '{node}@unknown' not found")

    unified_manager = SimpleNamespace(resolve_node_spec=lambda spec: (spec, 'unknown', False), install_by_id=install_by_id, cnr_map={})
    load_functions(ROOT / 'cm_cli/__main__.py', {'install', 'install_node', 'for_each_nodes', '_finalize_resolve'}, {
        'app': SimpleNamespace(command=lambda *args, **kwargs: lambda function: function),
        'typer': typer, 'Annotated': Annotated, 'List': List, 'Optional': Optional,
        'asyncio': asyncio, 'sys': sys, 'traceback': traceback, 'print': lambda *objects, style=None: print(*objects), 'NodeInstallError': NodeInstallError,
        'cmd_ctx': Mock(no_deps=False), 'comfy_path': '', 'context': Mock(), 'manager_util': Mock(),
        'core': SimpleNamespace(is_valid_url=lambda spec: False), 'unified_manager': unified_manager,
    })['install']([node], None, None, False, False, None, exit_on_fail)


def test_install_that_fails_ends_with_1_with_exit_on_fail(capsys):
    with pytest.raises(SystemExit) as exit:
        install('no-such-nodepack', exit_on_fail=True)

    assert exit.value.code == 1
    assert "An error occurred while installing 'no-such-nodepack'" in capsys.readouterr().out


def test_install_that_fails_goes_on_without_exit_on_fail():
    install('no-such-nodepack', exit_on_fail=False)
