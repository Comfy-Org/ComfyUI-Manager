import html
import json
import os
import unittest
from pathlib import Path

from js_lift import NODE, JsSource, parse as _parse, run_node as _run_node, slice_braced
from manager_test_utils import load_manager_util, load_markdown_functions

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_DIR = Path(os.environ.get("MANAGER_JS_DIR") or (REPO_ROOT / "js"))
JS = JsSource(JS_DIR)
MANAGER_UTIL = load_manager_util()


MODEL_MANAGER_SRC = (JS_DIR / "model-manager.js").read_text(encoding="utf-8")
COMMON_SRC = (JS_DIR / "common.js").read_text(encoding="utf-8")


def _lift_sanitize_html() -> str:
    return JS.lift_declaration("common.js", "export function sanitizeHTML(")


def _lift_icons() -> str:
    """The real `icons` constant — the url formatter embeds icons.download."""
    return JS.lift_declaration("common.js", "export const icons = ")


def _lift_url_helpers() -> str:
    """sanitizeUrl + safeHref, which live in common.js since the consolidation.

    Returns '' on a pre-consolidation tree so the MANAGER_JS_DIR reproduce still
    works against an older revision: there the helpers were local to
    model-manager.js and _lift_model_manager_helpers picks them up instead.
    """
    if "export function sanitizeUrl" not in COMMON_SRC:
        return ""
    span = JS.lift_span("common.js", "export const SAFE_URL_SCHEMES",
                        "export const safeHref = (url) => sanitizeHTML(sanitizeUrl(url));")
    return span.replace("export ", "")


def _lift_model_manager_helpers() -> str:
    """The escaping helpers that are still local to model-manager.js.

    escapeCell and renderOptions stay in the client file — they are specific to
    its grid and its filter dropdowns. On a pre-consolidation tree this block
    also still contains sanitizeUrl/safeHref, which is why the slice starts at
    whichever marker that revision actually has.
    """
    if "const escapeCell" not in MODEL_MANAGER_SRC:
        return ""
    marker = ("const SAFE_URL_SCHEMES" if "const SAFE_URL_SCHEMES" in MODEL_MANAGER_SRC
              else "const escapeCell")
    start = MODEL_MANAGER_SRC.index(marker)
    end = MODEL_MANAGER_SRC.index("const renderOptions")
    end = MODEL_MANAGER_SRC.index('}).join("");', end) + len('}).join("");')
    return MODEL_MANAGER_SRC[start:end]


def _slice_column(column_id: str) -> str:
    """Return one column-definition object out of the `}, {`-chained columns array.

    These objects are literals inside an array, so the first `{` after the id
    marker belongs to the NEXT column — brace matching cannot be used. The
    object instead ends at the first `}` sitting at the array's own indent.
    """
    start = MODEL_MANAGER_SRC.index("id: %s," % column_id)
    end = MODEL_MANAGER_SRC.index("\n\t\t}", start)
    return MODEL_MANAGER_SRC[start:end]


def _lift_formatter(anchor: str) -> str:
    """Lift the ``formatter: ...`` at ``anchor`` as a bare function expression."""
    block = slice_braced(MODEL_MANAGER_SRC, anchor)
    marker = "formatter:"
    return block[block.index(marker) + len(marker):].strip()


NAME_FORMATTER_ANCHOR = "formatter: function(name, rowItem, columnItem, cellNode)"
URL_FORMATTER_ANCHOR = "formatter: (url, rowItem, columnItem)"

BREAKOUT_HREF = "https://evil.example/a onmouseover=alert(1) x"
QUOTE_BREAKOUT = 'https://evil.example/a"><img src=x onerror=alert(1)>'
TEXT_PAYLOAD = "<img src=x onerror=alert(1)>"
ATTR_BREAKOUT = '" onfocus=alert(1) x="'


