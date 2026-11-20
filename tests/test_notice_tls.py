"""The notice route verifies the upstream certificate and survives a failed fetch (#3302).

Each case runs the real `get_notice` in a child process. The child points HTTPS_PROXY at a
local CONNECT proxy that hands the tunnel for github.com:443 to a local HTTPS server, which
holds a "github.com" certificate from a throwaway CA: a machine in the middle, unless the
case trusts that CA through SSL_CERT_FILE. Nothing leaves 127.0.0.1. A child is needed
because aiohttp builds its verifying SSL context when it is imported.

The last cases fetch a list through `get_data`, the same way and from a channel without
TLS. Both fetches are also held to raising no deprecation warning from a line of the
Manager (#2281).
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
from types import SimpleNamespace
from warnings import catch_warnings, simplefilter

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from manager_test_utils import GLOB_DIR, load_manager_util

NOTICE_PATH = "/ltdrdata/ltdrdata.github.io/wiki/News"
NOTICE_HTML = ('<div class="markdown-body"><p>Served by <b>the test server</b> '
               '<a href="https://example.com/notes">notes</a><script>x()</script></p></div>')
UNAVAILABLE = "Unable to retrieve Notice"
TUNNEL = "CONNECT github.com:443 HTTP/1.1"
OTHER_HOST = "notice-test.example"
LIST_PATH = "/a-channel/model-list.json"
LIST = {"models": [{"name": "served by the test server"}]}
MANAGER_FILES = ("manager_server.py", "manager_util.py")

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
"""
LEAF_EXTENSIONS = """
[leaf]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:{host}
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid, issuer
"""


def load_get_notice(bypass_ssl):
    source = (GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_notice"]
    assert len(nodes) == 1
    manager_util = load_manager_util()
    manager_util.bypass_ssl = bypass_ssl
    namespace = {
        "routes": web.RouteTableDef(), "aiohttp": aiohttp, "asyncio": asyncio, "logging": logging,
        "re": re, "web": web, "os": os, "manager_util": manager_util,
        "core": SimpleNamespace(version_str="3.test"),
        "manager_migration": SimpleNamespace(startup_notices=[]),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "manager_server.py", "exec"), namespace)
    return namespace["get_notice"]


def load_get_data(bypass_ssl):
    manager_util = load_manager_util()
    manager_util.bypass_ssl = bypass_ssl
    return manager_util.get_data


def manager_deprecations(caught):
    return [f"{os.path.basename(w.filename)}: {w.message}" for w in caught
            if issubclass(w.category, DeprecationWarning) and os.path.basename(w.filename) in MANAGER_FILES]


async def _pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def fetch_in_child(certdir, host, bypass_ssl, proxy_mode, what):
    """Child process: what `get_notice` answers and logs, or what `get_data` returns, and the tunnels
    the proxy was asked for."""
    async def notice_page(request):
        return web.Response(text=NOTICE_HTML, content_type="text/html")

    async def list_file(request):
        return web.json_response(LIST)

    upstream = web.Application()
    upstream.router.add_get(NOTICE_PATH, notice_page)
    upstream.router.add_get(LIST_PATH, list_file)
    runner = web.AppRunner(upstream)
    await runner.setup()
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(os.path.join(certdir, host + ".pem"), os.path.join(certdir, host + ".key"))
    await web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_context).start()
    upstream_port = runner.addresses[0][1]

    tunnels = []
    answered = asyncio.Event()

    async def connect_proxy(reader, writer):
        tunnels.append((await reader.readuntil(b"\r\n\r\n")).split(b"\r\n", 1)[0].decode())
        if proxy_mode == "bad_gateway":
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        if proxy_mode == "silent":
            await answered.wait()
        if proxy_mode != "tunnel":
            writer.close()
            return
        upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", upstream_port)
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer), return_exceptions=True)

    proxy = await asyncio.start_server(connect_proxy, "127.0.0.1", 0)
    proxy_port = proxy.sockets[0].getsockname()[1]
    if proxy_mode == "closed":
        proxy.close()
        await proxy.wait_closed()
    if proxy_mode == "silent":
        aiohttp.client.DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=0.5)
    os.environ["HTTPS_PROXY"] = f"http://127.0.0.1:{proxy_port}"

    # Only what get_notice logs: aiohttp warns through its own loggers, for example about .netrc.
    warnings = []
    handler = logging.Handler(logging.WARNING)
    handler.emit = lambda record: record.name == "root" and warnings.append(record.getMessage())
    logging.getLogger().addHandler(handler)

    with catch_warnings(record=True) as caught:
        simplefilter("always")
        if what == "list":
            try:
                result = {"list": await load_get_data(bypass_ssl)(f"https://github.com{LIST_PATH}", silent=True)}
            except aiohttp.ClientError as e:
                result = {"error": type(e).__name__}
        else:
            response = await load_get_notice(bypass_ssl)(None)
            result = {"status": response.status, "text": response.text}
    answered.set()
    proxy.close()
    await runner.cleanup()
    return {**result, "tunnels": tunnels, "warnings": warnings, "deprecations": manager_deprecations(caught)}


