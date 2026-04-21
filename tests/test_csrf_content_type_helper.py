"""AC verification for wi-001 (B2): Content-Type rejection helper.

Validates _reject_simple_form_content_type against the 5-item curl matrix
from the WI's acceptance criteria using aiohttp test client. The test
builds a minimal aiohttp app that mirrors the helper's wiring into a
no-body POST handler, so we exercise the real request.content_type
parsing path rather than a mock.

AC matrix:
  form-url     → 400
  multipart    → 400
  text/plain   → 400
  no-CT        → 200
  application/json → 200
"""
import asyncio
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


# Parse the helper from manager_server.py without importing it, to avoid
# pulling in the full ComfyUI/PromptServer stack. Note: we intentionally do
# NOT add the `glob/` directory to sys.path — the dir name would shadow
# Python's stdlib `glob` module and break pytest collection.
REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_helper():
    """Parse manager_server.py and execute only the helper definition."""
    import ast

    source = (REPO_ROOT / "glob" / "manager_server.py").read_text()
    tree = ast.parse(source)
    wanted = {"_SIMPLE_FORM_CONTENT_TYPES", "_reject_simple_form_content_type"}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            nodes.append(node)
    module = ast.Module(body=nodes, type_ignores=[])
    ns = {"web": web, "frozenset": frozenset}
    exec(compile(module, "manager_server_helpers", "exec"), ns)
    return ns["_reject_simple_form_content_type"]


_reject_simple_form_content_type = _load_helper()


async def _handler(request):
    resp = _reject_simple_form_content_type(request)
    if resp is not None:
        return resp
    return web.Response(status=200)


class ContentTypeRejectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.loop)
        app = web.Application()
        app.router.add_post("/noop", _handler)
        cls.server = TestServer(app, loop=cls.loop)
        cls.client = TestClient(cls.server, loop=cls.loop)
        cls.loop.run_until_complete(cls.client.start_server())

    @classmethod
    def tearDownClass(cls):
        cls.loop.run_until_complete(cls.client.close())
        cls.loop.close()

    def _post(self, headers):
        async def go():
            return await self.client.post("/noop", headers=headers, data=b"")

        return self.loop.run_until_complete(go())

    def test_form_urlencoded_rejected(self):
        r = self._post({"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status, 400)

    def test_multipart_form_data_rejected(self):
        # aiohttp requires a boundary for multipart; helper should still reject
        # based on the primary mimetype.
        r = self._post({"Content-Type": "multipart/form-data; boundary=xyz"})
        self.assertEqual(r.status, 400)

    def test_text_plain_rejected(self):
        r = self._post({"Content-Type": "text/plain"})
        self.assertEqual(r.status, 400)

    def test_no_content_type_allowed(self):
        # Explicitly strip Content-Type: aiohttp client may add a default,
        # so we use a raw request to ensure absence is tested.
        async def go():
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.client.make_url("/noop"),
                    data=None,
                    skip_auto_headers=["Content-Type"],
                ) as resp:
                    return resp.status

        status = self.loop.run_until_complete(go())
        self.assertEqual(status, 200)

    def test_application_json_allowed(self):
        r = self._post({"Content-Type": "application/json"})
        self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