@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class ModelManagerSinkEscapingTest(unittest.TestCase):
    """Every sink is exercised through the REAL lifted code, never a copy."""

    @classmethod
    def setUpClass(cls):
        cls.preamble = "\n".join([
            _lift_sanitize_html(),
            _lift_icons(),
            _lift_url_helpers(),
            _lift_model_manager_helpers(),
        ])

    def _eval(self, expressions: dict) -> dict:
        body = ",".join("%s: %s" % (json.dumps(k), v) for k, v in expressions.items())
        return _run_node(
            "%s\n"
            "const nameFormatter = %s;\n"
            "const urlFormatter = %s;\n"
            "console.log(JSON.stringify({%s}));\n"
            % (self.preamble,
               _lift_formatter(NAME_FORMATTER_ANCHOR),
               _lift_formatter(URL_FORMATTER_ANCHOR),
               body)
        )

    def _assert_inert(self, markup: str, allowed_tags):
        """No element outside the allow-list, and no event-handler attribute."""
        parsed = _parse(markup)
        self.assertEqual(
            [t for t in parsed.tags if t not in allowed_tags], [],
            "live element injected into: %r" % (markup,),
        )
        handlers = [name for name, _ in parsed.attrs if name.lower().startswith("on")]
        self.assertEqual(handlers, [], "event-handler attribute injected into: %r" % (markup,))

    # --- D-IV: name column, previously UNQUOTED href ------------------------
    def test_d4_name_href_survives_breakout_attempts(self):
        out = self._eval({
            "space": "nameFormatter('Model', {reference: %s})" % json.dumps(BREAKOUT_HREF),
            "quote": "nameFormatter('Model', {reference: %s})" % json.dumps(QUOTE_BREAKOUT),
        })
        for markup in out.values():
            self._assert_inert(markup, allowed_tags={"a", "b"})
            self.assertEqual(
                sorted(name for name, _ in _parse(markup).attrs),
                ["href", "rel", "target"],
                "unexpected attributes on the anchor: %r" % (markup,),
            )

    def test_d4_name_href_rejects_dangerous_schemes(self):
        out = self._eval({
            "js": "nameFormatter('Model', {reference: 'javascript:alert(1)'})",
            "obfuscated": r"nameFormatter('Model', {reference: 'java\tscript:alert(1)'})",
            "entity": "nameFormatter('Model', {reference: 'javascript&#58;alert(1)'})",
            "data": "nameFormatter('Model', {reference: 'data:text/html,<script>alert(1)</script>'})",
            "ok": "nameFormatter('Model', {reference: 'https://huggingface.co/repo'})",
        })
        for key in ("js", "obfuscated", "data"):
            href = dict(_parse(out[key]).attrs)["href"]
            self.assertEqual(href, "#", "%s: dangerous scheme survived as %r" % (key, href))
        # The entity form is defeated by the attribute escape, not the scheme
        # check: `&` becomes `&amp;`, so `&#58;` reaches the browser as text.
        self.assertIn("&amp;#58;", out["entity"])
        self.assertEqual(dict(_parse(out["ok"]).attrs)["href"], "https://huggingface.co/repo")

    # --- D-V: url column, quoted but previously unescaped -------------------
    def test_d5_url_href_escaped_inside_its_quotes(self):
        out = self._eval({
            "quote": "urlFormatter(%s)" % json.dumps(QUOTE_BREAKOUT),
            "attr": "urlFormatter(%s)" % json.dumps(ATTR_BREAKOUT),
            "js": "urlFormatter('javascript:alert(1)')",
        })
        self._assert_inert(out["quote"], allowed_tags={"a", "svg", "path"})
        self._assert_inert(out["attr"], allowed_tags={"a", "svg", "path"})
        self.assertEqual(dict(_parse(out["js"]).attrs)["href"], "#")

    # --- D-III: the four previously formatter-less columns ------------------
    def test_d3_columns_bind_the_escaping_formatter(self):
        for column in ("'type'", "'base'", '"save_path"', "'filename'"):
            block = _slice_column(column)
            self.assertIn(
                "formatter: escapeCell", block,
                "column %s still renders RAW model-list.json into innerHTML" % column,
            )

    def test_d3_escape_cell_neutralises_payload_and_keeps_empty_cells(self):
        out = _run_node(
            "%s\nconsole.log(JSON.stringify({"
            "payload: escapeCell(%s),"
            "nul: escapeCell(null), undef: escapeCell(undefined),"
            "num: escapeCell(42), plain: escapeCell('checkpoints')"
            "}));\n" % (self.preamble, json.dumps(TEXT_PAYLOAD))
        )
        self._assert_inert(out["payload"], allowed_tags=set())
        self.assertEqual(html.unescape(out["payload"]), TEXT_PAYLOAD,
                         "the payload must survive as visible text")
        # null/undefined pass through so turbogrid keeps rendering an empty cell.
        self.assertIsNone(out["nul"])
        self.assertNotIn("undef", out)
        self.assertEqual(out["num"], "42")
        self.assertEqual(out["plain"], "checkpoints")

    # --- D-VI: the showStatus message sink ----------------------------------
    def test_d6_show_status_renders_item_name_inert(self):
        """item.name must reach .cmm-manager-status innerHTML inert.

        This used to assert that the CALL SITE carried a sanitizeHTML. That was
        wrong in a way the assertion could not see: ``item.name`` arrives from
        ``/externalmodel/getlist`` ALREADY escaped by ``populate_markdown`` ->
        ``sanitize_tag``, so escaping it again rendered ``&lt;Flux&gt;`` to the
        user. The call-site escape was removed for that reason, and the sink
        deliberately does not escape either -- see
        tests/test_message_sink_provenance.py for why a blanket sink escape
        cannot be correct across these callers.

        The GUARANTEE is unchanged, and is now asserted end-to-end on the value
        the caller ACTUALLY receives: take the server's own output for a hostile
        name, push it through the REAL lifted sink, and read innerHTML. That is
        strictly stronger than the old form, which passed whether or not the
        rendered result was inert.
        """
        anchor = "this.showStatus(`Install "
        line = MODEL_MANAGER_SRC[MODEL_MANAGER_SRC.index(anchor):]
        line = line[:line.index("\n")]
        self.assertNotIn(
            "sanitizeHTML", line,
            "item.name is already server-escaped; escaping here is the mojibake "
            "bug this call site used to have: %r" % (line,),
        )
        # What populate_markdown -> sanitize_tag puts on the wire for the payload.
        server_value = TEXT_PAYLOAD.replace("<", "&lt;").replace(">", "&gt;")
        lifted = "function " + slice_braced(MODEL_MANAGER_SRC, "\tshowStatus(msg, color)")
        rendered = _run_node(
            "%s\nconst sink = %s;\n"
            "const item = {name: %s};\n"
            "const el = { innerHTML: '' };\n"
            "const ctx = { element: { querySelector: () => el } };\n"
            "sink.call(ctx, `Install ${item.name} ...`);\n"
            "console.log(JSON.stringify({msg: el.innerHTML}));\n"
            % (_lift_sanitize_html(), lifted, json.dumps(server_value))
        )
        self._assert_inert(rendered["msg"], allowed_tags=set())
        # ...and the user reads the payload as text, not as entity soup.
        self.assertEqual(
            html.unescape(rendered["msg"]), "Install %s ..." % TEXT_PAYLOAD
        )

    # --- filter dropdowns: same raw type/base values, different route -------
    def test_filter_dropdown_options_escape_label_and_value(self):
        out = _run_node(
            "%s\nconsole.log(JSON.stringify({"
            "label: renderOptions([{label: %s, value: 'x'}], ''),"
            "value: renderOptions([{label: 'x', value: %s}], ''),"
            "plain: renderOptions([{label: 'checkpoints', value: 'checkpoints'}], 'checkpoints')"
            "}));\n" % (self.preamble, json.dumps(TEXT_PAYLOAD), json.dumps(ATTR_BREAKOUT))
        )
        self._assert_inert(out["label"], allowed_tags={"option"})
        self._assert_inert(out["value"], allowed_tags={"option"})
        # Selection still matches on the RAW value, and benign data is untouched.
        self.assertIn(" selected", out["plain"])
        self.assertIn(">checkpoints</option>", out["plain"])

    def test_update_filter_routes_all_three_dropdowns_through_render_options(self):
        block = slice_braced(MODEL_MANAGER_SRC, "updateFilter()")
        for dropdown in ("$filter", "$type", "$base"):
            self.assertIn(
                "%s.innerHTML = renderOptions(" % dropdown, block,
                "%s still builds <option> markup inline" % dropdown,
            )

    # --- description: server-transformed HTML, must NOT be double-escaped ---
    def test_description_column_is_not_re_escaped(self):
        block = _slice_column("'description'")
        self.assertNotIn(
            "formatter", block,
            "description is server-transformed HTML (populate_markdown); re-escaping "
            "it renders visible mojibake such as 'Nodes for &lt;Flux&gt; workflows'",
        )

    def test_description_server_value_still_reads_cleanly(self):
        # What populate_markdown -> sanitize_tag actually emits for "<Flux>".
        server_value = "Nodes for &lt;Flux&gt; workflows"
        self.assertEqual(html.unescape(server_value), "Nodes for <Flux> workflows")
        # Run through the client escaper as well, the user would see the entity
        # text instead of the angle brackets — that is what this guard forbids.
        double = _run_node(
            "%s\nconsole.log(JSON.stringify({v: sanitizeHTML(%s)}));\n"
            % (_lift_sanitize_html(), json.dumps(server_value))
        )["v"]
        self.assertEqual(html.unescape(double), server_value)

