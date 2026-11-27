import asyncio
import logging
import os
import shutil
from types import SimpleNamespace

import pytest
from aiohttp import web

from test_comfyui_downgrade_level import LEVELS, functions

SERVER = {"is_allowed_security_level", "security_403_response", "_reject_non_json_content_type", "restore_snapshot"}


def restore_allowed(security_level, loopback):
    return security_level == "weak" or security_level == "normal-" and loopback


@pytest.fixture
def server(tmp_path):
    snapshot = tmp_path / "snapshots" / "saved.json"
    snapshot.parent.mkdir()
    snapshot.write_text("{}", encoding="utf-8")
    scheduled = tmp_path / "startup-scripts" / "restore-snapshot.json"

    def restore(security_level, loopback, body={"target": "saved"}, content_type="application/json"):
        namespace = {
            "routes": web.RouteTableDef(), "web": web, "logging": logging, "os": os, "shutil": shutil,
            "is_local_mode": loopback,
            "core": SimpleNamespace(get_config=lambda: {"security_level": security_level},
                                    manager_startup_script_path=str(scheduled.parent)),
            "manager_migration": SimpleNamespace(has_system_user_api=lambda: True),
            "get_safe_snapshot_path": lambda target: str(snapshot) if target == "saved" else None,
        }
        exec(functions("manager_server.py", SERVER), namespace)

        async def read_json():
            return body

        response = asyncio.run(namespace["restore_snapshot"](SimpleNamespace(json=read_json, content_type=content_type)))
        return response.status, scheduled.exists()

    return restore


@pytest.mark.parametrize("loopback", [True, False], ids=["loopback", "not loopback"])
@pytest.mark.parametrize("security_level", LEVELS)
def test_a_restore_needs_the_level_of_a_switch_to_an_older_version(server, security_level, loopback):
    status, scheduled = server(security_level, loopback)

    if restore_allowed(security_level, loopback):
        assert (status, scheduled) == (200, True)
    else:
        assert (status, scheduled) == (403, False)


@pytest.mark.parametrize("loopback", [True, False], ids=["loopback", "not loopback"])
@pytest.mark.parametrize("security_level", LEVELS)
@pytest.mark.parametrize("body", [{"target": "another"}, {"target": ""}, {"target": None}, {}, {"target": ["saved"]}],
                         ids=["a snapshot that does not exist", "an empty name", "null", "no target", "a list"])
def test_a_request_for_no_snapshot_schedules_nothing_at_any_level(server, security_level, loopback, body):
    status, scheduled = server(security_level, loopback, body)

    assert status == (400 if restore_allowed(security_level, loopback) else 403)
    assert scheduled is False


@pytest.mark.parametrize("security_level", LEVELS)
@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "application/octet-stream"])
def test_a_body_that_is_not_json_is_refused_before_the_level(server, security_level, content_type):
    assert server(security_level, True, content_type=content_type) == (400, False)
