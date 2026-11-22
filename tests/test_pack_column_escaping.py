"""RED->GREEN guard for the pack-grid column sinks in js/custom-nodes-manager.js.

WHY THESE THREE VALUES
----------------------
The Custom Nodes grid renders every cell through turbogrid, which hands a column
formatter the RAW row value and assigns the formatter's return through
``innerHTML``. Whatever a formatter returns unescaped is therefore live markup on
FIRST RENDER, before any click, for every row the list contains.

Three values reached that sink unescaped, and all three carry the same provenance
as ``author`` (which the neighbouring formatter in the same column array already
escapes):

  ``stars`` and ``last_update`` are written by ``populate_github_stats`` in
  glob/manager_core.py straight off github-stats.json, with no transform.
  ``populate_markdown`` -- the only server-side escape on this payload -- covers
  ``description``, ``name`` and ``title`` and NOTHING else, and
  ``populate_github_stats`` swallows a broken row with a bare ``except:``, so a
  channel-supplied ``stars`` / ``last_update`` survives untouched when
  ``v['reference']`` raises. That double fact is pinned in
  ``PopulateProvenanceTest`` below, because it is what makes escaping HERE
  correct rather than a double-escape.

  ``channel`` is the resolved channel alias from /customnode/getlist -- a key out
  of the channel-list config file, passed through untransformed into the
  "Channel: ..." banner's ``innerHTML``.

WHY THE OLD GUARDS DID NOT STOP THEM
------------------------------------
Neither ``stars`` guard was a guard. ``stars < 0`` is a NaN comparison for a
string ('<img ...>' < 0 is false), and ``typeof stars === 'number'`` only chooses
the toLocaleString branch -- so a string payload fell through to the bare
``return stars;``. ``last_update`` looked defended by ``.split(' ')[0]``, but a
space is not the only attribute separator a browser accepts: ``/`` works, and so
do tab and newline, so ``<img/src=x/onerror=alert(1)>`` passes through the split
whole. Escaping is what closes both; a smarter split would not.

REPRODUCE THE RED HALF against the pre-fix revision -- one command:
  mkdir -p /some/dir
  git show <base>:js/custom-nodes-manager.js > /some/dir/custom-nodes-manager.js
  git show <base>:js/common.js              > /some/dir/common.js
  MANAGER_JS_DIR=/some/dir pytest tests/test_pack_column_escaping.py
"""
import html
import json
import os
import unittest
from pathlib import Path

from js_lift import (
    NODE,
    JsSource,
    event_handlers,
    line_containing,
    parse,
    slice_object_entry,
    slice_braced,
)
from js_lift import run_node
from manager_test_utils import load_manager_util, load_markdown_functions

REPO_ROOT = Path(__file__).resolve().parent.parent
JS = JsSource(os.environ.get("MANAGER_JS_DIR") or (REPO_ROOT / "js"))
GLOB_DIR = Path(os.environ.get("MANAGER_GLOB_DIR") or (REPO_ROOT / "glob"))

MANAGER = "custom-nodes-manager.js"
COMMON = "common.js"

STARS_ANCHOR = "id: 'stars',"
LAST_UPDATE_ANCHOR = "id: 'last_update',"
CHANNEL_ANCHOR = '.cn-manager-channel").innerHTML'

# A space-separated payload for the columns that never split, and a
# SLASH-separated one for last_update, whose `.split(' ')[0]` used to read as a
# defence. Neither needs `<` to be dangerous in an attribute, but both are
# element injections here because the sink is element text.
TEXT_PAYLOAD = "<img src=x onerror=alert(1)>"
NO_SPACE_PAYLOAD = "<img/src=x/onerror=alert(1)>"
TAB_PAYLOAD = "<img\tsrc=x\tonerror=alert(1)>"


