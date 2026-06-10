"""[goal265 step4 — RED] Predicate truth table for ``is_dedicated_install_allowed``.

TARGET CONTRACT (NOT YET IMPLEMENTED — goal265-spec.md §1.2, LOCKED):

    comfyui_manager/common/manager_security.py::is_dedicated_install_allowed(
        flag_value: bool, listen_address: str, network_mode: str) -> bool

    P-direct: allowed iff bool(flag_value)
                      AND (is_loopback(listen_address)
                           OR network_mode.lower() == 'personal_cloud')

These tests are EXPECTED TO FAIL/ERROR against current code (the predicate
does not exist yet) — RED confirmation is goal265 Step 5. Do NOT weaken them
to pass against today's code.

SC rows covered (goal265-scenarios.md — predicate-level arm):
  SC-01, SC-02, SC-03, SC-05, SC-06, SC-07   ([D1] allow_git_url_install)
  SC-11, SC-12, SC-13, SC-14, SC-15           ([D2] allow_pip_install)
  SC-16, SC-17                                (flag independence, [D1][D2])

security_level is ABSENT from the predicate signature — its irrelevance is
proven BY CONSTRUCTION (spec §4 row 1): rows whose preconditions differ only
in security_level (SC-01 vs SC-02; SC-06/SC-14 parametrizations) map onto the
IDENTICAL predicate call, so no security_level value can change the outcome.

Fixtures: none — pure function (spec §4 binding patching constraint).
The module under test is loaded directly by file path so the test does not
import the ``comfyui_manager`` package (whose __init__ needs the ComfyUI
runtime); ``manager_security.py`` itself is dependency-light by design
(spec §1.2: MUST stay config-import-free).
"""

from __future__ import annotations

import importlib.util
import inspect
import pathlib

import pytest

_MANAGER_SECURITY_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "comfyui_manager" / "common" / "manager_security.py"
)

# Address / network-mode vocabulary (scenarios §0 preamble):
LOOPBACK = "127.0.0.1"
LOOPBACK_V6 = "::1"
PUBLIC_ADDR = "203.0.113.5"     # TEST-NET-3 — non-loopback ("listen=public")
NM_PUBLIC = "public"
NM_PERSONAL_CLOUD = "personal_cloud"

# security_level context values for irrelevance-by-construction params.
# The predicate takes NO security_level argument; these ids document which
# scenario-row context each identical call stands for.
SECURITY_LEVELS = ("strong", "normal", "normal-", "weak")


def _load_manager_security():
    spec = importlib.util.spec_from_file_location(
        "_manager_security_under_test", _MANAGER_SECURITY_PATH
    )
    assert spec is not None and spec.loader is not None, _MANAGER_SECURITY_PATH
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def predicate():
    """The predicate under test. FAILS (RED) while the function is absent."""
    mod = _load_manager_security()
    assert hasattr(mod, "is_dedicated_install_allowed"), (
        "RED: comfyui_manager/common/manager_security.py does not define "
        "is_dedicated_install_allowed yet (goal265-spec.md §1.2). "
        "This is the expected state before Step 6 (Develop)."
    )
    return mod.is_dedicated_install_allowed


# ---------------------------------------------------------------------------
# Structural: security_level is not even an input (irrelevance by construction)
# ---------------------------------------------------------------------------

def test_signature_has_no_security_level_parameter(predicate):
    """[SC-01..SC-17 foundation] Spec §1.2 locks the signature to exactly
    (flag_value, listen_address, network_mode) — security_level CANNOT
    influence the decision because it is not an input."""
    params = list(inspect.signature(predicate).parameters)
    assert params == ["flag_value", "listen_address", "network_mode"], (
        f"Locked signature drifted: {params!r} "
        "(goal265-spec.md §1.2 — security_level must NOT appear)"
    )


# ---------------------------------------------------------------------------
# [D1] allow_git_url_install — happy paths
# ---------------------------------------------------------------------------

def test_sc01_flag_true_loopback_allows_under_strong_security_level(predicate):
    """SC-01: git=true, sl=strong, listen=loopback, nm=public -> allowed.
    sl=strong is context only — the call has no security_level input."""
    assert predicate(True, LOOPBACK, NM_PUBLIC) is True


