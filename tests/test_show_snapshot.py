import ast
import asyncio
import json
import pathlib
from types import SimpleNamespace
from unittest.mock import Mock

import typer
from rich import print
from typing_extensions import Annotated

from test_core_print import core_print

CM_CLI = pathlib.Path(__file__).resolve().parent.parent / 'cm-cli.py'

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

    found = [node for node in ast.parse(CM_CLI.read_text(encoding='utf-8')).body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (name, 'show_snapshot')]
    for node in found:
        node.decorator_list = []
    scope = {'typer': typer, 'Annotated': Annotated, 'asyncio': asyncio, 'json': json, 'print': print,
             'core': SimpleNamespace(get_current_snapshot=get_current_snapshot, print=core_print()), 'cmd_ctx': Mock()}
    exec(compile(ast.Module(body=found, type_ignores=[]), str(CM_CLI), 'exec'), scope)
    return scope[name]


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
