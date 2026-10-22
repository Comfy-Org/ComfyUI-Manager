"""Check that the legacy notice endpoint verifies the upstream TLS certificate.

Each case runs ``get_notice`` from legacy/manager_server.py in a child process.
The child points HTTPS_PROXY at a local CONNECT proxy that hands the tunnel to
a local HTTPS server presenting a "github.com" certificate from a throwaway CA.
That is a man-in-the-middle with an untrusted certificate unless the case trusts
the CA through SSL_CERT_FILE. A child is needed because aiohttp builds its
verified SSL context at import time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import aiohttp
from aiohttp import web

import pytest

from legacy_html_testutil import PACKAGE, load_functions, load_renderer

TESTS_DIR = Path(__file__).resolve().parent
NOTICE_PATH = '/ltdrdata/ltdrdata.github.io/wiki/News'
UNAVAILABLE = 'Unable to retrieve Notice'
NOTICE_HTML = ('<div class="markdown-body"><p>Served by <b>the test server</b> '
               '<a href="https://example.com/notes">notes</a><script>x()</script></p></div>')
TUNNEL = 'CONNECT github.com:443 HTTP/1.1'

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


def load_get_notice(bypass_ssl):
    return load_functions(PACKAGE / 'legacy/manager_server.py', {'get_notice'}, {
        'routes': web.RouteTableDef(), 're': re, 'web': web, 'os': os, 'datetime': datetime,
        'aiohttp': aiohttp, 'asyncio': asyncio, 'logging': logging,
        'html_utils': load_renderer()['html_utils'],
        'manager_util': SimpleNamespace(bypass_ssl=bypass_ssl),
        'core': SimpleNamespace(version_str='4.test'),
    })['get_notice']


async def _pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def _fetch_notice(certdir, bypass_ssl, proxy_reachable):
    app = web.Application()
    app.router.add_get(NOTICE_PATH, lambda request: web.Response(text=NOTICE_HTML, content_type='text/html'))
    runner = web.AppRunner(app)
    await runner.setup()
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(os.path.join(certdir, 'leaf.pem'), os.path.join(certdir, 'leaf.key'))
    site = web.TCPSite(runner, '127.0.0.1', 0, ssl_context=server_context)
    await site.start()
    upstream_port = runner.addresses[0][1]

    tunnels = []

    async def connect_proxy(reader, writer):
        tunnels.append((await reader.readuntil(b'\r\n\r\n')).split(b'\r\n', 1)[0].decode())
        upstream_reader, upstream_writer = await asyncio.open_connection('127.0.0.1', upstream_port)
        writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
        await writer.drain()
        await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer), return_exceptions=True)

    proxy = await asyncio.start_server(connect_proxy, '127.0.0.1', 0)
    proxy_port = proxy.sockets[0].getsockname()[1]
    if not proxy_reachable:
        proxy.close()
        await proxy.wait_closed()
    os.environ['HTTPS_PROXY'] = f'http://127.0.0.1:{proxy_port}'

    response = await load_get_notice(bypass_ssl)(None)
    proxy.close()
    await runner.cleanup()
    return {'status': response.status, 'text': response.text, 'tunnels': tunnels}


def run_child(certdir, bypass_ssl, proxy_reachable):
    print(json.dumps(asyncio.run(_fetch_notice(certdir, bypass_ssl, proxy_reachable))))


@pytest.fixture(scope='module')
def certdir(tmp_path_factory):
    if shutil.which('openssl') is None:
        pytest.skip('openssl CLI is needed to create test certificates')
    path = tmp_path_factory.mktemp('notice-tls')
    config = path / 'openssl.cnf'
    config.write_text(OPENSSL_CONFIG)
    for args in (
        ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-config', str(config),
         '-extensions', 'ca', '-keyout', 'ca.key', '-out', 'ca.pem'],
        ['req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=github.com', '-config', str(config),
         '-keyout', 'leaf.key', '-out', 'leaf.csr'],
        ['x509', '-req', '-in', 'leaf.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-set_serial', '1',
         '-days', '2', '-extfile', str(config), '-extensions', 'leaf', '-out', 'leaf.pem'],
    ):
        subprocess.run(['openssl', *args], cwd=path, check=True, capture_output=True)
    return path


def _fetch(certdir, bypass_ssl=False, trust_ca=False, proxy_reachable=True):
    env = {key: value for key, value in os.environ.items()
           if not key.lower().endswith('_proxy') and key not in ('SSL_CERT_FILE', 'SSL_CERT_DIR')}
    env['__COMFYUI_DESKTOP_VERSION__'] = 'test'
    if trust_ca:
        env['SSL_CERT_FILE'] = str(certdir / 'ca.pem')
    code = "import sys, test_notice_tls; test_notice_tls.run_child(sys.argv[1], sys.argv[2] == 'True', sys.argv[3] == 'True')"
    proc = subprocess.run([sys.executable, '-c', code, str(certdir), str(bypass_ssl), str(proxy_reachable)],
                          cwd=TESTS_DIR, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, 'get_notice raised instead of returning a response:\n' + proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _assert_notice_presented(result):
    assert result['status'] == 200
    assert '<b>the test server</b>' in result['text']
    assert 'href="https://example.com/notes"' in result['text']
    assert '<script' not in result['text']
    assert 'Manager: 4.test' in result['text']
    assert result['tunnels'] == [TUNNEL]


def test_untrusted_certificate_is_rejected_before_its_content_is_used(certdir):
    result = _fetch(certdir)
    assert result['tunnels'] == [TUNNEL]
    assert (result['status'], result['text']) == (200, UNAVAILABLE)


def test_custom_ca_from_ssl_cert_file_is_trusted(certdir):
    _assert_notice_presented(_fetch(certdir, trust_ca=True))


def test_bypass_ssl_setting_still_accepts_an_untrusted_certificate(certdir):
    _assert_notice_presented(_fetch(certdir, bypass_ssl=True))


def test_unreachable_upstream_returns_the_unavailable_notice(certdir):
    result = _fetch(certdir, trust_ca=True, proxy_reachable=False)
    assert (result['status'], result['text']) == (200, UNAVAILABLE)
