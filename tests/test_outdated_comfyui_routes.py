import ast
import asyncio
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from manager_test_utils import GLOB_DIR

SERVED = {
    ("POST", "/manager/queue/update_comfyui"), ("POST", "/manager/queue/start"), ("POST", "/manager/queue/reset"),
    ("GET", "/manager/queue/status"), ("GET", "/manager/version"), ("GET", "/manager/notice"),
    ("GET", "/manager/startup_alerts"),
}
OTHERS = [("GET", "/system_stats", "server"), ("POST", "/prompt", "server"), ("POST", "/a_pack/run", "a_pack.routes"),
          ("GET", "/manager/of_another_pack", "another_manager")]
PREFIXES = ["", "/api"]


def routes_of(path):
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        for decorator in getattr(node, "decorator_list", []):
            if isinstance(decorator, ast.Call) and ast.unparse(decorator.func).endswith(("routes.get", "routes.post")):
                found.append((decorator.func.attr.upper(), decorator.args[0].value, path.stem, node.name))
    return found


ROUTES = [route for path in sorted(GLOB_DIR.glob("*.py")) for route in routes_of(path)]
REQUESTS = [(prefix, method, path) for prefix in PREFIXES for method, path, _, _ in ROUTES]


def serve(has_system_user_api):
    ran = []

    def recording(method, path, module):
        async def handler(request):
            ran.append((method, path))
            return web.Response(text="served")

        handler.__module__ = module
        return handler

    handlers = {(module, name): recording(method, path, module) for method, path, module, name in ROUTES}

    source = (GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if getattr(node, "name", None) in ("security_403_response", "serve_only_comfyui_update")
             or isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "COMFYUI_UPDATE_HANDLERS"
             or isinstance(node, ast.If) and "middlewares" in ast.unparse(node)]
    middlewares = []
    namespace = {
        "web": web, "manager_migration": SimpleNamespace(has_system_user_api=lambda: has_system_user_api),
        "PromptServer": SimpleNamespace(instance=SimpleNamespace(app=SimpleNamespace(middlewares=middlewares))),
        "threading": SimpleNamespace(Thread=lambda target: SimpleNamespace(start=lambda: None)),
        **{name: handler for (module, name), handler in handlers.items() if module == "manager_server"},
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "manager_server.py", "exec"), namespace)

    app = web.Application(middlewares=middlewares)
    for prefix in PREFIXES:
        for method, path, module, name in ROUTES:
            app.router.add_route(method, prefix + path, handlers[module, name])
        for method, path, module in OTHERS:
            app.router.add_route(method, prefix + path, recording(method, path, module))
    return app, ran, middlewares == [namespace.get("serve_only_comfyui_update")]


def answers(has_system_user_api, requests):
    app, ran, added = serve(has_system_user_api)

    async def run():
        async with TestClient(TestServer(app)) as client:
            return [(response.status, await response.text())
                    for response in [await client.request(method, url) for method, url in requests]]

    return asyncio.run(run()), ran, added


def url(path):
    return path.replace("{node_name}", "a-pack")


OUTDATED = (403, '{"error": "comfyui_outdated"}')


def test_the_routes_are_found():
    found = {(method, path) for method, path, _, _ in ROUTES}

    assert len(ROUTES) >= 50
    assert SERVED <= found
    assert {("POST", "/manager/queue/install"), ("POST", "/manager/reboot"), ("GET", "/customnode/getlist"),
            ("POST", "/snapshot/restore"), ("GET", "/snapshot/getlist"), ("POST", "/manager/share"),
            ("GET", "/manager/get_matrix_auth"), ("GET", "/customnode/versions/{node_name}")} <= found


def test_every_route_is_in_a_file_that_the_middleware_knows():
    assert {module for _, _, module, _ in ROUTES} == {"manager_server", "share_3rdparty"}


