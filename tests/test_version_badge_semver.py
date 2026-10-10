"""RED->GREEN guard for the Version column's CNR update badge (issue #3272).

WHY
---
The Custom Nodes grid's Version column used to decide whether to render the
``[↑x.y.z]`` update badge with a bare string inequality:

    if(rowItem.cnr_latest && version != rowItem.cnr_latest) {

String comparison says ``"1.47.0" != "1.78.1"``, so a node installed at
1.78.1 was flagged as updatable to 1.47.0 -- exactly the report in #3272,
confirmed by maintainers there. The backend never had this bug:
``is_updatable`` in glob/manager_core.py compares ``packaging`` versions via
``safe_version``. The fix adds a module-level ``compareVersionSpecs`` helper
to js/custom-nodes-manager.js and gates the badge on the registry version
being PROVABLY newer (cmp === 1); when either spec is not fully numeric
("nightly", "1.2.3rc1", ...) the helper returns null and the formatter keeps
the legacy string behavior.

A side effect pinned here: glob/manager_core.py injects ``cnr_latest =
'0.0.0'`` when the registry has no ``latest_version``. Under the string
inequality that rendered a nonsensical ``[↑0.0.0]`` badge on every such row;
under the numeric compare 0.0.0 is simply older than the install, so no
badge.

REPRODUCE THE RED HALF against the pre-fix revision -- one command:
  mkdir -p /some/dir
  git show <base>:js/custom-nodes-manager.js > /some/dir/custom-nodes-manager.js
  git show <base>:js/common.js              > /some/dir/common.js
  MANAGER_JS_DIR=/some/dir pytest tests/test_version_badge_semver.py
"""
import json
import os
import unittest
from pathlib import Path

from js_lift import NODE, JsSource, run_node, slice_braced, slice_object_entry

REPO_ROOT = Path(__file__).resolve().parent.parent

JS = JsSource(os.environ.get("MANAGER_JS_DIR") or (REPO_ROOT / "js"))

MANAGER = "custom-nodes-manager.js"
COMMON = "common.js"

VERSION_ANCHOR = "id: 'version',"
HELPER_MARKER = "function compareVersionSpecs"


def _helper_source() -> str:
    """The module-level compareVersionSpecs, lifted from the shipped file."""
    return slice_braced(JS.text(MANAGER), HELPER_MARKER)


def _version_formatter() -> str:
    """The Version column formatter, lifted verbatim out of its array entry."""
    block = slice_object_entry(JS.text(MANAGER), VERSION_ANCHOR)
    marker = "formatter:"
    return block[block.index(marker) + len(marker):].strip()


def _sanitize_html_source() -> str:
    return JS.lift_declaration(COMMON, "export function sanitizeHTML(")


def _render(formatter_source: str, installed, cnr_latest) -> str:
    script = "\n".join([
        _sanitize_html_source(),
        _helper_source(),
        "const formatter = %s;" % (formatter_source,),
        "const rowItem = {cnr_latest: %s, originalData: {id: 'x'}};" % json.dumps(cnr_latest),
        "console.log(JSON.stringify({markup: String(formatter(%s, rowItem, {}))}));"
        % json.dumps(installed),
    ])
    return run_node(script)["markup"]


# The installed/cnr_latest pairs the badge decision must get right, with the
# exact markup a correct formatter returns for each.
BADGE = "<div>%s</div><div>[↑%s]</div>"

CASES = [
    # (installed, cnr_latest, expected, why)
    ("1.78.1", "1.47.0", "1.78.1",
     "issue #3272: locally newer must NOT be flagged as updatable"),
    ("1.47.0", "1.47.0", "1.47.0",
     "equal versions: no badge"),
    ("1.0.0", "1.47.0", BADGE % ("1.0.0", "1.47.0"),
     "registry is genuinely newer: badge kept"),
    ("1.78.1", "0.0.0", "1.78.1",
     "manager_core's 'no latest_version' sentinel must not render [↑0.0.0]"),
    ("0.0.0", "1.47.0", BADGE % ("0.0.0", "1.47.0"),
     "a 0.0.0 install is still older than the registry: badge kept"),
    ("1.2", "1.10.0", BADGE % ("1.2", "1.10.0"),
     "numeric compare: 1.10.0 > 1.2 (a string compare would miss this update)"),
    ("1.10.0", "1.2", "1.10.0",
     "numeric compare: 1.10.0 > 1.2, so no badge"),
    ("nightly", "1.47.0", "<div>nightly</div><div>[1.47.0]</div>",
     "the nightly branch is untouched: no arrow, badge-free"),
    ("1.2.3rc1", "1.47.0", BADGE % ("1.2.3rc1", "1.47.0"),
     "unparseable spec: legacy string behavior kept"),
]


@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class VersionBadgeSemverTest(unittest.TestCase):
    """The Version column formatter, lifted and executed as shipped."""

    @classmethod
    def setUpClass(cls):
        cls.formatter = _version_formatter()

    def _markup(self, installed, cnr_latest) -> str:
        return _render(self.formatter, installed, cnr_latest)

    def test_the_badge_follows_numeric_ordering(self):
        for installed, latest, expected, why in CASES:
            with self.subTest(installed=installed, cnr_latest=latest):
                self.assertEqual(self._markup(installed, latest), expected, why)


@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class CompareVersionSpecsTest(unittest.TestCase):
    """The helper itself, lifted and executed directly."""

    def _compare(self, a, b):
        out = run_node(
            "%s\nconsole.log(JSON.stringify({r: compareVersionSpecs(%s, %s)}));"
            % (_helper_source(), json.dumps(a), json.dumps(b))
        )
        return out["r"]

    def test_dot_separated_specs_order_numerically(self):
        self.assertEqual(self._compare("1.2.10", "1.2.9"), 1)
        self.assertEqual(self._compare("1.10.0", "1.9"), 1)
        self.assertEqual(self._compare("1.9", "1.10.0"), -1)
        self.assertEqual(self._compare("1.47.0", "1.47.0"), 0)
        self.assertEqual(self._compare("1.2", "1.2.0"), 0)

    def test_non_numeric_specs_return_null(self):
        self.assertIsNone(self._compare("nightly", "1.47.0"))
        self.assertIsNone(self._compare("1.2.3rc1", "1.47.0"))
        self.assertIsNone(self._compare("1.47.0", ""))


if __name__ == "__main__":
    unittest.main()
