import ast
import asyncio
import json
import mimetypes
import os
import sys
from types import ModuleType, SimpleNamespace

import pytest
from aiohttp import web

from manager_test_utils import GLOB_DIR

MATRIX_ORG = "https://matrix.org"
SAVED = ("matrix.org", "user", "the saved password")
PASSWORDS_THAT_LOG_IN = {SAVED[2], "a new password"}
FUNCTIONS = ("is_matrix_org", "get_matrix_auth", "set_matrix_auth", "api_get_matrix_auth", "share_art")


class LoginResponse:
    access_token = "token"


class UploadResponse:
    content_uri = "mxc://test/asset"


@pytest.fixture
def manager(monkeypatch, tmp_path):
    logins = []

    class AsyncClient:
        def __init__(self, homeserver, username):
            self.homeserver, self.username = homeserver, username

        async def login(self, password):
            logins.append((self.homeserver, self.username, password))
            return LoginResponse() if password in PASSWORDS_THAT_LOG_IN else None

        async def upload(self, data, content_type=None, filename=None):
            return UploadResponse(), None

        async def room_send(self, **kwargs):
            pass

        async def close(self):
            pass

    nio = ModuleType("nio")
    nio.AsyncClient, nio.LoginResponse, nio.UploadResponse = AsyncClient, LoginResponse, UploadResponse
    monkeypatch.setitem(sys.modules, "nio", nio)

    files = tmp_path / "manager"
    output_dir = tmp_path / "output"
    files.mkdir()
    output_dir.mkdir()
    (output_dir / "a.png").write_bytes(b"output image")

    source = (GLOB_DIR / "share_3rdparty.py").read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCTIONS]
    assert len(nodes) == len(FUNCTIONS)
    namespace = {
        "PromptServer": SimpleNamespace(instance=SimpleNamespace(routes=web.RouteTableDef())),
        "folder_paths": SimpleNamespace(get_output_directory=lambda: str(output_dir),
                                        get_temp_directory=lambda: str(tmp_path / "temp")),
        "core": SimpleNamespace(manager_files_path=str(files)),
        "os": os, "web": web, "json": json, "mimetypes": mimetypes,
        "_reject_non_json_content_type": lambda request: None,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "share_3rdparty.py", "exec"), namespace)
    return SimpleNamespace(file=files / "matrix_auth", logins=logins, **{name: namespace[name] for name in FUNCTIONS})


def share(manager, matrix_auth, destinations=("matrix",)):
    body = {
        "matrix_auth": matrix_auth, "share_destinations": list(destinations),
        "credits": "", "title": "", "description": "", "prompt": {"workflow": {}}, "selected_output_index": 0,
        "potential_outputs": [{"type": "image", "image": {"filename": "a.png", "subfolder": "", "type": "output"}}],
    }

    async def read_json():
        return body

    try:
        return asyncio.run(manager.share_art(SimpleNamespace(json=read_json))).status
    except Exception:
        return 500


def account(homeserver=SAVED[0], username=SAVED[1], password=""):
    return {"homeserver": homeserver, "username": username, "password": password}


MATRIX_ORG_FORMS = ["matrix.org", "https://matrix.org", "http://matrix.org"]

OTHER_HOMESERVERS = [
    "matrix.example", "matrix.org.example", "sub.matrix.org", "matrix", "org", "Matrix.org", "MATRIX.ORG",
    "matrix.org/", "matrix.org.", " matrix.org", "matrix.org ", "matrix.org:8448", "matrix.org:443",
    "user@matrix.org", "matrix.org@other.example", "other.example/matrix.org", "other.example#matrix.org",
    "other.example?matrix.org", "https://other.example", "http://other.example", "https://https://matrix.org",
    "ftp://matrix.org", "//matrix.org", "matrix.org\\other.example", "matrix.org\nother.example", "127.0.0.1", "localhost:8188",
]


@pytest.mark.parametrize("text", [
    "matrix.org\nuser\nthe saved password",
    "matrix.org\nuser\nthe saved password\n",
    "\n\nmatrix.org\nuser\nthe saved password\n\n",
], ids=["three lines", "a final newline", "blank lines around"])
def test_the_answer_has_the_homeserver_and_the_username(manager, text):
    manager.file.write_text(text)

    response = asyncio.run(manager.api_get_matrix_auth(None))

    assert response.status == 200
    assert json.loads(response.text) == {"homeserver": "matrix.org", "username": "user"}


