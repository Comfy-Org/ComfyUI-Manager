"""Check that the notice route verifies the upstream TLS certificate.

Each case runs ``get_notice`` from manager_server.py in a child process. The
child points HTTPS_PROXY at a local CONNECT proxy that hands the tunnel to a
local HTTPS server presenting a "github.com" certificate from a throwaway CA.
That is a man-in-the-middle with an untrusted certificate unless the case trusts
the CA through SSL_CERT_FILE. A child is needed because aiohttp builds its
verified SSL context at import time.
"""
import ast
import asyncio
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path

import aiohttp
from aiohttp import web

from manager_test_utils import GLOB_DIR, load_manager_util

TESTS_DIR = Path(__file__).resolve().parent
NOTICE_PATH = "/ltdrdata/ltdrdata.github.io/wiki/News"
UNAVAILABLE = "Unable to retrieve Notice"
NOTICE_HTML = ('<div class="markdown-body"><p>Served by <b>the test server</b> '
               '<a href="https://example.com/notes">notes</a><script>x()</script></p></div>')

OPENSSL_CONFIG = """
[req]
distinguished_name = dn
prompt = no
[dn]
CN = ComfyUI-Manager notice test CA
[ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
[leaf]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:github.com
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid, issuer
"""


def load_get_notice(manager_util):
    source = (GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_notice")
    node.decorator_list = []  # exec needs no aiohttp routing context
    namespace = {
        "aiohttp": aiohttp, "web": web, "asyncio": asyncio, "logging": logging, "os": os, "re": re,
        "datetime": datetime, "manager_util": manager_util,
        "core": types.SimpleNamespace(version_str="V3.test"),
        "manager_migration": types.SimpleNamespace(startup_notices=[]),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<get_notice>", "exec"), namespace)
    return namespace["get_notice"]


async def _pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def _fetch_notice(certdir, bypass_ssl, proxy_reachable):
    app = web.Application()
    app.router.add_get(NOTICE_PATH, lambda request: web.Response(text=NOTICE_HTML, content_type="text/html"))
    runner = web.AppRunner(app)
    await runner.setup()
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(os.path.join(certdir, "leaf.pem"), os.path.join(certdir, "leaf.key"))
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_context)
    await site.start()
    upstream_port = runner.addresses[0][1]

    tunnels = []

    async def connect_proxy(reader, writer):
        tunnels.append((await reader.readuntil(b"\r\n\r\n")).split(b"\r\n", 1)[0].decode())
        upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", upstream_port)
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer), return_exceptions=True)

    proxy = await asyncio.start_server(connect_proxy, "127.0.0.1", 0)
    proxy_port = proxy.sockets[0].getsockname()[1]
    if not proxy_reachable:
        proxy.close()
        await proxy.wait_closed()
    os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{proxy_port}"

    manager_util = load_manager_util()
    manager_util.bypass_ssl = bypass_ssl
    response = await load_get_notice(manager_util)(None)
    proxy.close()
    await runner.cleanup()
    return {"status": response.status, "text": response.text, "tunnels": tunnels}


def run_child(certdir, bypass_ssl, proxy_reachable):
    print(json.dumps(asyncio.run(_fetch_notice(certdir, bypass_ssl, proxy_reachable))))


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI is needed to create test certificates")
class NoticeTlsVerificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.certdir = cls._tmp.name
        config = os.path.join(cls.certdir, "openssl.cnf")
        Path(config).write_text(OPENSSL_CONFIG)
        for args in (
            ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-config", config,
             "-extensions", "ca", "-keyout", "ca.key", "-out", "ca.pem"],
            ["req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=github.com", "-config", config,
             "-keyout", "leaf.key", "-out", "leaf.csr"],
            ["x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-set_serial", "1",
             "-days", "2", "-extfile", config, "-extensions", "leaf", "-out", "leaf.pem"],
        ):
            subprocess.run(["openssl", *args], cwd=cls.certdir, check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def fetch(self, bypass_ssl=False, trust_ca=False, proxy_reachable=True):
        env = {key: value for key, value in os.environ.items()
               if not key.lower().endswith("_proxy") and key not in ("SSL_CERT_FILE", "SSL_CERT_DIR")}
        env["__COMFYUI_DESKTOP_VERSION__"] = "test"
        if trust_ca:
            env["SSL_CERT_FILE"] = os.path.join(self.certdir, "ca.pem")
        code = "import sys, test_notice_tls; test_notice_tls.run_child(sys.argv[1], sys.argv[2] == 'True', sys.argv[3] == 'True')"
        proc = subprocess.run([sys.executable, "-c", code, self.certdir, str(bypass_ssl), str(proxy_reachable)],
                              cwd=TESTS_DIR, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, "get_notice raised instead of returning a response:\n" + proc.stderr[-2000:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def assert_notice_presented(self, result):
        self.assertEqual(result["status"], 200)
        self.assertIn("<b>the test server</b>", result["text"])
        self.assertIn('href="https://example.com/notes"', result["text"])
        self.assertNotIn("<script", result["text"])
        self.assertIn("Manager: V3.test", result["text"])
        self.assertEqual(result["tunnels"], ["CONNECT github.com:443 HTTP/1.1"])

    def test_untrusted_certificate_is_rejected_before_its_content_is_used(self):
        result = self.fetch()
        self.assertEqual(result["tunnels"], ["CONNECT github.com:443 HTTP/1.1"])
        self.assertEqual((result["status"], result["text"]), (200, UNAVAILABLE))

    def test_custom_ca_from_ssl_cert_file_is_trusted(self):
        self.assert_notice_presented(self.fetch(trust_ca=True))

    def test_bypass_ssl_setting_still_accepts_an_untrusted_certificate(self):
        self.assert_notice_presented(self.fetch(bypass_ssl=True))

    def test_unreachable_upstream_returns_the_unavailable_notice(self):
        result = self.fetch(trust_ca=True, proxy_reachable=False)
        self.assertEqual((result["status"], result["text"]), (200, UNAVAILABLE))


if __name__ == "__main__":
    unittest.main()
