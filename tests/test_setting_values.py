"""The server stores only a `db_mode`, an `update_policy` or a `component_policy` that the Manager knows.

Each case runs the real handler of `glob/manager_server.py` with the functions
and the lists of values it uses; `core` holds a configuration in memory and
counts how often it is written.
"""
import ast
import asyncio
import json
from types import SimpleNamespace

import pytest
from aiohttp import web

from manager_test_utils import GLOB_DIR

SETTINGS = [
    ("set_db_mode_handler", "db_mode", ["cache", "local", "remote"]),
    ("set_update_policy_handler", "update_policy", ["stable-comfyui", "nightly-comfyui"]),
    ("set_component_policy_handler", "component_policy", ["workflow", "higher", "mine"]),
]
NAMES = {handler for handler, key, values in SETTINGS} | {"set_db_mode", "set_update_policy", "set_component_policy"}
BEFORE = "the value before the request"


def post(handler, key, body):
    """The status the handler answers, the stored value and how often the configuration was written."""
    source = (GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in NAMES)
             or (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "").startswith("ALLOWED_"))]
    config, written = {key: BEFORE}, []
    namespace = {
        "web": web, "routes": SimpleNamespace(post=lambda path: lambda function: function),
        "core": SimpleNamespace(get_config=lambda: config, write_config=lambda: written.append(dict(config))),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<setting handlers>", "exec"), namespace)

    async def read():
        return json.loads(body)

    return asyncio.run(namespace[handler](SimpleNamespace(json=read))).status, config[key], len(written)


@pytest.mark.parametrize("handler, key, value", [(handler, key, value) for handler, key, values in SETTINGS for value in values])
def test_known_value_is_stored(handler, key, value):
    assert post(handler, key, json.dumps({"value": value})) == (200, value, 1)


@pytest.mark.parametrize("handler, key, values", SETTINGS)
@pytest.mark.parametrize("value", ['"no-such-value"', '""', '"CACHE"', "7", "null", '["cache"]'])
def test_unknown_value_is_refused(handler, key, values, value):
    assert post(handler, key, '{"value": %s}' % value) == (400, BEFORE, 0)


@pytest.mark.parametrize("handler, key, values", SETTINGS)
@pytest.mark.parametrize("body", ["{}", "[]", '"cache"', "7", "null"])
def test_request_without_a_value_is_refused(handler, key, values, body):
    assert post(handler, key, body) == (400, BEFORE, 0)
