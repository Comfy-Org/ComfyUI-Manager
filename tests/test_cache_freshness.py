"""Cache freshness and durability:

- freshness must be mtime-based: on Windows getctime is the CREATION time,
  and in-place rewrites never changed it, so every rewritten cache was
  'expired' forever after day one;
- writes must be atomic: a kill mid-dump used to leave a truncated cache
  that looked fresh but served {} for the whole TTL.
"""

import json
import os
import time
from unittest.mock import patch

from manager_test_utils import load_manager_util

MANAGER_UTIL = load_manager_util()


def _fresh_cache(tmp_path, body):
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps(body), encoding="utf-8")
    return cache


def test_rewritten_cache_stays_fresh(tmp_path):
    cache = _fresh_cache(tmp_path, {"a": 1})
    with patch.object(MANAGER_UTIL, "get_cache_path", return_value=str(cache)):
        MANAGER_UTIL.save_to_cache("https://example/list.json", {"b": 2}, silent=True)
        # the rewrite moved mtime forward; freshness must hold
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
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".cache-")]
    assert leftovers == []
