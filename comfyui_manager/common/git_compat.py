"""
git_compat.py — Compatibility layer for git operations in ComfyUI-Manager.

Wraps either GitPython (`git` module) or `pygit2`, depending on availability
and the CM_USE_PYGIT2 environment variable (set by Desktop 2.0 Launcher).

Exports:
    USE_PYGIT2          — bool: which backend is active
    GitCommandError     — exception class for git command failures
    open_repo(path)     — returns a repo wrapper object
    clone_repo(url, dest, progress=None) — clone a repository
    get_comfyui_tag(repo_path) — get describe --tags output
    setup_git_environment(git_exe) — configure git executable path
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone, timedelta


# Snapshot of the user's global `http.proxy` (captured before the config
# search path is blanked under the pygit2 backend) so corporate proxy
# settings survive and can be passed explicitly to fetch/clone. None means
# "no proxy".
_HTTP_PROXY = None


def _to_https_url(url):
    """Rewrite an SSH-form git URL to its anonymous HTTPS equivalent.

    Handles `git@host:owner/repo(.git)` and `ssh://git@host[:port]/owner/repo(.git)`.
    A custom SSH port is dropped — the HTTPS endpoint of a hosting service
    lives on the standard port regardless of its SSH port. Leading slashes in
    the path part are collapsed so `git@host:/abs/path` does not yield a
    double-slash URL. Returns the URL unchanged if it is not SSH-form, so
    pygit2 clone/fetch of public repos never requires SSH credentials even
    when a repo's own config stores an SSH origin.
    """
    if not url:
        return url
    m = re.match(r"^ssh://git@([^:/]+)(?::\d+)?/(.+)$", url)
    if m is None:
        m = re.match(r"^git@([^:/]+):(.+)$", url)
    if m:
        return "https://%s/%s" % (m.group(1), m.group(2).lstrip("/"))
    return url

# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def which_on_path(name):
    """Return the file that the directories of PATH give for a command name.

    `shutil.which` looks in the current directory first on Windows, and takes
    a directory of PATH that is not absolute.
    """
    names = [name]
    if os.name == 'nt':
        extensions = [x for x in os.environ.get('PATHEXT', '.COM;.EXE;.BAT;.CMD').split(os.pathsep) if x]
        if not name.lower().endswith(tuple(x.lower() for x in extensions)):
            names = [name + x for x in extensions]

    for directory in os.get_exec_path():
        for x in names:
            path = os.path.join(directory, x)
            if os.path.isabs(directory) and os.path.isfile(path) and os.access(path, os.X_OK):
                return path

    return None


def find_git_executable(git_exe, timeout=10):
    # A name without a directory is a command of PATH; GitPython would take it
    # as a file of the current directory.
    path = shutil.which(git_exe) if os.path.dirname(git_exe) else which_on_path(git_exe)
    if path is None:
        return None

    try:
        # The answer goes to a file: with a pipe, Windows waits after the time
        # is up for every program that holds the pipe.
        with tempfile.TemporaryFile() as answer:
            res = subprocess.run([path, 'version'], stdout=answer, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, timeout=timeout)
            answer.seek(0)
            is_git = res.returncode == 0 and answer.read(11) == b'git version'
    except (OSError, subprocess.SubprocessError):
        return None

    return os.path.abspath(path) if is_git else None


_PYGIT2_REQUESTED = os.environ.get('CM_USE_PYGIT2', '').strip() == '1'
USE_PYGIT2 = _PYGIT2_REQUESTED

_GIT_EXE = os.environ.get('GIT_EXE_PATH')
_GIT_EXE_FOUND = None


def _find_configured_git():
    found = find_git_executable(_GIT_EXE)
    if found is not None:
        os.environ['GIT_PYTHON_GIT_EXECUTABLE'] = found
    else:
        print(f"[ComfyUI-Manager] `git_exe = {_GIT_EXE}` is not a working git executable. The default git is used.", file=sys.stderr)
    return found


if not USE_PYGIT2 and _GIT_EXE:
    _GIT_EXE_FOUND = _find_configured_git()

if not USE_PYGIT2:
    try:
        import git as _git
        _git.Git().execute([_git.Git.GIT_PYTHON_GIT_EXECUTABLE, '--version'])
    except Exception:
        USE_PYGIT2 = True

if USE_PYGIT2:
    # Without a git, GitPython raises already when it is imported, unless it
    # is told to keep quiet. The legacy modules import it themselves.
    os.environ.setdefault('GIT_PYTHON_REFRESH', 'quiet')

    try:
        import pygit2 as _pygit2
    except ImportError:
        # pygit2 not available either — fall back to GitPython and let it
        # fail at the point of use.
        USE_PYGIT2 = False
        if _PYGIT2_REQUESTED and _GIT_EXE:
            _GIT_EXE_FOUND = _find_configured_git()
        _PYGIT2_REQUESTED = False
        import git as _git
        if not _git.GIT_OK:
            print("[ComfyUI-Manager] No git executable was found and pygit2 is not installed. What needs git will fail.", file=sys.stderr)
    else:
        # Disable owner validation once at import time.
        # Required for Desktop 2.0 standalone installs where repo directories
        # may be owned by a different user (e.g., system-installed paths).
        # See CVE-2022-24765 for context on this validation.
        _pygit2.option(_pygit2.GIT_OPT_SET_OWNER_VALIDATION, 0)

        # Snapshot the global http.proxy BEFORE blanking the config search
        # path, so a corporate proxy survives and can be passed explicitly
        # to clone/fetch below.
        try:
            _global_cfg = _pygit2.Config.get_global_config()
            try:
                _HTTP_PROXY = _global_cfg["http.proxy"] or None
            except Exception:
                _HTTP_PROXY = None
        except Exception:
            _HTTP_PROXY = None

        # Ignore system/global/XDG git config for libgit2 operations. A
        # user's global config can carry `insteadOf` rewrites (e.g.
        # https->ssh) or credential helpers that force authentication,
        # which libgit2 cannot satisfy without a credentials callback
        # ("authentication required but no callback set"). The bundled
        # pygit2 has no SSH transport, so an SSH rewrite can never succeed;
        # blanking the config search path keeps clone/fetch on anonymous
        # HTTPS.
        try:
            from pygit2.enums import ConfigLevel as _ConfigLevel
            _cfg_levels = [_ConfigLevel.SYSTEM, _ConfigLevel.XDG, _ConfigLevel.GLOBAL]
        except (ImportError, AttributeError):
            _cfg_levels = [
                _pygit2.GIT_CONFIG_LEVEL_SYSTEM,
                _pygit2.GIT_CONFIG_LEVEL_XDG,
                _pygit2.GIT_CONFIG_LEVEL_GLOBAL,
            ]
        for _lvl in _cfg_levels:
            try:
                _pygit2.settings.search_path[_lvl] = ""
            except Exception:
                pass

if not USE_PYGIT2:
    import git as _git

# ---------------------------------------------------------------------------
# Shared exception type
# ---------------------------------------------------------------------------

if USE_PYGIT2:
    class GitCommandError(Exception):
        """Stand-in for git.GitCommandError when using pygit2 backend."""
        pass
else:
    from git import GitCommandError  # noqa: F401

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

if USE_PYGIT2:
    if _PYGIT2_REQUESTED:
        print("[ComfyUI-Manager] Using pygit2 backend (CM_USE_PYGIT2=1)")
    else:
        print("[ComfyUI-Manager] Using pygit2 backend (system git not available)")
else:
    print("[ComfyUI-Manager] Using GitPython backend")


# ===================================================================
# Abstract base class
# ===================================================================

class GitRepo(ABC):
    """Abstract interface for git repository operations."""

    @property
    @abstractmethod
    def working_dir(self) -> str: ...

    @property
    @abstractmethod
    def head_commit_hexsha(self) -> str: ...

    @property
    @abstractmethod
    def head_is_detached(self) -> bool: ...

    @property
    @abstractmethod
    def head_commit_datetime(self): ...

    @property
    @abstractmethod
    def active_branch_name(self) -> str: ...

    @abstractmethod
    def is_dirty(self) -> bool: ...

    @abstractmethod
    def get_tracking_remote_name(self) -> str: ...

    @abstractmethod
    def get_remote(self, name: str): ...

    @abstractmethod
    def has_ref(self, ref_name: str) -> bool: ...

    @abstractmethod
    def get_ref_commit_hexsha(self, ref_name: str) -> str: ...

    @abstractmethod
    def get_ref_commit_datetime(self, ref_name: str): ...

    @abstractmethod
    def list_remotes(self) -> list: ...

    @abstractmethod
    def get_remote_url(self, index_or_name) -> str: ...

    @abstractmethod
    def iter_commits_count(self) -> int: ...

    @abstractmethod
    def symbolic_ref(self, ref: str) -> str: ...

    @abstractmethod
    def describe_tags(self, exact_match=False): ...

    @abstractmethod
    def list_tags(self) -> list: ...

    @abstractmethod
    def list_heads(self) -> list: ...

    @abstractmethod
    def list_branches(self) -> list: ...

    @abstractmethod
    def get_head_by_name(self, name: str): ...

    @abstractmethod
    def head_commit_equals(self, other_commit) -> bool: ...

    @abstractmethod
    def get_ref_object(self, ref_name: str): ...

    @abstractmethod
    def stash(self): ...

    @abstractmethod
    def pull_ff_only(self): ...

    @abstractmethod
    def reset_hard(self, ref: str): ...

    @abstractmethod
    def create_backup_branch(self, name: str): ...

    @abstractmethod
    def checkout(self, ref): ...

    @abstractmethod
    def checkout_new_branch(self, branch_name: str, start_point: str): ...

    @abstractmethod
    def submodule_update(self, init=True): ...

    def undo_pull(self, commit):
        self.reset_hard(commit)
        try:
            self.submodule_update(init=False)
        except Exception:
            pass

    @abstractmethod
    def clear_cache(self): ...

    @abstractmethod
    def fetch_remote_by_index(self, index): ...

    @abstractmethod
    def pull_remote_by_index(self, index): ...

    @abstractmethod
    def close(self): ...

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ===================================================================
# Helper types for tag/head/ref proxies
# ===================================================================

class _TagProxy:
    """Mimics a GitPython tag reference: .name and .commit."""
    def __init__(self, name, commit_obj):
        self.name = name
        self.commit = commit_obj


class _HeadProxy:
    """Mimics a GitPython head reference: .name and .commit."""
    def __init__(self, name, commit_obj=None):
        self.name = name
        self.commit = commit_obj


class _RefProxy:
    """Mimics a GitPython ref: .object.hexsha, .object.committed_datetime, .reference.commit."""
    def __init__(self, hexsha, committed_datetime, commit_obj=None):
        self.object = type('obj', (), {
            'hexsha': hexsha,
            'committed_datetime': committed_datetime,
        })()
        self.reference = type('ref', (), {'commit': commit_obj})() if commit_obj is not None else None


class _RemoteProxy:
    """Mimics a GitPython remote: .name, .url, .fetch(), .pull()."""
    def __init__(self, name, url, fetch_fn, pull_fn=None):
        self.name = name
        self.url = url
        self._fetch = fetch_fn
        self._pull = pull_fn

    def fetch(self):
        return self._fetch()

    def pull(self):
        if self._pull is not None:
            return self._pull()
        raise GitCommandError("pull not supported on this remote")


# ===================================================================
# GitPython wrapper — 1:1 pass-throughs
# ===================================================================

class _GitPythonRepo(GitRepo):
    def __init__(self, path):
        self._repo = _git.Repo(path)

    @property
    def working_dir(self):
        return self._repo.working_dir

    @property
    def head_commit_hexsha(self):
        return self._repo.head.commit.hexsha

    @property
    def head_is_detached(self):
        return self._repo.head.is_detached

    @property
    def head_commit_datetime(self):
        return self._repo.head.commit.committed_datetime

    @property
    def active_branch_name(self):
        return self._repo.active_branch.name

    def is_dirty(self):
        return self._repo.is_dirty()

    def get_tracking_remote_name(self):
        return self._repo.active_branch.tracking_branch().remote_name

    def get_remote(self, name):
        r = self._repo.remote(name=name)
        return _RemoteProxy(r.name, r.url, r.fetch, getattr(r, 'pull', None))

    def has_ref(self, ref_name):
        return ref_name in self._repo.refs

    def get_ref_commit_hexsha(self, ref_name):
        return self._repo.refs[ref_name].object.hexsha

    def get_ref_commit_datetime(self, ref_name):
        return self._repo.refs[ref_name].object.committed_datetime

    def list_remotes(self):
        return [_RemoteProxy(r.name, r.url, r.fetch, getattr(r, 'pull', None))
                for r in self._repo.remotes]

    def get_remote_url(self, index_or_name):
        if isinstance(index_or_name, int):
            return self._repo.remotes[index_or_name].url
        return self._repo.remote(name=index_or_name).url

    def iter_commits_count(self):
        return len(list(self._repo.iter_commits('HEAD')))

    def symbolic_ref(self, ref):
        return self._repo.git.symbolic_ref(ref)

    def describe_tags(self, exact_match=False):
        try:
            if exact_match:
                return self._repo.git.describe('--tags', '--exact-match')
            else:
                return self._repo.git.describe('--tags')
        except Exception:
            return None

    def list_tags(self):
        return [_TagProxy(t.name, t.commit) for t in self._repo.tags]

    def list_heads(self):
        return [_HeadProxy(h.name, h.commit) for h in self._repo.heads]

    def list_branches(self):
        return [_HeadProxy(b.name, b.commit) for b in self._repo.branches]

    def get_head_by_name(self, name):
        head = getattr(self._repo.heads, name)
        return _HeadProxy(head.name, head.commit)

    def head_commit_equals(self, other_commit):
        return self._repo.head.commit == other_commit

    def get_ref_object(self, ref_name):
        ref = self._repo.refs[ref_name]
        try:
            ref_commit = ref.reference.commit
        except (TypeError, AttributeError):
            ref_commit = ref.object
        return _RefProxy(
            ref.object.hexsha,
            ref.object.committed_datetime,
            commit_obj=ref_commit,
        )

    def stash(self):
        self._repo.git.stash()

    def pull_ff_only(self):
        self._repo.git.pull('--ff-only')

    def reset_hard(self, ref):
        self._repo.git.reset('--hard', ref)

    def create_backup_branch(self, name):
        self._repo.create_head(name)

    def checkout(self, ref):
        # ref can be a _HeadProxy from get_head_by_name
        if isinstance(ref, _HeadProxy):
            ref = ref.name

        self._repo.git.checkout(ref)

    def checkout_new_branch(self, branch_name, start_point):
        self._repo.git.checkout('-b', branch_name, start_point)

    def submodule_update(self, init=True):
        self._repo.git.submodule('update', *(['--init'] if init else []), '--recursive')

    def clear_cache(self):
        self._repo.git.clear_cache()

    def fetch_remote_by_index(self, index):
        self._repo.remotes[index].fetch()

    def pull_remote_by_index(self, index):
        self._repo.remotes[index].pull()

    def close(self):
        self._repo.close()


# ===================================================================
# Pygit2 wrapper
# ===================================================================

def _remote_callbacks():
    """The callbacks of a clone or a fetch, without the one for the progress messages of the server.

    pygit2 decodes each piece of such a message as UTF-8 before it calls that one, and a piece can end
    in the middle of a character: the clone or the fetch then ended with UnicodeDecodeError.
    """
    callbacks = _pygit2.RemoteCallbacks()
    callbacks.sideband_progress = None
    return callbacks


class _Pygit2Repo(GitRepo):
    def __init__(self, path):
        repo_path = os.path.abspath(path)
        git_dir = os.path.join(repo_path, '.git')
        for sub in ['refs/heads', 'refs/tags', 'refs/remotes']:
            try:
                os.makedirs(os.path.join(git_dir, sub), exist_ok=True)
            except OSError:
                pass
        self._repo = _pygit2.Repository(git_dir)
        self._working_dir = repo_path

    def _fetch_remote(self, remote, refspecs=None):
        """Fetch *remote* over the preserved proxy, transparently rewriting an
        SSH-form origin to anonymous HTTPS in memory.

        The bundled pygit2 has no SSH transport, so a stored `git@host:...`
        origin would fail with an auth error. When the URL is SSH-form we fetch
        through an in-memory anonymous remote over HTTPS, leaving `.git/config`
        untouched (no on-disk rewrite).
        """
        https_url = _to_https_url(remote.url)
        if https_url != remote.url:
            anon = self._repo.remotes.create_anonymous(https_url)
            anon.fetch(
                list(refspecs) if refspecs is not None
                else list(remote.fetch_refspecs),
                proxy=_HTTP_PROXY, callbacks=_remote_callbacks(),
            )
        elif refspecs is not None:
            remote.fetch(list(refspecs), proxy=_HTTP_PROXY, callbacks=_remote_callbacks())
        else:
            remote.fetch(proxy=_HTTP_PROXY, callbacks=_remote_callbacks())

    @property
    def working_dir(self):
        return self._working_dir

    @property
    def head_commit_hexsha(self):
        return str(self._repo.head.peel(_pygit2.Commit).id)

    @property
    def head_is_detached(self):
        return self._repo.head_is_detached

    @property
    def head_commit_datetime(self):
        commit = self._repo.head.peel(_pygit2.Commit)
        ts = commit.commit_time
        offset_minutes = commit.commit_time_offset
        tz = timezone(timedelta(minutes=offset_minutes))
        return datetime.fromtimestamp(ts, tz=tz)

    @property
    def active_branch_name(self):
        ref = self._repo.head.name
        if ref.startswith('refs/heads/'):
            return ref[len('refs/heads/'):]
        return ref

    def is_dirty(self):
        st = self._repo.status()
        for flags in st.values():
            if flags == _pygit2.GIT_STATUS_CURRENT:
                continue
            if flags == _pygit2.GIT_STATUS_IGNORED:
                continue
            if flags == _pygit2.GIT_STATUS_WT_NEW:
                continue
            return True
        return False

    def get_tracking_remote_name(self):
        branch = self._repo.branches.get(self.active_branch_name)
        if branch is None:
            raise GitCommandError("Cannot determine tracking branch: HEAD is detached or branch not found")
        upstream = branch.upstream
        if upstream is None:
            raise GitCommandError(f"No upstream configured for branch '{self.active_branch_name}'")
        # upstream.name can be "origin/master" or "refs/remotes/origin/master"
        name = upstream.name
        if name.startswith('refs/remotes/'):
            name = name[len('refs/remotes/'):]
        return name.split('/')[0]

    def _pull_remote(self, remote):
        """Fetch *remote* and fast-forward the active branch onto its upstream."""
        self._fetch_remote(remote)
        branch_name = self.active_branch_name
        branch = self._repo.branches.get(branch_name)
        if branch and branch.upstream:
            remote_commit = branch.upstream.peel(_pygit2.Commit)
            analysis, _ = self._repo.merge_analysis(remote_commit.id)
            if analysis & _pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD:
                self._repo.checkout_tree(self._repo.get(remote_commit.id))
                branch_ref = self._repo.references.get(f'refs/heads/{branch_name}')
                if branch_ref is not None:
                    branch_ref.set_target(remote_commit.id)
                self._repo.head.set_target(remote_commit.id)

    def get_remote(self, name):
        remote = self._repo.remotes[name]
        return _RemoteProxy(remote.name, remote.url,
                            lambda: self._fetch_remote(remote),
                            lambda: self._pull_remote(remote))

    def has_ref(self, ref_name):
        for prefix in [f'refs/remotes/{ref_name}', f'refs/heads/{ref_name}',
                        f'refs/tags/{ref_name}', ref_name]:
            try:
                if self._repo.references.get(prefix) is not None:
                    return True
            except Exception:
                pass
        return False

    def _resolve_ref(self, ref_name):
        for prefix in [f'refs/remotes/{ref_name}', f'refs/heads/{ref_name}',
                        f'refs/tags/{ref_name}', ref_name]:
            ref = self._repo.references.get(prefix)
            if ref is not None:
                return ref.peel(_pygit2.Commit)
        raise GitCommandError(f"Reference not found: {ref_name}")

    def get_ref_commit_hexsha(self, ref_name):
        return str(self._resolve_ref(ref_name).id)

    def get_ref_commit_datetime(self, ref_name):
        commit = self._resolve_ref(ref_name)
        ts = commit.commit_time
        offset_minutes = commit.commit_time_offset
        tz = timezone(timedelta(minutes=offset_minutes))
        return datetime.fromtimestamp(ts, tz=tz)

    def list_remotes(self):
        result = []
        for r in self._repo.remotes:
            result.append(_RemoteProxy(r.name, r.url,
                                       lambda r=r: self._fetch_remote(r),
                                       lambda r=r: self._pull_remote(r)))
        return result

    def get_remote_url(self, index_or_name):
        if isinstance(index_or_name, int):
            remotes = list(self._repo.remotes)
            return remotes[index_or_name].url
        return self._repo.remotes[index_or_name].url

    def iter_commits_count(self):
        count = 0
        head_commit = self._repo.head.peel(_pygit2.Commit)
        visited = set()
        queue = deque([head_commit.id])
        while queue:
            oid = queue.popleft()
            if oid in visited:
                continue
            visited.add(oid)
            count += 1
            commit = self._repo.get(oid)
            if commit is not None:
                for parent_id in commit.parent_ids:
                    if parent_id not in visited:
                        queue.append(parent_id)
        return count

    def symbolic_ref(self, ref):
        git_dir = self._repo.path
        ref_file = os.path.join(git_dir, ref)
        if os.path.isfile(ref_file):
            with open(ref_file, 'r') as f:
                content = f.read().strip()
            if content.startswith('ref: '):
                return content[5:]
            return content
        ref_obj = self._repo.references.get(ref)
        if ref_obj is not None and ref_obj.type == _pygit2.GIT_REFERENCE_SYMBOLIC:
            return ref_obj.target
        raise GitCommandError(f"Not a symbolic reference: {ref}")

    def describe_tags(self, exact_match=False):
        try:
            if exact_match:
                head_oid = self._repo.head.peel(_pygit2.Commit).id
                for ref_name in self._repo.references:
                    if not ref_name.startswith('refs/tags/'):
                        continue
                    ref = self._repo.references.get(ref_name)
                    if ref is None:
                        continue
                    try:
                        if ref.peel(_pygit2.Commit).id == head_oid:
                            return ref_name[len('refs/tags/'):]
                    except Exception:
                        pass
                return None
            else:
                import math
                num_objects = sum(1 for _ in self._repo.odb)
                abbrev = max(7, math.ceil(math.log2(max(num_objects, 1)) / 2)) if num_objects > 0 else 7
                return self._repo.describe(
                    describe_strategy=1,
                    abbreviated_size=abbrev,
                )
        except Exception:
            return None

    def list_tags(self):
        tags = []
        for ref_name in self._repo.references:
            if ref_name.startswith('refs/tags/'):
                tag_name = ref_name[len('refs/tags/'):]
                ref = self._repo.references.get(ref_name)
                if ref is not None:
                    try:
                        commit = ref.peel(_pygit2.Commit)
                        commit_obj = type('commit', (), {
                            'hexsha': str(commit.id),
                            'committed_datetime': datetime.fromtimestamp(
                                commit.commit_time,
                                tz=timezone(timedelta(minutes=commit.commit_time_offset))
                            ),
                        })()
                        tags.append(_TagProxy(tag_name, commit_obj))
                    except Exception:
                        tags.append(_TagProxy(tag_name, None))
        return tags

    def list_heads(self):
        heads = []
        for ref_name in self._repo.references:
            if ref_name.startswith('refs/heads/'):
                branch_name = ref_name[len('refs/heads/'):]
                ref = self._repo.references.get(ref_name)
                commit_obj = None
                if ref is not None:
                    try:
                        commit = ref.peel(_pygit2.Commit)
                        commit_obj = type('commit', (), {
                            'hexsha': str(commit.id),
                            'committed_datetime': datetime.fromtimestamp(
                                commit.commit_time,
                                tz=timezone(timedelta(minutes=commit.commit_time_offset))
                            ),
                        })()
                    except Exception:
                        pass
                heads.append(_HeadProxy(branch_name, commit_obj))
        return heads

    def list_branches(self):
        return self.list_heads()

    def get_head_by_name(self, name):
        ref = self._repo.references.get(f'refs/heads/{name}')
        if ref is None:
            raise AttributeError(f"Head '{name}' not found")
        try:
            commit = ref.peel(_pygit2.Commit)
            commit_obj = type('commit', (), {
                'hexsha': str(commit.id),
                'committed_datetime': datetime.fromtimestamp(
                    commit.commit_time,
                    tz=timezone(timedelta(minutes=commit.commit_time_offset))
                ),
            })()
        except Exception:
            commit_obj = None
        return _HeadProxy(name, commit_obj)

    def head_commit_equals(self, other_commit):
        head_sha = str(self._repo.head.peel(_pygit2.Commit).id)
        if hasattr(other_commit, 'hexsha'):
            return head_sha == other_commit.hexsha
        return head_sha == str(other_commit)

    def get_ref_object(self, ref_name):
        commit = self._resolve_ref(ref_name)
        hexsha = str(commit.id)
        dt = datetime.fromtimestamp(
            commit.commit_time,
            tz=timezone(timedelta(minutes=commit.commit_time_offset))
        )
        commit_obj = type('commit', (), {
            'hexsha': hexsha,
            'committed_datetime': dt,
        })()
        return _RefProxy(hexsha, dt, commit_obj=commit_obj)

    def stash(self):
        sig = _pygit2.Signature('comfyui-manager', 'manager@comfy')
        try:
            self._repo.stash(sig)
        except KeyError:
            # nothing to stash, which is no error for git: a submodule that is at another commit makes the repository dirty
            pass

    def pull_ff_only(self):
        branch_name = self.active_branch_name
        branch = self._repo.branches.get(branch_name)
        if branch is None:
            raise GitCommandError(f"Branch '{branch_name}' not found")
        upstream = branch.upstream
        if upstream is None:
            raise GitCommandError(f"No upstream for branch '{branch_name}'")

        remote_name = upstream.remote_name
        self._fetch_remote(self._repo.remotes[remote_name])

        upstream = self._repo.branches.get(branch_name).upstream
        if upstream is None:
            raise GitCommandError(f"Upstream lost after fetch for '{branch_name}'")

        remote_commit = upstream.peel(_pygit2.Commit)
        analysis, _ = self._repo.merge_analysis(remote_commit.id)

        if analysis & _pygit2.GIT_MERGE_ANALYSIS_UP_TO_DATE:
            return

        if analysis & _pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD:
            self._repo.checkout_tree(self._repo.get(remote_commit.id))
            branch_ref = self._repo.references.get(f'refs/heads/{branch_name}')
            if branch_ref is not None:
                branch_ref.set_target(remote_commit.id)
            self._repo.head.set_target(remote_commit.id)
        else:
            raise GitCommandError("Cannot fast-forward; merge or rebase required")

    def reset_hard(self, ref):
        commit = None
        # Try as hex SHA first
        try:
            oid = _pygit2.Oid(hex=ref)
            commit = self._repo.get(oid)
        except (ValueError, Exception):
            pass

        if commit is None:
            # Try as named reference
            for candidate in [ref, f'refs/remotes/{ref}', f'refs/heads/{ref}', f'refs/tags/{ref}']:
                try:
                    ref_obj = self._repo.references.get(candidate)
                    if ref_obj is not None:
                        commit = ref_obj.peel(_pygit2.Commit)
                        break
                except Exception:
                    continue

        if commit is None:
            raise GitCommandError(f"Cannot resolve ref: {ref}")

        self._repo.reset(commit.id, _pygit2.GIT_RESET_HARD)

    def create_backup_branch(self, name):
        head_commit = self._repo.head.peel(_pygit2.Commit)
        self._repo.branches.local.create(name, head_commit)

    def checkout(self, ref):
        # ref can be a _HeadProxy from get_head_by_name
        if isinstance(ref, _HeadProxy):
            ref = ref.name

        branch = self._repo.branches.get(ref)
        if branch is not None:
            branch_ref = self._repo.lookup_reference(f'refs/heads/{ref}')
            self._repo.checkout(branch_ref)
            self._repo.set_head(branch_ref.name)
            return

        for prefix in [f'refs/remotes/{ref}', f'refs/tags/{ref}']:
            ref_obj = self._repo.references.get(prefix)
            if ref_obj is not None:
                commit = ref_obj.peel(_pygit2.Commit)
                self._repo.checkout_tree(self._repo.get(commit.id))
                self._repo.set_head(commit.id)
                return

        try:
            oid = _pygit2.Oid(hex=ref)
            obj = self._repo.get(oid)
            if obj is not None:
                commit = obj.peel(_pygit2.Commit)
                self._repo.checkout_tree(self._repo.get(commit.id))
                self._repo.set_head(commit.id)
                return
        except Exception:
            pass

        raise GitCommandError(f"Cannot resolve ref for checkout: {ref}")

    def checkout_new_branch(self, branch_name, start_point):
        commit = self._resolve_ref(start_point)
        branch = self._repo.branches.local.create(branch_name, commit)
        for prefix in [f'refs/remotes/{start_point}']:
            remote_ref = self._repo.references.get(prefix)
            if remote_ref is not None:
                try:
                    branch.upstream = remote_ref
                except Exception:
                    pass
                break
        self._repo.checkout(branch)
        self._repo.set_head(branch.name)

    @staticmethod
    def _check_out_from(git_dir, path):
        # set before the repository is opened: pygit2 does not open one whose `core.worktree` names a folder that is not there
        _pygit2.Config(os.path.join(git_dir, 'config'))['core.worktree'] = os.path.relpath(path, git_dir).replace(os.sep, '/')
        repo = _pygit2.Repository(git_dir)
        with open(os.path.join(path, '.git'), 'w', encoding='utf-8') as f:
            f.write('gitdir: ' + os.path.relpath(git_dir, path).replace(os.sep, '/') + '\n')
        if not repo.head_is_unborn:
            repo.reset(repo.head.target, _pygit2.GIT_RESET_HARD)

    @staticmethod
    def _is_left_without_a_checkout(git_dir):
        if not os.path.exists(os.path.join(git_dir, 'HEAD')):
            return False
        # git keeps the repository of a submodule under its name, which can be the path of another one
        config = _pygit2.Config(os.path.join(git_dir, 'config'))
        return 'core.worktree' not in config or not os.path.exists(os.path.join(git_dir, config['core.worktree'], '.git'))

    @staticmethod
    def _fetchable_submodules(repo):
        # pygit2 lists the submodules by path, and one that is looked up by its path has no url when its name is another
        names = {}
        gitmodules = os.path.join(repo.workdir, '.gitmodules')
        if os.path.exists(gitmodules):
            names = {entry.value: entry.name[len('submodule.'):-len('.path')] for entry in _pygit2.Config(gitmodules)
                     if entry.name.startswith('submodule.') and entry.name.endswith('.path')}
        top = os.path.normcase(os.path.realpath(repo.workdir))
        named = [repo.submodules.get(names[path]) for path in repo.listall_submodules()
                 if path in names and os.path.normcase(os.path.realpath(os.path.join(top, path))).startswith(top + os.sep)]
        return [submodule.name for submodule in named
                if submodule is not None and submodule.head_id is not None and submodule.url is not None]

    def _update_submodules(self, repo, init):
        def checkout_of(name):
            return os.path.join(repo.workdir, repo.submodules[name].path)

        fetchable = self._fetchable_submodules(repo)
        if init:
            for name in fetchable:
                # pygit2 does not clone into a folder that is not there
                os.makedirs(checkout_of(name), exist_ok=True)
                # a repository in `.git/modules` without a checkout: pygit2 refuses to clone into it
                leftover = os.path.join(repo.path, 'modules', repo.submodules[name].path)
                if not os.path.exists(os.path.join(checkout_of(name), '.git')) and self._is_left_without_a_checkout(leftover):
                    self._check_out_from(leftover, checkout_of(name))
        checked_out = [name for name in fetchable if os.path.exists(os.path.join(checkout_of(name), '.git'))]
        names = fetchable if init else checked_out

        if init and names:
            repo.submodules.init(names)
            for name in names:
                url = repo.config[f'submodule.{name}.url']
                if _to_https_url(url) != url:
                    repo.config[f'submodule.{name}.url'] = _to_https_url(url)

        if _HTTP_PROXY is not None:
            # `update` cannot be given the proxy: what it would fetch is fetched here, and it is left the checkout
            for name in names:
                submodule = repo.submodules[name]
                if name not in checked_out:
                    # the url that `init` resolved: the one of `.gitmodules` may be relative
                    _pygit2.clone_repository(repo.config[f'submodule.{name}.url'], os.path.join(repo.workdir, submodule.path),
                                             proxy=_HTTP_PROXY, callbacks=_remote_callbacks())
                else:
                    cloned = submodule.open()
                    if submodule.head_id not in cloned:
                        cloned.remotes['origin'].fetch(proxy=_HTTP_PROXY, callbacks=_remote_callbacks())
        if names:
            repo.submodules.update(names, callbacks=_remote_callbacks())

        for name in names:
            self._update_submodules(repo.submodules[name].open(), init)

    def submodule_update(self, init=True):
        try:
            self._update_submodules(self._repo, init)
        except Exception as e:
            try:
                result = subprocess.run(
                    ['git', 'submodule', 'update', *(['--init'] if init else []), '--recursive'],
                    cwd=self._working_dir,
                    capture_output=True, timeout=120,
                )
            except FileNotFoundError:
                raise GitCommandError(f"submodule update failed: {e}") from e

            if result.returncode != 0:
                raise GitCommandError(
                    f"submodule update failed (exit {result.returncode}): "
                    f"{result.stderr.decode(errors='replace')}")

    def clear_cache(self):
        pass

    def fetch_remote_by_index(self, index):
        remotes = list(self._repo.remotes)
        self._fetch_remote(remotes[index])

    def pull_remote_by_index(self, index):
        remotes = list(self._repo.remotes)
        remote = remotes[index]
        self._fetch_remote(remote)
        # After fetch, try to ff-merge tracking branch
        try:
            branch_name = self.active_branch_name
            branch = self._repo.branches.get(branch_name)
            if branch and branch.upstream:
                remote_commit = branch.upstream.peel(_pygit2.Commit)
                analysis, _ = self._repo.merge_analysis(remote_commit.id)
                if analysis & _pygit2.GIT_MERGE_ANALYSIS_FASTFORWARD:
                    self._repo.checkout_tree(self._repo.get(remote_commit.id))
                    branch_ref = self._repo.references.get(f'refs/heads/{branch_name}')
                    if branch_ref is not None:
                        branch_ref.set_target(remote_commit.id)
                    self._repo.head.set_target(remote_commit.id)
        except Exception:
            pass

    def close(self):
        self._repo.free()


# ===================================================================
# Public API
# ===================================================================

def open_repo(path) -> GitRepo:
    """Open a repository and return a backend-appropriate wrapper."""
    if USE_PYGIT2:
        return _Pygit2Repo(path)
    else:
        return _GitPythonRepo(path)


def clone_repo(url, dest, progress=None):
    """Clone a repository from *url* into *dest*.

    Returns a repo wrapper that the caller can use for post-clone operations
    (checkout, clear_cache, close, etc.).
    """
    if USE_PYGIT2:
        # The proxy= kwarg requires pygit2>=1.18; omit it when no proxy is
        # configured so proxy-less installs keep working on older pygit2.
        # (A configured proxy still needs >=1.18 — see requirements.txt.)
        if _HTTP_PROXY is not None:
            _pygit2.clone_repository(_to_https_url(url), dest, proxy=_HTTP_PROXY, callbacks=_remote_callbacks())
        else:
            _pygit2.clone_repository(_to_https_url(url), dest, callbacks=_remote_callbacks())
        repo = _Pygit2Repo(dest)
        repo.submodule_update()
        return repo
    else:
        if progress is None:
            r = _git.Repo.clone_from(url, dest, recursive=True)
        else:
            r = _git.Repo.clone_from(url, dest, recursive=True, progress=progress)
        return _GitPythonRepo(r.working_dir)


def setup_git_environment(git_exe):
    """Configure the git executable path (GitPython only)."""
    if USE_PYGIT2 or not git_exe:
        return

    if git_exe == _GIT_EXE:
        found = _GIT_EXE_FOUND
    else:
        found = find_git_executable(git_exe)
        if found is None:
            print(f"[ComfyUI-Manager] `git_exe = {git_exe}` is not a working git executable. The default git is used.", file=sys.stderr)

    if found is not None and _git.Git.GIT_PYTHON_GIT_EXECUTABLE != found:
        _git.refresh(found)
