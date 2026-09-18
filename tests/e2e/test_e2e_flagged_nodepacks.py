"""Real ComfyUI HTTP/queue/install tests with a local CNR service and harmless ZIPs.

Run with E2E_ROOT pointing to the existing ComfyUI + venv fixture. Each server
uses an isolated base directory; no installed nodes or user config are changed.
"""

import ast
import configparser
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

import pytest
import requests


E2E_ROOT = Path(os.environ.get('E2E_ROOT', '/nonexistent'))
REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (E2E_ROOT / 'venv/bin/python').is_file(), reason='E2E_ROOT is required',
)
PACKS = ['fixture-active', 'fixture-flagged', 'fixture-pending', 'fixture-banned',
         'fixture-latest', 'fixture-switch', 'fixture-update', 'fixture-reinstall', 'fixture-snapshot']


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


REGISTRY_BOOTSTRAP = '''
import json, os, urllib.request
from comfyui_manager.common import cnr_utils, manager_util
cnr_utils.base_url = os.environ['CM_E2E_REGISTRY']
with urllib.request.urlopen(cnr_utils.base_url + '/nodes') as response:
    manager_util.save_to_cache(cnr_utils.base_url + '/nodes', json.load(response))
'''
BOOTSTRAP = '''
import os, runpy, sys
sys.argv = [os.environ['CM_E2E_MAIN'], *sys.argv[1:]]
import comfy.options
comfy.options.enable_args_parsing()
''' + REGISTRY_BOOTSTRAP + "\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
RESTORE_BOOTSTRAP = '''
import os
from comfy.cli_args import args
args.base_directory = os.environ['CM_E2E_BASE']
''' + REGISTRY_BOOTSTRAP + '''
from comfyui_manager.legacy import manager_core as core
core.unified_manager.custom_node_map_cache[(core.normalize_channel('default'), 'cache')] = core.NormalizedKeyDict()
'''


def prepare_environment(root, override, security, registry):
    (root / 'custom_nodes').mkdir(exist_ok=True)
    config_dir = root / 'user/__manager'
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / 'config.ini').write_text(
        '[default]\nnetwork_mode = offline\nuse_uv = false\n'
        f'security_level = {security}\nallow_flagged_nodepack_install = {override}\n'
    )
    # The real restore subprocess inherits the same isolated Registry and paths.
    (root / 'sitecustomize.py').write_text(
        "import sys\nif sys.argv[0] == '-m' and 'cm_cli' in sys.orig_argv:\n"
        + '\n'.join('    ' + line for line in RESTORE_BOOTSTRAP.splitlines())
    )
    env = dict(os.environ, PYTHONUNBUFFERED='1',
               PYTHONPATH=os.pathsep.join([str(root), str(REPO_ROOT), str(E2E_ROOT / 'comfyui')]),
               COMFYUI_PATH=str(E2E_ROOT / 'comfyui'), COMFYUI_FOLDERS_BASE_PATH=str(root),
               CM_E2E_BASE=str(root),
               CM_E2E_MAIN=str(E2E_ROOT / 'comfyui/main.py'), CM_E2E_REGISTRY=registry.url)
    return env


