"""execute_install_script() must read a node pack's requirements.txt the way
the other install paths do (manager_util.robust_readlines), not with the
locale encoding.

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

from manager_test_utils import GLOB_DIR, load_manager_util


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
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<install-extract>", "exec"), namespace)
    return namespace["execute_install_script"]


class FakePIPFixer:
    def __init__(self, *args):
        pass

    def fix_broken(self):
        pass


def test_utf8_requirements_with_non_ascii_comment_install(tmp_path, monkeypatch):
    real_util = load_manager_util()
    monkeypatch.setattr(real_util, "open", ansi_open, raising=False)
    manager_util = types.SimpleNamespace(
        PIPFixer=FakePIPFixer,
        get_installed_packages=lambda: {},
        make_pip_cmd=lambda args: ["pip"] + args,
        robust_readlines=real_util.robust_readlines,
    )
    (tmp_path / "requirements.txt").write_text(
        "# Łukasz ✨ 中文\nnumpy\nrich  # Łukasz\n", encoding="utf-8")

    calls = []
    execute_install_script = load_execute_install_script(manager_util, calls)

    assert execute_install_script("https://example.invalid/pack", str(tmp_path)) is True
    assert calls == [["pip", "install", "numpy"], ["pip", "install", "rich"]]
