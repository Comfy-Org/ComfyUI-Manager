import configparser
import importlib.util
import logging
import os

import pytest

from manager_test_utils import GLOB_DIR
from test_git_exe_setting import take

URL = "https://github.com/someone/some%20pack"
PLAIN = '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://github.com/someone/pack\n'
PERCENT = f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {URL}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n'
NO_VALUE = '[core]\n\tbare\n[remote "origin"]\n\turl = https://github.com/someone/pack\n'
NO_VALUE_THEN_DEEPER = '[core]\n\tbare\n\t\tfilemode = false\n[remote "origin"]\n\turl = https://github.com/someone/pack\n'
NO_REMOTE = '[core]\n\tbare = false\n'
BOM = "\ufeff" + PLAIN
NOT_A_CONFIG = "ref: refs/heads/master\n" + PLAIN
NOT_ASCII = PLAIN + '[user]\n\tname = 홍길동\n'
NOT_UTF8 = PLAIN.encode() + b'[user]\n\tname = \xff\xfe\n'
BRANCH_NOT_UTF8 = PLAIN.encode() + b'[branch "release-\xfe"]\n\tremote = origin\n\tmerge = refs/heads/release-\xfe\n'
ORIGIN = '[remote "origin"]\n\turl = https://github.com/someone/pack\n'
OTHER = '\t[remote "other"]\n\turl = https://github.com/someone/other\n'
VALUE_OVER_TWO_LINES = '[core]\n\tdescription = a \\\n' + OTHER + ORIGIN
QUOTED_VALUE_OVER_TWO_LINES = '[core]\n\tdescription = "a # b \\\n' + OTHER.replace('\n', '"\n', 1) + ORIGIN
COMMENT_THAT_ENDS_IN_A_BACKSLASH = '[core]\n\t# a comment \\\n' + ORIGIN
VALUE_THAT_ENDS_IN_A_BACKSLASH = '[core]\n\tdescription = a\\\\\n' + ORIGIN
VALUE_THAT_GOES_ON_WHERE_THE_FILE_ENDS = '[remote "origin"]\n\turl = https://github.com/someone/pack\\'
URL_BEFORE_THE_FIRST_SECTION = "url = https://someone:a-token@github.com/someone/pack\n" + PLAIN


def git_utils():
    spec = importlib.util.spec_from_file_location("_git_utils", GLOB_DIR / "git_utils.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git_url():
    return git_utils().git_url


def resolve():
    return take(GLOB_DIR / "manager_core.py", "resolve_giturl_from_path", {
        "os": os, "configparser": configparser, "logging": logging, "git_utils": git_utils(),
    })


@pytest.fixture(params=[git_url, resolve], ids=["git_url", "resolve_giturl_from_path"])
def read(request, tmp_path):
    reader = request.param()

    def read(config, mode=None):
        (tmp_path / ".git").mkdir(exist_ok=True)
        (tmp_path / ".git" / "config").write_bytes(config if isinstance(config, bytes) else config.encode())
        if mode is not None:
            (tmp_path / ".git" / "config").chmod(mode)
        return reader(str(tmp_path))

    return read


def test_url_is_read(read):
    assert read(PLAIN) == "https://github.com/someone/pack"


def test_url_with_a_percent_sign_is_read_as_it_is(read):
    assert read(PERCENT) == URL


def test_url_is_read_beside_a_key_without_a_value(read):
    assert read(NO_VALUE) == "https://github.com/someone/pack"


def test_config_without_a_remote_has_no_url(read):
    assert read(NO_REMOTE) is None


def test_url_without_a_value_is_no_url(read):
    assert read('[remote "origin"]\n\turl\n') is None


def test_url_is_read_after_a_byte_order_mark(read):
    assert read(BOM) == "https://github.com/someone/pack"


def test_url_is_read_beside_text_that_is_not_ascii(read):
    assert read(NOT_ASCII) == "https://github.com/someone/pack"


def test_url_is_read_beside_bytes_that_are_not_utf8(read):
    assert read(NOT_UTF8) == "https://github.com/someone/pack"


def test_url_is_read_beside_a_branch_that_is_not_utf8(read):
    assert read(BRANCH_NOT_UTF8) == "https://github.com/someone/pack"


def test_config_that_cannot_be_parsed_has_no_url_and_is_reported(read, caplog, tmp_path):
    assert read(NOT_A_CONFIG) is None
    assert str(tmp_path / ".git" / "config") in caplog.text


def test_key_before_a_deeper_line_is_read(read):
    """For git a line that is indented more is a key of its own; the parser would take it as more of the value before it."""
    assert read(NO_VALUE_THEN_DEEPER) == "https://github.com/someone/pack"
    assert read('[remote "origin"]\n\turl = https://github.com/someone/pack\n\t\tfetch = +refs/heads/*:refs/remotes/origin/*\n') == "https://github.com/someone/pack"


def test_value_that_goes_on_at_the_next_line_is_one_value(read):
    """As for git: what looks like a section in the second line of a value is text of that value."""
    assert read(VALUE_OVER_TWO_LINES) == "https://github.com/someone/pack"
    assert read(QUOTED_VALUE_OVER_TWO_LINES) == "https://github.com/someone/pack"
    assert read(VALUE_THAT_GOES_ON_WHERE_THE_FILE_ENDS) == "https://github.com/someone/pack"


def test_line_that_does_not_go_on_is_a_line_of_its_own(read):
    assert read(COMMENT_THAT_ENDS_IN_A_BACKSLASH) == "https://github.com/someone/pack"
    assert read(VALUE_THAT_ENDS_IN_A_BACKSLASH) == "https://github.com/someone/pack"


def test_config_that_cannot_be_parsed_is_reported_without_its_text(read, caplog, tmp_path):
    assert read(URL_BEFORE_THE_FIRST_SECTION) is None
    assert str(tmp_path / ".git" / "config") in caplog.text
    assert "a-token" not in caplog.text


def test_config_that_cannot_be_parsed_is_reported_once(read, caplog, tmp_path):
    for _ in range(3):
        assert read(NOT_A_CONFIG) is None

    assert caplog.text.count(f"Cannot read '{tmp_path / '.git' / 'config'}'") == 1


def test_config_that_may_not_be_read_has_no_url_and_is_reported(read, caplog, tmp_path):
    url = read(PLAIN, mode=0)
    try:
        open(tmp_path / ".git" / "config").close()
    except OSError:
        pass
    else:
        pytest.skip("the file can be read here, as by root or on Windows")

    assert url is None
    assert str(tmp_path / ".git" / "config") in caplog.text
