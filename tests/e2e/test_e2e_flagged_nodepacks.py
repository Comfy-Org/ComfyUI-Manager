"""Real ComfyUI HTTP/queue/install tests with a local CNR service and harmless ZIPs.

Run with E2E_ROOT pointing to the existing ComfyUI + venv fixture. Each server
uses an isolated base directory; no installed nodes or user config are changed.
"""

import asyncio
import ast
import io
import json
import os
import socket
import subprocess
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest
import requests


E2E_ROOT = Path(os.environ.get('E2E_ROOT', '/nonexistent'))
REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (E2E_ROOT / 'venv/bin/python').is_file(), reason='E2E_ROOT is required',
)
PACKS = ['fixture-active', 'fixture-flagged', 'fixture-pending', 'fixture-banned', 'fixture-latest', 'fixture-switch', 'fixture-reinstall', 'fixture-update', 'fixture-snapshot']


@pytest.fixture(scope='module')
def registry():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            calls.append(parsed.path + ('?' + parsed.query if parsed.query else ''))
            parts = parsed.path.strip('/').split('/')
            version = parse_qs(parsed.query).get('version', ['2.0.0'])[0]
            node = parts[1] if len(parts) > 1 else ''
            base = f'http://127.0.0.1:{self.server.server_port}'

            def metadata(node, version):
                status = {'1.0.0': 'Active', '1.1.0': 'Active', '2.0.0': 'Flagged', '3.0.0': 'Pending'}[version]
                return {'id': f'{node}-{version}', 'node_id': node, 'version': version,
                        'status': 'NodeVersionStatus' + status, 'dependencies': [],
                        'downloadUrl': f'{base}/zip/{node}/{version}'}

            status = 200
            if parts[0] == 'zip':
                node, version = parts[1:]
                archive = io.BytesIO()
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('__init__.py', 'NODE_CLASS_MAPPINGS = {}\n')
                    z.writestr('pyproject.toml', f'[project]\nname = "{node}"\nversion = "{version}"\n')
                    z.writestr('install.py', 'from pathlib import Path\n'
                               f'Path("installed.txt").write_text("{version}")\n')
                body = archive.getvalue()
            elif parsed.path == '/nodes':
                body = json.dumps({'nodes': [
                    {'id': name, 'name': name, 'description': '', 'status': 'NodeStatusActive',
                     'repository': f'https://example.invalid/{name}',
                     'publisher': {'id': 'fixture', 'name': 'Fixture'},
                     'latest_version': metadata(name, '2.0.0')}
                    for name in PACKS], 'totalPages': 1}).encode()
            elif len(parts) == 3 and parts[0] == 'nodes' and parts[2] == 'install':
                if node == 'fixture-banned':
                    status, body = 404, b'{"message":"Not found"}'
                else:
                    body = json.dumps(metadata(node, version)).encode()
            else:
                status, body = 404, b'{}'
            self.send_response(status)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Type', 'application/zip' if parts[0] == 'zip' else 'application/json')
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield SimpleNamespace(url=f'http://127.0.0.1:{server.server_port}', calls=calls)
    server.shutdown()
    server.server_close()
    thread.join()


# Redirect only the external Registry in both ComfyUI and its restore subprocess.
REGISTRY_BOOTSTRAP = '''
import asyncio, json, os, sys, urllib.request
sys.path.insert(0, os.environ['CM_E2E_MANAGER_GLOB'])
import manager_core, cnr_utils, manager_util
cnr_utils.base_url = os.environ['CM_E2E_REGISTRY']
with urllib.request.urlopen(cnr_utils.base_url + '/nodes') as response:
    manager_util.save_to_cache(cnr_utils.base_url + '/nodes', json.load(response))
asyncio.run(manager_core.unified_manager.reload('cache', dont_wait=False))
manager_core.unified_manager.custom_node_map_cache[(manager_core.normalize_channel('default'), 'cache')] = manager_core.NormalizedKeyDict()
'''
BOOTSTRAP = '''
import os, runpy, sys
sys.argv = [os.environ['CM_E2E_MAIN'], *sys.argv[1:]]
import comfy.options
comfy.options.enable_args_parsing()
''' + REGISTRY_BOOTSTRAP + "\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"


