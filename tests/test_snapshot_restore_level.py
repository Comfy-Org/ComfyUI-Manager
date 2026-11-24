import asyncio
import importlib.util
import logging
import os
import shutil
import sys
from types import SimpleNamespace

import pytest
from aiohttp import web

from legacy_html_testutil import PACKAGE, load_functions

LEVELS = ["strong", "normal", "normal-", "weak"]
LISTENERS = ["loopback", "personal_cloud", "public"]
IS_LOOPBACK = {"glob": load_functions(PACKAGE / "common/manager_security.py", {"is_loopback"})["is_loopback"],
               "legacy": load_functions(PACKAGE / "legacy/manager_server.py", {"is_loopback"})["is_loopback"]}


def restore_allowed(security_level, listener):
    return security_level == "weak" and listener != "public" or security_level == "normal-" and listener == "loopback"


@pytest.fixture(params=["glob", "legacy"])
def server(request, monkeypatch, tmp_path):
    snapshot = tmp_path / "snapshots" / "saved.json"
    snapshot.parent.mkdir()
    snapshot.write_text("{}", encoding="utf-8")
    scheduled = tmp_path / "startup-scripts" / "restore-snapshot.json"
    package = PACKAGE / request.param

    def restore(security_level, listener, query={"target": "saved.json"}, listen=None):
        if listen is None:
            listen = "127.0.0.1" if listener == "loopback" else "0.0.0.0"
        core = SimpleNamespace(get_config=lambda: {
            "security_level": security_level,
            "network_mode": "personal_cloud" if listener == "personal_cloud" else "public"})
        files = SimpleNamespace(
            reject_non_json_post=lambda request: None,
            get_safe_file_path=lambda target, base: os.path.join(base, target) if target == "saved.json" else None)
        namespace = {
            "routes": web.RouteTableDef(), "web": web, "logging": logging, "os": os, "shutil": shutil, "core": core,
            "context": SimpleNamespace(manager_snapshot_path=str(snapshot.parent),
                                       manager_startup_script_path=str(scheduled.parent)),
            "SECURITY_MESSAGE_HIGH_P": "",
        }
        if request.param == "glob":
            spec = importlib.util.spec_from_file_location("_generated_models", PACKAGE / "data_models/generated_models.py")
            models = importlib.util.module_from_spec(spec)
            monkeypatch.setitem(sys.modules, spec.name, models)
            spec.loader.exec_module(models)
            security = load_functions(package / "utils/security_utils.py", {"is_allowed_security_level"}, {
                "core": core, "args": SimpleNamespace(listen=listen), "is_loopback": IS_LOOPBACK["glob"],
                "SecurityLevel": models.SecurityLevel, "RiskLevel": models.RiskLevel,
            })
            namespace["security_utils"] = SimpleNamespace(**vars(files), **security)
            names = {"restore_snapshot"}
        else:
            namespace.update(manager_security=files, is_local_mode=IS_LOOPBACK["legacy"](listen))
            names = {"restore_snapshot", "is_allowed_security_level"}
        load_functions(package / "manager_server.py", names, namespace)

        response = asyncio.run(namespace["restore_snapshot"](SimpleNamespace(rel_url=SimpleNamespace(query=query))))
        return response.status, scheduled.exists()

    return restore


@pytest.mark.parametrize("listener", LISTENERS)
@pytest.mark.parametrize("security_level", LEVELS)
def test_a_restore_needs_the_level_of_the_switch_route(server, security_level, listener):
    status, scheduled = server(security_level, listener)

    if restore_allowed(security_level, listener):
        assert (status, scheduled) == (200, True)
    else:
        assert (status, scheduled) == (403, False)


@pytest.mark.parametrize("listener", LISTENERS)
@pytest.mark.parametrize("security_level", LEVELS)
@pytest.mark.parametrize("query", [{"target": "another.json"}, {"target": ""}, {}],
                         ids=["a snapshot that does not exist", "an empty name", "no target"])
def test_a_request_for_no_snapshot_schedules_nothing_at_any_level(server, security_level, listener, query):
    status, scheduled = server(security_level, listener, query)

    assert status == (400 if restore_allowed(security_level, listener) else 403)
    assert scheduled is False


@pytest.mark.parametrize("listen, loopback", [
    ("127.0.0.1", True), ("127.0.0.2", True), ("::1", True), ("0.0.0.0", False), ("::", False), ("192.168.0.10", False),
    ("localhost", False), ("127.0.0.1,::1", False), ("", False)])
def test_the_listener_is_loopback_only_by_one_loopback_address_given_to_listen(server, listen, loopback):
    assert server("normal-", "public", listen=listen) == ((200, True) if loopback else (403, False))
