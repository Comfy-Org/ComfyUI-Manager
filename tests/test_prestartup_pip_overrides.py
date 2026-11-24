import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

PRESTARTUP = Path(os.environ.get("MANAGER_PRESTARTUP") or (Path(__file__).resolve().parent.parent / "prestartup_script.py"))
OVERRIDES = [{"a-package": "another-package==2.0"}, {"a-package": "a-package==1.0", "torch": "torch==2.5.1"}, {}]


def overrides_after_start(has_system_user_api, path):
    body = ast.parse(PRESTARTUP.read_text(encoding="utf-8")).body
    first = next(index for index, node in enumerate(body)
                 if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "cm_global.pip_overrides")
    statements = body[first:first + 2]
    assert isinstance(statements[1], ast.If) and "manager_pip_overrides_path" in ast.unparse(statements[1].test)
    cm_global = SimpleNamespace()
    exec(compile(ast.Module(body=statements, type_ignores=[]), str(PRESTARTUP), "exec"), {
        "cm_global": cm_global, "os": os, "json": json,
        "manager_pip_overrides_path": str(path), "_has_system_user_api": has_system_user_api,
    })
    return cm_global.pip_overrides


@pytest.mark.parametrize("overrides", OVERRIDES, ids=["one package", "two packages", "empty"])
def test_with_the_system_user_api_the_file_is_read(tmp_path, overrides):
    path = tmp_path / "pip_overrides.json"
    path.write_text(json.dumps(overrides), encoding="utf-8")

    assert overrides_after_start(True, path) == overrides


@pytest.mark.parametrize("text", [json.dumps(OVERRIDES[0]), json.dumps(OVERRIDES[1]), "{}", "", "not json"],
                         ids=["one package", "two packages", "empty", "an empty file", "not json"])
def test_on_an_older_comfyui_the_file_is_not_read(tmp_path, text):
    path = tmp_path / "pip_overrides.json"
    path.write_text(text, encoding="utf-8")

    assert overrides_after_start(False, path) == {}


@pytest.mark.parametrize("has_system_user_api", [True, False], ids=["with the API", "an older ComfyUI"])
def test_without_a_file_no_package_is_remapped(tmp_path, has_system_user_api):
    assert overrides_after_start(has_system_user_api, tmp_path / "pip_overrides.json") == {}
