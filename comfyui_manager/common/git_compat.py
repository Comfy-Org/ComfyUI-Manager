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
import sys
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

_PYGIT2_REQUESTED = os.environ.get('CM_USE_PYGIT2', '').strip() == '1'
USE_PYGIT2 = _PYGIT2_REQUESTED

if not USE_PYGIT2:
    try:
        import git as _git
        _git.Git().execute(['git', '--version'])
    except Exception:
        USE_PYGIT2 = True

if USE_PYGIT2:
    try:
        import pygit2 as _pygit2
    except ImportError:
        # pygit2 not available either — fall back to GitPython and let it
        # fail at the point of use, preserving pre-existing behavior.
        USE_PYGIT2 = False
        _PYGIT2_REQUESTED = False
        import git as _git
    else:
        # Disable owner validation once at import time.
        # Required for Desktop 2.0 standalone installs where repo directories
        # may be owned by a different user (e.g., system-installed paths).
        # See CVE-2022-24765 for context on this validation.
        _pygit2.option(_pygit2.GIT_OPT_SET_OWNER_VALIDATION, 0)

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
    def submodule_update(self): ...

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
        self._repo.git.checkout(ref)

    def checkout_new_branch(self, branch_name, start_point):
        self._repo.git.checkout('-b', branch_name, start_point)

    def submodule_update(self):
        self._repo.git.submodule('update', '--init', '--recursive')

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

    def get_remote(self, name):
        remote = self._repo.remotes[name]

        def _pull():
            remote.fetch()
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

        return _RemoteProxy(remote.name, remote.url, remote.fetch, _pull)

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
            result.append(_RemoteProxy(r.name, r.url, r.fetch))
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
        self._repo.stash(sig)

    def pull_ff_only(self):
        branch_name = self.active_branch_name
        branch = self._repo.branches.get(branch_name)
        if branch is None:
            raise GitCommandError(f"Branch '{branch_name}' not found")
        upstream = branch.upstream
        if upstream is None:
            raise GitCommandError(f"No upstream for branch '{branch_name}'")

        remote_name = upstream.remote_name
        self._repo.remotes[remote_name].fetch()

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

    def submodule_update(self):
        try:
            self._repo.submodules.init()
            self._repo.submodules.update()
        except Exception as e:
            import subprocess
            try:
                result = subprocess.run(
                    ['git', 'submodule', 'update', '--init', '--recursive'],
                    cwd=self._working_dir,
                    capture_output=True, timeout=120,
                )
                if result.returncode != 0:
                    raise GitCommandError(
                        f"submodule update failed (exit {result.returncode}): "
                        f"{result.stderr.decode(errors='replace')}")
            except FileNotFoundError:
                print(f"[ComfyUI-Manager] pygit2: submodule update requires system git (not installed)", file=sys.stderr)
            except GitCommandError:
                raise
            except Exception as sub_e:
                print(f"[ComfyUI-Manager] pygit2: submodule update failed: {sub_e}", file=sys.stderr)

    def clear_cache(self):
        pass

    def fetch_remote_by_index(self, index):
        remotes = list(self._repo.remotes)
        remotes[index].fetch()

    def pull_remote_by_index(self, index):
        remotes = list(self._repo.remotes)
        remote = remotes[index]
        remote.fetch()
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
        _pygit2.clone_repository(url, dest)
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
    if USE_PYGIT2:
        return
    if git_exe:
        _git.Git().update_environment(GIT_PYTHON_GIT_EXECUTABLE=git_exe)
