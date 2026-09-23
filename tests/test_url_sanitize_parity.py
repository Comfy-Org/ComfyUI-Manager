"""Drift guard: the JS sanitizeUrl must agree with glob/manager_util.py::sanitize_url.

There are two implementations of one URL allow-list — ``sanitizeUrl`` in
js/common.js and ``sanitize_url`` in glob/manager_util.py. They agree today.
Nothing structural keeps them agreeing: a change to either side has no failing
test on the other, and the JS side is what stands between channel data and an
href. This module is that missing coupling. It runs BOTH real implementations
over a shared case list and fails on any divergence, naming the input and both
answers.

WHAT IT COMPARES: the real shipped code on both sides. The Python function is
loaded by file location (``glob/`` has no ``__init__.py``, and putting it on
sys.path would shadow the stdlib ``glob``); the JS function is lifted out of
js/common.js by tests/js_lift and executed in node. Neither is a copy, so a
perturbation of either implementation turns this guard RED.

CASES: the shared matrix at ``cases/url_sanitize_cases.json`` (57 inputs handed
over by gm3-review from the WI-112 and WI-122 reviews, since extended) PLUS a
generated grid that composes scheme x in-scheme-noise x delimiter. The generated
half matters because a fixed list can only catch divergence it happens to
contain, and the implementations are what is under test, not the list.

TWO AXES ARE COMPARED, not one. Behaviour over sampled inputs cannot see a
difference no sample happens to hold, so the two pieces of CONFIGURATION the
implementations branch on are compared directly as well: the scheme allow-list
(``test_the_scheme_allow_lists_are_identical``) and the whitespace set each side
trims off an accepted URL (``test_the_trim_sets_are_identical``). The trim axis
was added after the matrix was found to contain no BOM or unicode-whitespace
input at all — ``String.prototype.trim()`` and ``str.strip()`` disagree on six
codepoints (U+FEFF one way; U+001C-001F and U+0085 the other), and every case in
the matrix had ASCII edges, so the divergence sat unguarded. js/common.js now
spells Python's set out rather than delegating to ``trim()``; see the
``unicode_whitespace_divergence`` block in the case file.

⛔ STRING INPUTS ONLY, deliberately. Python ``str()`` and JS ``String()`` are
not equivalent for non-strings — 1.0 -> '1.0' vs '1', True -> 'True' vs 'true',
[1,2] -> '[1, 2]' vs '1,2', {} -> '{}' vs '[object Object]' — so feeding
non-strings would report divergence for something that is not a defect. In
practice ``url`` arrives as a string off the JSON payload. The two aligned
non-string cases that DO matter are pinned separately in
``test_null_and_undefined_agree`` rather than left as an undocumented gap; the
right response to a coercion mismatch is to narrow the domain, never to loosen
the comparison, because a loosened comparison stops catching real drift.
"""
import inspect
import json
import os
import re
import unittest
from pathlib import Path

from js_lift import NODE, JsSource, run_node
from manager_test_utils import load_manager_util

REPO_ROOT = Path(__file__).resolve().parent.parent
JS = JsSource(os.environ.get("MANAGER_JS_DIR") or (REPO_ROOT / "js"))
CASES_PATH = Path(__file__).resolve().parent / "cases" / "url_sanitize_cases.json"

# Every codepoint ``str.strip()`` removes, measured by RUNNING it rather than by
# restating a table. sanitize_url returns ``raw.strip()``, so this is the set the
# JS side has to match; test_the_trim_sets_are_identical asserts that linkage
# still holds before comparing.
PYTHON_TRIM_SET = frozenset(c for c in range(0x110000) if chr(c).strip() == "")


def _generated_cases(allow_listed):
    """Compose scheme x in-scheme noise x delimiter into extra inputs.

    A fixed list only catches the divergence it already contains. This grid is
    derived from the axes the two implementations actually branch on — the
    scheme allow-list, the control-char strip, and the head-delimiter cut — so
    it explores combinations nobody wrote down.

    ``allow_listed`` is the UNION of the two live allow-lists, not a literal, so
    a scheme added to either side is exercised behaviourally without anyone
    remembering to add a case for it. That is a second layer under
    test_the_scheme_allow_lists_are_identical, which is what catches an
    allow-list divergence definitively; this layer only makes the behavioural
    sampling track the configuration instead of drifting away from it.
    """
    schemes = sorted(set(allow_listed) | {
        "HTTP", "javascript", "data", "vbscript", "file", "a-b", "a.b",
    })
    noises = ["", "\t", "\n", "\x00", "\x01", " ", "\x7f"]
    delimiters = ["", "/", "?", "#", "//host/p", "?q=1", "#frag"]
    for scheme in schemes:
        for noise in noises:
            head = scheme[:2] + noise + scheme[2:]
            for delimiter in delimiters:
                yield "%s:%s" % (head, delimiter)
                yield " %s:%s" % (head, delimiter)


