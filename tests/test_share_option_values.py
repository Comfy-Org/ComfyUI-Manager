import ast
import asyncio
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

from manager_test_utils import GLOB_DIR

MENU = Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js")) / "comfyui-manager.js"
CHOICES = ["all", "none", "youml", "matrix"]
ROUTE = "/manager/share_option"


@pytest.fixture
def route():
    source = (GLOB_DIR / "share_3rdparty.py").read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.AsyncFunctionDef) and node.name in ("share_option", "set_share_option")
             or isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "SHARE_OPTIONS"]
    assert len(nodes) == 3
    check = next(node for node in ast.parse((GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")).body
                 if isinstance(node, ast.FunctionDef) and node.name == "_reject_non_json_content_type")
    routes = web.RouteTableDef()
    config, written, read = {"share_option": "all"}, [], []
    namespace = {
        "PromptServer": SimpleNamespace(instance=SimpleNamespace(routes=routes)), "web": web, "json": json,
        "core": SimpleNamespace(get_config=lambda: config, write_config=lambda: written.append(dict(config))),
    }
    exec(compile(ast.Module(body=[check, *nodes], type_ignores=[]), "share_3rdparty.py", "exec"), namespace)

    def get(query):
        response = asyncio.run(namespace["share_option"](SimpleNamespace(rel_url=SimpleNamespace(query=query))))
        return response.status, response.text

    def post(body, content_type="application/json"):
        async def read_json():
            read.append(True)
            return json.loads(body)

        return asyncio.run(namespace["set_share_option"](SimpleNamespace(content_type=content_type, json=read_json))).status

    return SimpleNamespace(get=get, post=post, config=config, written=written, read=read, choices=namespace["SHARE_OPTIONS"],
                           methods=sorted((entry.method, entry.path) for entry in routes))


def test_the_choices_are_those_of_the_share_menu(route):
    menu = re.search(r"const share_options = \[(.*?)\];", MENU.read_text(encoding="utf-8"), re.S).group(1)

    assert sorted(route.choices) == sorted(re.findall(r"\['(\w+)',", menu)) == sorted(CHOICES)


def test_the_option_is_read_with_get_and_saved_with_post(route):
    assert route.methods == [("GET", ROUTE), ("POST", ROUTE)]


@pytest.mark.parametrize("saved", CHOICES)
@pytest.mark.parametrize("value", CHOICES)
def test_a_choice_of_the_menu_is_saved(route, saved, value):
    route.config["share_option"] = saved

    assert route.post(json.dumps({"value": value})) == 200
    assert route.written == [{"share_option": value}]


@pytest.mark.parametrize("value", [
    "", " ", "ALL", "All", "all ", " all", "all,none", "none\n", "openart", "comfyworkflows", "true", "<b>all</b>", "all\x00",
    "a" * 5000, None, 0, 1, True, ["all"], {"all": "none"},
], ids=repr)
@pytest.mark.parametrize("saved", ["all", "none"])
def test_any_other_value_is_refused_and_nothing_is_saved(route, saved, value):
    route.config["share_option"] = saved

    assert route.post(json.dumps({"value": value})) == 400
    assert route.config == {"share_option": saved}
    assert route.written == []


@pytest.mark.parametrize("body", ['{}', '{"other": "none"}', '[]', '["value"]', '"none"', 'null', '1', '', '{"value": "none"', 'value=none',
                                  b'{"value": "\xff"}', b'\xff\xfe'], ids=repr)
def test_a_body_without_a_value_is_refused_and_nothing_is_saved(route, body):
    assert route.post(body) == 400
    assert route.config == {"share_option": "all"}
    assert route.written == []


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data",
                                          "application/octet-stream"])
def test_a_value_that_is_not_sent_as_json_is_refused_before_the_body_is_read(route, content_type):
    assert route.post(json.dumps({"value": "none"}), content_type) == 400
    assert route.read == []
    assert route.written == []


@pytest.mark.parametrize("saved", [*CHOICES, "openart", ""], ids=lambda saved: saved or "empty")
def test_get_answers_the_saved_option_as_it_is(route, saved):
    route.config["share_option"] = saved

    assert route.get({}) == (200, saved)
    assert route.written == []


@pytest.mark.parametrize("value", [*CHOICES, "openart"])
def test_get_saves_nothing_whatever_it_is_given(route, value):
    assert route.get({"value": value}) == (200, "all")
    assert route.config == {"share_option": "all"}
    assert route.written == []


def test_the_menu_saves_the_option_with_a_json_post():
    source = MENU.read_text(encoding="utf-8")

    assert "share_option?value=" not in source
    assert re.search(r"fetchApi\(\s*'/manager/share_option'\s*,\s*\{[^;]*?\bmethod:\s*'POST'[^;]*?\bbody:\s*JSON\.stringify\(\{\s*value\s*\}\)",
                     source)
