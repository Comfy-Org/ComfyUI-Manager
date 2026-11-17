"""Both servers store only a `db_mode` or an `update_policy` that Manager knows.

Each case runs the real handler of `legacy/manager_server.py` or of
`glob/manager_server.py` with the functions and the lists of values it uses;
`core` holds a configuration in memory and counts how often it is written.
"""
import ast
import asyncio
import importlib.util
import json
import logging
from types import SimpleNamespace

import pytest
import yaml
from aiohttp import web

from legacy_html_testutil import PACKAGE

DB_MODE = ("set_db_mode_api", "db_mode", ["cache", "channel", "local", "remote"])
UPDATE_POLICY = ("set_update_policy_api", "update_policy", ["stable", "stable-comfyui", "nightly", "nightly-comfyui"])
SETTINGS = [DB_MODE, UPDATE_POLICY]
HANDLERS = {"set_db_mode_api", "set_update_policy_api"}
SETTERS = {"set_db_mode", "set_update_policy"}
BEFORE = "the value before the request"


def take(path, names, namespace):
    """Define the functions named, and the lists of known values, of the file in the namespace."""
    nodes = [node for node in ast.parse(path.read_text(encoding="utf-8")).body
             if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names)
             or (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "").startswith("ALLOWED_"))]
    exec(compile(ast.Module(nodes, []), str(path), "exec"), namespace)
    return namespace


@pytest.fixture(params=["legacy", "glob"])
def post(request):
    def post(handler, key, body, allowed=True):
        """The status the handler answers, the stored value and how often the configuration was written."""
        config, written = {key: BEFORE}, []
        core = SimpleNamespace(get_config=lambda: config, write_config=lambda: written.append(dict(config)))
        namespace = {"web": web, "logging": logging, "json": json, "core": core, "SECURITY_MESSAGE_MIDDLE": "",
                     "routes": SimpleNamespace(post=lambda path: lambda function: function)}
        if request.param == "legacy":
            namespace["is_allowed_security_level"] = lambda level: allowed
            take(PACKAGE / "legacy/manager_server.py", HANDLERS | SETTERS, namespace)
        else:
            setters = take(PACKAGE / "glob/utils/environment_utils.py", SETTERS, {"core": core})
            namespace["environment_utils"] = SimpleNamespace(**{name: setters[name] for name in SETTERS})
            namespace["security_utils"] = SimpleNamespace(is_allowed_security_level=lambda level: allowed)
            take(PACKAGE / "glob/manager_server.py", HANDLERS, namespace)

        async def read():
            return json.loads(body)

        return asyncio.run(namespace[handler](SimpleNamespace(json=read))).status, config[key], len(written)

    return post


@pytest.mark.parametrize("handler, key, value", [(handler, key, value) for handler, key, values in SETTINGS for value in values])
def test_known_value_is_stored(post, handler, key, value):
    assert post(handler, key, json.dumps({"value": value})) == (200, value, 1)


@pytest.mark.parametrize("handler, key, values", SETTINGS)
@pytest.mark.parametrize("value", ['"no-such-value"', '""', '"CACHE"', '"STABLE"', "7", "null", '["cache"]', '["stable"]'])
def test_unknown_value_is_refused(post, handler, key, values, value):
    assert post(handler, key, '{"value": %s}' % value) == (400, BEFORE, 0)


@pytest.mark.parametrize("handler, key, values", SETTINGS)
@pytest.mark.parametrize("body", ["{}", "not json", "[]", '"cache"', "7", "null"])
def test_request_without_a_value_is_refused(post, handler, key, values, body):
    assert post(handler, key, body) == (400, BEFORE, 0)


@pytest.mark.parametrize("handler, key, values", SETTINGS)
def test_request_is_refused_by_the_security_level(post, handler, key, values):
    assert post(handler, key, json.dumps({"value": values[0]}), allowed=False) == (403, BEFORE, 0)


def test_enums_hold_the_values_the_servers_use():
    spec = importlib.util.spec_from_file_location("_enums", PACKAGE / "common/enums.py")
    enums = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(enums)
    known = take(PACKAGE / "glob/utils/environment_utils.py", set(), {})
    openapi = yaml.safe_load((PACKAGE.parent / "openapi.yaml").read_text(encoding="utf-8"))

    assert sorted(mode.value for mode in enums.DBMode) == sorted(known["ALLOWED_DB_MODES"])
    assert sorted(level.value for level in enums.SecurityLevel) == sorted(openapi["components"]["schemas"]["SecurityLevel"]["enum"])
