import ast
import asyncio
import functools
import importlib.util
import logging
import sys
from types import SimpleNamespace

import pytest
from packaging import version

from legacy_html_testutil import PACKAGE, load_functions

LEVELS = ["strong", "normal", "normal-", "weak"]
LISTENERS = ["loopback", "personal_cloud", "public"]
METHODS = frozenset({"is_enabled", "get_cnr_active_version", "is_unknown_active", "resolve_unspecified_version",
                     "get_from_cnr_active_nodes", "get_from_cnr_inactive_nodes", "safe_version"})

CNR_ENABLED_NIGHTLY_DISABLED = dict(active={"pack": ("1.0.0", "custom_nodes/pack")},
                                    nightly_inactive={"pack": "custom_nodes/.disabled/pack@nightly"})


def nightly_install_allowed(security_level, listener):
    return security_level != "strong" and listener != "public"


@functools.lru_cache
def normalized_key_dict(server):
    source = (PACKAGE / server / "manager_core.py").read_text(encoding="utf-8")
    classes = [node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == "NormalizedKeyDict"]
    namespace = {}
    exec(compile(ast.Module(classes, []), "manager_core.py", "exec"), namespace)
    return namespace["NormalizedKeyDict"]


@functools.lru_cache
def functions_named(path, names):
    nodes = [node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(nodes) == len(names)
    namespace = {"version": version}
    exec(compile(ast.Module(nodes, []), str(path), "exec"), namespace)
    return {name: namespace[name] for name in names}


def load(monkeypatch, server, security_level, listener, active=None, nightly_inactive=None, cnr_inactive=None,
         unknown_active=None, unknown_inactive=None):
    enabled = []
    package = PACKAGE / server
    manager = type("UnifiedManager", (), functions_named(package / "manager_core.py", METHODS))()

    def packs(items, normalized=server == "glob"):
        if not normalized:
            return dict(items or {})
        kept = normalized_key_dict(server)()
        for key, value in (items or {}).items():
            kept[key] = value
        return kept

    manager.cnr_map = packs({"pack": {"latest_version": {"version": "1.0.0"}}}, normalized=True)
    manager.active_nodes = packs(active)
    manager.nightly_inactive_nodes = packs(nightly_inactive)
    manager.cnr_inactive_nodes = packs(cnr_inactive)
    manager.unknown_active_nodes = unknown_active or {}
    manager.unknown_inactive_nodes = unknown_inactive or {}
    manager.unified_enable = lambda cnr_id: enabled.append(cnr_id) or SimpleNamespace(result=True)
    core = SimpleNamespace(
        unified_manager=manager,
        get_config=lambda: {"security_level": security_level,
                            "network_mode": "personal_cloud" if listener == "personal_cloud" else "public"},
    )
    namespace = {"logging": logging, "core": core, "SECURITY_MESSAGE_MIDDLE_P": ""}

    if server == "glob":
        spec = importlib.util.spec_from_file_location("_generated_models", PACKAGE / "data_models/generated_models.py")
        models = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, models)
        spec.loader.exec_module(models)
        security = load_functions(package / "utils/security_utils.py", {"is_allowed_security_level"}, {
            "core": core, "args": SimpleNamespace(listen="127.0.0.1" if listener == "loopback" else "0.0.0.0"),
            "is_loopback": load_functions(PACKAGE / "common/manager_security.py", {"is_loopback"})["is_loopback"],
            "SecurityLevel": models.SecurityLevel, "RiskLevel": models.RiskLevel,
        })
        namespace.update(security_utils=SimpleNamespace(**security), OperationResult=models.OperationResult,
                         EnablePackParams=models.EnablePackParams)
        item = lambda node_id: models.EnablePackParams(cnr_id=node_id)  # noqa: E731
    else:
        namespace["is_local_mode"] = load_functions(package / "manager_server.py", {"is_loopback"})["is_loopback"](
            "127.0.0.1" if listener == "loopback" else "0.0.0.0")
        item = lambda node_id: ("ui", node_id)  # noqa: E731

    path = package / "manager_server.py"
    names = {"do_enable", "replaces_cnr_with_nightly"} | ({"is_allowed_security_level"} if server == "legacy" else set())
    nodes = [node for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(nodes) == len(names)
    exec(compile(ast.Module(nodes, []), str(path), "exec"), namespace)

    def enable(node_id="pack"):
        return asyncio.run(namespace["do_enable"](item(node_id)))

    return SimpleNamespace(enable=enable, enabled=enabled)


@pytest.mark.parametrize("server", ["glob", "legacy"])
@pytest.mark.parametrize("listener", LISTENERS)
@pytest.mark.parametrize("security_level", LEVELS)
def test_a_nightly_in_the_place_of_a_registry_version_needs_the_level_of_a_nightly_install(monkeypatch, server, security_level, listener):
    worker = load(monkeypatch, server, security_level, listener, **CNR_ENABLED_NIGHTLY_DISABLED)

    result = worker.enable()

    if nightly_install_allowed(security_level, listener):
        assert result == "success"
        assert worker.enabled == ["pack"]
    else:
        assert result == "failed"
        assert worker.enabled == []


@pytest.mark.parametrize("server", ["glob", "legacy"])
@pytest.mark.parametrize("listener", LISTENERS)
@pytest.mark.parametrize("security_level", LEVELS)
@pytest.mark.parametrize("versions", [
    dict(nightly_inactive={"pack": "custom_nodes/.disabled/pack@nightly"}),
    dict(cnr_inactive={"pack": {"1.0.0": "custom_nodes/.disabled/pack@1_0_0"}}),
    dict(active={"pack": ("nightly", "custom_nodes/pack")},
         cnr_inactive={"pack": {"1.0.0": "custom_nodes/.disabled/pack@1_0_0"}}),
    dict(active={"pack": ("1.0.0", "custom_nodes/pack")},
         cnr_inactive={"pack": {"0.9.0": "custom_nodes/.disabled/pack@0_9_0"}},
         nightly_inactive={"pack": "custom_nodes/.disabled/pack@nightly"}),
    dict(active={"pack": ("1.0.0", "custom_nodes/pack")}),
    dict(active={"pack": ("nightly", "custom_nodes/pack")}),
    dict(unknown_inactive={"pack": ("https://example.com/pack", "custom_nodes/.disabled/pack")}),
    dict(),
], ids=["a disabled nightly, nothing enabled", "a disabled registry version, nothing enabled",
        "a registry version in the place of a nightly", "another registry version, with a nightly disabled too",
        "a registry version enabled, nothing disabled", "a nightly enabled, nothing disabled",
        "a disabled pack without a version", "a pack that is not installed"])
def test_another_enable_is_not_held_to_a_level(monkeypatch, server, security_level, listener, versions):
    worker = load(monkeypatch, server, security_level, listener, **versions)

    assert worker.enable() == "success"
    assert worker.enabled == ["pack"]


@pytest.mark.parametrize("server", ["glob", "legacy"])
@pytest.mark.parametrize("node_id", ["other", "pack@nightly", "pack2", ""],
                         ids=["another pack", "with a version", "a longer name", "empty"])
def test_a_pack_that_the_manager_does_not_know_is_not_held_to_a_level(monkeypatch, server, node_id):
    worker = load(monkeypatch, server, "strong", "public", **CNR_ENABLED_NIGHTLY_DISABLED)

    assert worker.enable(node_id) == "success"
    assert worker.enabled == [node_id]


@pytest.mark.parametrize("listener", LISTENERS)
@pytest.mark.parametrize("security_level", LEVELS)
@pytest.mark.parametrize("node_id", ["Pack", "PACK", "pack ", " pack"],
                         ids=["capitalized", "upper case", "trailing space", "leading space"])
def test_the_glob_server_holds_the_pack_to_the_level_however_its_name_is_written(monkeypatch, security_level, listener, node_id):
    worker = load(monkeypatch, "glob", security_level, listener, **CNR_ENABLED_NIGHTLY_DISABLED)

    result = worker.enable(node_id)

    if nightly_install_allowed(security_level, listener):
        assert (result, worker.enabled) == ("success", [node_id])
    else:
        assert (result, worker.enabled) == ("failed", [])


@pytest.mark.parametrize("node_id", ["Pack", "pack "], ids=["capitalized", "trailing space"])
def test_to_the_legacy_server_a_name_written_otherwise_is_another_pack(monkeypatch, node_id):
    worker = load(monkeypatch, "legacy", "strong", "public", **CNR_ENABLED_NIGHTLY_DISABLED)

    assert worker.enable(node_id) == "success"
    assert worker.enabled == [node_id]
