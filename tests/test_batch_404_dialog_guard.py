"""Regression guard for issue #3128 C1 — the batch 404 dialog.

WHAT WENT WRONG (the behaviour this pins):
    The batch install and uninstall paths threw away the server's 404 body and
    substituted a fixed string: "With the current security level configuration,
    only custom nodes from the "default channel" can be installed/uninstalled".
    That lead was false. `/manager/queue/install` returns 404 from the
    `allow_git_url_install` gate (`manager_server.py`, the `risky_level ==
    'high'` arm, which routes through `is_dedicated_install_allowed()` and
    never reads `security_level`), from the `is_allowed_security_level` arm,
    and from a node pack with no `nightly` version — so a user who followed the
    message adjusted a setting that was never consulted. Fixed in a45db52a by
    deleting the 404 branch at both sites, letting 404 fall through to the
    `else` that already surfaced the server body.

WHY IT IS PINNED THIS WAY:
    The defect lives in `js/`, and this repo has no JavaScript test surface —
    no package.json, no eslint config, no tsconfig — so nothing in CI could
    have caught a reinstatement. Rather than add a JS toolchain, this module
    shells out to `node` and drives the SHIPPED client modules
    (`CustomNodesManager.installNodes`, `uninstallNodes`) through a stubbed 404,
    then reads the string that reached `app.ui.dialog.show()` — the sink the
    user actually reads. What runs is the real client code; only the network
    and the browser are stood in for (see tests/js/).

RED -> GREEN, IN ONE COMMITTED TEST:
    `test_batch_404_surfaces_server_reason` runs the guard against the CURRENT
    js/ and requires the fixed behaviour. `test_guard_catches_the_pre_c1_client`
    runs the SAME predicate against the client as it was at _PRE_C1_COMMIT and
    requires it to FAIL there, on the false message specifically. Without that
    second arm the first proves only that today's code passes today's test; with
    it, the guard is demonstrably able to fail.

Requires `node` on PATH. Without it every node here SKIPS rather than errors,
so a node-less runner is not broken by this file — but note that it then
verifies nothing.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_DIR = REPO_ROOT / "js"
HARNESS_DIR = Path(__file__).resolve().parent / "js"

#: Last commit before the C1 fix — "Merge pull request #3157 from
#: Comfy-Org/fix/issue-3128". Its js/ is the client that shows the false
#: message, and it is what the RED arm measures.
_PRE_C1_COMMIT = "14de630433a5f0665881de4ae973c12ea94b02f2"

#: One of the bodies the server actually sends on a batch denial
#: (`web.Response(status=404, text=...)` in glob/manager_server.py).
SERVER_404_BODY = "A security error has occurred. Please check the terminal logs"

#: Fragments of the false message the fix removed. Kept as separate patterns
#: because a reinstatement is more likely to be a reworded variant than a
#: byte-identical copy.
_FALSE_LEAD_PATTERNS = (
    re.compile(r"default\s+channel", re.I),
    re.compile(r"security\s+level\s+configuration", re.I),
)

SITES = ("install", "uninstall")


def _node_or_skip():
    node = shutil.which("node")
    if node is None:
        pytest.skip(
            "`node` is not on PATH. This guard drives the shipped js/ client "
            "through node; without it the batch-404 dialog is unverified here."
        )
    return node


def _build_sandbox(tmp_path, js_dir, name):
    """Lay out a harness sandbox whose ./pkg/js is `js_dir`.

    The client's own imports are written as `../../scripts/*.js`, so the
    stand-ins must sit two levels above it. Pointing at `js_dir` with a symlink
    (and running node with --preserve-symlinks) satisfies that while still
    executing the real files from `js_dir` rather than a copy.
    """
    sandbox = tmp_path / name
    shutil.copytree(HARNESS_DIR, sandbox)
    (sandbox / "pkg").mkdir()
    os.symlink(js_dir, sandbox / "pkg" / "js", target_is_directory=True)
    return sandbox


def _capture(sandbox, site, body=SERVER_404_BODY):
    """Run one site through a 404 and return the harness's JSON payload."""
    node = _node_or_skip()
    proc = subprocess.run(
        [node, "--preserve-symlinks", "capture_dialog.mjs", site, body],
        cwd=str(sandbox),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise AssertionError(
            "batch-404 harness failed for site=%s (rc=%d). stderr tail:\n%s"
            % (site, proc.returncode, "\n".join(proc.stderr.strip().splitlines()[-12:]))
        )
    lines = proc.stdout.strip().splitlines()
    if not lines:
        raise AssertionError(
            "batch-404 harness exited 0 but printed nothing for site=%s. stderr tail:\n%s"
            % (site, "\n".join(proc.stderr.strip().splitlines()[-12:]))
        )
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as e:
        raise AssertionError(
            "batch-404 harness emitted a non-JSON last line for site=%s: %r\nfull stdout:\n%s"
            % (site, lines[-1], proc.stdout)
        ) from e
    if not payload.get("dialog"):
        raise AssertionError(
            "batch-404 harness captured NO dialog text for site=%s — the error "
            "path did not run, so neither arm of this guard means anything. "
            "payload: %r" % (site, payload)
        )
    return payload


def _c1_violations(payload):
    """The guard predicate. Empty list == the fixed (C1) behaviour.

    Both arms call THIS function, so the RED arm demonstrates the failure of
    the same check the GREEN arm passes — not of a differently-worded cousin.
    """
    dialog = payload["dialog"]
    problems = []
    if payload["server_body"] not in dialog:
        problems.append("the server's own reason is missing from the dialog")
    for pattern in _FALSE_LEAD_PATTERNS:
        if pattern.search(dialog):
            problems.append(f"the dialog still carries the false lead /{pattern.pattern}/")
    return problems


def _pre_c1_js_or_skip(tmp_path):
    """Extract js/ as it was at _PRE_C1_COMMIT, for the RED arm."""
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{_PRE_C1_COMMIT}^{{commit}}"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if probe.returncode != 0:
        pytest.skip(
            f"commit {_PRE_C1_COMMIT[:12]} (the pre-C1 client) is not in this "
            "checkout — a shallow clone cannot run the RED arm."
        )
    archive = tmp_path / "pre-c1.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", f"--output={archive}", _PRE_C1_COMMIT, "js"],
        cwd=str(REPO_ROOT), check=True, capture_output=True, text=True,
    )
    dest = tmp_path / "pre-c1"
    with tarfile.open(archive) as tar:
        if sys.version_info >= (3, 12):
            tar.extractall(dest, filter="data")
        else:  # pragma: no cover - older interpreters
            tar.extractall(dest)
    return dest / "js"


