"""Cache freshness and durability:

- freshness must be mtime-based: on Windows getctime is the CREATION time,
  and in-place rewrites never changed it, so every rewritten cache was
  'expired' forever after day one;
- writes must be atomic: a kill mid-dump used to leave a truncated cache
  that looked fresh but served {} for the whole TTL. A write that fails
  part-way leaves the previous cache, the cache keeps its mode, and a cache
  that stays open elsewhere is left as it is rather than written in place.
"""

import errno
import json
import os
import sys
import time
from unittest.mock import patch

import pytest

from manager_test_utils import load_manager_util

MANAGER_UTIL = load_manager_util()


def _fresh_cache(tmp_path, body):
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps(body), encoding="utf-8")
    return cache


def test_rewritten_cache_stays_fresh(tmp_path):
    cache = _fresh_cache(tmp_path, {"a": 1})
    stale_creation = time.time() - 86401
    with patch.object(MANAGER_UTIL, "get_cache_path", return_value=str(cache)), \
         patch.object(os.path, "getctime", return_value=stale_creation):
        MANAGER_UTIL.save_to_cache("https://example/list.json", {"b": 2}, silent=True)
        # the rewrite moved mtime forward; freshness must hold even with a
        # creation time older than a day (the Windows getctime regression)
        assert MANAGER_UTIL.is_file_created_within_one_day(str(cache)) is True
        # age the file explicitly: only then is it expired
        old = time.time() - 86401
        os.utime(cache, (old, old))
        assert MANAGER_UTIL.is_file_created_within_one_day(str(cache)) is False


def test_save_to_cache_leaves_no_tmp_debris_and_valid_json(tmp_path):
    cache = _fresh_cache(tmp_path, {"a": 1})
    with patch.object(MANAGER_UTIL, "get_cache_path", return_value=str(cache)):
        MANAGER_UTIL.save_to_cache("https://example/list.json", {"b": 2}, silent=True)
    assert json.loads(cache.read_text(encoding="utf-8")) == {"b": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


def _save(cache, body):
    with patch.object(MANAGER_UTIL, "get_cache_path", return_value=str(cache)):
        MANAGER_UTIL.save_to_cache("https://example/list.json", body, silent=True)


def test_write_that_fails_on_a_value_keeps_the_previous_cache(tmp_path):
    cache = _fresh_cache(tmp_path, {"a": 1})
    with pytest.raises(TypeError):
        _save(cache, {"b": 2, "c": object()})
    assert json.loads(cache.read_text(encoding="utf-8")) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


def test_write_that_runs_out_of_space_keeps_the_previous_cache(tmp_path):
    cache = _fresh_cache(tmp_path, {"a": 1})

    def disk_full(obj, file, **_):
        file.write('{"b": ')
        raise OSError(errno.ENOSPC, "No space left on device")

    with patch.object(MANAGER_UTIL.json, "dump", disk_full), pytest.raises(OSError):
        _save(cache, {"b": 2})
    assert json.loads(cache.read_text(encoding="utf-8")) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_cache_keeps_its_mode(tmp_path):
    plain = tmp_path / "plain"
    plain.write_text("")
    default_mode = plain.stat().st_mode & 0o777
    plain.unlink()

    cache = tmp_path / "cache.json"
    _save(cache, {"a": 1})
    assert cache.stat().st_mode & 0o777 == default_mode

    other_mode = default_mode ^ 0o040  # never what a new file gets
    os.chmod(cache, other_mode)
    _save(cache, {"b": 2})
    assert cache.stat().st_mode & 0o777 == other_mode


def test_cache_is_replaced_where_its_mode_cannot_be_set(tmp_path):
    cache = _fresh_cache(tmp_path, {"a": 1})
    replace = os.replace
    replaced = []

    def refuse(path, mode):
        raise PermissionError(errno.EPERM, "Operation not permitted", path)

    def record(src, dst):
        replaced.append(dst)
        replace(src, dst)

    with patch.object(os, "chmod", refuse), patch.object(os, "replace", record):
        _save(cache, {"b": 2})
    assert replaced == [str(cache)]
    assert json.loads(cache.read_text(encoding="utf-8")) == {"b": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


def _refusing_replace(refusals):
    """An os.replace that refuses the given number of times, as Windows does
    while another reader has the file open, and then replaces."""
    replace = os.replace
    attempts = []

    def attempt(src, dst):
        attempts.append(dst)
        if len(attempts) <= refusals:
            raise PermissionError(13, "The process cannot access the file", dst)
        replace(src, dst)

    return attempt, attempts


def test_cache_is_replaced_once_the_reader_has_closed_it(tmp_path):
    cache = _fresh_cache(tmp_path, {"a": 1})
    attempt, attempts = _refusing_replace(2)

    with patch.object(os, "replace", attempt), patch.object(MANAGER_UTIL.time, "sleep"), \
         patch.object(MANAGER_UTIL.json, "dump", wraps=json.dump) as dump:
        _save(cache, {"b": 2})
    assert len(attempts) == 3
    assert dump.call_count == 1, "the cache must not be written in place"
    assert json.loads(cache.read_text(encoding="utf-8")) == {"b": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


def test_cache_that_stays_open_elsewhere_is_left_as_it_is(tmp_path, caplog):
    cache = _fresh_cache(tmp_path, {"a": 1})
    attempt, attempts = _refusing_replace(100)

    with patch.object(os, "replace", attempt), patch.object(MANAGER_UTIL.time, "sleep"), \
         patch.object(MANAGER_UTIL, "get_cache_path", return_value=str(cache)), caplog.at_level("INFO"):
        # the caller sees no error: it goes on with the data it fetched
        MANAGER_UTIL.save_to_cache("https://example/list.json", {"b": 2})
    assert len(attempts) == 3
    assert json.loads(cache.read_text(encoding="utf-8")) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]
    assert "The cache could not be replaced" in caplog.text
    assert "default cache updated" not in caplog.text


def test_temporary_file_that_is_open_elsewhere_does_not_fail_the_write(tmp_path):
    # a scanner that opens the new file keeps Windows from replacing with it and from removing it
    cache = _fresh_cache(tmp_path, {"a": 1})
    attempt, attempts = _refusing_replace(100)

    def refuse(path):
        raise PermissionError(13, "The process cannot access the file", path)

    with patch.object(os, "replace", attempt), patch.object(os, "remove", refuse), \
         patch.object(MANAGER_UTIL.time, "sleep"):
        assert MANAGER_UTIL.write_cache_file(str(cache), {"b": 2}) is False
    assert len(attempts) == 3
    assert json.loads(cache.read_text(encoding="utf-8")) == {"a": 1}