@pytest.mark.parametrize("text", [
    None, "", "matrix.org\nuser", "matrix.org\nuser\nthe saved password\nmore",
    "matrix.org\n\nthe saved password", "matrix.org\nuser\n", "\nuser\nthe saved password",
], ids=["no file", "an empty file", "two lines", "four lines", "an empty username", "an empty password",
        "an empty homeserver"])
def test_a_file_that_is_not_an_account_is_answered_as_nothing_saved(manager, text):
    if text is not None:
        manager.file.write_text(text)

    assert asyncio.run(manager.api_get_matrix_auth(None)).status == 404
    assert share(manager, account()) == 400
    assert manager.logins == [(MATRIX_ORG, "user", "")]


@pytest.mark.parametrize("homeserver", [h for h in OTHER_HOMESERVERS if h == h.strip() and "\n" not in h])
def test_an_account_saved_for_another_homeserver_is_not_used(manager, homeserver):
    text = "\n".join((homeserver, SAVED[1], SAVED[2]))
    manager.file.write_text(text)

    assert asyncio.run(manager.api_get_matrix_auth(None)).status == 404
    assert share(manager, account()) == 400
    assert manager.logins == [(MATRIX_ORG, "user", "")]
    assert manager.file.read_text() == text


@pytest.mark.parametrize("homeserver", MATRIX_ORG_FORMS[1:])
def test_matrix_org_saved_with_a_scheme_is_the_saved_account(manager, homeserver):
    text = "\n".join((homeserver, SAVED[1], SAVED[2]))
    manager.file.write_text(text)

    assert json.loads(asyncio.run(manager.api_get_matrix_auth(None)).text) == {"homeserver": homeserver, "username": "user"}
    assert share(manager, account()) == 200
    assert manager.logins == [(MATRIX_ORG, "user", SAVED[2])]


@pytest.mark.parametrize("password", ["", None], ids=["empty", "null"])
def test_no_password_for_the_saved_account_logs_in_with_the_saved_one(manager, password):
    manager.file.write_text("\n".join(SAVED))

    assert share(manager, account(password=password)) == 200
    assert manager.logins == [(MATRIX_ORG, "user", SAVED[2])]
    assert manager.file.read_text() == "\n".join(SAVED)


@pytest.mark.parametrize("matrix_auth", [
    *(account(homeserver) for homeserver in MATRIX_ORG_FORMS), {"username": "user", "password": ""},
], ids=[*MATRIX_ORG_FORMS, "no homeserver field"])
def test_matrix_org_is_logged_in_however_the_request_writes_it(manager, matrix_auth):
    manager.file.write_text("\n".join(SAVED))

    assert share(manager, matrix_auth) == 200
    assert manager.logins == [(MATRIX_ORG, "user", SAVED[2])]
    assert manager.file.read_text() == "\n".join(SAVED)


@pytest.mark.parametrize("homeserver", OTHER_HOMESERVERS + [""])
@pytest.mark.parametrize("password", ["", "a new password"], ids=["no password", "a password that logs in"])
def test_another_homeserver_is_refused_before_any_login(manager, homeserver, password):
    manager.file.write_text("\n".join(SAVED))

    assert share(manager, account(homeserver, password=password)) == 400
    assert manager.logins == []
    assert manager.file.read_text() == "\n".join(SAVED)


@pytest.mark.parametrize("username", ["User", "user ", " user", "user2", "use", ""],
                         ids=["upper case", "trailing space", "leading space", "longer", "shorter", "empty"])
def test_a_username_written_otherwise_is_another_account(manager, username):
    manager.file.write_text("\n".join(SAVED))

    assert share(manager, account(username=username)) == 400
    assert manager.logins == [(MATRIX_ORG, username, "")]
    assert manager.file.read_text() == "\n".join(SAVED)


@pytest.mark.parametrize("homeserver", MATRIX_ORG_FORMS)
def test_a_password_that_logs_in_replaces_the_saved_account(manager, homeserver):
    manager.file.write_text("\n".join(SAVED))

    assert share(manager, account(homeserver, "someone", "a new password")) == 200
    assert manager.logins == [(MATRIX_ORG, "someone", "a new password")]
    assert manager.file.read_text() == "matrix.org\nsomeone\na new password"


@pytest.mark.parametrize("password", ["a wrong password", " "], ids=["wrong", "a space"])
def test_a_password_that_does_not_log_in_leaves_the_saved_account(manager, password):
    manager.file.write_text("\n".join(SAVED))

    assert share(manager, account(password=password)) == 400
    assert manager.logins == [(MATRIX_ORG, "user", password)]
    assert manager.file.read_text() == "\n".join(SAVED)


