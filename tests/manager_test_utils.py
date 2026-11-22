"""Load Python escaping code without importing the ComfyUI server.

MANAGER_GLOB_DIR can point to another revision for regression checks. Loading
manager_util by path avoids shadowing the standard library's glob module.
"""
import ast
import importlib.util
import os
import re
from pathlib import Path

GLOB_DIR = Path(os.environ.get("MANAGER_GLOB_DIR") or (Path(__file__).resolve().parent.parent / "glob"))


def load_manager_util():
    path = GLOB_DIR / "manager_util.py"
    spec = importlib.util.spec_from_file_location("_manager_util_under_test", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_markdown_functions(manager_util):
    source = (GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")
    names = {"convert_markdown_to_html", "populate_markdown"}
    functions = [node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(functions) == len(names) and {node.name for node in functions} == names
    namespace = {"re": re, "manager_util": manager_util}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<markdown-extract>", "exec"), namespace)
    return namespace
