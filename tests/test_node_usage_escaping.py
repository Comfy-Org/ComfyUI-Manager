"""RED->GREEN guard for the js/node-usage-analyzer.js innerHTML sinks.

The analyzer writes pack data and workflow data into innerHTML through turbogrid
cells, a flyover, and the status/message elements. Before the fix: the title
column built an UNQUOTED href (a bare space breaks out of the attribute); the
install-progress showStatus interpolated a raw pack key; the usage-details
flyover interpolated a raw workflow filename; and the install error path
interpolated both a raw pack key and raw server text.

One value needed fixing at its SOURCE rather than at the sink. The title column
is built as `pack.title || packKey`: /customnode/getlist runs populate_markdown
over each pack, so `pack.title` is server-escaped, but `packKey` is a dict key
that no server transform touches. Escaping at the formatter would have
double-escaped the common path into visible entity text ("Nodes for &lt;Flux&gt;
workflows"); leaving it bare would have shipped the raw fallback. The fix
normalises the fallback so the column carries ONE provenance, which is what
makes the bare formatter correct by construction.

This grid uses cellResizeObserver only — no rowFilter, no
highlightKeywordsFilter — so the keyword-highlight re-render does not reach it.
The two searchable managers use js/manager-grid.js to secure that path without
modifying the vendored TurboGrid bundle.

The status/message sinks take DISPLAY-READY text and do NOT escape, because
their callers carry mixed provenance; every caller is classified in
tests/test_message_sink_provenance.py. This analyzer is the only file that
reaches BOTH sink implementations — the shared one from common.js via `this.ui`
and its own class methods.

REPRODUCE THE RED HALF against the pre-fix revision — one command:
  mkdir -p /some/dir
  git show <base>:js/node-usage-analyzer.js > /some/dir/node-usage-analyzer.js
  git show <base>:js/common.js             > /some/dir/common.js
  MANAGER_JS_DIR=/some/dir pytest tests/test_node_usage_escaping.py
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
    parse,
    run_node,
    slice_braced,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
JS = JsSource(os.environ.get("MANAGER_JS_DIR") or (REPO_ROOT / "js"))

ANALYZER = "node-usage-analyzer.js"
COMMON = "common.js"
TITLE_FORMATTER_ANCHOR = "formatter: function (name, rowItem, columnItem, cellNode)"

BREAKOUT_HREF = "https://evil.example/a onmouseover=alert(1) x"
QUOTE_BREAKOUT = 'https://evil.example/a"><img src=x onerror=alert(1)>'
# An ordinary pack reference, for the legs that ask what a CORRECT link
# looks like rather than what a hostile one cannot do.
BENIGN_REFERENCE = "https://github.com/owner/repo"
TEXT_PAYLOAD = "<img src=x onerror=alert(1)>"


def _url_helper_home() -> str:
    """Which file currently owns sanitizeUrl/safeHref, or '' on a pre-fix tree.

    They were local to the analyzer when this guard was written and now live in
    common.js, imported by every client file. Resolving the home rather than
    hard-coding it keeps the MANAGER_JS_DIR reproduce working against both
    revisions, and makes a THIRD home fail loudly instead of being lifted twice.
    """
    for filename in (COMMON, ANALYZER):
        if "SAFE_URL_SCHEMES" in JS.text(filename):
            return filename
    return ""


def _preamble() -> str:
    parts = [JS.lift_declaration(COMMON, "export function sanitizeHTML(")]
    home = _url_helper_home()
    if home:
        span = JS.lift_span(
            home, "SAFE_URL_SCHEMES", "safeHref = (url) => sanitizeHTML(sanitizeUrl(url));")
        parts.append("const " + span.replace("export ", ""))
    return "\n".join(parts)


@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class NodeUsageSinkEscapingTest(unittest.TestCase):
    """Every sink is exercised through the REAL lifted code, never a copy."""

    def _assert_inert(self, markup: str, allowed_tags):
        """No element outside the allow-list, and no event-handler attribute."""
        parsed = parse(markup)
        self.assertEqual(
            [t for t in parsed.tags if t not in allowed_tags], [],
            "live element injected into: %r" % (markup,),
        )
        self.assertEqual(
            event_handlers(markup), [],
            "event-handler attribute injected into: %r" % (markup,),
        )

    # --- C2: title column, previously UNQUOTED href -------------------------
    def _render_title(self, reference: str, name: str = "My Pack") -> str:
        return run_node(
            "%s\nconst titleFormatter = %s;\n"
            "console.log(JSON.stringify({markup: titleFormatter(%s, {reference: %s})}));\n"
            % (_preamble(),
               JS.lift_formatter(ANALYZER, TITLE_FORMATTER_ANCHOR),
               json.dumps(name), json.dumps(reference))
        )["markup"]

    def test_c2_href_survives_breakout_attempts(self):
        for reference in (BREAKOUT_HREF, QUOTE_BREAKOUT):
            markup = self._render_title(reference)
            self._assert_inert(markup, allowed_tags={"a", "b"})
            self.assertEqual(
                sorted(name for name, _ in parse(markup).attrs),
                ["href", "rel", "target"],
                "unexpected attributes on the anchor: %r" % (markup,),
            )

    def test_c2_title_anchor_severs_the_opener(self):
        """The pack chooses this host, so the page it opens must not keep us.

        `reference` is channel data, so the pack author picks the page that
        opens; without rel that page holds a live window.opener back into the
        Manager UI. Membership on the SPLIT attribute, not a literal match:
        'noreferrer noopener' is the same thing, and pinning token order would
        report a correct fix as a defect.
        """
        markup = self._render_title(BENIGN_REFERENCE)
        attrs = dict(parse(markup).attrs)
        self.assertEqual(
            attrs.get("target"), "_blank",
            "this guard is about _blank anchors; the target changed, so "
            "re-derive it rather than deleting the assertion: %r" % (markup,))
        self.assertIn(
            "rel", attrs,
            "the title anchor opens a pack-chosen page in a new tab without "
            "rel, so that page keeps a reference to this window: %r" % (markup,))
        tokens = attrs["rel"].lower().split()
        self.assertIn("noopener", tokens, markup)
        self.assertIn("noreferrer", tokens, markup)

    def test_c2_href_rejects_dangerous_schemes(self):
        for reference in ("javascript:alert(1)", "java\tscript:alert(1)",
                          "data:text/html,<script>alert(1)</script>"):
            href = dict(parse(self._render_title(reference)).attrs)["href"]
            self.assertEqual(href, "#", "%r survived as %r" % (reference, href))

    def test_c2_benign_reference_and_title_are_untouched(self):
        markup = self._render_title(BENIGN_REFERENCE, name="My Pack")
        self.assertEqual(dict(parse(markup).attrs)["href"], BENIGN_REFERENCE)
        self.assertIn("<b>My Pack</b>", markup)

    def test_c2_title_is_not_double_escaped_at_the_formatter(self):
        # The column value is already escaped HTML text by the time it arrives,
        # so re-escaping here would put entity text on screen.
        block = JS.lift_formatter(ANALYZER, TITLE_FORMATTER_ANCHOR)
        self.assertNotIn(
            "sanitizeHTML(String(name))", block,
            "title is normalised at its source; escaping it again renders '&lt;' to the user",
        )
        server_value = "Nodes for &lt;Flux&gt; workflows"
        markup = self._render_title("https://example.com/x", name=server_value)
        self.assertIn(server_value, markup)
        self.assertEqual(html.unescape(server_value), "Nodes for <Flux> workflows")

    def _run_panel(self, action, packs=None, status=500):
        """Run the production data, operation and rendering methods with stubbed I/O."""
        methods = ",\n".join(slice_braced(JS.text(ANALYZER), "\n\t" + marker) for marker in [
            "async loadData()", "async installModels(list, btn)", "async uninstallModels(list, btn)",
            "showUsageDetails(rowItem)", "showError(err)", "showMessage(msg, color)", "showStatus(msg, color)",
        ])
        return run_node("""
            %s
            %s
            %s
            const elements = {};
            const messages = {};
            const posts = [];
            const manager_instance = {datasrc_combo: {value: 'default'}};
            const fetchData = async () => ({data: {channel: 'default', node_packs: %s}});
            const analyzeWorkflowUsage = async () => ({success: true});
            const api = {fetchApi: async (url, options) => {
                if (options?.body) posts.push(JSON.parse(options.body));
                return {status: %d, json: async () => ({is_processing: false}), text: async () => %s};
            }};
            const customConfirm = async () => true;
            const md5 = () => 'hash';
            const show_message = message => messages.dialog = message;
            const btn = {classList: {add() {}, remove() {}}};
            const ctx = {
                %s,
                element: {querySelector: selector => elements[selector] ||= {innerHTML: '', style: {}}},
                grid: {scrollRowIntoView() {}, updateCell() {}, updateRow() {}},
                flyover: {show: (title, body) => Object.assign(messages, {title, body})},
                showLoading() {}, hideLoading() {}, renderGrid() {}, getModelList(rows) {return rows;}
            };
            ctx.ui = createUIStateManager(ctx.element, {
                status: '.nu-manager-status', message: '.nu-manager-message'
            });
            %s
            console.log(JSON.stringify({elements, messages, posts, rows: ctx.modelList}));
        """ % (_preamble(),
               JS.lift_declaration(COMMON, "export function createUIStateManager(element, selectors)"),
               JS.lift_declaration(COMMON, "export async function uninstallNodes(nodeList, options = {})"),
               json.dumps(packs or {}), status, json.dumps(TEXT_PAYLOAD), methods, action))

    def test_title_fallback_is_escaped_at_its_source(self):
        out = self._run_panel("await ctx.loadData();", {TEXT_PAYLOAD: {"state": "enabled"}})
        row = out["rows"][0]
        self._assert_inert(row["title"], allowed_tags=set())
        self.assertEqual(html.unescape(row["title"]), TEXT_PAYLOAD)
        self.assertEqual(row["name"], TEXT_PAYLOAD)

    def test_install_progress_and_errors_escape_raw_values(self):
        for status in (403, 500):
            with self.subTest(status=status):
                out = self._run_panel("await ctx.loadData(); await ctx.installModels(ctx.modelList, btn);",
                                      {TEXT_PAYLOAD: {"state": "enabled"}}, status)
                progress = out["elements"][".nu-manager-status"]["innerHTML"]
                self._assert_inert(progress, allowed_tags=set())
                self.assertEqual(html.unescape(progress), f"Install {TEXT_PAYLOAD} ...")
                errors = [out["elements"][".nu-manager-message"]["innerHTML"], out["messages"]["dialog"]]
                for error in errors:
                    self._assert_inert(error, allowed_tags={"font"})
                    self.assertIn(f"'{TEXT_PAYLOAD}': ", html.unescape(error))
                    if status == 500:
                        self.assertIn(": " + TEXT_PAYLOAD, html.unescape(error))

    def test_flyover_escapes_workflow_filename(self):
        for filename in (TEXT_PAYLOAD, "workflow <Flux> & friends.json"):
            with self.subTest(filename=filename):
                out = self._run_panel("ctx.showUsageDetails(%s);" % json.dumps({
                    "title": "My Pack", "workflowDetails": [{"filename": filename, "nodeCount": 2}],
                }))
                body = out["messages"]["body"]
                self._assert_inert(body, allowed_tags={"div"})
                self.assertIn(filename, html.unescape(body))
                self.assertIn("2 nodes", body)

    def test_uninstall_failure_keeps_normalized_titles_readable(self):
        for name in ("Pack <Flux> & friends", TEXT_PAYLOAD):
            for has_title in (False, True):
                for status in (403, 500):
                    with self.subTest(name=name, has_title=has_title, status=status):
                        pack = {"state": "enabled"}
                        if has_title:
                            pack["title"] = html.escape(name)
                        out = self._run_panel("await ctx.loadData(); await ctx.uninstallModels(ctx.modelList, btn);",
                                              {name: pack}, status)
                        progress = out["elements"][".nu-manager-status"]["innerHTML"]
                        self.assertEqual(html.unescape(progress), f"Uninstall {name} ...")
                        errors = [out["elements"][".nu-manager-message"]["innerHTML"], out["messages"]["dialog"]]
                        for error in errors:
                            self._assert_inert(error, allowed_tags={"font"})
                            self.assertIn(f"'{name}': ", html.unescape(error))
                            if status == 500:
                                self.assertIn(": " + TEXT_PAYLOAD, html.unescape(error))

    def test_uninstall_helper_escapes_a_raw_name_fallback(self):
        out = self._run_panel("""
            await uninstallNodes([{name: %s}], {
                onProgress: msg => messages.progress = msg,
                onError: msg => messages.error = msg
            });
        """ % json.dumps(TEXT_PAYLOAD))
        for message in out["messages"].values():
            self._assert_inert(message, allowed_tags=set())
            self.assertIn(TEXT_PAYLOAD, html.unescape(message))
        self.assertEqual(out["posts"][0]["name"], TEXT_PAYLOAD)

    def test_grid_has_no_keyword_highlight_path(self):
        # The premise the row states: this grid cannot hit the highlight defect.
        source = JS.text(ANALYZER)
        self.assertNotIn("highlightKeywordsFilter", source)
        self.assertNotIn("rowFilter:", source)


if __name__ == "__main__":
    unittest.main()
