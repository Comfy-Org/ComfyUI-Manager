"""A registry install whose archive cannot be extracted leaves nothing behind.

The install reports the failure and removes both the downloaded archive and the
directory it created for the node pack, so that installing the pack again starts
from a clean state instead of stopping at 'Install path already exists'. When the
cleanup fails as well, the install still reports the extraction error. An uninstall
whose directory can neither be removed nor scheduled for removal is still an error.

The cases run in the isolated child of tests/test_install_flags_config.py, against
the real glob/manager_core and the real extraction.
"""

import pytest

from test_install_flags_config import _run_child


PRELUDE = '''
import pathlib, zipfile
from types import SimpleNamespace
from unittest.mock import Mock
import cnr_utils
core = manager_core
nodes = pathlib.Path(tmp) / 'custom_nodes'
nodes.mkdir()
core.get_default_custom_nodes_path = lambda: str(nodes)
cnr_utils.requests.get = Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {
    'id': 'version-id', 'node_id': 'fixture', 'version': '2.0.0',
    'status': 'NodeVersionStatusActive', 'downloadUrl': 'https://example.invalid/fixture.zip',
}))
manager = core.UnifiedManager()
core.unified_manager = manager
manager.execute_install_script = Mock(return_value=True)

def good(path):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('__init__.py', 'VERSION = "2.0.0"')

def failing_midway(path):
    # 'nodes' is extracted as a file, so the entry below it cannot be created
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('__init__.py', 'VERSION = "2.0.0"')
        archive.writestr('nodes', 'a file')
        archive.writestr('nodes/loader.py', 'a file inside a file')

def not_a_zip(path):
    pathlib.Path(path).write_bytes(b'<html>502 Bad Gateway</html>')

def install(write_archive):
    core.manager_downloader.download_url = lambda url, directory, name: write_archive(pathlib.Path(directory) / name)
    return manager.cnr_install('fixture', '2.0.0', instant_execution=True, no_deps=True)

def left():
    return sorted(path.name for path in nodes.iterdir())
'''


def run(body):
    return _run_child(PRELUDE + body)


@pytest.mark.parametrize('archive, message', [
    ('failing_midway', 'Failed to extract archive: fixture@2.0.0: '),
    ('not_a_zip', 'Empty archive file: fixture@2.0.0'),
])
def test_failed_extraction_leaves_nothing_behind(archive, message):
    data = run(f'''
result = install({archive})
print(json.dumps({{'ok': result.result, 'message': result.msg, 'left': left()}}))
''')
    assert data['ok'] is False
    assert data['message'].startswith(message), data
    assert data['left'] == []


def test_install_succeeds_after_a_failed_extraction():
    data = run('''
install(failing_midway)
result = install(good)
print(json.dumps({'ok': result.result, 'message': result.msg, 'left': left(),
    'file': (nodes / 'fixture/__init__.py').read_text()}))
''')
    assert data == {'ok': True, 'message': data['message'], 'left': ['fixture'], 'file': 'VERSION = "2.0.0"'}


@pytest.mark.parametrize('archive, message', [
    ('failing_midway', 'Failed to extract archive: fixture@2.0.0: '),
    ('not_a_zip', 'Empty archive file: fixture@2.0.0'),
])
def test_cleanup_that_fails_does_not_hide_the_extraction_error(archive, message):
    data = run(f'''
core.try_rmtree = Mock(side_effect=OSError('the directory cannot be removed'))
error = None
try:
    result = install({archive})
except Exception as e:
    error = repr(e)
print(json.dumps({{'error': error, 'message': error or result.msg, 'cleanups': core.try_rmtree.call_count}}))
''')
    assert data['error'] is None, data
    assert data['message'].startswith(message), data
    assert data['cleanups'] == 1


def test_uninstall_that_can_neither_remove_nor_schedule_is_an_error():
    data = run('''
installed = nodes / 'fixture'
installed.mkdir()
manager.active_nodes['fixture'] = ('2.0.0', str(installed))
core.shutil.rmtree = Mock(side_effect=OSError('the directory is in use'))
core.reserve_script = Mock(side_effect=OSError('the startup script cannot be written'))
try:
    outcome = 'reported as ' + manager.unified_uninstall('fixture', False).action
except OSError as e:
    outcome = 'error: ' + str(e)
print(json.dumps({'outcome': outcome, 'left': left()}))
''')
    assert data == {'outcome': 'error: the startup script cannot be written', 'left': ['fixture']}


def test_uninstall_schedules_a_directory_it_cannot_remove():
    data = run('''
installed = nodes / 'fixture'
installed.mkdir()
manager.active_nodes['fixture'] = ('2.0.0', str(installed))
core.shutil.rmtree = Mock(side_effect=OSError('the directory is in use'))
scheduled = []
core.reserve_script = lambda title, commands: scheduled.append([title] + commands)
result = manager.unified_uninstall('fixture', False)
print(json.dumps({'action': result.action, 'ok': result.result,
    'scheduled': scheduled == [['fixture', '#LAZY-DELETE-NODEPACK', str(installed)]]}))
''')
    assert data == {'action': 'uninstall', 'ok': True, 'scheduled': True}