def test_sc02_flag_true_loopback_allows_under_default_security_level(predicate):
    """SC-02: git=true, sl=normal (default), listen=loopback, nm=public ->
    allowed. Identical call to SC-01: proves sl irrelevance by construction."""
    assert predicate(True, LOOPBACK, NM_PUBLIC) is True


def test_sc03_flag_true_public_listener_personal_cloud_allows(predicate):
    """SC-03: git=true, sl=normal, listen=public, nm=personal_cloud ->
    allowed (personal_cloud arm of the network-position invariant)."""
    assert predicate(True, PUBLIC_ADDR, NM_PERSONAL_CLOUD) is True


# ---------------------------------------------------------------------------
# [D1] allow_git_url_install — failure paths
# ---------------------------------------------------------------------------

def test_sc05_flag_false_denies_even_at_weak_security_level(predicate):
    """SC-05: git=false, sl=weak, listen=loopback -> denied. Deny-direction
    proof of security_level irrelevance (today sl=weak would ALLOW)."""
    assert predicate(False, LOOPBACK, NM_PUBLIC) is False


@pytest.mark.parametrize("security_level_context", SECURITY_LEVELS[:3],
                         ids=[f"sl={s}" for s in SECURITY_LEVELS[:3]])
def test_sc06_flag_false_denies_for_every_security_level(
        predicate, security_level_context):
    """SC-06: git=false, sl in {strong, normal, normal-}, listen=loopback ->
    denied for EVERY sl value. The parametrize axis documents that all three
    scenario contexts collapse onto the same flag-only call — the flag is
    the sole decider."""
    assert predicate(False, LOOPBACK, NM_PUBLIC) is False


def test_sc07_flag_true_cannot_open_public_listener(predicate):
    """SC-07: git=true, sl=weak, listen=public, nm=public -> denied.
    Network-position invariant retained (spec §1.1 invariant 2): the flag
    must never widen exposure beyond what is possible today."""
    assert predicate(True, PUBLIC_ADDR, NM_PUBLIC) is False


# ---------------------------------------------------------------------------
# [D2] allow_pip_install — happy paths
# ---------------------------------------------------------------------------

def test_sc11_pip_flag_true_loopback_allows_under_strong(predicate):
    """SC-11: pip=true, sl=strong, listen=loopback, nm=public -> allowed."""
    assert predicate(True, LOOPBACK, NM_PUBLIC) is True


def test_sc12_pip_flag_true_public_listener_personal_cloud_allows(predicate):
    """SC-12: pip=true, sl=normal, listen=public, nm=personal_cloud ->
    allowed."""
    assert predicate(True, PUBLIC_ADDR, NM_PERSONAL_CLOUD) is True


# ---------------------------------------------------------------------------
# [D2] allow_pip_install — failure paths
# ---------------------------------------------------------------------------

def test_sc13_pip_flag_false_denies_even_at_weak(predicate):
    """SC-13: pip=false, sl=weak, listen=loopback -> denied."""
    assert predicate(False, LOOPBACK, NM_PUBLIC) is False


@pytest.mark.parametrize("security_level_context", SECURITY_LEVELS[:3],
                         ids=[f"sl={s}" for s in SECURITY_LEVELS[:3]])
def test_sc14_pip_flag_false_denies_for_every_security_level(
        predicate, security_level_context):
    """SC-14: pip=false, sl in {strong, normal, normal-}, listen=loopback ->
    denied each. Same irrelevance-by-construction pattern as SC-06."""
    assert predicate(False, LOOPBACK, NM_PUBLIC) is False


def test_sc15_pip_flag_true_cannot_open_public_listener(predicate):
    """SC-15: pip=true, sl=weak, listen=public, nm=public -> denied
    (network invariant)."""
    assert predicate(True, PUBLIC_ADDR, NM_PUBLIC) is False


# ---------------------------------------------------------------------------
# Flag independence (cross-link [D1]+[D2])
# ---------------------------------------------------------------------------