@pytest.fixture(scope="module")
def certdir(tmp_path_factory):
    if shutil.which("openssl") is None:
        pytest.skip("the openssl command is needed to create the test certificates")
    path = tmp_path_factory.mktemp("notice-tls")
    config = path / "openssl.cnf"
    config.write_text(OPENSSL_CONFIG, encoding="utf-8")

    def openssl(*args):
        subprocess.run(["openssl", *args], cwd=path, check=True, capture_output=True)

    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-config", str(config),
            "-extensions", "ca", "-keyout", "ca.key", "-out", "ca.pem")
    for serial, host in enumerate(("github.com", OTHER_HOST), start=1):
        (path / f"{host}.ext").write_text(LEAF_EXTENSIONS.format(host=host), encoding="utf-8")
        openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={host}", "-config", str(config),
                "-keyout", f"{host}.key", "-out", f"{host}.csr")
        openssl("x509", "-req", "-in", f"{host}.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
                "-set_serial", str(serial), "-days", "2", "-extfile", f"{host}.ext", "-extensions", "leaf",
                "-out", f"{host}.pem")
    return path


def fetch(certdir, host="github.com", trust_ca=False, bypass_ssl=False, proxy_mode="tunnel", what="notice"):
    env = {key: value for key, value in os.environ.items()
           if not key.lower().endswith("_proxy") and key not in ("SSL_CERT_FILE", "SSL_CERT_DIR")}
    env["__COMFYUI_DESKTOP_VERSION__"] = "test"
    if trust_ca:
        env["SSL_CERT_FILE"] = str(certdir / "ca.pem")
    child = subprocess.run(
        [sys.executable, __file__, str(certdir), host, str(int(bypass_ssl)), proxy_mode, what],
        env=env, capture_output=True, text=True, timeout=60)
    assert child.returncode == 0, "the fetch raised instead of answering:\n" + child.stderr[-2000:]
    return json.loads(child.stdout.strip().splitlines()[-1])


def assert_unavailable(result, *cause):
    assert (result["status"], result["text"]) == (200, UNAVAILABLE)
    assert len(result["warnings"]) == 1
    for text in cause:
        assert text in result["warnings"][0]


def test_untrusted_certificate_is_rejected_before_its_content_is_used(certdir):
    result = fetch(certdir)

    assert result["tunnels"] == [TUNNEL]
    assert_unavailable(result, "ClientConnectorCertificateError", "CERTIFICATE_VERIFY_FAILED")


def test_bypass_ssl_accepts_the_untrusted_certificate(certdir):
    result = fetch(certdir, bypass_ssl=True)

    assert result["tunnels"] == [TUNNEL]
    assert result["status"] == 200
    assert "<b>the test server</b>" in result["text"]
    assert result["warnings"] == []
    assert result["deprecations"] == []


def test_trusted_certificate_for_another_host_is_rejected(certdir):
    result = fetch(certdir, host=OTHER_HOST, trust_ca=True)

    assert result["tunnels"] == [TUNNEL]
    assert_unavailable(result, "ClientConnectorCertificateError", "not valid for 'github.com'")


def test_ca_trusted_through_ssl_cert_file_is_accepted(certdir):
    result = fetch(certdir, trust_ca=True)

    assert result["tunnels"] == [TUNNEL]
    assert result["status"] == 200
    assert "<b>the test server</b>" in result["text"]
    assert 'href="https://example.com/notes"' in result["text"]
    assert "<script" not in result["text"]
    assert result["warnings"] == []
    assert "Manager: 3.test" in result["text"]


@pytest.mark.parametrize("proxy_mode, error", [
    ("closed", "ClientProxyConnectionError"),
    ("bad_gateway", "ClientHttpProxyError"),
    ("silent", "TimeoutError"),
], ids=["proxy_closed", "proxy_answers_502", "proxy_silent"])
def test_failed_fetch_answers_with_the_unavailable_notice(certdir, proxy_mode, error):
    result = fetch(certdir, trust_ca=True, proxy_mode=proxy_mode)

    assert_unavailable(result, error)


def test_list_from_an_untrusted_certificate_is_rejected(certdir):
    result = fetch(certdir, what="list")

    assert result["tunnels"] == [TUNNEL]
    assert result["error"] == "ClientConnectorCertificateError"


def test_list_from_a_trusted_certificate_for_another_host_is_rejected(certdir):
    result = fetch(certdir, host=OTHER_HOST, trust_ca=True, what="list")

    assert result["tunnels"] == [TUNNEL]
    assert result["error"] == "ClientConnectorCertificateError"


def test_list_from_a_ca_trusted_through_ssl_cert_file_is_accepted(certdir):
    result = fetch(certdir, trust_ca=True, what="list")

    assert result["list"] == LIST
    assert result["deprecations"] == []


def test_bypass_ssl_accepts_the_list_from_the_untrusted_certificate(certdir):
    result = fetch(certdir, bypass_ssl=True, what="list")

    assert result["tunnels"] == [TUNNEL]
    assert result["list"] == LIST
    assert result["deprecations"] == []


@pytest.mark.parametrize("bypass_ssl", [False, True], ids=["certificates checked", "bypass_ssl"])
def test_list_from_a_channel_without_tls_raises_no_deprecation_warning(bypass_ssl, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")

    async def fetch_list():
        async def list_file(request):
            return web.json_response(LIST)

        channel = web.Application()
        channel.router.add_get(LIST_PATH, list_file)
        server = TestServer(channel)
        await server.start_server()
        try:
            with catch_warnings(record=True) as caught:
                simplefilter("always")
                fetched = await load_get_data(bypass_ssl)(str(server.make_url(LIST_PATH)), silent=True)
            return fetched, manager_deprecations(caught)
        finally:
            await server.close()

    assert asyncio.run(fetch_list()) == (LIST, [])


if __name__ == "__main__":
    print(json.dumps(asyncio.run(fetch_in_child(sys.argv[1], sys.argv[2], sys.argv[3] == "1", sys.argv[4], sys.argv[5]))))
