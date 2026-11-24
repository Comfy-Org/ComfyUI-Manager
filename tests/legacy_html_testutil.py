"""Execute the legacy renderer without starting ComfyUI or its network threads."""
import ast
import importlib.util
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / 'comfyui_manager'


def load_functions(path, names, namespace=None):
    namespace = {} if namespace is None else namespace
    nodes = [node for node in ast.parse(path.read_text(encoding='utf-8')).body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(nodes) == len(names)
    exec(compile(ast.Module(nodes, []), str(path), 'exec'), namespace)
    return namespace


def load_renderer():
    path = PACKAGE / 'legacy/html_utils.py'
    spec = importlib.util.spec_from_file_location('_legacy_html_utils', path)
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    util = load_functions(PACKAGE / 'common/manager_util.py', {'sanitize_tag'})
    return load_functions(PACKAGE / 'legacy/manager_server.py', {'convert_markdown_to_html', 'populate_markdown'},
                          {'re': re, 'html_utils': helpers, 'manager_util': types.SimpleNamespace(**util)})


if __name__ == '__main__':
    item = json.load(sys.stdin)
    load_renderer()['populate_markdown'](item)
    print(json.dumps(item))
