import asyncio
import io
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import typer
from rich.console import Console
from typing_extensions import Annotated

from legacy_html_testutil import ROOT, load_functions
from test_snapshot_restore_pins import core, manager  # noqa: F401


@pytest.fixture
def show(manager, tmp_path):  # noqa: F811
    manager.get_custom_nodes = AsyncMock(return_value={
        'listed-pack': {'title': 'Listed Pack', 'author': 'someone', 'files': ['https://github.com/someone/listed-pack']},
    })
    manager.cnr_map['registry-pack'] = {'id': 'registry-pack', 'name': 'Registry Pack', 'publisher': {'name': 'someone'},
                                        'latest_version': {'version': '1.0.0'}}
    manager.active_nodes['registry-pack'] = ('1.0.0', str(tmp_path / 'registry-pack'))
    manager.unknown_active_nodes['listed-pack'] = ('https://github.com/someone/listed-pack', str(tmp_path / 'listed-pack'))
    manager.unknown_active_nodes['git-pack'] = ('https://example.invalid/git-pack', str(tmp_path / 'git-pack'))
    manager.unknown_inactive_nodes['old-git-pack'] = ('https://example.invalid/old-git-pack', str(tmp_path / '.disabled/old-git-pack'))

    def show(name, kind):
        out = io.StringIO()
        load_functions(ROOT / 'cm_cli/__main__.py', {name, 'show_list'}, {
            'app': SimpleNamespace(command=lambda *args, **kwargs: lambda function: function),
            'typer': typer, 'Annotated': Annotated, 'asyncio': asyncio, 'os': os,
            'print': Console(file=out, width=1000, color_system=None).print, 'cmd_ctx': Mock(), 'unified_manager': manager,
        })[name](kind, None, None, None)
        return [' '.join(line.split()) for line in out.getvalue().splitlines()]

    return show


def test_simple_show_lists_every_installed_nodepack(show):
    assert show('simple_show', 'enabled') == ['Registry Pack@1.0.0', 'Listed Pack@unknown', 'git-pack@unknown']
    assert show('simple_show', 'disabled') == ['old-git-pack@unknown']
    assert show('simple_show', 'installed') == ['Registry Pack@1.0.0', 'Listed Pack@unknown', 'git-pack@unknown', 'old-git-pack@unknown']


def test_show_names_a_git_nodepack_that_the_lists_do_not_know_by_its_id(show):
    assert show('show', 'installed')[2:] == [
        '[ ENABLED ] git-pack git-pack (author: N/A ) [UNKNOWN]',
        '[ DISABLED ] old-git-pack old-git-pack (author: N/A ) [UNKNOWN]',
    ]