def _all_cases(allow_listed):
    matrix = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = list(matrix["shared_matrix"])
    cases.extend(_generated_cases(allow_listed))
    # De-duplicate while preserving order so a failure names a stable index.
    seen = set()
    ordered = []
    for case in cases:
        if case not in seen:
            seen.add(case)
            ordered.append(case)
    return ordered


def _lift_sanitize_url() -> str:
    """The REAL sanitizeUrl and the two constants it closes over, from common.js.

    Lifted as one contiguous span rather than three declarations: SAFE_URL_SCHEMES
    is an array literal, so a brace-matching lift would run past it into the
    function body and declare the constants twice.
    """
    span = JS.lift_span("common.js", "export const SAFE_URL_SCHEMES",
                        "export const safeHref = (url) => sanitizeHTML(sanitizeUrl(url));")
    # safeHref needs sanitizeHTML, which this guard does not exercise; drop the
    # trailing line rather than pulling an unrelated dependency into the script.
    span = span[:span.index("export const safeHref")]
    return span.replace("export ", "")


_JS_ALLOW_LIST_LITERAL = re.compile(r"(SAFE_URL_SCHEMES\s*=\s*)\[[^\]]*\]")


def _js_allow_list(lifted_js=None):
    """The JS SAFE_URL_SCHEMES as the running code actually sees it.

    Evaluated in node rather than parsed out of the source, so a change to how
    the list is spelled cannot make this silently read the old value.
    """
    return run_node(
        "%s\nconsole.log(JSON.stringify({v: SAFE_URL_SCHEMES}));\n"
        % (lifted_js if lifted_js is not None else _lift_sanitize_url())
    )["v"]


def _js_trim_set(lifted_js=None):
    """Every codepoint the JS side strips off the edges of an accepted URL.

    Evaluated in node, for the same reason ``_js_allow_list`` is: a set parsed
    out of the source text stops describing the running code the moment the
    spelling changes.

    Shimmed on a PRE-FIX tree, where sanitizeUrl called ``raw.trim()`` inline and
    no ``trimUrl`` exists. Without the shim this guard would raise on the old
    revision instead of reporting the divergence, and the RED half of the fix
    could not be demonstrated with the guard that is supposed to catch it.
    """
    lifted = _lift_sanitize_url() if lifted_js is None else lifted_js
    shim = "" if "trimUrl" in lifted else "const trimUrl = (value) => value.trim();\n"
    return set(run_node(
        "%s\n%sconst out = [];\n"
        "for (let c = 0; c < 0x110000; c += 1) {\n"
        "  if (trimUrl(String.fromCodePoint(c)) === '') out.push(c);\n"
        "}\n"
        "console.log(JSON.stringify({v: out}));\n" % (lifted, shim)
    )["v"])


def _perturb_js_allow_list(lifted_js, extra_scheme):
    """Add a scheme to the lifted JS allow-list, whatever it currently holds.

    Rewriting the array by PATTERN rather than by a hard-coded literal matters:
    a literal-match perturbation stops applying the moment someone edits the
    allow-list, and then the harness's own did-it-apply self-test fires instead
    of the parity comparison — a red that looks like coverage and is not.
    """
    perturbed, count = _JS_ALLOW_LIST_LITERAL.subn(
        lambda m: "%s%s" % (m.group(1), json.dumps(sorted(
            set(_js_allow_list(lifted_js)) | {extra_scheme}))),
        lifted_js, count=1,
    )
    assert count == 1, "could not locate the JS SAFE_URL_SCHEMES array to perturb"
    return perturbed


def _js_results(cases):
    """Run the REAL js/common.js sanitizeUrl over every case, in node."""
    lifted = _lift_sanitize_url()
    return run_node(
        "%s\nconst cases = %s;\n"
        "console.log(JSON.stringify({results: cases.map((c) => sanitizeUrl(c))}));\n"
        % (lifted, json.dumps(cases))
    )["results"]