@pytest.mark.parametrize("prefix, method, path", REQUESTS, ids=[f"{method} {prefix}{path}" for prefix, method, path in REQUESTS])
def test_on_an_older_comfyui_only_the_update_of_comfyui_is_served(prefix, method, path):
    (answer,), ran, added = answers(False, [(method, prefix + url(path))])

    assert added
    if (method, path) in SERVED:
        assert answer == (200, "served")
        assert ran == [(method, path)]
    else:
        assert answer == OUTDATED
        assert ran == []


def test_with_the_system_user_api_every_route_is_served():
    requests = [(method, prefix + url(path)) for prefix, method, path in REQUESTS]

    got, ran, added = answers(True, requests)

    assert not added
    assert got == [(200, "served")] * len(REQUESTS)
    assert len(ran) == len(REQUESTS)


@pytest.mark.parametrize("has_system_user_api", [True, False], ids=["with the API", "an older ComfyUI"])
@pytest.mark.parametrize("prefix", PREFIXES, ids=["without a prefix", "under /api"])
def test_routes_that_are_not_of_manager_are_served(prefix, has_system_user_api):
    got, ran, _ = answers(has_system_user_api, [(method, prefix + path) for method, path, _ in OTHERS])

    assert got == [(200, "served")] * len(OTHERS)
    assert ran == [(method, path) for method, path, _ in OTHERS]


@pytest.mark.parametrize("method, path, status", [
    ("GET", "/manager/no_such_route", 404), ("GET", "/no_such_route", 404), ("GET", "/api/api/manager/version", 404),
    ("GET", "/manager/queue/start", 405), ("POST", "/api/manager/version", 405), ("DELETE", "/manager/queue/update_comfyui", 405),
], ids=["an unknown route of that prefix", "an unknown route", "the prefix twice", "GET for a served POST",
        "POST for a served GET", "another method"])
def test_on_an_older_comfyui_an_unknown_request_is_answered_as_before(method, path, status):
    (answer,), ran, _ = answers(False, [(method, path)])

    assert answer[0] == status
    assert ran == []


@pytest.mark.parametrize("path, served_as", [
    ("/manager/queue/update_comfyui?x=1", "/manager/queue/update_comfyui"), ("/api/manager/queue/start?mode=cache", "/manager/queue/start"),
    ("/manager/queue/./start", "/manager/queue/start"),
    ("/manager/queue/update_comfyui/", None), ("/manager/queue/install?x=/manager/queue/start", None),
    ("/api/manager/queue/install?x=/api/manager/queue/start", None),
    ("/manager/queue//start", None), ("/manager/queue/update_all", None), ("/api/manager/queue/update", None),
    ("/manager/queue/install", None),
], ids=["a query", "a query on start", "a dot segment", "a trailing slash", "a served path in the query",
        "a served path in the query under /api", "a doubled slash", "update_all", "update", "install"])
def test_on_an_older_comfyui_a_path_is_served_only_as_a_route_that_updates_comfyui(path, served_as):
    (answer,), ran, _ = answers(False, [("POST", path)])

    if served_as:
        assert answer == (200, "served")
        assert ran == [("POST", served_as)]
    else:
        assert answer[0] in (403, 404)
        assert ran == []


@pytest.mark.parametrize("has_system_user_api", [True, False], ids=["with the API", "an older ComfyUI"])
def test_the_lists_are_fetched_at_the_start_only_with_the_system_user_api(has_system_user_api):
    source = (GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")
    statements = [node for node in ast.parse(source).body if isinstance(node, (ast.If, ast.Expr)) and "default_cache_update" in ast.unparse(node)]
    assert len(statements) == 1
    started = []
    exec(compile(ast.Module(body=statements, type_ignores=[]), "manager_server.py", "exec"), {
        "manager_migration": SimpleNamespace(has_system_user_api=lambda: has_system_user_api),
        "threading": SimpleNamespace(Thread=lambda target: SimpleNamespace(start=lambda: started.append(target))),
        "PromptServer": SimpleNamespace(instance=SimpleNamespace(app=SimpleNamespace(middlewares=[]))),
        "serve_only_comfyui_update": None,
    })

    assert len(started) == (1 if has_system_user_api else 0)