@contextmanager
def running_server(root, listen, override, registry, security='normal'):
    custom_nodes = root / 'custom_nodes'
    custom_nodes.mkdir(exist_ok=True)
    mount = custom_nodes / 'comfyui-manager'
    if not mount.exists():
        mount.symlink_to(REPO_ROOT, target_is_directory=True)
    config_dir = root / 'user/__manager'
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / 'config.ini').write_text(
        '[default]\nnetwork_mode = offline\nuse_uv = false\n'
        f'security_level = {security}\nallow_flagged_nodepack_install = {override}\n'
    )
    # cm-cli.py inherits this test-only IO redirection from its real parent.
    hook = root / 'sitecustomize.py'
    hook.write_text("import os, sys\nif os.path.basename(sys.argv[0]) == 'cm-cli.py':\n"
                    "    from comfy.cli_args import args\n"
                    "    args.base_directory = os.environ['CM_E2E_BASE']\n"
                    + '\n'.join('    ' + line for line in REGISTRY_BOOTSTRAP.splitlines()))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = dict(os.environ, PYTHONUNBUFFERED='1',
               PYTHONPATH=os.pathsep.join([str(root), str(E2E_ROOT / 'comfyui')]),
               COMFYUI_PATH=str(E2E_ROOT / 'comfyui'), COMFYUI_FOLDERS_BASE_PATH=str(root),
               CM_E2E_BASE=str(root), CM_E2E_MAIN=str(E2E_ROOT / 'comfyui/main.py'),
               CM_E2E_MANAGER_GLOB=str(REPO_ROOT / 'glob'), CM_E2E_REGISTRY=registry.url)
    command = [str(E2E_ROOT / 'venv/bin/python'), '-c', BOOTSTRAP, '--cpu',
               '--base-directory', str(root), '--listen', listen, '--port', str(port),
               '--database-url', f'sqlite:///{root / "comfyui.db"}']
    log_path = root / ('server-' + uuid.uuid4().hex + '.log')
    with log_path.open('w') as log:
        process = subprocess.Popen(command, env=env, cwd=E2E_ROOT / 'comfyui', stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                assert process.poll() is None, log_path.read_text()[-6000:]
                try:
                    if requests.get(base + '/system_stats', timeout=1).status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(.2)
            else:
                pytest.fail(log_path.read_text()[-6000:])
            assert requests.get(base + '/manager/version', timeout=5).status_code == 200, log_path.read_text()[-6000:]
            assert 'PRESTARTUP FAILED' not in log_path.read_text(), log_path.read_text()
            yield SimpleNamespace(root=root, base=base, listen=listen, override=override,
                                  security=security, registry=registry, log=log_path, env=env)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize('operation', ['install', 'restore-snapshot'])
def test_direct_cli_installs_flagged_without_server_options(tmp_path, registry, operation):
    with running_server(tmp_path, '0.0.0.0', False, registry) as server:
        env = server.env
    command = [str(E2E_ROOT / 'venv/bin/python'), str(REPO_ROOT / 'cm-cli.py'), operation]
    if operation == 'install':
        command += ['fixture-flagged@2.0.0', '--mode', 'cache']
    else:
        snapshot = tmp_path / 'direct-snapshot.json'
        snapshot.write_text(json.dumps({'cnr_custom_nodes': {'fixture-flagged': '2.0.0'},
                                       'git_custom_nodes': {}, 'file_custom_nodes': []}))
        command.append(str(snapshot))
    command += ['--user-directory', str(tmp_path / 'user')]
    before = len(registry.calls)

    result = subprocess.run(command, env=env, cwd=E2E_ROOT / 'comfyui',
                            capture_output=True, text=True, timeout=60)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    installed = tmp_path / 'custom_nodes/fixture-flagged'
    assert 'version = "2.0.0"' in (installed / 'pyproject.toml').read_text(), output
    if operation == 'install':
        assert (installed / 'installed.txt').read_text() == '2.0.0', output
    assert sum('/install' in call for call in registry.calls[before:]) == 1
    assert 'Installation of this flagged CNR version is blocked' not in output


@pytest.fixture(scope='module', params=[
    ('127.0.0.1', False, 'normal'), ('0.0.0.0', False, 'normal'),
    ('0.0.0.0', True, 'normal'), ('0.0.0.0', True, 'strong'),
    ('127.0.0.1', False, 'strong'),
], ids=lambda row: '-'.join(map(str, row)))
def comfy_server(request, tmp_path_factory, registry):
    listen, override, security = request.param
    root = tmp_path_factory.mktemp('flagged-v3')
    with running_server(root, listen, override, registry, security) as server:
        yield server


def install(server, node, version, operation='install'):
    async def request_and_wait():
        ui_id = uuid.uuid4().hex
        params = {'id': node, 'version': '1.0.0', 'selected_version': version,
                  'mode': 'cache', 'channel': 'default', 'ui_id': ui_id,
                  'repository': 'https://example.invalid/fixture'}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40)) as session:
            # Subscribe first: a fast worker can emit completion before POST returns.
            async with session.ws_connect(server.base + '/ws?clientId=' + ui_id) as ws:
                async with session.post(server.base + '/manager/queue/' + operation, json=params) as response:
                    if response.status != 200:
                        return {'http': response.status, 'message': await response.text()}
                async with session.post(server.base + '/manager/queue/start') as response:
                    response.raise_for_status()
                while True:
                    event = await ws.receive_json(timeout=30)
                    data = event.get('data', {})
                    if event.get('type') == 'cm-queue-status' and data.get('status') == 'done':
                        if ui_id in data.get('nodepack_result', {}):
                            return {'http': 200, 'message': data['nodepack_result'][ui_id]}
    return asyncio.run(request_and_wait())


