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


def test_inline_pre_release_sorts_before_release():
    """The patch-component suffix is preserved as the pre-release, so
    '1.0.0rc1' still sorts strictly before '1.0.0' (CodeRabbit review)."""
    assert StrictVersion("1.0.0rc1") < StrictVersion("1.0.0")
    assert StrictVersion("1.2.0b1") <= StrictVersion("1.2.0")


def test_local_build_tag_is_equivalent_to_the_release():
    """'+cu124' is a local version tag, not a pre-release: for pin
    comparison it must be equal to the plain release (CodeRabbit review)."""
    assert StrictVersion("2.4.0+cu124") == StrictVersion("2.4.0")
    assert StrictVersion("2.4.0+cu124") >= StrictVersion("2.4.0")