@contextmanager
def running_server(root, tree, listen, override, security, registry):
    env = prepare_environment(root, override, security, registry)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    command = [str(E2E_ROOT / 'venv/bin/python'), '-c', BOOTSTRAP,
               '--cpu', '--enable-manager', '--base-directory', str(root),
               '--listen', listen, '--port', str(port),
               '--database-url', f'sqlite:///{root / "comfyui.db"}']
    if tree == 'legacy':
        command.append('--enable-manager-legacy-ui')
    log_path = root / 'server.log'
    with log_path.open('w') as log:
        process = subprocess.Popen(command, env=env, cwd=E2E_ROOT / 'comfyui', stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                assert process.poll() is None, log_path.read_text()
                try:
                    if requests.get(base + '/system_stats', timeout=1).status_code == 200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(.2)
            else:
                pytest.fail('ComfyUI did not start:\n' + log_path.read_text())
            yield SimpleNamespace(root=root, tree=tree, base=base, listen=listen,
                                  override=override, security=security, registry=registry,
                                  process=process, command=command, env=env)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture(scope='module', params=[
    (tree, listen, override, security)
    for tree in ('legacy', 'glob')
    for listen, override, security in [
        ('127.0.0.1', False, 'normal'),
        ('0.0.0.0', False, 'normal'),
        ('0.0.0.0', True, 'normal'),
        ('0.0.0.0', True, 'strong'),
        ('127.0.0.1', False, 'strong'),
    ]
], ids=lambda row: '-'.join(map(str, row)))
def comfy_server(request, tmp_path_factory, registry):
    tree, listen, override, security = request.param
    root = tmp_path_factory.mktemp('flagged-' + tree)
    with running_server(root, tree, listen, override, security, registry) as server:
        yield server


def install(server, node, version, operation='install'):
    ui_id = uuid.uuid4().hex
    params = {'id': node, 'version': '1.0.0', 'selected_version': version,
              'mode': 'cache', 'channel': 'default', 'ui_id': ui_id,
              'repository': 'https://example.invalid/fixture'}
    if server.tree == 'legacy':
        response = requests.post(server.base + '/v2/manager/queue/batch',
                                 json={'batch_id': ui_id, operation: [params]}, timeout=10)
        response.raise_for_status()
        if response.json()['failed']:
            return response.json()
        query = {'id': ui_id}
    else:
        if operation == 'update':
            params = {'node_name': node, 'node_ver': '1.0.0'}
        response = requests.post(server.base + '/v2/manager/queue/task', json={
            'ui_id': ui_id, 'client_id': 'flagged-e2e', 'kind': operation, 'params': params,
        }, timeout=10)
        response.raise_for_status()
        requests.post(server.base + '/v2/manager/queue/start', timeout=10).raise_for_status()
        query = {'ui_id': ui_id}
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = requests.get(server.base + '/v2/manager/queue/history', params=query, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if server.tree == 'legacy' or data.get('history'):
                return data
        time.sleep(.1)
    pytest.fail('Install did not complete:\n' + (server.root / 'server.log').read_text()[-6000:])


def assert_terminal_guidance(log):
    for detail in ('--listen 127.0.0.1', '--listen ::1', '0.0.0.0', '[default]',
                   'allow_flagged_nodepack_install = true', 'config.ini',
                   'trusted private network', 'Restart ComfyUI'):
        assert detail in log


def assert_flagged_denial(result, log):
    message = json.dumps(result)
    assert ('This action is not allowed by the current security configuration. '
            'See the terminal for details.') in message, result
    assert 'allow_flagged_nodepack_install' not in message, result
    assert '--listen' not in message, result
    assert_terminal_guidance(log)


@pytest.mark.parametrize('node,version', [
    ('fixture-active', '1.0.0'), ('fixture-flagged', '2.0.0'),
    ('fixture-pending', '3.0.0'), ('fixture-banned', '1.0.0'),
    ('fixture-latest', 'latest'),
])
def test_install_policy(comfy_server, node, version):
    server = comfy_server
    log_before = len((server.root / 'server.log').read_text())
    before = len(server.registry.calls)
    result = install(server, node, version)
    calls = server.registry.calls[before:]
    strong = server.security == 'strong'
    flagged = version in ('2.0.0', 'latest')
    allowed = not strong and node != 'fixture-banned' and (
        not flagged or server.override or server.listen == '127.0.0.1')
    marker = server.root / 'custom_nodes' / node / 'installed.txt'
    assert marker.exists() is allowed, (result, (server.root / 'server.log').read_text()[-6000:])
    assert sum('/install' in call for call in calls) == (0 if strong else 1), calls
    assert any(call.startswith('/zip/') for call in calls) is allowed, calls
    if allowed:
        assert marker.read_text() == ('2.0.0' if version == 'latest' else version)
        if server.tree == 'legacy':
            assert list(result['nodepack_result'].values()) == ['success'], result
        else:
            assert result['history']['result'] == 'success', result
    elif flagged and not strong:
        assert_flagged_denial(result, (server.root / 'server.log').read_text()[log_before:])


@pytest.mark.parametrize('operation', ['install', 'update'])
def test_flagged_transition_preserves_active_version(comfy_server, operation):
    server = comfy_server
    if server.security == 'strong':
        pytest.skip('No installed version in strong mode')
    # Keep this state separate from test_install_policy, regardless of test order.
    node = 'fixture-switch' if operation == 'install' else 'fixture-update'
    marker = server.root / 'custom_nodes' / node / 'installed.txt'
    install(server, node, '1.0.0')
    log_before = len((server.root / 'server.log').read_text())
    before = len(server.registry.calls)
    result = install(server, node, '2.0.0', operation)
    calls = server.registry.calls[before:]
    assert sum('/install' in call for call in calls) == 1
    assert not any(call.startswith('/zip/') for call in calls)
    assert marker.read_text() == '1.0.0'
    reserved = server.root / 'user/__manager/startup-scripts/install-scripts.txt'
    if server.override or server.listen == '127.0.0.1':
        assert '#LAZY-CNR-SWITCH-SCRIPT' in reserved.read_text()
        if server.tree == 'legacy':
            assert list(result['nodepack_result'].values()) == ['success'], result
        else:
            assert result['history']['result'] == 'success', result
    else:
        assert not reserved.exists()
        assert_flagged_denial(result, (server.root / 'server.log').read_text()[log_before:])


@pytest.mark.parametrize('listen,override', [
    ('127.0.0.1', False), ('0.0.0.0', False), ('0.0.0.0', True),
])
@pytest.mark.parametrize('version', ['1.0.0', '2.0.0'])
def test_legacy_reinstall_preserves_denied_pack_and_runs_allowed_script(
        tmp_path, registry, listen, override, version):
    with running_server(tmp_path, 'legacy', listen, override, 'normal', registry) as server:
        node = 'fixture-reinstall'
        install(server, node, '1.0.0')
        marker = tmp_path / 'custom_nodes' / node / 'installed.txt'
        assert marker.read_text() == '1.0.0'
        original = (marker.read_bytes(), marker.stat().st_mtime_ns)
        stale = marker.parent / 'stale.txt'
        stale.write_text('removed only by an allowed reinstall')
        before = len(registry.calls)
        log_before = len((server.root / 'server.log').read_text())

        result = install(server, node, version, 'reinstall')

        calls = registry.calls[before:]
        allowed = version == '1.0.0' or override or listen == '127.0.0.1'
        assert sum('/install' in call for call in calls) == 1, calls
        assert any(call.startswith('/zip/') for call in calls) is allowed, calls
        if allowed:
            assert list(result['nodepack_result'].values()) == ['success'], result
            assert marker.read_text() == version, result
            assert not stale.exists()
        else:
            assert_flagged_denial(result, (server.root / 'server.log').read_text()[log_before:])
            assert marker.exists(), 'Rejected reinstall removed the existing pack'
            assert (marker.read_bytes(), marker.stat().st_mtime_ns) == original
            assert stale.exists()


def test_nonlocal_override_does_not_allow_nightly(comfy_server):
    server = comfy_server
    if server.listen == '127.0.0.1':
        pytest.skip('This regression checks the non-local Git gate')
    log_path = server.root / 'server.log'
    log_before = len(log_path.read_text())
    before = len(server.registry.calls)
    result = install(server, 'fixture-nightly', 'nightly')
    # A missing node or a failed clone must not count as a security rejection.
    if server.tree == 'legacy':
        assert result['failed'] == ['fixture-nightly'], result
    else:
        assert result['history']['result'] == 'failed', result
    expected_reason = ('normal or below' if server.security == 'strong' and server.tree == 'legacy'
                       else 'network_mode must be set to `personal_cloud`')
    assert expected_reason in log_path.read_text()[log_before:], result
    assert not (server.root / 'custom_nodes/fixture-nightly').exists()
    assert not any('/install' in call or call.startswith('/zip/')
                   for call in server.registry.calls[before:])


@pytest.mark.parametrize('tree', ['legacy', 'glob'])
@pytest.mark.parametrize('listen,override,restart_listen,restart_override,allowed', [
    ('127.0.0.1', False, '0.0.0.0', False, False),
    ('0.0.0.0', True, '0.0.0.0', False, False),
    ('127.0.0.1', False, '127.0.0.1', False, True),
    ('0.0.0.0', True, '0.0.0.0', True, True),
])
@pytest.mark.parametrize('stored_status', [True, False])
def test_restart_applies_current_policy_without_registry_query(
        tree, listen, override, restart_listen, restart_override, allowed, stored_status, tmp_path, registry):
    with running_server(tmp_path, tree, listen, override, 'normal', registry) as server:
        marker = server.root / 'custom_nodes/fixture-active/installed.txt'
        install(server, 'fixture-active', '1.0.0')
        reserved = server.root / 'user/__manager/startup-scripts/install-scripts.txt'
        install(server, 'fixture-active', '2.0.0')
        assert 'NodeVersionStatusFlagged' in reserved.read_text()
        original_marker = (marker.read_bytes(), marker.stat().st_mtime_ns)
        server.process.terminate()
        server.process.wait(timeout=10)
        if not stored_status:
            record = ast.literal_eval(reserved.read_text().strip())
            assert record[1] == '#LAZY-CNR-SWITCH-SCRIPT'
            assert len(record) == 9
            reserved.write_text(repr(record[:8]) + '\n')

        config_path = server.root / 'user/__manager/config.ini'
        config = configparser.ConfigParser()
        config.read(config_path)
        config['default']['allow_flagged_nodepack_install'] = str(restart_override)
        with config_path.open('w') as config_file:
            config.write(config_file)
        command = list(server.command)
        command[command.index('--listen') + 1] = restart_listen
        before = len(server.registry.calls)
        log_path = server.root / 'restart.log'
        with log_path.open('w') as log:
            process = subprocess.Popen(command, env=server.env, cwd=E2E_ROOT / 'comfyui',
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()[-6000:]
                    try:
                        if requests.get(server.base + '/system_stats', timeout=1).status_code == 200:
                            break
                    except requests.RequestException:
                        pass
                    time.sleep(.2)
                else:
                    pytest.fail(log_path.read_text()[-6000:])
                calls = server.registry.calls[before:]
                assert not any('/install' in call for call in calls), calls
                assert any(call.startswith('/zip/') for call in calls) is allowed, calls
                if allowed:
                    assert marker.read_text() == '2.0.0', log_path.read_text()[-6000:]
                else:
                    if stored_status:
                        assert_terminal_guidance(log_path.read_text())
                    else:
                        assert 'stored Registry status is missing' in log_path.read_text()
                        assert 'Request the installation again' in log_path.read_text()
                    assert (marker.read_bytes(), marker.stat().st_mtime_ns) == original_marker
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@pytest.mark.parametrize('operation', ['install', 'restore-snapshot'])
def test_direct_cli_installs_flagged_without_server_options(tmp_path, registry, operation):
    env = prepare_environment(tmp_path, False, 'normal', registry)
    command = [str(E2E_ROOT / 'venv/bin/python'), '-m', 'cm_cli', operation]
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


@pytest.mark.parametrize('tree', ['legacy', 'glob'])
@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('version,listen,override,allowed', [
    ('1.1.0', '0.0.0.0', False, True),
    ('2.0.0', '0.0.0.0', False, False),
    ('2.0.0', '0.0.0.0', True, True),
    ('2.0.0', '127.0.0.1', False, True),
])
def test_scheduled_snapshot_restores_through_server_restart(
        tmp_path, registry, tree, existing, version, listen, override, allowed):
    installed = tmp_path / 'custom_nodes/fixture-snapshot'
    marker = installed / 'installed.txt'
    reservation = tmp_path / 'user/__manager/startup-scripts/restore-snapshot.json'
    with running_server(tmp_path, tree, '127.0.0.1', False, 'normal', registry) as server:
        if existing:
            install(server, 'fixture-snapshot', '1.0.0')
            assert marker.read_text() == '1.0.0'
            original = (marker.read_bytes(), marker.stat().st_mtime_ns)
        snapshot = tmp_path / 'user/__manager/snapshots/flagged-policy.json'
        snapshot.write_text(json.dumps({'cnr_custom_nodes': {'fixture-snapshot': version},
                                        'git_custom_nodes': {}, 'file_custom_nodes': []}))
        before = len(registry.calls)
        response = requests.post(server.base + '/v2/snapshot/restore',
                                 params={'target': snapshot.stem}, json={}, timeout=10)
        assert response.status_code == 200, response.text
        assert reservation.read_bytes() == snapshot.read_bytes()
        assert registry.calls[before:] == []
        if existing:
            assert (marker.read_bytes(), marker.stat().st_mtime_ns) == original
        else:
            assert not installed.exists()

    before = len(registry.calls)
    with running_server(tmp_path, tree, listen, override, 'normal', registry):
        log = (tmp_path / 'server.log').read_text()
        calls = registry.calls[before:]
        assert 'Restore snapshot done.' in log, log[-6000:]
        assert 'Restore snapshot failed.' not in log, log[-6000:]
        assert 'Error in sitecustomize' not in log, log[-6000:]
        assert not reservation.exists()
        assert sum('/install' in call for call in calls) == 1, (calls, log[-6000:])
        assert any(call.startswith('/zip/') for call in calls) is allowed, calls
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
