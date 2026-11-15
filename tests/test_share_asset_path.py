"""The share route uploads only a file inside the output or temp directory (#3427).

Each case runs the real `share_art` against a recording Matrix client, which stands in for
the `nio` module. The filename and the subfolder of the selected output come from the request.
"""
import ast
import asyncio
import json
import mimetypes
import ntpath
import os
import sys
from types import ModuleType, SimpleNamespace

import pytest
from aiohttp import web

from manager_test_utils import GLOB_DIR

SECRET = b"not an output"


class LoginResponse:
    access_token = "token"


class UploadResponse:
    content_uri = "mxc://test/asset"


def load_share_art(monkeypatch, output_dir, temp_dir, os_module: object = os):
    """Returns `share_art` and the list that receives (homeserver, uploaded bytes)."""
    uploads = []

    class AsyncClient:
        def __init__(self, homeserver, username):
            self.homeserver = homeserver

        async def login(self, password):
            return LoginResponse()

        async def upload(self, data, content_type=None, filename=None):
            uploads.append((self.homeserver, data.read()))
            return UploadResponse(), None

        async def room_send(self, **kwargs):
            pass

        async def close(self):
            pass

    nio = ModuleType("nio")
    nio.AsyncClient, nio.LoginResponse, nio.UploadResponse = AsyncClient, LoginResponse, UploadResponse
    monkeypatch.setitem(sys.modules, "nio", nio)

    source = (GLOB_DIR / "share_3rdparty.py").read_text(encoding="utf-8")
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, ast.AsyncFunctionDef) and node.name == "share_art"]
    assert len(nodes) == 1
    namespace = {
        "PromptServer": SimpleNamespace(instance=SimpleNamespace(routes=web.RouteTableDef())),
        "folder_paths": SimpleNamespace(get_output_directory=lambda: str(output_dir),
                                        get_temp_directory=lambda: str(temp_dir)),
        "os": os_module, "web": web, "json": json, "mimetypes": mimetypes,
        "set_matrix_auth": lambda matrix_auth: None,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "share_3rdparty.py", "exec"), namespace)
    return namespace["share_art"], uploads


def share(share_art, output):
    body = {
        "matrix_auth": {"homeserver": "matrix.example", "username": "user", "password": "password"},
        "share_destinations": ["matrix"], "credits": "", "title": "", "description": "",
        "prompt": {"workflow": {}}, "potential_outputs": [output], "selected_output_index": 0,
    }

    async def read_json():
        return body

    return asyncio.run(share_art(SimpleNamespace(json=read_json)))


def image(filename, subfolder="", type="output"):
    return {"type": "image", "image": {"filename": filename, "subfolder": subfolder, "type": type}}


@pytest.fixture
def dirs(tmp_path):
    output_dir = tmp_path / "output"
    temp_dir = tmp_path / "temp"
    (output_dir / "sub").mkdir(parents=True)
    temp_dir.mkdir()
    (output_dir / "a.png").write_bytes(b"output image")
    (output_dir / "sub" / "b.png").write_bytes(b"image in a subfolder")
    (temp_dir / "c.png").write_bytes(b"preview image")
    (tmp_path / "secret.txt").write_bytes(SECRET)
    (tmp_path / "output-other").mkdir()
    (tmp_path / "output-other" / "d.png").write_bytes(SECRET)
    return output_dir, temp_dir


@pytest.mark.parametrize("output, content", [
    (image("a.png"), b"output image"),
    (image("b.png", "sub"), b"image in a subfolder"),
    (image("c.png", type="temp"), b"preview image"),
    ({"type": "output", "output": {"filename": "b.png", "subfolder": "sub"}}, b"image in a subfolder"),
])
def test_a_file_in_the_directory_is_shared(monkeypatch, dirs, output, content):
    share_art, uploads = load_share_art(monkeypatch, *dirs)

    response = share(share_art, output)

    assert response.status == 200
    assert uploads[0] == ("https://matrix.example", content)


@pytest.mark.parametrize("output", [
    image("../secret.txt"),
    image("secret.txt", ".."),
    image("secret.txt", "sub/../.."),
    image("d.png", "../output-other"),  # a sibling whose name starts with the directory's name
    image("a.png", "../output", type="temp"),  # the output directory is not inside the temp directory
    {"type": "output", "output": {"filename": "../secret.txt", "subfolder": ""}},
])
def test_a_path_that_leaves_the_directory_is_refused(monkeypatch, dirs, output):
    share_art, uploads = load_share_art(monkeypatch, *dirs)

    response = share(share_art, output)

    assert response.status == 400
    assert "output directory" in json.loads(response.body)["error"]
    assert uploads == []


def test_an_absolute_path_is_refused(monkeypatch, dirs, tmp_path):
    share_art, uploads = load_share_art(monkeypatch, *dirs)

    response = share(share_art, image(str(tmp_path / "secret.txt"), "sub"))

    assert response.status == 400
    assert uploads == []


def test_a_symlink_that_the_user_placed_in_the_directory_is_followed(monkeypatch, dirs, tmp_path):
    """ComfyUI's /view shows such a file, so the image that the dialog previews can be shared."""
    output_dir, _ = dirs
    elsewhere = tmp_path / "another-disk"
    elsewhere.mkdir()
    (elsewhere / "e.png").write_bytes(b"image on another disk")
    try:
        (output_dir / "link").symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create a symlink here")
    share_art, uploads = load_share_art(monkeypatch, *dirs)

    response = share(share_art, image("e.png", "link"))

    assert response.status == 200
    assert uploads[0][1] == b"image on another disk"


def test_the_path_that_was_checked_is_the_path_that_is_read(monkeypatch, dirs, tmp_path):
    """`link/..` is the output directory once normalized, and the parent of the link's target on disk."""
    output_dir, _ = dirs
    elsewhere = tmp_path / "another-disk"
    elsewhere.mkdir()
    (tmp_path / "a.png").write_bytes(SECRET)
    try:
        (output_dir / "link").symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create a symlink here")
    share_art, uploads = load_share_art(monkeypatch, *dirs)

    response = share(share_art, image("a.png", "link/.."))

    assert response.status == 200
    assert uploads[0][1] == b"output image"


def test_a_path_on_another_windows_drive_is_refused(monkeypatch):
    """`os.path.commonpath` raises ValueError for paths on different drives."""
    windows = SimpleNamespace(path=ntpath)
    share_art, uploads = load_share_art(monkeypatch, r"C:\ComfyUI\output", r"C:\ComfyUI\temp", os_module=windows)

    for output in (image(r"D:\secret.txt"), image("secret.txt", "D:\\"), image(r"\\server\share\secret.txt")):
        response = share(share_art, output)

        assert response.status == 400
        assert uploads == []
