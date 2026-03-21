"""
Tests for comfyui_manager.common.git_compat

Each test spawns a subprocess with/without CM_USE_PYGIT2=1 to fully isolate
backend selection.  Both backends are tested against the same local git
repository and the results are compared for behavioral parity.

Requirements:
    - Both `pygit2` and `GitPython` installed in the test venv.
    - A working `git` CLI (so GitPython backend can function).
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

# Path to the Python interpreter that has both pygit2 and GitPython
PYTHON = sys.executable

# The git_compat module lives here
COMPAT_DIR = os.path.join(os.path.dirname(__file__), '..', 'comfyui_manager', 'common')
COMPAT_DIR = os.path.abspath(COMPAT_DIR)


def _run_snippet(snippet: str, repo_path: str, *, use_pygit2: bool) -> dict:
    """Run a Python snippet in a subprocess and return JSON output.

    The snippet must print a single JSON line to stdout.
    """
    env = os.environ.copy()
    if use_pygit2:
        env['CM_USE_PYGIT2'] = '1'
    else:
        env.pop('CM_USE_PYGIT2', None)

    full_code = textwrap.dedent(f"""\
        import sys, os, json
        sys.path.insert(0, {COMPAT_DIR!r})
        os.environ.setdefault('CM_USE_PYGIT2', os.environ.get('CM_USE_PYGIT2', ''))
        REPO_PATH = {repo_path!r}
        from git_compat import open_repo, clone_repo, GitCommandError, setup_git_environment, USE_PYGIT2
    """) + textwrap.dedent(snippet)

    result = subprocess.run(
        [PYTHON, '-c', full_code],
        capture_output=True, text=True, env=env, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Subprocess failed (pygit2={use_pygit2}):\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )
    # Find the last JSON line in stdout (skip banner lines)
    for line in reversed(result.stdout.strip().split('\n')):
        line = line.strip()
        if line.startswith('{'):
            return json.loads(line)
    raise RuntimeError(
        f"No JSON output found (pygit2={use_pygit2}):\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )


def _run_both(snippet: str, repo_path: str) -> tuple:
    """Run snippet with both backends and return (gitpython_result, pygit2_result)."""
    gp = _run_snippet(snippet, repo_path, use_pygit2=False)
    p2 = _run_snippet(snippet, repo_path, use_pygit2=True)
    return gp, p2


class TestGitCompat(unittest.TestCase):
    """Test suite comparing GitPython and pygit2 backends."""

    @classmethod
    def setUpClass(cls):
        """Create a temporary git repository for testing."""
        cls._tmpdir = tempfile.mkdtemp(prefix='test_git_compat_')
        cls.repo_path = os.path.join(cls._tmpdir, 'test_repo')
        os.makedirs(cls.repo_path)

        # Initialize a git repo with a commit
        _git = lambda *args: subprocess.run(
            ['git'] + list(args),
            cwd=cls.repo_path, capture_output=True, text=True, check=True,
        )
        _git('init', '-b', 'master')
        _git('config', 'user.email', 'test@test.com')
        _git('config', 'user.name', 'Test')

        # Create initial commit
        with open(os.path.join(cls.repo_path, 'file.txt'), 'w') as f:
            f.write('hello')
        _git('add', '.')
        _git('commit', '-m', 'initial commit')

        # Create a tag
        _git('tag', 'v1.0.0')

        # Create a second commit
        with open(os.path.join(cls.repo_path, 'file2.txt'), 'w') as f:
            f.write('world')
        _git('add', '.')
        _git('commit', '-m', 'second commit')

        # Create another tag
        _git('tag', 'v1.1.0')

        # Create a branch
        _git('branch', 'feature-branch')

        # Store the HEAD commit hash for assertions
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=cls.repo_path, capture_output=True, text=True, check=True,
        )
        cls.head_sha = result.stdout.strip()

        # Store first commit hash
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD~1'],
            cwd=cls.repo_path, capture_output=True, text=True, check=True,
        )
        cls.first_sha = result.stdout.strip()

        # Create a bare remote to test fetch/tracking
        cls.remote_path = os.path.join(cls._tmpdir, 'remote_repo.git')
        subprocess.run(
            ['git', 'clone', '--bare', cls.repo_path, cls.remote_path],
            capture_output=True, check=True,
        )
        _git('remote', 'add', 'origin', cls.remote_path)
        _git('push', '-u', 'origin', 'master')

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # === Backend selection ===

    def test_backend_selection_gitpython(self):
        gp = _run_snippet('print(json.dumps({"backend": "pygit2" if USE_PYGIT2 else "gitpython"}))',
                          self.repo_path, use_pygit2=False)
        self.assertEqual(gp['backend'], 'gitpython')

    def test_backend_selection_pygit2(self):
        p2 = _run_snippet('print(json.dumps({"backend": "pygit2" if USE_PYGIT2 else "gitpython"}))',
                          self.repo_path, use_pygit2=True)
        self.assertEqual(p2['backend'], 'pygit2')

    # === head_commit_hexsha ===

    def test_head_commit_hexsha(self):
        snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"sha": repo.head_commit_hexsha}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['sha'], self.head_sha)
        self.assertEqual(p2['sha'], self.head_sha)

    # === head_is_detached ===

    def test_head_is_detached_false(self):
        snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"detached": repo.head_is_detached}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertFalse(gp['detached'])
        self.assertFalse(p2['detached'])

    # === head_commit_datetime ===

    def test_head_commit_datetime(self):
        snippet = """