def _lift_get_time_ago() -> str:
    """getTimeAgo, lifted by SPAN rather than by brace matching.

    js_lift's brace scanner reads a lone ``/`` as a regex literal -- correct for
    every range it was written for -- and getTimeAgo DIVIDES
    (``Math.abs(diff) / divisor``), so ``slice_braced`` raises on it by design
    rather than handing back a wrong slice. The span is bounded by the
    function's own last statement instead, so a change to that statement fails
    loudly here rather than lifting a truncated body.
    """
    span = JS.lift_span(COMMON, "export function getTimeAgo(", "'in a year', diff < 0);")
    return span.replace("export ", "", 1) + "\n}"


def _preamble() -> str:
    """sanitizeHTML and getTimeAgo, lifted from the shipped common.js."""
    return "\n".join([
        JS.lift_declaration(COMMON, "export function sanitizeHTML("),
        _lift_get_time_ago(),
    ])


def _render(formatter_source: str, value) -> str:
    return run_node(
        "%s\nconst formatter = %s;\n"
        "console.log(JSON.stringify({markup: String(formatter(%s))}));\n"
        % (_preamble(), formatter_source, json.dumps(value))
    )["markup"]


class _InertAssertions(unittest.TestCase):
    def assert_inert(self, markup: str, allowed_tags):
        parsed = parse(markup)
        self.assertEqual(
            [t for t in parsed.tags if t not in allowed_tags], [],
            "live element injected into: %r" % (markup,),
        )
        self.assertEqual(
            event_handlers(markup), [],
            "event-handler attribute injected into: %r" % (markup,),
        )


@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class StarsColumnTest(_InertAssertions):
    """The ★ column formatter, lifted and executed as shipped."""

    @classmethod
    def setUpClass(cls):
        cls.formatter = JS.lift_formatter(MANAGER, STARS_ANCHOR)

    def test_a_string_payload_renders_inert(self):
        for payload in (TEXT_PAYLOAD, NO_SPACE_PAYLOAD, TAB_PAYLOAD):
            with self.subTest(payload=payload):
                markup = self._markup(payload)
                self.assert_inert(markup, allowed_tags=set())
                self.assertEqual(
                    html.unescape(markup), payload,
                    "the payload must survive as READABLE TEXT, not be dropped",
                )

    def _markup(self, value):
        return _render(self.formatter, value)

    def test_a_number_still_renders_through_toLocaleString(self):
        """The behaviour the fix must not disturb: a real star count is grouped.

        Compared against node's OWN toLocaleString rather than a hard-coded
        "1,234", so the assertion does not encode the runtime's default locale.
        """
        expected = run_node(
            "console.log(JSON.stringify({v: (1234567).toLocaleString()}));"
        )["v"]
        markup = self._markup(1234567)
        self.assertEqual(markup, expected)
        self.assertNotIn("&", markup, "a number must not come back entity-escaped")

    def test_a_negative_count_is_still_na(self):
        # -1 is populate_github_stats' "no stats for this pack" sentinel.
        self.assertEqual(self._markup(-1), "N/A")

    def test_zero_is_not_treated_as_missing(self):
        self.assertEqual(self._markup(0), "0")

    def test_a_missing_value_still_renders_an_empty_cell(self):
        """null / undefined pass through, as at every other escaped column.

        turbogrid's renderNodeContent does `void 0===e&&(e="")` and then assigns
        `innerHTML`, which is [LegacyNullToEmptyString] -- so a formatter that
        passes null/undefined THROUGH yields an empty cell, while one that
        stringifies them first puts the literal words "undefined" / "null" on
        screen. That is the shape spelled out at the id formatter in this same
        file and at model-manager's escapeCell, both of which say so in a comment.

        It is reachable on exactly the malformed-row path this file is about:
        populate_github_stats swallows a broken entry with a bare `except:`, so
        `stars` is simply ABSENT for a pack whose `reference` lookup raises.

        Asserted through renderNodeContent's own semantics rather than on the
        formatter's return alone, because "returns undefined" and "renders an
        empty cell" are different claims and it is the second one the user sees.
        """
        out = run_node(
            "%s\nconst formatter = %s;\n"
            "const cell = (v) => { let e = formatter(v); if (void 0 === e) e = '';\n"
            "  return e === null ? '' : String(e); };\n"
            "console.log(JSON.stringify({\n"
            "  undefined_passthrough: formatter(undefined) === undefined,\n"
            "  null_passthrough: formatter(null) === null,\n"
            "  undefined_cell: cell(undefined), null_cell: cell(null)}));\n"
            % (_preamble(), self.formatter)
        )
        self.assertTrue(
            out["undefined_passthrough"],
            "a missing star count is stringified instead of passed through, so "
            "the cell reads 'undefined' where it used to be empty",
        )
        self.assertTrue(out["null_passthrough"], "null is stringified, not passed through")
        self.assertEqual(out["undefined_cell"], "")
        self.assertEqual(out["null_cell"], "")