@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class ModelManagerMessageSinkTest(unittest.TestCase):
    """model-manager's OWN message sinks — it does not use createUIStateManager.

    This class replaces an earlier ``test_turbogrid_bundle_untouched`` guard,
    which asserted that ``js/turbogrid.esm.js`` was unchanged relative to a
    fixed base commit. That was an INTEGRATION ARTIFACT, not a property of this
    file: it encoded "only model-manager was touched by the work item that
    added these tests". In the integrated tree the vendored grid IS changed on
    purpose, so the assertion reported a cross-file fact that says nothing
    about whether model-manager's own sinks are safe. What this file can
    actually guarantee is asserted instead — and it is strictly more coverage,
    because the sinks below were not covered by anything before.
    """

    @classmethod
    def setUpClass(cls):
        cls.sanitize = _lift_sanitize_html()

    def _call_sink(self, method: str, msg, color=None) -> str:
        """Run one lifted sink against a stub element; return the real innerHTML."""
        lifted = "function " + slice_braced(MODEL_MANAGER_SRC, "\t%s(msg, color)" % method)
        args = json.dumps(msg) + ("" if color is None else ", " + json.dumps(color))
        return _run_node(
            "%s\n"
            "const sink = %s;\n"
            "const el = { innerHTML: '' };\n"
            "const ctx = { element: { querySelector: () => el } };\n"
            "sink.call(ctx, %s);\n"
            "console.log(JSON.stringify({v: el.innerHTML}));\n"
            % (self.sanitize, lifted, args)
        )["v"]

    # --- the sinks take DISPLAY-READY text and do NOT escape ---------------
    def test_the_sinks_deliberately_do_not_escape(self):
        # Structural, and load-bearing: a well-meaning sanitizeHTML added here
        # would double-escape the server-escaped values these sinks actually
        # receive. tests/test_message_sink_provenance.py is what keeps that safe
        # by classifying every caller.
        for method in ("showStatus(msg, color)", "showMessage(msg, color)"):
            body = slice_braced(MODEL_MANAGER_SRC, "\t" + method)
            self.assertNotIn(
                "sanitizeHTML", body,
                "%s escapes at the sink; its callers pass ALREADY-escaped server "
                "values, so this renders '&lt;Flux&gt;' to the user" % method,
            )
            self.assertIn("innerHTML", body)

    def test_a_server_escaped_value_renders_inert_through_the_sink(self):
        server_value = "Install %s ..." % TEXT_PAYLOAD.replace(
            "<", "&lt;").replace(">", "&gt;")
        rendered = self._call_sink("showStatus", server_value)
        self.assertNotIn("img", _parse(rendered).tags)

    def test_a_benign_angle_bracket_name_is_not_double_escaped(self):
        # THE regression this arrangement exists to prevent. The server sends
        # 'Model for &lt;Flux&gt; workflows'; the user must read the angle
        # brackets, not the entities.
        server_value = "Install Model for &lt;Flux&gt; workflows ..."
        rendered = self._call_sink("showStatus", server_value)
        self.assertEqual(
            html.unescape(rendered), "Install Model for <Flux> workflows ..."
        )
        self.assertNotIn("&amp;lt;", rendered)

    def test_the_font_wrapper_still_renders(self):
        rendered = self._call_sink("showMessage", "plain text", "red")
        collector = _parse(rendered)
        self.assertIn("font", collector.tags)
        self.assertIn(("color", "red"), collector.attrs)

    # --- showError: HTML BY CONTRACT, escaped by its callers ---------------
    def test_show_error_forwards_to_the_non_escaping_show_message(self):
        # showError is HTML by contract: its errorMsg is built escaped because
        # the SAME string also goes to ComfyUI-core show_message(). Forwarding
        # to a NON-escaping showMessage keeps that at exactly one escape.
        body = slice_braced(MODEL_MANAGER_SRC, "\tshowError(err)")
        self.assertIn("this.showMessage(err, \"red\")", body)

    # --- the caller side ---------------------------------------------------
    def test_the_install_status_caller_passes_the_server_value_untouched(self):
        self.assertIn("this.showStatus(`Install ${item.name} ...`)", MODEL_MANAGER_SRC)

    def test_the_install_error_message_escapes_only_the_raw_response(self):
        # The name is already escaped by the server; the error response is raw.
        self.assertIn(
            "errorMsg = `'${item.name}': `", MODEL_MANAGER_SRC
        )
        self.assertIn("errorMsg += sanitizeHTML(await res.text())", MODEL_MANAGER_SRC)

    def test_install_failure_preserves_server_escaped_names_in_both_sinks(self):
        populate = load_markdown_functions(MANAGER_UTIL)["populate_markdown"]
        methods = ",\n".join(slice_braced(MODEL_MANAGER_SRC, marker) for marker in [
            "async installModels(list, btn)", "showError(err)", "showMessage(msg, color)", "showStatus(msg, color)"
        ])
        response_text = '<img src=x onerror="window.__probe=1"> download failed'
        for name in ["Model <Flux>", '<img src=x onerror="window.__probe=1">']:
            for status in [403, 500]:
                with self.subTest(name=name, status=status):
                    item = {"name": name, "originalData": {}, "hash": "model"}
                    populate(item)
                    rendered = _run_node("""
                        %s
                        const messages = {};
                        const elements = {};
                        const api = {fetchApi: async (url) => url.endsWith('/status')
                            ? {json: async () => ({is_processing: false})}
                            : {status: %d, json: async () => ({}), text: async () => %s}};
                        const show_message = (message) => messages.dialog = message;
                        const ctx = {
                            %s,
                            element: {querySelector: (selector) => elements[selector] ||= {innerHTML: ''}},
                            grid: {scrollRowIntoView() {}, updateCell() {}},
                            focusInstall() {return true;}
                        };
                        await ctx.installModels([%s], {classList: {add() {}}});
                        messages.panel = elements['.cmm-manager-message'].innerHTML;
                        console.log(JSON.stringify(messages));
                    """ % (self.sanitize, status, json.dumps(response_text), methods, json.dumps(item)))
                    self.assertEqual(set(rendered), {"panel", "dialog"})
                    for message in rendered.values():
                        self.assertIn("'%s': " % name, html.unescape(message))
                        self.assertNotIn("img", _parse(message).tags)
                        if status == 500:
                            self.assertIn(response_text, html.unescape(message))

    def test_the_queue_result_error_text_is_escaped_by_the_caller(self):
        self.assertIn("errorMsg += sanitizeHTML(String(v))", MODEL_MANAGER_SRC)


if __name__ == "__main__":
    unittest.main()