@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class UrlSanitizeParityTest(unittest.TestCase):
    """Both real implementations, one case list, zero tolerated divergence."""

    @classmethod
    def setUpClass(cls):
        cls.manager_util = load_manager_util()
        cls.allow_lists = {
            "python": set(cls.manager_util.SAFE_URL_SCHEMES),
            "js": set(_js_allow_list()),
        }
        cls.cases = _all_cases(cls.allow_lists["python"] | cls.allow_lists["js"])
        cls.js = _js_results(cls.cases)

    def test_case_matrix_is_actually_loaded(self):
        # A guard that silently ran zero cases would pass forever.
        matrix = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(matrix["shared_matrix"]), 57)
        self.assertGreater(len(self.cases), 400)
        self.assertEqual(len(self.js), len(self.cases))

    def test_the_scheme_allow_lists_are_identical(self):
        """Compare the CONFIGURATION, not only the behaviour it drives.

        Comparing behaviour over sampled inputs cannot see a scheme added to one
        allow-list unless that scheme happens to be in the sample — adding 'ftp'
        or 'mailto' or 'ws' to either side changes what is accepted and produces
        no divergence at all. That is the most plausible future drift for this
        pair (someone adds a scheme for a real reason and forgets the other
        side), so it is closed definitively here rather than by sampling.
        """
        self.assertEqual(
            self.allow_lists["js"], self.allow_lists["python"],
            "the URL scheme allow-lists have diverged — js/common.js accepts %r "
            "and glob/manager_util.py accepts %r. A scheme added to one side and "
            "not the other silently changes what reaches an href. Fix the lists, "
            "do NOT relax this comparison."
            % (sorted(self.allow_lists["js"]), sorted(self.allow_lists["python"])),
        )

    def test_the_trim_sets_are_identical(self):
        """Compare the trim CONFIGURATION, the way the allow-lists are compared.

        Both implementations end an accepted URL with a trim, and the two trims
        are NOT the same function: ``String.prototype.trim()`` strips U+FEFF,
        which ``str.strip()`` keeps, and leaves U+001C-001F and U+0085, which
        ``str.strip()`` strips. Sampling cannot be relied on to find that — the
        handed-over matrix had ASCII edges on all 62 inputs and reported no
        divergence for years of cases. The cases added alongside this test do
        catch it, but the set comparison is what closes the axis DEFINITIVELY,
        exactly as test_the_scheme_allow_lists_are_identical does for schemes.

        The fix direction is fixed, not free: glob/manager_util.py is the
        declared source of truth for this pair, so the JS side matches Python.
        """
        source = inspect.getsource(self.manager_util.sanitize_url)
        self.assertIn(
            "raw.strip()", source,
            "sanitize_url no longer returns raw.strip(), so PYTHON_TRIM_SET is "
            "measuring the wrong function — re-derive it from whatever the "
            "Python side trims with now.",
        )
        js = _js_trim_set()
        self.assertEqual(
            js, set(PYTHON_TRIM_SET),
            "the URL trim sets have diverged. js/common.js strips %s that "
            "glob/manager_util.py keeps, and keeps %s that it strips. Both sides "
            "must trim the SAME set or the two implementations answer differently "
            "for the same accepted URL; fix js/common.js's URL_TRIM, do NOT relax "
            "this comparison."
            % (sorted("U+%04X" % c for c in js - PYTHON_TRIM_SET) or "nothing",
               sorted("U+%04X" % c for c in PYTHON_TRIM_SET - js) or "nothing"),
        )

    def test_js_and_python_agree_on_every_case(self):
        divergences = []
        for case, js_answer in zip(self.cases, self.js):
            py_answer = self.manager_util.sanitize_url(case)
            if py_answer != js_answer:
                divergences.append(
                    "  input=%r\n    python=%r\n    js    =%r" % (case, py_answer, js_answer)
                )
        self.assertEqual(
            divergences, [],
            "js/common.js sanitizeUrl has drifted from "
            "glob/manager_util.py::sanitize_url over %d case(s):\n%s\n"
            "Fix the implementations so they agree again — do NOT loosen this "
            "comparison, which is the only thing coupling them."
            % (len(divergences), "\n".join(divergences)),
        )

    def test_null_and_undefined_agree(self):
        """The two non-string inputs both sides handle explicitly.

        Everything else non-string is out of domain — see the module docstring.
        """
        out = run_node(
            "%s\nconsole.log(JSON.stringify({"
            "nul: sanitizeUrl(null), undef: sanitizeUrl(undefined)}));\n"
            % _lift_sanitize_url()
        )
        self.assertEqual(out["nul"], self.manager_util.sanitize_url(None))
        self.assertEqual(out["undef"], "#")

    def _divergences_against(self, lifted_js):
        """Run the SAME comparison test_js_and_python_agree_on_every_case runs."""
        js = run_node(
            "%s\nconst cases = %s;\n"
            "console.log(JSON.stringify({results: cases.map((c) => sanitizeUrl(c))}));\n"
            % (lifted_js, json.dumps(self.cases))
        )["results"]
        return [
            case for case, answer in zip(self.cases, js)
            if self.manager_util.sanitize_url(case) != answer
        ]

    def test_the_guard_goes_red_on_each_perturbation_of_the_js_side(self):
        """Prove the comparison has teeth rather than asserting that it does.

        Each perturbation is a shape a real regression takes — a scheme added to
        the allow-list, the control-char strip losing its /g flag so only the
        FIRST noise byte is removed, the scheme-less branch changing its answer,
        and the empty-input fallback changing. Every one must be caught by the
        case list as it stands, so a guard whose lift silently returned a stub,
        or whose matrix had rotted into irrelevance, cannot look healthy.
        """
        base = _lift_sanitize_url()
        perturbations = {
            # By PATTERN, not by literal: a literal-match perturbation stops
            # applying the moment someone edits the allow-list, and the
            # did-it-apply assertion below then fires INSTEAD of the parity
            # comparison — a red that reads like coverage and is not.
            "allow-list gains a scheme": _perturb_js_allow_list(base, "javascript"),
            "noise strip loses its /g flag":
                base.replace("/[\\x00-\\x20\\x7f]/g", "/[\\x00-\\x20\\x7f]/", 1),
            "scheme-less branch stops trimming":
                base.replace("return trimUrl(raw);\n}", "return raw;\n}", 1),
            # The regression this fix closed: delegating back to String.trim(),
            # which strips U+FEFF that str.strip() keeps and keeps U+001C-001F
            # and U+0085 that str.strip() strips. Caught only by the unicode
            # cases added with the fix — before them the matrix had ASCII edges
            # throughout and this perturbation produced zero divergence.
            "trim delegates back to String.trim()":
                base.replace("trimUrl(raw)", "raw.trim()"),
            "empty-input fallback changes": base.replace("return '#';", "return '';", 1),
        }
        for label, lifted in perturbations.items():
            with self.subTest(perturbation=label):
                self.assertNotEqual(
                    lifted, base,
                    "perturbation %r did not apply — this is the HARNESS "
                    "self-test, NOT the parity comparison. Do not read it as "
                    "coverage: fix the perturbation so the comparison is "
                    "actually exercised." % (label,),
                )
                caught = self._divergences_against(lifted)
                self.assertNotEqual(
                    caught, [],
                    "perturbing the JS side (%s) produced NO divergence — the case "
                    "list cannot detect this drift, so the guard is weaker than it "
                    "looks. Add a case that distinguishes it." % (label,),
                )

    def test_the_guard_goes_red_when_either_allow_list_gains_a_scheme(self):
        """The perturbation that was NOT caught before this test existed.

        Both directions are exercised, because the drift can start on either
        side and the guard is only worth having if it is symmetric. 'ftp' is used
        deliberately: it is absent from the shared matrix, so nothing but the
        allow-list comparison itself can catch it.
        """
        with self.subTest(side="python (the declared SoT)"):
            real = self.manager_util.SAFE_URL_SCHEMES
            try:
                setattr(self.manager_util, "SAFE_URL_SCHEMES", frozenset(set(real) | {"ftp"}))
                self.assertNotEqual(
                    set(self.manager_util.SAFE_URL_SCHEMES), self.allow_lists["js"],
                    "adding a scheme to the PYTHON allow-list produced no "
                    "divergence — the configuration axis is unguarded again",
                )
            finally:
                setattr(self.manager_util, "SAFE_URL_SCHEMES", real)
            self.assertEqual(set(self.manager_util.SAFE_URL_SCHEMES), self.allow_lists["python"])

        with self.subTest(side="js"):
            perturbed = _js_allow_list(_perturb_js_allow_list(_lift_sanitize_url(), "ftp"))
            self.assertIn("ftp", perturbed, "the JS perturbation did not apply")
            self.assertNotEqual(
                set(perturbed), self.allow_lists["python"],
                "adding a scheme to the JS allow-list produced no divergence",
            )

    def test_the_guard_goes_red_on_a_perturbed_python_side(self):
        """The coupling has to run both ways, not just JS-drifts-from-Python."""
        real = self.manager_util.sanitize_url
        try:
            setattr(self.manager_util, "sanitize_url", lambda url: "#")
            caught = self._divergences_against(_lift_sanitize_url())
        finally:
            setattr(self.manager_util, "sanitize_url", real)
        self.assertNotEqual(
            caught, [],
            "perturbing the PYTHON side produced no divergence — the comparison "
            "is not reading the Python implementation it claims to",
        )

    def test_sanitize_url_has_exactly_one_client_side_home(self):
        """The consolidation this guard exists to protect."""
        js_dir = JS.js_dir
        homes = sorted(
            path.name for path in js_dir.glob("*.js")
            if "function sanitizeUrl" in path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            homes, ["common.js"],
            "sanitizeUrl must live only in common.js; every other client file "
            "imports it. A second copy is the drift this guard cannot see, "
            "because it only compares the copy in common.js.",
        )


if __name__ == "__main__":
    unittest.main()
