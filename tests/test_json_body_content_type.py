import ast
import asyncio
import re
from types import SimpleNamespace
from typing import Optional

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from legacy_html_testutil import PACKAGE

JS_DIR = PACKAGE / "js"
FILES = sorted(str(path.relative_to(PACKAGE)) for server in ("glob", "legacy") for path in (PACKAGE / server).rglob("*.py"))
CHECK = "reject_non_json_post"

NOT_GET = ("routes.post", "routes.put", "routes.patch", "routes.delete")
BODYLESS = {"/v2/manager/queue/start", "/v2/manager/queue/reset", "/v2/manager/queue/update_all", "/v2/manager/queue/update_comfyui",
            "/v2/snapshot/save", "/v2/snapshot/remove", "/v2/snapshot/restore", "/v2/manager/reboot"}

NOT_JSON = [
    None, "text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded",
    "multipart/form-data; boundary=x", "application/octet-stream", "text/json", "application/jsonp",
    "application/json-patch+json", "application/ld+json", "",
]
JSON = ["application/json", "application/json; charset=utf-8", "application/json;charset=UTF-8", "Application/JSON"]


def functions(filename):
    tree = ast.parse((PACKAGE / filename).read_text(encoding="utf-8"))
    return {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def routes_that_change_something():
    found = []
    for filename in FILES:
        for node in functions(filename).values():
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and ast.unparse(decorator.func).endswith(NOT_GET):
                    found.append((filename, decorator.args[0].value, node.name))
    return found


ROUTES = routes_that_change_something()


def load_check():
    node = functions("common/manager_security.py").get(CHECK)
    assert node is not None, "manager_security.py has no " + CHECK
    namespace = {"web": web, "Optional": Optional}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "manager_security.py", "exec"), namespace)
    return namespace[CHECK]


def load_handler(filename, name):
    routes = web.RouteTableDef()
    security = SimpleNamespace(**{CHECK: load_check()})
    namespace = {"web": web, "routes": routes, "PromptServer": SimpleNamespace(instance=SimpleNamespace(routes=routes)),
                 "security_utils": security, "manager_security": security}
    exec(compile(ast.Module(body=[functions(filename)[name]], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


def test_the_routes_are_found():
    routes = {route for _, route, _ in ROUTES}

    assert len(ROUTES) >= 38
    assert {"/v2/manager/queue/task", "/v2/manager/queue/batch", "/v2/customnode/install/git_url", "/v2/manager/db_mode",
            "/v2/comfyui_manager/comfyui_switch_version", "/v2/manager/share"} <= routes
    for server in ("glob", "legacy"):
        assert BODYLESS | {"/v2/manager/share_option"} <= {route for filename, route, _ in ROUTES if filename.startswith(server + "/")}


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "application/octet-stream"])
@pytest.mark.parametrize("filename, route, name", ROUTES, ids=["%s %s" % (f.split("/")[0], route) for f, route, _ in ROUTES])
def test_a_route_refuses_a_request_that_is_not_json_before_anything_else(filename, route, name, content_type):
    read = []

    async def read_json():
        read.append(True)
        return {}

    request = SimpleNamespace(content_type=content_type, json=read_json)
    try:
        response = load_handler(filename, name)(request)
        if asyncio.iscoroutine(response):
            response = asyncio.run(response)
    except NameError as error:
        pytest.fail("the handler went on to use `%s`" % error.name)

    assert response.status == 400
    assert "application/json" in response.text
    assert read == []


def answer(content_type):
    check = load_check()

    async def handler(request):
        return check(request) or web.Response(status=200)

    async def post():
        app = web.Application()
        app.router.add_post("/", handler)
        async with TestClient(TestServer(app)) as client:
            headers = {} if content_type is None else {"Content-Type": content_type}
            async with client.post("/", data=b'{"value": "x"}', headers=headers, skip_auto_headers=["Content-Type"]) as response:
                return response.status

    return asyncio.run(post())


@pytest.mark.parametrize("content_type", NOT_JSON, ids=[repr(c) for c in NOT_JSON])
def test_a_content_type_that_is_not_json_is_refused(content_type):
    assert answer(content_type) == 400


@pytest.mark.parametrize("content_type", JSON)
def test_json_is_accepted_with_any_parameters_and_in_any_case(content_type):
    assert answer(content_type) == 200


def past_literal(source, pos):
    if source.startswith("//", pos):
        return source.index("\n", pos)
    if source.startswith("/*", pos):
        return source.index("*/", pos) + 2
    quote = source[pos]
    if quote not in "\"'`":
        return pos
    pos += 1
    while source[pos] != quote:
        pos += 2 if source[pos] == "\\" else 1
    return pos + 1


def script_calls():
    found = []
    for path in sorted(JS_DIR.glob("*.js")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\bfetch(?:Api|Data)\(", source):
            pos, depth, commas = match.end(), 1, []
            while depth:
                skipped = past_literal(source, pos)
                if skipped != pos:
                    pos = skipped
                    continue
                depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(source[pos], 0)
                if source[pos] == "," and depth == 1:
                    commas.append(pos)
                pos += 1
            options = source[commas[0] + 1:[*commas, pos - 1][1]].strip() if commas else ""
            found.append((path.name, source.count("\n", 0, match.start()) + 1, source[match.start():pos], options))
    return found


PASSES_ITS_OPTIONS_ON = [("common.js", "fetchData(route, options)"), ("common.js", "fetchApi(route, options)")]


def test_the_options_of_a_call_are_written_where_it_is_made():
    assert [(name, call) for name, _, call, options in script_calls()
            if options and not options.startswith("{")] == PASSES_ITS_OPTIONS_ON


def calls_that_post():
    return [(name, line, call) for name, line, call, _ in script_calls()
            if re.search(r"""['"]?\bbody\b['"]?\s*[:,}]|\bmethod\s*:\s*['"](?!GET)""", call)]


CALLS = calls_that_post()


def test_the_calls_are_found():
    assert len(CALLS) >= 24


@pytest.mark.parametrize("name, line, call", CALLS, ids=["%s:%d" % (name, line) for name, line, _ in CALLS])
def test_a_script_that_posts_names_json(name, line, call):
    assert re.search(r"""['"]Content-Type['"]\s*:\s*['"]application/json['"]""", call), call