@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class LastUpdateColumnTest(_InertAssertions):
    """The Last Update column formatter, lifted and executed as shipped."""

    @classmethod
    def setUpClass(cls):
        cls.formatter = JS.lift_formatter(MANAGER, LAST_UPDATE_ANCHOR)

    def _markup(self, value):
        return _render(self.formatter, value)

    def test_a_slash_separated_payload_renders_inert(self):
        """The case `.split(' ')[0]` cannot touch: no space anywhere in it."""
        markup = self._markup(NO_SPACE_PAYLOAD)
        self.assert_inert(markup, allowed_tags={"span"})

    def test_separator_variants_render_inert(self):
        for payload in (TEXT_PAYLOAD, NO_SPACE_PAYLOAD, TAB_PAYLOAD):
            with self.subTest(payload=payload):
                self.assert_inert(self._markup(payload), allowed_tags={"span"})

    def test_the_title_attribute_cannot_be_broken_out_of(self):
        # `ago` is not escaped, deliberately: getTimeAgo returns "" or a phrase
        # off a fixed table and never echoes its input. This pins that premise
        # behaviourally rather than trusting it.
        markup = self._markup('x" onmouseover=alert(1) y')
        self.assertEqual(event_handlers(markup), [], markup)
        self.assertEqual(
            sorted(name for name, _ in parse(markup).attrs), ["title"], markup,
        )

    def test_a_normal_date_still_renders_its_short_form(self):
        markup = self._markup("2024-01-02 03:04:05")
        self.assertIn(">2024-01-02<", markup)
        self.assertEqual([t for t in parse(markup).tags], ["span"])

    def test_a_negative_timestamp_is_still_na(self):
        self.assertEqual(self._markup(-1), "N/A")


@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class ChannelBannerTest(_InertAssertions):
    """The "Channel: ..." banner, rendered through the shipped source line."""

    @classmethod
    def setUpClass(cls):
        cls.line = line_containing(JS.text(MANAGER), CHANNEL_ANCHOR)

    def _markup(self, channel):
        expression = self.line.split("innerHTML =", 1)[1].strip().rstrip(";")
        return run_node(
            "%s\nconst self = {channel: %s};\n"
            "console.log(JSON.stringify({markup: %s}));\n"
            % (_preamble(), json.dumps(channel),
               expression.replace("this.channel", "self.channel"))
        )["markup"]

    def test_a_payload_in_the_channel_alias_renders_inert(self):
        markup = self._markup(TEXT_PAYLOAD)
        self.assert_inert(markup, allowed_tags=set())
        self.assertIn("Channel: ", markup)

    def test_a_benign_alias_is_still_readable(self):
        # No server transform touches this value, so escaping it once is
        # correct and cannot show entity text for an ordinary alias.
        self.assertIn("Channel: dev (Incomplete list)", self._markup("dev"))