def assert_terminal_guidance(log):
    for detail in ('--listen 127.0.0.1', '--listen ::1', '0.0.0.0', '[default]',
                   'allow_flagged_nodepack_install = true', 'config.ini',
                   'trusted private network', 'Restart ComfyUI'):
        assert detail in log


def assert_flagged_denial(result, log):
    assert result['message'] == ('This action is not allowed by the current security configuration. '
                                 'See the terminal for details.'), result
    assert_terminal_guidance(log)


@pytest.mark.parametrize('node,version,flagged', [
    ('fixture-active', '1.0.0', False), ('fixture-flagged', '2.0.0', True),
    ('fixture-pending', '3.0.0', False), ('fixture-banned', '1.0.0', False),
    ('fixture-latest', 'latest', True),
])
def test_install_policy(comfy_server, node, version, flagged):
    server = comfy_server
    log_before = len(server.log.read_text())
    before = len(server.registry.calls)
    result = install(server, node, version)
    calls = server.registry.calls[before:]
    strong = server.security == 'strong'
    allowed = not strong and node != 'fixture-banned' and (
        not flagged or server.override or server.listen == '127.0.0.1')
    marker = server.root / 'custom_nodes' / node / 'installed.txt'
    assert marker.exists() is allowed, (result, server.log.read_text()[-6000:])
    assert sum('/install' in call for call in calls) == (0 if strong else 1), calls
    assert any(call.startswith('/zip/') for call in calls) is allowed
    if allowed:
        assert result['message'] == 'success', result
        assert marker.read_text() == ('2.0.0' if version == 'latest' else version)
    elif strong:
        assert result['http'] == 403, result
    elif flagged:
        assert_flagged_denial(result, server.log.read_text()[log_before:])


@pytest.mark.parametrize('operation', ['install', 'reinstall', 'update'])
def test_existing_pack_policy(comfy_server, operation):
    server = comfy_server
    if server.security == 'strong':
        pytest.skip('Existing-pack transitions require an installed pack')
    node = {'install': 'fixture-switch', 'reinstall': 'fixture-reinstall', 'update': 'fixture-update'}[operation]
    assert install(server, node, '1.0.0')['message'] == 'success'
    marker = server.root / 'custom_nodes' / node / 'installed.txt'
    log_before = len(server.log.read_text())
    before = len(server.registry.calls)
    result = install(server, node, '2.0.0', operation)
    calls = server.registry.calls[before:]
    allowed = server.override or server.listen == '127.0.0.1'
    assert sum('/install' in call for call in calls) == 1, calls
    if allowed:
        assert result['message'] == 'success', result
        if operation == 'reinstall':
            assert marker.read_text() == '2.0.0', server.log.read_text()[-6000:]
        else:
            assert marker.read_text() == '1.0.0'
            assert 'NodeVersionStatusFlagged' in (server.root / 'user/__manager/startup-scripts/install-scripts.txt').read_text()
    else:
        assert_flagged_denial(result, server.log.read_text()[log_before:])
        assert marker.read_text() == '1.0.0'
    assert any(call.startswith('/zip/') for call in calls) is (allowed and operation == 'reinstall')