repo = open_repo(REPO_PATH)
dt = repo.head_commit_datetime
print(json.dumps({"ts": dt.timestamp()}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertAlmostEqual(gp['ts'], p2['ts'], places=0)

    # === active_branch_name ===

    def test_active_branch_name(self):
        snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"branch": repo.active_branch_name}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['branch'], 'master')
        self.assertEqual(p2['branch'], 'master')

    # === is_dirty ===

    def test_is_dirty_clean(self):
        snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"dirty": repo.is_dirty()}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertFalse(gp['dirty'])
        self.assertFalse(p2['dirty'])

    def test_is_dirty_modified(self):
        # Modify a file temporarily
        filepath = os.path.join(self.repo_path, 'file.txt')
        with open(filepath, 'r') as f:
            original = f.read()
        with open(filepath, 'w') as f:
            f.write('modified')
        try:
            snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"dirty": repo.is_dirty()}))
repo.close()
"""
            gp, p2 = _run_both(snippet, self.repo_path)
            self.assertTrue(gp['dirty'])
            self.assertTrue(p2['dirty'])
        finally:
            with open(filepath, 'w') as f:
                f.write(original)

    def test_is_dirty_untracked_not_dirty(self):
        # Untracked files should NOT make is_dirty() return True
        untracked = os.path.join(self.repo_path, 'untracked_file.txt')
        with open(untracked, 'w') as f:
            f.write('untracked')
        try:
            snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"dirty": repo.is_dirty()}))
repo.close()
"""
            gp, p2 = _run_both(snippet, self.repo_path)
            self.assertFalse(gp['dirty'])
            self.assertFalse(p2['dirty'])
        finally:
            os.remove(untracked)

    # === working_dir ===

    def test_working_dir(self):
        snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"wd": repo.working_dir}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(os.path.normcase(gp['wd']), os.path.normcase(self.repo_path))
        self.assertEqual(os.path.normcase(p2['wd']), os.path.normcase(self.repo_path))

    # === list_remotes ===

    def test_list_remotes(self):
        snippet = """
repo = open_repo(REPO_PATH)
remotes = repo.list_remotes()
print(json.dumps({"names": [r.name for r in remotes]}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertIn('origin', gp['names'])
        self.assertIn('origin', p2['names'])

    # === get_remote ===

    def test_get_remote(self):
        snippet = """
repo = open_repo(REPO_PATH)
r = repo.get_remote('origin')
print(json.dumps({"name": r.name, "has_url": bool(r.url)}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['name'], 'origin')
        self.assertTrue(gp['has_url'])
        self.assertEqual(p2['name'], 'origin')
        self.assertTrue(p2['has_url'])

    # === get_tracking_remote_name ===

    def test_get_tracking_remote_name(self):
        snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"remote": repo.get_tracking_remote_name()}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['remote'], 'origin')
        self.assertEqual(p2['remote'], 'origin')

    # === has_ref ===

    def test_has_ref_true(self):
        snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"has": repo.has_ref('origin/master')}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['has'])
        self.assertTrue(p2['has'])

    def test_has_ref_false(self):
        snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"has": repo.has_ref('origin/nonexistent')}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertFalse(gp['has'])
        self.assertFalse(p2['has'])

    # === get_ref_commit_hexsha ===

    def test_get_ref_commit_hexsha(self):
        snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"sha": repo.get_ref_commit_hexsha('origin/master')}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['sha'], self.head_sha)
        self.assertEqual(p2['sha'], self.head_sha)

    # === get_ref_commit_datetime ===

    def test_get_ref_commit_datetime(self):
        snippet = """
repo = open_repo(REPO_PATH)
dt = repo.get_ref_commit_datetime('origin/master')
print(json.dumps({"ts": dt.timestamp()}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertAlmostEqual(gp['ts'], p2['ts'], places=0)

    # === iter_commits_count ===

    def test_iter_commits_count(self):
        snippet = """
