"""A Registry install whose archive cannot be extracted leaves nothing behind.

The install reports the failure, and removes both the downloaded archive and the
directory it created for the nodepack, so that installing the nodepack again starts
from a clean state instead of stopping at 'Install path already exists'. When the
cleanup fails as well, the install still reports the extraction failure.
"""

import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from _install_flags_testutil import import_reader


def write_good(path):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('__init__.py', 'VERSION = "2.0.0"')


def write_failing_midway(path):
    """'nodes' is extracted as a file, so the entry below it cannot be created."""
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('__init__.py', 'VERSION = "2.0.0"')
        archive.writestr('nodes', 'a file')
        archive.writestr('nodes/loader.py', 'a file inside a file')


def write_not_a_zip(path):
    Path(path).write_bytes(b'<html>502 Bad Gateway</html>')


@pytest.fixture(params=['glob', 'legacy'])
def core(request):
    return import_reader(request.param)


@pytest.fixture
def install(core, monkeypatch, tmp_path):
    """Install 'fixture' from an archive written by the given function; return the result."""
    monkeypatch.setattr(core, 'get_default_custom_nodes_path', lambda: str(tmp_path))
    monkeypatch.setattr(core.cnr_utils.requests, 'get', Mock(return_value=SimpleNamespace(
        status_code=200, json=lambda: {
            'id': 'version-id', 'node_id': 'fixture', 'version': '2.0.0',
            'status': 'NodeVersionStatusActive', 'downloadUrl': 'https://example.invalid/fixture.zip',
        })))
    manager = core.UnifiedManager()
    manager.execute_install_script = Mock(return_value=True)

    def run(write_archive):
        monkeypatch.setattr(core.manager_downloader, 'download_url',
                            lambda url, directory, name: write_archive(Path(directory) / name))
        return manager.cnr_install('fixture', '2.0.0', instant_execution=True, no_deps=True)

    return run


@pytest.mark.parametrize('write_archive, message', [
    (write_failing_midway, 'Failed to extract archive: fixture@2.0.0: '),
    (write_not_a_zip, 'Empty archive file: fixture@2.0.0'),
])
def test_failed_extraction_leaves_nothing_behind(install, tmp_path, write_archive, message):
    result = install(write_archive)

    assert result.result is False
    assert result.msg.startswith(message)
    assert list(tmp_path.iterdir()) == []


def test_install_succeeds_after_a_failed_extraction(install, tmp_path):
    install(write_failing_midway)

    result = install(write_good)

    assert result.result is True, result.msg
    assert sorted(path.name for path in tmp_path.iterdir()) == ['fixture']
    assert (tmp_path / 'fixture/__init__.py').read_text() == 'VERSION = "2.0.0"'


@pytest.mark.parametrize('write_archive, message', [
    (write_failing_midway, 'Failed to extract archive: fixture@2.0.0: '),
    (write_not_a_zip, 'Empty archive file: fixture@2.0.0'),
])
def test_cleanup_that_fails_does_not_hide_the_extraction_failure(core, install, monkeypatch, write_archive, message):
    cleanup = Mock(side_effect=OSError('the directory cannot be removed'))
    monkeypatch.setattr(core, 'try_rmtree', cleanup)

    result = install(write_archive)

    assert result.result is False
    assert result.msg.startswith(message)
    assert cleanup.call_count == 1