@pytest.mark.parametrize("site", SITES)
def test_batch_404_surfaces_server_reason(tmp_path, site):
    """GREEN — a 404 denial shows the server's reason, at both batch sites."""
    _node_or_skip()  # decide skip-vs-run before doing any setup work
    sandbox = _build_sandbox(tmp_path, JS_DIR, f"head-{site}")
    payload = _capture(sandbox, site)
    assert _c1_violations(payload) == [], (
        "issue #3128 C1 has regressed on the %s path: %s\n"
        "The user was shown:\n%s\nThe server had said: %r"
        % (site, "; ".join(_c1_violations(payload)), payload["dialog"], payload["server_body"])
    )


@pytest.mark.parametrize("site", SITES)
def test_guard_catches_the_pre_c1_client(tmp_path, site):
    """RED — the same predicate must FAIL on the client as it was before C1.

    This is what makes the node above a guard rather than a tautology: run it
    against the code that had the defect and it has to notice.
    """
    _node_or_skip()  # skip on a node-less runner before shelling out to git
    pre_c1_js = _pre_c1_js_or_skip(tmp_path)
    sandbox = _build_sandbox(tmp_path, pre_c1_js, f"pre-c1-{site}")
    payload = _capture(sandbox, site)

    problems = _c1_violations(payload)
    assert problems, (
        "the guard predicate PASSED against the pre-C1 client (%s @ %s), so it "
        "cannot detect the defect it exists for. The dialog it accepted:\n%s"
        % (site, _PRE_C1_COMMIT[:12], payload["dialog"])
    )
    # Fail for the RIGHT reason: the pre-C1 client's specific fault is the
    # substituted channel/security-level lead, not merely a missing body.
    assert any("default" in p for p in problems), (
        "the pre-C1 client failed the predicate, but not on the false 'default "
        "channel' lead this guard is about (%s). Problems: %r\nDialog:\n%s"
        % (site, problems, payload["dialog"])
    )
