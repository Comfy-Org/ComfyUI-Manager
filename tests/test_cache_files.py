"""Cache files stay fresh for a day after they are written, and are written whole.

A cache file is fresh for one day counted from its last write. A write puts the new
content in place in one step, so the file holds the previous content or the new content
and never a part of either, and it keeps the permissions it had. A file that stays open
elsewhere, which cannot be replaced, is left as it is.
"""

import asyncio
import errno
import json
import os
import sys
import time
from unittest.mock import Mock

import pytest

from _install_flags_testutil import import_context


URI = 'https://example.invalid/custom-node-list.json'


@pytest.fixture
def util(monkeypatch, tmp_path):
    import_context()
    from comfyui_manager.common import manager_util

    monkeypatch.setattr(manager_util, 'cache_dir', str(tmp_path))
    return manager_util


def cache_files(tmp_path):
    return sorted(path.name for path in tmp_path.iterdir())


def test_rewritten_cache_is_fresh_whatever_its_creation_time(util, monkeypatch):
    """On Windows a rewritten file keeps the creation time of the first write."""
    util.save_to_cache(URI, {'a': 1}, silent=True)
    monkeypatch.setattr(util.os.path, 'getctime', lambda path: time.time() - 10 * 86400)

    assert util.get_cache_state(URI) == 'cached'


def test_cache_expires_a_day_after_its_last_write(util):
    util.save_to_cache(URI, {'a': 1}, silent=True)
    cache = util.get_cache_path(URI)

    almost_a_day_ago = time.time() - 86400 + 60
    os.utime(cache, (almost_a_day_ago, almost_a_day_ago))
    assert util.get_cache_state(URI) == 'cached'

    over_a_day_ago = time.time() - 86400 - 60
    os.utime(cache, (over_a_day_ago, over_a_day_ago))
    assert util.get_cache_state(URI) == 'expired'


def test_failed_write_keeps_the_previous_content(util, tmp_path):
    util.save_to_cache(URI, {'a': 1}, silent=True)
    cache = util.get_cache_path(URI)

    with pytest.raises(TypeError):
        util.save_to_cache(URI, {'b': 2, 'c': object()}, silent=True)

    assert json.loads(open(cache, encoding='utf-8').read()) == {'a': 1}
    assert cache_files(tmp_path) == [os.path.basename(cache)]


def test_write_that_runs_out_of_space_keeps_the_previous_content(util, monkeypatch, tmp_path):
    util.save_to_cache(URI, {'a': 1}, silent=True)
    cache = util.get_cache_path(URI)

    def disk_full(obj, file, **_):
        file.write('{"b": ')
        raise OSError(errno.ENOSPC, 'No space left on device')

    monkeypatch.setattr(util.json, 'dump', disk_full)
    with pytest.raises(OSError):
        util.save_to_cache(URI, {'b': 2}, silent=True)

    assert json.loads(open(cache, encoding='utf-8').read()) == {'a': 1}
    assert cache_files(tmp_path) == [os.path.basename(cache)]


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX permission bits')
def test_write_keeps_the_permissions_of_the_file(util, tmp_path):
    plain = tmp_path / 'plain'
    plain.write_text('')
    default_mode = plain.stat().st_mode & 0o777
    plain.unlink()

    util.save_to_cache(URI, {'a': 1}, silent=True)
    cache = util.get_cache_path(URI)
    assert os.stat(cache).st_mode & 0o777 == default_mode

    other_mode = default_mode ^ 0o040  # never what a new file gets
    os.chmod(cache, other_mode)
    util.save_to_cache(URI, {'b': 2}, silent=True)
    assert os.stat(cache).st_mode & 0o777 == other_mode


def test_cache_is_replaced_where_its_mode_cannot_be_set(util, monkeypatch, tmp_path):
    """A file system may refuse chmod; the cache is still replaced in one step."""
    util.save_to_cache(URI, {'a': 1}, silent=True)
    cache = util.get_cache_path(URI)
    replace = util.os.replace
    replaced = []

    def refuse(path, mode):
        raise PermissionError(errno.EPERM, 'Operation not permitted', path)

    def record(src, dst):
        replaced.append(dst)
        replace(src, dst)

    monkeypatch.setattr(util.os, 'chmod', refuse)
    monkeypatch.setattr(util.os, 'replace', record)
    util.save_to_cache(URI, {'b': 2}, silent=True)

    assert replaced == [cache]
    assert json.loads(open(cache, encoding='utf-8').read()) == {'b': 2}
    assert cache_files(tmp_path) == [os.path.basename(cache)]


@pytest.fixture
def refusing_replace(util, monkeypatch):
    """Make os.replace refuse the given number of times, as Windows does while another reader has
    the file open, and then replace; returns the list of attempts."""
    def install(refusals):
        replace = util.os.replace
        attempts = []

        def attempt(src, dst):
            attempts.append(dst)
            if len(attempts) <= refusals:
                raise PermissionError(13, 'The process cannot access the file', dst)
            replace(src, dst)

        monkeypatch.setattr(util.os, 'replace', attempt)
        monkeypatch.setattr(util.time, 'sleep', lambda seconds: None)
        return attempts

    return install


def test_file_is_replaced_once_the_reader_has_closed_it(util, refusing_replace, monkeypatch, tmp_path):
    util.save_to_cache(URI, {'a': 1}, silent=True)
    cache = util.get_cache_path(URI)
    attempts = refusing_replace(2)
    dump = Mock(wraps=util.json.dump)
    monkeypatch.setattr(util.json, 'dump', dump)

    util.save_to_cache(URI, {'b': 2}, silent=True)

    assert len(attempts) == 3
    assert dump.call_count == 1, 'the cache must not be written in place'
    assert json.loads(open(cache, encoding='utf-8').read()) == {'b': 2}
    assert cache_files(tmp_path) == [os.path.basename(cache)]


def test_file_that_stays_open_elsewhere_is_left_as_it_is(util, refusing_replace, tmp_path, caplog):
    util.save_to_cache(URI, {'a': 1}, silent=True)
    cache = util.get_cache_path(URI)
    attempts = refusing_replace(100)

    with caplog.at_level('INFO'):
        # The caller sees no error: it goes on with the data it fetched.
        util.save_to_cache(URI, {'b': 2})

    assert len(attempts) == 3
    assert json.loads(open(cache, encoding='utf-8').read()) == {'a': 1}
    assert cache_files(tmp_path) == [os.path.basename(cache)]
    assert 'The cache could not be replaced' in caplog.text
    assert 'default cache updated' not in caplog.text


def test_temporary_file_that_is_open_elsewhere_does_not_fail_the_write(util, refusing_replace, monkeypatch):
    """A scanner that opens the new file keeps Windows from replacing with it and from removing it."""
    util.save_to_cache(URI, {'a': 1}, silent=True)
    cache = util.get_cache_path(URI)
    attempts = refusing_replace(100)

    def refuse(path):
        raise PermissionError(13, 'The process cannot access the file', path)

    monkeypatch.setattr(util.os, 'remove', refuse)

    assert util.write_cache_file(cache, {'b': 2}) is False
    assert len(attempts) == 3
    assert json.loads(open(cache, encoding='utf-8').read()) == {'a': 1}


def test_fetched_data_is_cached_whole(util, tmp_path):
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'a': 1}))
    cache = util.get_cache_path(str(source))

    assert asyncio.run(util.get_data_with_cache(str(source), silent=True, cache_mode=False)) == {'a': 1}

    assert json.loads(open(cache, encoding='utf-8').read()) == {'a': 1}
    assert cache_files(tmp_path) == sorted([os.path.basename(cache), 'source.json'])
