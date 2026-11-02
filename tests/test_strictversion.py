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


def test_post_release_sorts_after_the_release():
    """An installed 1.0.0post1 must NOT satisfy pkg<1.0.0 (CodeRabbit round 3):
    post-releases are newer than the final release, unlike pre-releases."""
    assert StrictVersion("1.0.0post1") > StrictVersion("1.0.0")
    assert StrictVersion("1.0.0post2") > StrictVersion("1.0.0post1")
    assert StrictVersion("1.0.0post1") > StrictVersion("1.0.0rc1")


def test_str_round_trips_through_the_parser():
    """citizenadam's crash: cnr_utils normalizes with str(StrictVersion(...))
    and feeds the result back. The parser must accept every string it
    emits, across local tags, pre-releases and post-releases."""
    for v in ("0.1.3.post1", "1.0.0.post2", "2.4.0+cu124", "1.0.0rc1", "0.1.3"):
        emitted = str(StrictVersion(v))
        reparsed = StrictVersion(emitted)
        assert reparsed == StrictVersion(v), f"{v!r} -> {emitted!r} did not round-trip"


def test_dash_emitted_form_also_round_trips():
    """'1.0.0-rc1' arrives from sources that normalize with the old dash
    format; the parser strips the dash and pre_release round-trips."""
    assert StrictVersion("1.0.0-rc1") == StrictVersion("1.0.0rc1")
    assert StrictVersion(str(StrictVersion("1.0.0-rc1"))) == StrictVersion("1.0.0rc1")