repo = open_repo(REPO_PATH)
print(json.dumps({"count": repo.iter_commits_count()}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['count'], 2)
        self.assertEqual(p2['count'], 2)

    # === symbolic_ref ===

    def test_symbolic_ref(self):
        snippet = """
repo = open_repo(REPO_PATH)
try:
    ref = repo.symbolic_ref('refs/remotes/origin/HEAD')
    print(json.dumps({"ref": ref}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        # Both should return refs/remotes/origin/master or error consistently
        if 'ref' in gp:
            self.assertIn('master', gp['ref'])
        if 'ref' in p2:
            self.assertIn('master', p2['ref'])

    # === describe_tags ===

    def test_describe_tags(self):
        snippet = """
repo = open_repo(REPO_PATH)
desc = repo.describe_tags()
print(json.dumps({"desc": desc}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        # HEAD is at v1.1.0, so describe should return v1.1.0
        self.assertIsNotNone(gp['desc'])
        self.assertIsNotNone(p2['desc'])
        self.assertIn('v1.1.0', gp['desc'])
        self.assertIn('v1.1.0', p2['desc'])

    def test_describe_tags_exact_match(self):
        snippet = """
repo = open_repo(REPO_PATH)
desc = repo.describe_tags(exact_match=True)
print(json.dumps({"desc": desc}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['desc'], 'v1.1.0')
        self.assertEqual(p2['desc'], 'v1.1.0')

    # === list_tags ===

    def test_list_tags(self):
        snippet = """
repo = open_repo(REPO_PATH)
tags = [t.name for t in repo.list_tags()]
print(json.dumps({"tags": sorted(tags)}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['tags'], ['v1.0.0', 'v1.1.0'])
        self.assertEqual(p2['tags'], ['v1.0.0', 'v1.1.0'])

    # === list_heads ===

    def test_list_heads(self):
        snippet = """
repo = open_repo(REPO_PATH)
heads = sorted([h.name for h in repo.list_heads()])
print(json.dumps({"heads": heads}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertIn('master', gp['heads'])
        self.assertIn('feature-branch', gp['heads'])
        self.assertIn('master', p2['heads'])
        self.assertIn('feature-branch', p2['heads'])

    # === list_branches ===

    def test_list_branches(self):
        snippet = """
repo = open_repo(REPO_PATH)
branches = sorted([b.name for b in repo.list_branches()])
print(json.dumps({"branches": branches}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['branches'], p2['branches'])

    # === get_head_by_name ===

    def test_get_head_by_name(self):
        snippet = """
repo = open_repo(REPO_PATH)
h = repo.get_head_by_name('master')
print(json.dumps({"name": h.name, "has_commit": h.commit is not None}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['name'], 'master')
        self.assertTrue(gp['has_commit'])
        self.assertEqual(p2['name'], 'master')
        self.assertTrue(p2['has_commit'])

    def test_get_head_by_name_not_found(self):
        snippet = """
repo = open_repo(REPO_PATH)
try:
    h = repo.get_head_by_name('nonexistent')
    print(json.dumps({"error": False}))
except (AttributeError, Exception):
    print(json.dumps({"error": True}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['error'])
        self.assertTrue(p2['error'])

    # === head_commit_equals ===

    def test_head_commit_equals_same(self):
        snippet = """
repo = open_repo(REPO_PATH)
h = repo.get_head_by_name('master')
print(json.dumps({"eq": repo.head_commit_equals(h.commit)}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['eq'])
        self.assertTrue(p2['eq'])

    def test_head_commit_equals_different(self):
        snippet = """
repo = open_repo(REPO_PATH)
h = repo.get_head_by_name('feature-branch')
# feature-branch points to same commit as master in setup, so this should be True
print(json.dumps({"eq": repo.head_commit_equals(h.commit)}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['eq'], p2['eq'])

    # === context manager ===

    def test_context_manager(self):
        snippet = """
with open_repo(REPO_PATH) as repo:
    sha = repo.head_commit_hexsha
print(json.dumps({"sha": sha}))
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['sha'], self.head_sha)
        self.assertEqual(p2['sha'], self.head_sha)

    # === get_remote_url ===

    def test_get_remote_url_by_name(self):
        snippet = """
repo = open_repo(REPO_PATH)
url = repo.get_remote_url('origin')
print(json.dumps({"has_url": bool(url)}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['has_url'])
        self.assertTrue(p2['has_url'])

    def test_get_remote_url_by_index(self):
        snippet = """
repo = open_repo(REPO_PATH)
url = repo.get_remote_url(0)
print(json.dumps({"has_url": bool(url)}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['has_url'])
        self.assertTrue(p2['has_url'])

    # === clone_repo ===

    def test_clone_repo(self):
        snippet = """
import tempfile, shutil
dest = tempfile.mkdtemp()
try:
    repo = clone_repo(REPO_PATH, os.path.join(dest, 'cloned'))
    sha = repo.head_commit_hexsha
    repo.close()
    print(json.dumps({"sha": sha}))
finally:
    shutil.rmtree(dest, ignore_errors=True)
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['sha'], self.head_sha)
        self.assertEqual(p2['sha'], self.head_sha)

    # === checkout ===

    def test_checkout_tag(self):
        # Test in a clone to avoid messing up the shared repo
        head = self.head_sha
        snippet = f"""
import tempfile, shutil
dest = tempfile.mkdtemp()
try:
    repo = clone_repo(REPO_PATH, os.path.join(dest, 'cloned'))
    repo.checkout('v1.0.0')
    sha = repo.head_commit_hexsha
    detached = repo.head_is_detached
    repo.close()
    print(json.dumps({{"detached": detached, "not_head": sha != {head!r}}}))
finally:
    shutil.rmtree(dest, ignore_errors=True)
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['detached'])
        self.assertTrue(gp['not_head'])
        self.assertTrue(p2['detached'])
        self.assertTrue(p2['not_head'])

    # === checkout_new_branch ===

    def test_checkout_new_branch(self):
        snippet = """
import tempfile, shutil
dest = tempfile.mkdtemp()
try:
    repo = clone_repo(REPO_PATH, os.path.join(dest, 'cloned'))
    repo.checkout_new_branch('test-branch', 'origin/master')
    name = repo.active_branch_name
    repo.close()
    print(json.dumps({"branch": name}))
finally:
    shutil.rmtree(dest, ignore_errors=True)
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['branch'], 'test-branch')
        self.assertEqual(p2['branch'], 'test-branch')

    # === create_backup_branch ===

    def test_create_backup_branch(self):
        snippet = """
import tempfile, shutil
dest = tempfile.mkdtemp()
try:
    repo = clone_repo(REPO_PATH, os.path.join(dest, 'cloned'))
    repo.create_backup_branch('backup_test')
    heads = [h.name for h in repo.list_heads()]
    repo.close()
    print(json.dumps({"has_backup": 'backup_test' in heads}))
finally:
    shutil.rmtree(dest, ignore_errors=True)
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['has_backup'])
        self.assertTrue(p2['has_backup'])

    # === stash ===

    def test_stash(self):
        snippet = """
import tempfile, shutil
dest = tempfile.mkdtemp()
try:
    repo = clone_repo(REPO_PATH, os.path.join(dest, 'cloned'))
    # Make dirty
    with open(os.path.join(dest, 'cloned', 'file.txt'), 'w') as f:
        f.write('dirty')
    dirty_before = repo.is_dirty()
    repo.stash()
    dirty_after = repo.is_dirty()
    repo.close()
    print(json.dumps({"dirty_before": dirty_before, "dirty_after": dirty_after}))
finally:
    shutil.rmtree(dest, ignore_errors=True)
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['dirty_before'])
        self.assertFalse(gp['dirty_after'])
        self.assertTrue(p2['dirty_before'])
        self.assertFalse(p2['dirty_after'])

    # === reset_hard ===

    def test_reset_hard(self):
        first = self.first_sha
        snippet = f"""
import tempfile, shutil
dest = tempfile.mkdtemp()
try:
    repo = clone_repo(REPO_PATH, os.path.join(dest, 'cloned'))
    repo.reset_hard({first!r})
    sha = repo.head_commit_hexsha
    repo.close()
    print(json.dumps({{"sha": sha}}))
finally:
    shutil.rmtree(dest, ignore_errors=True)
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['sha'], self.first_sha)
        self.assertEqual(p2['sha'], self.first_sha)

    # === clear_cache ===

    def test_clear_cache(self):
        snippet = """
repo = open_repo(REPO_PATH)
repo.clear_cache()
print(json.dumps({"ok": True}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['ok'])
        self.assertTrue(p2['ok'])

    # === close ===

    def test_close(self):
        snippet = """
repo = open_repo(REPO_PATH)
repo.close()
print(json.dumps({"ok": True}))
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['ok'])
        self.assertTrue(p2['ok'])

    # === fetch_remote_by_index ===

    def test_fetch_remote_by_index(self):
        snippet = """
repo = open_repo(REPO_PATH)
repo.fetch_remote_by_index(0)
print(json.dumps({"ok": True}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['ok'])
        self.assertTrue(p2['ok'])

    # === get_ref_object ===

    def test_get_ref_object(self):
        snippet = """
repo = open_repo(REPO_PATH)
ref = repo.get_ref_object('origin/master')
print(json.dumps({"sha": ref.object.hexsha, "has_dt": ref.object.committed_datetime is not None}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['sha'], self.head_sha)
        self.assertTrue(gp['has_dt'])
        self.assertEqual(p2['sha'], self.head_sha)
        self.assertTrue(p2['has_dt'])

    # === tag.commit ===

    def test_tag_commit(self):
        snippet = """
repo = open_repo(REPO_PATH)
tags = {t.name: t.commit.hexsha for t in repo.list_tags() if t.commit is not None}
print(json.dumps({"tags": tags}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertIn('v1.0.0', gp['tags'])
        self.assertIn('v1.1.0', gp['tags'])
        self.assertEqual(gp['tags']['v1.1.0'], self.head_sha)
        self.assertEqual(p2['tags']['v1.1.0'], self.head_sha)
        self.assertEqual(gp['tags']['v1.0.0'], p2['tags']['v1.0.0'])

    # === setup_git_environment ===

    def test_setup_git_environment(self):
        snippet = """
# Just verify it doesn't crash
setup_git_environment('')
setup_git_environment(None)
print(json.dumps({"ok": True}))
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['ok'])
        self.assertTrue(p2['ok'])

    # === GitCommandError ===

    def test_git_command_error(self):
        snippet = """
try:
    raise GitCommandError("test error")
except GitCommandError as e:
    print(json.dumps({"has_msg": "test error" in str(e)}))
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['has_msg'])
        self.assertTrue(p2['has_msg'])

    # === pull_ff_only ===

    def test_pull_ff_only(self):
        snippet = """
import tempfile, shutil, subprocess
dest = tempfile.mkdtemp()
try:
    # Create a bare remote from REPO_PATH so we can push to it
    bare = os.path.join(dest, 'bare.git')
    subprocess.run(['git', 'clone', '--bare', REPO_PATH, bare], capture_output=True, check=True)
    # Clone from the bare remote
    repo = clone_repo(bare, os.path.join(dest, 'cloned'))
    # Push a new commit to the bare remote via a second clone
    work = os.path.join(dest, 'work')
    subprocess.run(['git', 'clone', bare, work], capture_output=True, check=True)
    with open(os.path.join(work, 'new.txt'), 'w') as f:
        f.write('new')
    subprocess.run(['git', '-C', work, 'add', '.'], capture_output=True, check=True)
    subprocess.run(['git', '-C', work, 'commit', '-m', 'new'], capture_output=True, check=True)
    subprocess.run(['git', '-C', work, 'push'], capture_output=True, check=True)
    old_sha = repo.head_commit_hexsha
    repo.pull_ff_only()
    new_sha = repo.head_commit_hexsha
    repo.close()
    print(json.dumps({"advanced": old_sha != new_sha}))
finally:
    shutil.rmtree(dest, ignore_errors=True)
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['advanced'])
        self.assertTrue(p2['advanced'])

    # === submodule_update ===

    def test_submodule_update(self):
        snippet = """
repo = open_repo(REPO_PATH)
repo.submodule_update()
print(json.dumps({"ok": True}))
repo.close()
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertTrue(gp['ok'])
        self.assertTrue(p2['ok'])

    # === checkout by SHA ===

    def test_checkout_by_sha(self):
        first = self.first_sha
        snippet = f"""
import tempfile, shutil
dest = tempfile.mkdtemp()
try:
    repo = clone_repo(REPO_PATH, os.path.join(dest, 'cloned'))
    repo.checkout({first!r})
    sha = repo.head_commit_hexsha
    detached = repo.head_is_detached
    repo.close()
    print(json.dumps({{"sha": sha, "detached": detached}}))
finally:
    shutil.rmtree(dest, ignore_errors=True)
"""
        gp, p2 = _run_both(snippet, self.repo_path)
        self.assertEqual(gp['sha'], self.first_sha)
        self.assertTrue(gp['detached'])
        self.assertEqual(p2['sha'], self.first_sha)
        self.assertTrue(p2['detached'])


if __name__ == '__main__':
    unittest.main()