def test_sc16_git_false_pip_true_independent_outcomes(predicate):
    """SC-16: git=false, pip=true, sl=normal, listen=loopback -> git denied,
    pip allowed. At predicate level each surface passes ONLY its own flag —
    same network inputs, opposite outcomes."""
    git_allowed = predicate(False, LOOPBACK, NM_PUBLIC)
    pip_allowed = predicate(True, LOOPBACK, NM_PUBLIC)
    assert git_allowed is False
    assert pip_allowed is True


def test_sc17_git_true_pip_false_independent_outcomes(predicate):
    """SC-17: git=true, pip=false, sl=normal, listen=loopback -> git allowed,
    pip denied (mirror of SC-16)."""
    git_allowed = predicate(True, LOOPBACK, NM_PUBLIC)
    pip_allowed = predicate(False, LOOPBACK, NM_PUBLIC)
    assert git_allowed is True
    assert pip_allowed is False


# ---------------------------------------------------------------------------
# Supplementary: exhaustive flag x loopback x personal_cloud truth table
# (spec §4 row 1 — "flag x loopback x personal_cloud" full table)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("flag", "listen", "network_mode", "expected"),
    [
        (True,  LOOPBACK,    NM_PUBLIC,         True),   # SC-01/02/11
        (True,  LOOPBACK,    NM_PERSONAL_CLOUD, True),   # both arms true
        (True,  PUBLIC_ADDR, NM_PERSONAL_CLOUD, True),   # SC-03/12
        (True,  PUBLIC_ADDR, NM_PUBLIC,         False),  # SC-07/15
        (False, LOOPBACK,    NM_PUBLIC,         False),  # SC-05/06/13/14
        (False, LOOPBACK,    NM_PERSONAL_CLOUD, False),
        (False, PUBLIC_ADDR, NM_PERSONAL_CLOUD, False),
        (False, PUBLIC_ADDR, NM_PUBLIC,         False),
    ],
    ids=[
        "flag+loopback+nm_public",
        "flag+loopback+personal_cloud",
        "flag+public+personal_cloud",
        "flag+public+nm_public",
        "noflag+loopback+nm_public",
        "noflag+loopback+personal_cloud",
        "noflag+public+personal_cloud",
        "noflag+public+nm_public",
    ],
)
def test_truth_table_flag_x_loopback_x_personal_cloud(
        predicate, flag, listen, network_mode, expected):
    """Full 2x2x2 truth table for P-direct (spec §1.1): allowed iff flag AND
    (loopback OR personal_cloud). Consolidates SC-01/02/03/05/06/07 ([D1])
    and SC-11/12/13/14/15 ([D2]) plus the two combinations no single row
    pins (flag+loopback+personal_cloud, noflag+public+personal_cloud)."""
    assert predicate(flag, listen, network_mode) is expected


# ---------------------------------------------------------------------------
# Supplementary edge handling locked by the spec text
# ---------------------------------------------------------------------------

def test_ipv6_loopback_counts_as_loopback(predicate):
    """SC-01/SC-02 edge (loopback arm): `is_loopback` is ipaddress-based
    (manager_security.py) — ::1 must be treated as loopback too."""
    assert predicate(True, LOOPBACK_V6, NM_PUBLIC) is True


@pytest.mark.parametrize("network_mode", ["Personal_Cloud", "PERSONAL_CLOUD"],
                         ids=["mixed-case", "upper-case"])
def test_network_mode_personal_cloud_is_case_insensitive(predicate, network_mode):
    """SC-03/SC-12 edge (personal_cloud arm): spec §1.2 predicate body —
    network_mode.lower() == 'personal_cloud' (case-insensitive)."""
    assert predicate(True, PUBLIC_ADDR, network_mode) is True


def test_unparseable_listen_address_is_not_loopback(predicate):
    """SC-07/SC-15 edge (network invariant): is_loopback returns False for
    unparseable addresses (ValueError arm) — the predicate must fail CLOSED
    on a malformed listen address."""
    assert predicate(True, "not-an-ip-address", NM_PUBLIC) is False
