"""StrictVersion must survive real-world pip version suffixes.

The parse fed int(parts[2]) directly; pip pins like '2.4.0+cu124' (every
CUDA torch build) or '1.0.0rc1' raised ValueError and, in the lazy-install
path, silently dropped the node's whole install-script line.
"""

from manager_test_utils import load_manager_util

MANAGER_UTIL = load_manager_util()
StrictVersion = MANAGER_UTIL.StrictVersion


def test_local_build_suffix_parses_and_compares():
    v = StrictVersion("2.4.0+cu124")
    assert (v.major, v.minor, v.patch) == (2, 4, 0)
    assert v == StrictVersion("2.4.0")


def test_pre_release_suffix_parses():
    assert StrictVersion("1.0.0rc1").patch == 0
    assert StrictVersion("2.5.0a1") >= StrictVersion("2.4.9")


def test_garbage_component_still_raises():
    try:
        StrictVersion("not-a-version")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
