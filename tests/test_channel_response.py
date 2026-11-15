"""A channel response that is not JSON is not cached and does not empty the list (#3480).

The channel is a local HTTP server. `get_data_by_mode` is the real function from
manager_core.py, run against a temporary cache directory and a temporary bundled list.
"""
import ast
import asyncio
import json
import os

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from manager_test_utils import GLOB_DIR, load_manager_util

FILENAME = "model-list.json"
BUNDLED = {"models": [{"name": "bundled with the Manager"}]}
SERVED = {"models": [{"name": "served by the channel"}]}
NOT_JSON = [
    pytest.param(200, "<html><body>Access blocked</body></html>", id="block page"),
    pytest.param(404, "404: Not Found", id="missing file"),
]


@pytest.fixture(autouse=True)
def reach_the_channel_directly(monkeypatch):
    # get_data() honors the proxy variables of the environment.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")


def load_get_data_by_mode(manager_util, channel_url):
    source = (GLOB_DIR / "manager_core.py").read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_data_by_mode"]
    assert len(nodes) == 1
    config = {"channel_url": channel_url, "network_mode": "public"}
    namespace = {"os": os, "json": json, "manager_util": manager_util,
                 "get_config": lambda: config, "get_channel_dict": lambda: {}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "manager_core.py", "exec"), namespace)
    return namespace["get_data_by_mode"]


class Channel:
    def __init__(self):
        self.requests = 0
        self.serve(200, json.dumps(SERVED))

    def serve(self, status, text):
        self.status, self.text = status, text

    async def handle(self, request):
        self.requests += 1
        return web.Response(status=self.status, text=self.text)


def run(tmp_path, scenario):
    async def main():
        channel = Channel()
        app = web.Application()
        app.router.add_get("/main/{name}", channel.handle)
        server = TestServer(app)
        await server.start_server()
        try:
            manager_util = load_manager_util()
            manager_util.comfyui_manager_path = str(tmp_path / "manager")
            manager_util.cache_dir = str(tmp_path / "cache")
            os.makedirs(manager_util.comfyui_manager_path)
            os.makedirs(manager_util.cache_dir)
            with open(os.path.join(manager_util.comfyui_manager_path, FILENAME), "w", encoding="utf-8") as f:
                json.dump(BUNDLED, f)
            channel_url = str(server.make_url("/main"))
            return await scenario(channel, manager_util, load_get_data_by_mode(manager_util, channel_url), channel_url)
        finally:
            await server.close()

    return asyncio.run(main())


@pytest.mark.parametrize("status, text", NOT_JSON)
def test_response_that_is_not_json_is_an_error(tmp_path, status, text):
    async def scenario(channel, manager_util, get_data_by_mode, channel_url):
        channel.serve(status, text)
        with pytest.raises(json.JSONDecodeError):
            await manager_util.get_data(f"{channel_url}/{FILENAME}")

    run(tmp_path, scenario)


@pytest.mark.parametrize("status, text", NOT_JSON)
def test_bundled_list_is_used_and_nothing_is_cached(tmp_path, status, text):
    async def scenario(channel, manager_util, get_data_by_mode, channel_url):
        channel.serve(status, text)
        return await get_data_by_mode("cache", FILENAME), os.listdir(manager_util.cache_dir), channel.requests

    result, cached, requests = run(tmp_path, scenario)

    assert requests == 1
    assert result == BUNDLED
    assert cached == []


@pytest.mark.parametrize("status, text", NOT_JSON)
def test_channel_is_read_again_once_it_answers_with_the_list(tmp_path, status, text):
    async def scenario(channel, manager_util, get_data_by_mode, channel_url):
        channel.serve(status, text)
        await get_data_by_mode("cache", FILENAME)
        channel.serve(200, json.dumps(SERVED))
        return await get_data_by_mode("cache", FILENAME)

    assert run(tmp_path, scenario) == SERVED


def test_list_from_the_channel_is_cached(tmp_path):
    async def scenario(channel, manager_util, get_data_by_mode, channel_url):
        first = await get_data_by_mode("cache", FILENAME)
        second = await get_data_by_mode("cache", FILENAME)
        return first, second, channel.requests

    assert run(tmp_path, scenario) == (SERVED, SERVED, 1)


def test_unreadable_local_file_still_reads_as_empty(tmp_path):
    async def scenario(channel, manager_util, get_data_by_mode, channel_url):
        path = os.path.join(manager_util.comfyui_manager_path, "broken.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{")
        return await manager_util.get_data(path)

    assert run(tmp_path, scenario) == {}
