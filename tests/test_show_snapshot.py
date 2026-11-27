import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import rich
import typer
from rich import print
from rich.console import Console
from typing_extensions import Annotated

from legacy_html_testutil import PACKAGE, ROOT, load_functions

COMFYUI = 'f0123456789abcdef0123456789abcdef0123456'
PACK = 'abcdef0123456789abcdef0123456789abcdef01'
URL = 'https://gitlab.com/group/' + 'subgroup/' * 30 + 'pack'
SNAPSHOT = {
    'comfyui': COMFYUI,
    'git_custom_nodes': {URL: {'hash': PACK, 'disabled': False}},
    'cnr_custom_nodes': {'registry-pack': '1.0.0'},
    'file_custom_nodes': [{'filename': 'single.py', 'disabled': False}],
    'pips': {'torch': '2.0.0'},
}


def command(name):
    async def get_current_snapshot():
        return SNAPSHOT

    core = load_functions(PACKAGE / 'legacy/manager_core.py', {'print'}, {'rich': rich, 'Console': Console})
    return load_functions(ROOT / 'cm_cli/__main__.py', {name, 'show_snapshot'}, {
        'app': SimpleNamespace(command=lambda *args, **kwargs: lambda function: function),
        'typer': typer, 'Annotated': Annotated, 'asyncio': asyncio, 'json': json, 'print': print,
        'core': SimpleNamespace(get_current_snapshot=get_current_snapshot, print=core['print']), 'cmd_ctx': Mock(),
    })[name]


def test_show_snapshot_prints_the_current_snapshot(capsys):
    command('show')('snapshot', None, None, None)

    assert json.loads(capsys.readouterr().out) == SNAPSHOT


def test_simple_show_snapshot_prints_a_line_per_nodepack(capsys):
    command('simple_show')('snapshot', None, None, None)

    assert capsys.readouterr().out.splitlines() == [
        f'[{COMFYUI}] comfyui',
        f'[{PACK}] {URL}',
        '[                   N/A                  ] single.py',
    ]