@pytest.mark.parametrize("homeserver", ["matrix.org", "other.example"])
def test_sharing_without_matrix_leaves_the_saved_account(manager, homeserver):
    manager.file.write_text("\n".join(SAVED))

    assert share(manager, account(homeserver), destinations=()) == 200
    assert manager.logins == []
    assert manager.file.read_text() == "\n".join(SAVED)


@pytest.mark.parametrize("matrix_auth", [
    None, [], {}, {"homeserver": "matrix.org", "username": "user"},
    {"homeserver": None, "username": "user", "password": ""},
    {"homeserver": ["matrix.org"], "username": "user", "password": ""},
    {"homeserver": 1, "username": "user", "password": ""},
    {"homeserver": "matrix.org", "username": None, "password": None},
    {"homeserver": "matrix.org", "username": 1, "password": 0},
], ids=["null", "a list", "no fields", "no password field", "null homeserver", "a list as homeserver",
        "a number as homeserver", "null username", "numbers"])
def test_a_malformed_account_leaves_the_saved_account(manager, matrix_auth):
    manager.file.write_text("\n".join(SAVED))

    assert share(manager, matrix_auth) >= 400
    assert SAVED[2] not in [login[2] for login in manager.logins]
    assert all(login[0] == MATRIX_ORG for login in manager.logins)
    assert manager.file.read_text() == "\n".join(SAVED)


@pytest.mark.skipif(os.name == "nt", reason="the mode of a file is not kept on Windows")
@pytest.mark.parametrize("umask", [0o022, 0o002, 0o000])
@pytest.mark.parametrize("before", [None, 0o664, 0o644, 0o600], ids=["no file", "0664", "0644", "0600"])
def test_the_saved_account_is_a_file_of_its_user_only(manager, before, umask):
    if before is not None:
        manager.file.write_text("\n".join(SAVED))
        manager.file.chmod(before)
    previous = os.umask(umask)
    try:
        assert share(manager, account(username="someone", password="a new password")) == 200
    finally:
        os.umask(previous)

    assert manager.file.stat().st_mode & 0o777 == 0o600
    assert manager.file.read_text() == "matrix.org\nsomeone\na new password"


@pytest.mark.skipif(os.name == "nt", reason="the mode of a file is not kept on Windows")
def test_the_password_is_written_after_the_file_is_of_its_user_only(manager, monkeypatch):
    manager.file.write_text("\n".join(SAVED))
    manager.file.chmod(0o644)
    seen = []
    chmod = os.chmod

    def record(path, mode):
        chmod(path, mode)
        seen.append((manager.file.stat().st_mode & 0o777, manager.file.read_text()))

    monkeypatch.setattr(os, "chmod", record)

    assert share(manager, account(username="someone", password="a new password")) == 200
    assert seen == [(0o600, "\n".join(SAVED))]
    assert manager.file.read_text() == "matrix.org\nsomeone\na new password"


def test_a_file_whose_mode_cannot_be_set_is_saved_all_the_same(manager, monkeypatch):
    manager.file.write_text("\n".join(SAVED))

    def refuse(path, mode):
        raise PermissionError(1, "Operation not permitted", str(path))

    monkeypatch.setattr(os, "chmod", refuse)

    assert share(manager, account(username="someone", password="a new password")) == 200
    assert manager.file.read_text() == "matrix.org\nsomeone\na new password"


@pytest.mark.skipif(os.name == "nt", reason="the mode of a file is not kept on Windows")
def test_a_new_file_is_of_its_user_only_from_the_moment_it_is_made(manager, monkeypatch):
    seen = []
    monkeypatch.setattr(os, "chmod", lambda path, mode: seen.append(manager.file.stat().st_mode & 0o777))
    previous = os.umask(0)
    try:
        assert share(manager, account(username="someone", password="a new password")) == 200
    finally:
        os.umask(previous)

    assert seen == [0o600]
    assert manager.file.stat().st_mode & 0o777 == 0o600


def test_a_shorter_account_replaces_a_longer_one_whole(manager):
    manager.file.write_text("matrix.org\n" + "a" * 200 + "\nthe saved password")

    assert share(manager, account(username="someone", password="a new password")) == 200
    assert manager.file.read_text() == "matrix.org\nsomeone\na new password"