class ColumnShapeTest(unittest.TestCase):
    """The formatters must keep EXISTING, or the grid's default takes over.

    turbogrid's default formatter is a pass-through, so deleting either
    formatter silently restores the raw-value-into-innerHTML path these tests
    exist to close -- with every behavioural test above still passing, because
    they lift the formatter and would simply stop being able to find one.
    """

    def test_both_columns_declare_a_formatter(self):
        source = JS.text(MANAGER)
        for anchor in (STARS_ANCHOR, LAST_UPDATE_ANCHOR):
            with self.subTest(column=anchor):
                entry = slice_object_entry(source, anchor)
                self.assertIn(
                    "formatter:", entry,
                    "%s lost its formatter; the grid default renders the raw "
                    "value into innerHTML" % (anchor,),
                )
                self.assertIn("sanitizeHTML(", entry)


class PopulateProvenanceTest(unittest.TestCase):
    """WHY escaping here is single-escaping, not double-escaping.

    If the server ever started escaping these two fields, the formatters would
    render entity text to the user and this file would be the thing to change.
    The premise is therefore asserted rather than assumed.
    """

    def test_populate_markdown_does_not_cover_stars_or_last_update(self):
        source = (GLOB_DIR / "manager_server.py").read_text(encoding="utf-8")
        body = source[source.index("def populate_markdown("):]
        body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
        for field in ("'description'", "'name'", "'title'"):
            self.assertIn("if %s in x:" % field, body)
        for field in ("stars", "last_update"):
            self.assertNotIn(
                "'%s'" % field, body,
                "populate_markdown now touches %s -- if it escapes it, the "
                "formatter must STOP escaping or the user reads entity text"
                % (field,),
            )

    def test_the_stats_fields_are_written_untransformed(self):
        source = (GLOB_DIR / "manager_core.py").read_text(encoding="utf-8")
        body = source[source.index("def populate_github_stats("):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn("v['stars'] = json_obj_github[url]['stars']", body)
        self.assertIn("v['last_update'] = json_obj_github[url]['last_update']", body)
        self.assertIn(
            "except:", body,
            "the bare except is what leaves a channel-supplied stars/last_update "
            "in place when reference lookup raises; if it is gone, re-derive the "
            "provenance argument in this file's docstring",
        )


@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class PackOperationErrorTest(_InertAssertions):
    def test_failed_operations_keep_server_escaped_titles_readable(self):
        populate = load_markdown_functions(load_manager_util())["populate_markdown"]
        methods = ",\n".join(slice_braced(JS.text(MANAGER), "\n\t" + marker) for marker in [
            "async installNodes(list, btn, title, selected_version)",
            "showError(err)", "showMessage(msg, color)", "showStatus(msg, color)",
        ])
        for title in ("Pack <Flux> & friends", TEXT_PAYLOAD):
            item = {"title": title, "originalData": {}, "hash": "pack"}
            populate(item)
            for mode in ("install", "uninstall"):
                for status in (403, 500):
                    with self.subTest(title=title, mode=mode, status=status):
                        out = run_node("""
                            %s
                            const item = %s;
                            const elements = {};
                            const messages = {};
                            const api = {fetchApi: async () => ({status: %d,
                                json: async () => ({is_processing: false}), text: async () => %s})};
                            const show_message = message => messages.dialog = message;
                            const customConfirm = async () => true;
                            const ctx = {
                                %s,
                                element: {querySelector: selector => elements[selector] ||= {innerHTML: ''}},
                                grid: {getRowItemBy: () => item, scrollRowIntoView() {}, updateCell() {}},
                                focusInstall() {return true;}
                            };
                            await ctx.installNodes(['pack'], {target: {classList: {add() {}}},
                                label: 'Operation', mode: %s}, '', null);
                            messages.panel = elements['.cn-manager-message'].innerHTML;
                            console.log(JSON.stringify(messages));
                        """ % (_preamble(), json.dumps(item), status, json.dumps(TEXT_PAYLOAD), methods, json.dumps(mode)))
                        for message in out.values():
                            self.assert_inert(message, allowed_tags={"font"})
                            self.assertIn(f"'{title}': ", html.unescape(message))
                            if status == 500:
                                self.assertIn(": " + TEXT_PAYLOAD, html.unescape(message))


if __name__ == "__main__":
    unittest.main()
