"""aria2_download_url keeps the contract of download_url: it returns only when the
file is at <model_dir>/<filename> on this machine, and raises otherwise."""
import os
import time

import pytest

from _install_flags_testutil import import_context


class FakeDownload:
    def __init__(self, statuses, local_file=None, error_message=None, target=None):
        self._statuses = list(statuses)
        self.status = self._statuses.pop(0)
        self._local_file = local_file          # what aria2 writes through the mount when it completes
        self.error_message = error_message
        self.total_length = 10
        self.completed_length = 0
        self.updates = 0
        self.files = [type('F', (), {'is_metadata': False, 'path': target})()] if target else []
        self._write_if_complete()

    def _write_if_complete(self):
        if self.status == 'complete' and self._local_file:
            os.makedirs(os.path.dirname(self._local_file), exist_ok=True)
            open(self._local_file, 'wb').close()

    is_active = property(lambda self: self.status == 'active')
    is_waiting = property(lambda self: self.status == 'waiting')
    is_paused = property(lambda self: self.status == 'paused')
    has_failed = property(lambda self: self.status == 'error')
    is_complete = property(lambda self: self.status == 'complete')
    is_removed = property(lambda self: self.status == 'removed')

    def update(self):
        self.updates += 1
        if self._statuses:
            self.status = self._statuses.pop(0)
            self._write_if_complete()


class FakeAria2:
    def __init__(self, new, existing=()):
        self.new, self.existing, self.added = new, list(existing), []

    def get_downloads(self):
        return self.existing

    def add(self, url, options):
        self.added.append(dict(options))
        return [self.new]


@pytest.fixture
def md(tmp_path, monkeypatch):
    import_context()
    from comfyui_manager.common import context, manager_downloader
    monkeypatch.setattr(context, 'comfy_path', str(tmp_path))
    monkeypatch.setattr(time, 'sleep', lambda s: None)
    return manager_downloader


def install(md, tmp_path, monkeypatch, fake):
    monkeypatch.setattr(md, 'aria2', fake)
    return md.download_url('https://huggingface.co/x/y.safetensors', str(tmp_path / 'models' / 'checkpoints'), 'y.safetensors')


def local(tmp_path):
    return str(tmp_path / 'models' / 'checkpoints' / 'y.safetensors')


def test_a_download_that_aria2_fails_raises_with_its_message(md, tmp_path, monkeypatch):
    fake = FakeAria2(FakeDownload(['error'], error_message='Failed to make the directory /models/checkpoints, cause: Permission denied'))
    with pytest.raises(Exception, match='Permission denied'):
        install(md, tmp_path, monkeypatch, fake)


def test_a_file_that_aria2_saved_elsewhere_raises(md, tmp_path, monkeypatch):
    fake = FakeAria2(FakeDownload(['complete']))          # complete, but not through a mount of this models folder
    with pytest.raises(Exception, match='y.safetensors'):
        install(md, tmp_path, monkeypatch, fake)


def test_a_queued_download_is_waited_for(md, tmp_path, monkeypatch):
    download = FakeDownload(['waiting', 'active', 'complete'], local_file=local(tmp_path))
    fake = FakeAria2(download)
    install(md, tmp_path, monkeypatch, fake)
    assert download.is_complete and os.path.exists(local(tmp_path))
    assert fake.added == [{'dir': '/models/checkpoints', 'out': 'y.safetensors'}]


def test_a_failed_earlier_download_is_not_reused(md, tmp_path, monkeypatch):
    old = FakeDownload(['error'], target='/models/checkpoints/y.safetensors')
    fake = FakeAria2(FakeDownload(['complete'], local_file=local(tmp_path)), existing=[old])
    install(md, tmp_path, monkeypatch, fake)
    assert len(fake.added) == 1


def test_a_finished_earlier_download_whose_file_is_there_is_reused(md, tmp_path, monkeypatch):
    os.makedirs(os.path.dirname(local(tmp_path))); open(local(tmp_path), 'wb').close()
    old = FakeDownload(['complete'], target='/models/checkpoints/y.safetensors')
    fake = FakeAria2(FakeDownload(['complete']), existing=[old])
    install(md, tmp_path, monkeypatch, fake)
    assert fake.added == []
