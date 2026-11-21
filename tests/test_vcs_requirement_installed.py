"""A 'git+https://…' requirement line must be recognized as already installed.

`parse_pip_spec` cannot name the distribution of a bare VCS URL — the repo may
install a dist whose name differs from the repo name (sam2 installs SAM-2) —
so the name-based `is_installed` check never saw it, and pip re-cloned the
repo on every startup (issue #3575). The fix matches the requirement against
the install origin pip records in each distribution's direct_url.json.
"""

from types import SimpleNamespace

from manager_test_utils import load_manager_util


class FakeDist:
    def __init__(self, direct_url):
        self._direct_url = direct_url

    def read_text(self, filename):
        if filename == "direct_url.json" and self._direct_url is not None:
            return self._direct_url
        return None


def test_direct_url_repo_normalizes_vcs_urls():
    module = load_manager_util()
    assert module.direct_url_repo("git+https://GitHub.com/facebookresearch/sam2") == ("github.com", "facebookresearch/sam2")
    assert module.direct_url_repo("git+https://github.com/facebookresearch/sam2.git") == ("github.com", "facebookresearch/sam2")
    assert module.direct_url_repo("git+https://github.com/facebookresearch/sam2@v1.0") == ("github.com", "facebookresearch/sam2")
    assert module.direct_url_repo("git+ssh://git@github.com/facebookresearch/sam2") == ("github.com", "facebookresearch/sam2")


def test_direct_url_repo_rejects_non_urls():
    module = load_manager_util()
    assert module.direct_url_repo("sam2") is None
    assert module.direct_url_repo("./local/path") is None
    assert module.direct_url_repo("") is None
    assert module.direct_url_repo("ftp://github.com/a/b") is None


def test_vcs_requirement_installed_matches_pip_recorded_origin(monkeypatch):
    module = load_manager_util()

    dists = [
        # an unrelated PyPI package: no direct_url.json at all
        FakeDist(None),
        # the sam2 clone: pip recorded the origin URL, dist name differs from repo name
        FakeDist('{"url": "https://github.com/facebookresearch/sam2", "vcs_info": {"vcs": "git", "commit_id": "abc"}}'),
    ]
    monkeypatch.setattr(module.importlib.metadata, "distributions", lambda: dists)

    assert module.vcs_requirement_installed("git+https://github.com/facebookresearch/sam2") is True
    assert module.vcs_requirement_installed("git+https://github.com/facebookresearch/sam2.git#egg=sam2") is True


def test_vcs_requirement_installed_false_when_origin_differs(monkeypatch):
    module = load_manager_util()
    dists = [FakeDist('{"url": "https://github.com/someone-else/other-repo"}')]
    monkeypatch.setattr(module.importlib.metadata, "distributions", lambda: dists)

    assert module.vcs_requirement_installed("git+https://github.com/facebookresearch/sam2") is False


def test_vcs_requirement_installed_false_with_no_dists(monkeypatch):
    module = load_manager_util()
    monkeypatch.setattr(module.importlib.metadata, "distributions", lambda: [])

    assert module.vcs_requirement_installed("git+https://github.com/facebookresearch/sam2") is False


def test_is_installed_bare_vcs_line_uses_origin_match(monkeypatch):
    """The prestartup guard routes a bare VCS line through the origin match.

    The guard is compiled from source the same way the pip-name guards test
    it, so the production body is what runs here.
    """
    import ast
    import re

    from manager_test_utils import GLOB_DIR

    module = load_manager_util()
    inventory = "Package Version\n------- -------\nSAM-2 1.0\n"
    monkeypatch.setattr(module.subprocess, "check_output", lambda *args, **kwargs: inventory)

    path = GLOB_DIR.resolve().parent / "prestartup_script.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "is_installed")
    config = SimpleNamespace(pip_blacklist=set(), pip_downgrade_blacklist=set())
    namespace = {"re": re, "cm_global": config, "manager_util": module}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    is_installed = namespace["is_installed"]

    monkeypatch.setattr(module, "vcs_requirement_installed", lambda spec: spec.startswith("git+https://github.com/facebookresearch/sam2"))
    assert is_installed("git+https://github.com/facebookresearch/sam2") is True
    assert is_installed("git+https://github.com/someone/other") is False
    # a name-based requirement still goes through the inventory, unchanged
    assert is_installed("SAM-2") is True
    assert is_installed("numpy==9.9.9") is False
