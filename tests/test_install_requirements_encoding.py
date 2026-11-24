"""execute_install_script() must install from a node pack's requirements.txt
that the locale encoding cannot decode, and take from the encoding that
chardet guesses only requirements that do not depend on the guess.

On Windows the locale encoding is the ANSI code page, so a UTF-8
requirements.txt with a non-ASCII comment made the module-level installer
raise UnicodeDecodeError before any package was installed. The test pins the
locale to cp1252 so it reproduces the Windows behavior on any platform.
"""
import ast
import builtins
import os
import sys
import types

import chardet
import pytest

from manager_test_utils import GLOB_DIR, load_manager_util

NOT_TEXT = bytes(range(128, 256)) * 4 + b"\nnumpy\n"
MAC_ROMAN = "# Dependências do nó – instalação\nrich\n".encode("mac_roman")
SHIFT_JIS = "numpy\nrich  # 画像処理用\n".encode("shift_jis")
EBCDIC = "pandas\r".encode("cp500")


def ansi_open(file, mode="r", *args, encoding=None, **kwargs):
    if "b" not in mode and encoding is None:
        encoding = "cp1252"
    return builtins.open(file, mode, *args, encoding=encoding, **kwargs)


def load_execute_install_script(manager_util, calls):
    source = (GLOB_DIR / "manager_core.py").read_text(encoding="utf-8")
    functions = [node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == "execute_install_script"]
    assert len(functions) == 1
    namespace = {
        "os": os,
        "sys": sys,
        "open": ansi_open,
        "manager_util": manager_util,
        "remap_pip_package": lambda name: name,
        "try_install_script": lambda url, repo_path, cmd, instant_execution=False: calls.append(cmd),
        "comfy_path": "",
        "manager_files_path": "",
        "manager_migration": types.SimpleNamespace(has_system_user_api=lambda: False),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<install-extract>", "exec"), namespace)
    return namespace["execute_install_script"]


def load_install_at_startup(manager_util, calls):
    source = (GLOB_DIR.parent / "prestartup_script.py").read_text(encoding="utf-8")
    functions = [node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == "execute_lazy_install_script"]
    assert len(functions) == 1
    namespace = {
        "os": os,
        "manager_util": manager_util,
        "remap_pip_package": lambda name: name,
        "is_installed": lambda name: False,
        "process_wrap": lambda cmd, cwd, **kwargs: calls.append(cmd),
        "processed_install": set(),
        "comfy_path": "",
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<startup-extract>", "exec"), namespace)
    return namespace["execute_lazy_install_script"]


class FakePIPFixer:
    def __init__(self, *args):
        pass

    def fix_broken(self):
        pass


def ansi_manager_util(monkeypatch):
    real_util = load_manager_util()
    monkeypatch.setattr(real_util, "open", ansi_open, raising=False)
    monkeypatch.setattr(real_util, "PIPFixer", FakePIPFixer)
    monkeypatch.setattr(real_util, "get_installed_packages", lambda: {})
    monkeypatch.setattr(real_util, "make_pip_cmd", lambda args: ["pip"] + args)
    return real_util


def chardet_names(monkeypatch, encoding):
    monkeypatch.setattr(chardet, "detect", lambda data: {"encoding": encoding, "confidence": 0.06, "language": None})


def install(manager_util, tmp_path):
    calls = []
    execute_install_script = load_execute_install_script(manager_util, calls)
    assert execute_install_script("https://example.invalid/pack", str(tmp_path)) is True
    return calls


def test_utf8_requirements_with_non_ascii_comment_install(tmp_path, monkeypatch):
    manager_util = ansi_manager_util(monkeypatch)
    (tmp_path / "requirements.txt").write_text(
        "# Łukasz ✨ 中文\nnumpy\nrich  # Łukasz\n", encoding="utf-8")

    assert install(manager_util, tmp_path) == [["pip", "install", "numpy"], ["pip", "install", "rich"]]


@pytest.mark.parametrize("content, named, installed", [
    (MAC_ROMAN, "ISO-8859-5", ["rich"]),
    (SHIFT_JIS, "cp1006", ["numpy", "rich"]),
], ids=["mac-roman-chardet-7.1.0", "shift-jis-chardet-7.1.0"])
def test_requirements_whose_comment_chardet_misreads_install(tmp_path, monkeypatch, content, named, installed):
    manager_util = ansi_manager_util(monkeypatch)
    chardet_names(monkeypatch, named)
    (tmp_path / "requirements.txt").write_bytes(content)

    assert install(manager_util, tmp_path) == [["pip", "install", name] for name in installed]


@pytest.mark.parametrize("text, installed", [
    ("\u3000# 依存関係\nnumpy\n", ["numpy"]),
    ("# 依存関係\nnumpy\n\u00a0\u00a0\nrich\n", ["numpy", "rich"]),
], ids=["comment-indented-with-an-ideographic-space", "line-of-no-break-spaces"])
def test_utf8_requirements_with_non_ascii_blanks_install(tmp_path, monkeypatch, text, installed):
    manager_util = ansi_manager_util(monkeypatch)
    chardet_names(monkeypatch, "utf-8")
    (tmp_path / "requirements.txt").write_text(text, encoding="utf-8")

    assert install(manager_util, tmp_path) == [["pip", "install", name] for name in installed]


def test_requirement_line_with_a_no_break_space_fails_the_install(tmp_path, monkeypatch):
    manager_util = ansi_manager_util(monkeypatch)
    chardet_names(monkeypatch, "utf-8")
    (tmp_path / "requirements.txt").write_text("numpy\u00a0 # 依存関係\nrich\n", encoding="utf-8")

    calls = []
    execute_install_script = load_execute_install_script(manager_util, calls)

    with pytest.raises(UnicodeDecodeError) as error:
        execute_install_script("https://example.invalid/pack", str(tmp_path))
    assert str(error.value) == "'charmap' codec can't decode byte 0x9d in position 12: character maps to <undefined>"
    assert calls == []


def test_utf16_requirements_with_byte_order_mark_install_only_their_requirements(tmp_path, monkeypatch):
    manager_util = ansi_manager_util(monkeypatch)
    chardet_names(monkeypatch, "utf-16-le")
    (tmp_path / "requirements.txt").write_bytes("# 依赖列表\nrich\n".encode("utf-16"))

    assert install(manager_util, tmp_path) == [["pip", "install", "rich"]]


@pytest.mark.parametrize("named", ["ISO-8859-5", "MacCyrillic", None],
                         ids=["chardet-7.7.0", "chardet-7.1.0", "no-encoding"])
def test_requirements_that_are_not_text_fail_the_install(tmp_path, monkeypatch, named):
    manager_util = ansi_manager_util(monkeypatch)
    chardet_names(monkeypatch, named)
    (tmp_path / "requirements.txt").write_bytes(NOT_TEXT)

    calls = []
    execute_install_script = load_execute_install_script(manager_util, calls)

    with pytest.raises(UnicodeDecodeError) as error:
        execute_install_script("https://example.invalid/pack", str(tmp_path))
    assert str(error.value) == "'charmap' codec can't decode byte 0x81 in position 1: character maps to <undefined>"
    assert calls == []


@pytest.mark.parametrize("named", ["cp500", "cp1140"])
def test_requirements_that_an_ebcdic_guess_reads_as_ascii_fail_the_install(tmp_path, monkeypatch, named):
    manager_util = ansi_manager_util(monkeypatch)
    chardet_names(monkeypatch, named)
    (tmp_path / "requirements.txt").write_bytes(EBCDIC)

    calls = []
    execute_install_script = load_execute_install_script(manager_util, calls)

    with pytest.raises(UnicodeDecodeError) as error:
        execute_install_script("https://example.invalid/pack", str(tmp_path))
    assert str(error.value) == "'charmap' codec can't decode byte 0x81 in position 1: character maps to <undefined>"
    assert calls == []


def test_requirements_with_carriage_return_line_ends_install(tmp_path, monkeypatch):
    manager_util = ansi_manager_util(monkeypatch)
    chardet_names(monkeypatch, "utf-8")
    (tmp_path / "requirements.txt").write_bytes("pandas\r# 依存関係\r".encode("utf-8"))

    assert install(manager_util, tmp_path) == [["pip", "install", "pandas"]]


def test_the_install_at_startup_takes_the_requirements_chardet_reads(tmp_path, monkeypatch):
    manager_util = ansi_manager_util(monkeypatch)
    chardet_names(monkeypatch, "ISO-8859-5")
    (tmp_path / "requirements.txt").write_bytes(MAC_ROMAN)

    calls = []
    load_install_at_startup(manager_util, calls)(str(tmp_path), sys.executable)

    assert calls == [["pip", "install", "rich"]]