@pytest.mark.parametrize('restart_listen,restart_override,allowed', [
    ('0.0.0.0', False, False), ('0.0.0.0', True, True), ('127.0.0.1', False, True),
])
@pytest.mark.parametrize('stored_status', [True, False])
def test_restart_uses_current_policy(tmp_path, registry, restart_listen, restart_override, allowed, stored_status):
    with running_server(tmp_path, '127.0.0.1', False, registry) as server:
        assert install(server, 'fixture-switch', '1.0.0')['message'] == 'success'
        assert install(server, 'fixture-switch', '2.0.0')['message'] == 'success'
    if not stored_status:
        reservation = tmp_path / 'user/__manager/startup-scripts/install-scripts.txt'
        record = ast.literal_eval(reservation.read_text().strip())
        assert record[1] == '#LAZY-CNR-SWITCH-SCRIPT'
        assert len(record) == 9
        reservation.write_text(repr(record[:8]) + '\n')
    marker = tmp_path / 'custom_nodes/fixture-switch/installed.txt'
    original = (marker.read_bytes(), marker.stat().st_mtime_ns)
    before = len(registry.calls)
    with running_server(tmp_path, restart_listen, restart_override, registry) as server:
        calls = registry.calls[before:]
        assert not any('/install' in call for call in calls), calls
        assert any(call.startswith('/zip/') for call in calls) is allowed
        if allowed:
            assert marker.read_text() == '2.0.0', server.log.read_text()[-6000:]
        else:
            assert (marker.read_bytes(), marker.stat().st_mtime_ns) == original
            if stored_status:
                assert_terminal_guidance(server.log.read_text())
            else:
                assert 'stored Registry status is missing' in server.log.read_text()
                assert 'Request the installation again' in server.log.read_text()


@pytest.mark.parametrize('surface,payload,flag', [
    ('git_url', {'url': 'https://example.invalid/fixture'}, 'allow_git_url_install'),
    ('pip', {'packages': 'fixture-do-not-install'}, 'allow_pip_install'),
])
def test_other_install_flags_remain_required(comfy_server, surface, payload, flag):
    server = comfy_server
    before = len(server.registry.calls)
    response = requests.post(server.base + '/customnode/install/' + surface, json=payload, timeout=10)
    assert response.status_code == 403, response.text
    assert response.json() == {'error': flag}
    assert server.registry.calls[before:] == []


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('version,listen,override,allowed', [
    ('1.1.0', '0.0.0.0', False, True),
    ('2.0.0', '0.0.0.0', False, False),
    ('2.0.0', '0.0.0.0', True, True),
    ('2.0.0', '127.0.0.1', False, True),
])
def test_scheduled_snapshot_inherits_parent_policy(tmp_path, registry, existing, version, listen, override, allowed):
    installed = tmp_path / 'custom_nodes/fixture-snapshot'
    marker = installed / 'installed.txt'
    reservation = tmp_path / 'user/__manager/startup-scripts/restore-snapshot.json'
    with running_server(tmp_path, '127.0.0.1', False, registry) as server:
        if existing:
            assert install(server, 'fixture-snapshot', '1.0.0')['message'] == 'success'
            assert marker.read_text() == '1.0.0'
            original = (marker.read_bytes(), marker.stat().st_mtime_ns)
        snapshot = tmp_path / 'user/__manager/snapshots/flagged-policy.json'
        snapshot.write_text(json.dumps({'cnr_custom_nodes': {'fixture-snapshot': version},
                                        'git_custom_nodes': {}, 'file_custom_nodes': []}))
        before = len(registry.calls)
        response = requests.post(server.base + '/snapshot/restore',
                                 json={'target': snapshot.stem}, timeout=10)
        assert response.status_code == 200, response.text
        assert reservation.read_bytes() == snapshot.read_bytes()
        assert registry.calls[before:] == []
        if existing:
            assert (marker.read_bytes(), marker.stat().st_mtime_ns) == original
        else:
            assert not installed.exists()

    before = len(registry.calls)
    with running_server(tmp_path, listen, override, registry) as server:
        log = server.log.read_text()
        calls = registry.calls[before:]
        assert 'Restore snapshot done.' in log, log[-6000:]
        assert 'Restore snapshot failed.' not in log, log[-6000:]
        assert 'Error in sitecustomize' not in log, log[-6000:]
        assert not reservation.exists()
        assert sum('/install' in call for call in calls) == 1, (calls, log[-6000:])
        assert any(call.startswith('/zip/') for call in calls) is allowed
        if allowed:
            assert f'version = "{version}"' in (installed / 'pyproject.toml').read_text(), log[-6000:]
            assert 'allow_flagged_nodepack_install' not in log
        else:
            assert_terminal_guidance(log)
            if existing:
                assert (marker.read_bytes(), marker.stat().st_mtime_ns) == original
                assert '1.0.0' in (installed / 'pyproject.toml').read_text()
            else:
                assert not installed.exists()
