"""Check remote notice HTML, sharing URLs, snapshot names and node selection UI.

Execute shipped Python and JavaScript with isolated external boundaries. Rendering
checks cover hostile inputs and readable controls; link checks preserve opener isolation.
"""
import ast
import os
import re
import unittest
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from js_lift import NODE, JsSource, run_node
from manager_test_utils import GLOB_DIR, load_manager_util, load_markdown_functions

REPO_ROOT = Path(__file__).resolve().parent.parent
JS = JsSource(os.environ.get("MANAGER_JS_DIR") or (REPO_ROOT / "js"))

COMMON = "common.js"
SHARE_COMMON = "comfyui-share-common.js"
SHARE_OPENART = "comfyui-share-openart.js"
SHARE_COPUS = "comfyui-share-copus.js"
SHARE_YOUML = "comfyui-share-youml.js"
SNAPSHOT = "snapshot.js"
MANAGER = "custom-nodes-manager.js"

# A scheme that executes on click, and a scheme that carries its own document.
# Both are strings a third party can put in a URL field; neither is a host.
SCHEME_PAYLOAD = "javascript:window.__probe=1"
DATA_PAYLOAD = "data:text/html,<b>x</b>"
BENIGN_URL = "https://example.com/w/123?a=1&b=2"
# An http URL that ALSO closes the attribute it lands in. A service-chosen URL
# is not "either a bad scheme or a quote" -- it is one string that can be both,
# so a scheme allow-list alone leaves the quote. One variant per quoting style,
# because the call sites differ.
BREAKOUT_SINGLE_QUOTED = "https://example.com/x' onmouseover='window.__probe=1"
BREAKOUT_DOUBLE_QUOTED = 'https://example.com/x" onmouseover="window.__probe=1'
# Element text, for the sinks that render a name rather than a link.
TEXT_PAYLOAD = '<img src=x onerror="window.__probe=1">'


def _function_source(name: str, filename: str = "manager_server.py") -> str:
    """The source text of one top-level function, WITHOUT importing its module.

    Used for the wiring legs, where the question is "does this call site pass
    its value through the normaliser" -- a question about the call site, which a
    behavioural test on the normaliser alone cannot answer.
    """
    source = (GLOB_DIR / filename).read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    assert len(wanted) == 1, "expected exactly one %s, got %d" % (name, len(wanted))
    return ast.get_source_segment(source, wanted[0]) or ""


class _Collector(HTMLParser):
    """What a browser would actually build from a fragment."""

    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


def parse(markup: str) -> _Collector:
    collector = _Collector()
    collector.feed(markup)
    collector.close()
    return collector


def tags(markup: str):
    return [tag for tag, _ in parse(markup).elements]


def handler_attrs(markup: str):
    return [
        "%s@%s" % (tag, name)
        for tag, attrs in parse(markup).elements
        for name in attrs
        if name.lower().startswith("on")
    ]


def hrefs(markup: str):
    return [
        attrs["href"] for tag, attrs in parse(markup).elements
        if tag == "a" and "href" in attrs
    ]


# ---------------------------------------------------------------------------
# [D1] the relayed wiki fragment
# ---------------------------------------------------------------------------
class NoticeFragmentSanitizerTest(unittest.TestCase):
    """Notice sanitization must remove executable content while preserving formatting."""

    @classmethod
    def setUpClass(cls):
        cls.manager_util = load_manager_util()

    def _sanitize(self, fragment: str) -> str:
        fn = getattr(self.manager_util, "sanitize_html_fragment", None)
        self.assertIsNotNone(
            fn,
            "glob/manager_util.py exposes no sanitize_html_fragment(fragment). "
            "The notice fragment is remote HTML the server relays verbatim and "
            "the client assigns to innerHTML by design, so the server is the "
            "only boundary that can constrain it.",
        )
        return fn(fragment)

    def test_a_script_element_does_not_survive(self):
        out = self._sanitize('<p>before</p><script>window.__probe=1</script><p>after</p>')
        self.assertNotIn("script", tags(out), out)
        self.assertIn("p", tags(out), "ordinary markup was destroyed along with it: %r" % (out,))

    def test_a_handler_attribute_does_not_survive(self):
        out = self._sanitize('<img src="https://example.com/i.png" onerror="window.__probe=1">')
        self.assertEqual(handler_attrs(out), [], out)

    def test_a_handler_attribute_does_not_survive_on_any_element(self):
        # The allow-list is over ATTRIBUTES, not over one element that happened
        # to be tested: a deny-list keyed to <img> leaves <div onmouseover=...>.
        for markup in (
            '<div onmouseover="window.__probe=1">hover</div>',
            '<a href="https://example.com/" onclick="window.__probe=1">click</a>',
            '<b ONERROR="window.__probe=1">bold</b>',
        ):
            with self.subTest(markup=markup):
                self.assertEqual(handler_attrs(self._sanitize(markup)), [], markup)

    def test_an_executing_scheme_does_not_survive_in_an_href(self):
        for payload in (SCHEME_PAYLOAD, DATA_PAYLOAD):
            with self.subTest(payload=payload):
                out = self._sanitize('<a href="%s">click</a>' % (payload,))
                self.assertEqual(
                    [h for h in hrefs(out) if h.startswith(("javascript:", "data:"))], [],
                    "the scheme survived into an href: %r" % (out,),
                )

    def test_ordinary_formatting_still_displays(self):
        """The half a strip-everything sanitizer would fail.

        The notice is formatted prose. If the fix returns text, the feature is
        gone and no other test in this file would say so.
        """
        fragment = (
            '<p><b>bold</b> and <i>italic</i></p>'
            '<ul><li>one</li><li>two</li></ul>'
            '<a href="https://example.com/x">link</a>'
            '<img src="https://example.com/i.png">'
        )
        out = self._sanitize(fragment)
        for tag in ("p", "b", "i", "ul", "li", "a", "img"):
            with self.subTest(tag=tag):
                self.assertIn(tag, tags(out), "%r was dropped: %r" % (tag, out))
        self.assertIn("https://example.com/x", hrefs(out), out)
        self.assertIn("one", out)
        self.assertIn("two", out)

    def test_an_unclosed_element_does_not_blank_the_rest_of_the_notice(self):
        """Malformed elements must not discard unrelated notice content."""
        for wrapper in ("div", "blockquote", "section", "article", "figure",
                        "main", "header", "nav", "aside"):
            with self.subTest(wrapper=wrapper):
                out = self._sanitize(
                    "<%s><svg></%s><p>after</p>" % (wrapper, wrapper))
                self.assertIn(
                    "after", out,
                    "an unclosed element inside <%s> swallowed the rest of the "
                    "notice: %r" % (wrapper, out))
                self.assertNotIn("svg", tags(out), out)

    def test_an_unterminated_script_still_fails_closed(self):
        """HTML script/style contents must not be emitted as notice markup."""
        for fragment in ("<section><script></section><p>after</p>",
                         "<div><style></div><p>after</p>"):
            with self.subTest(fragment=fragment):
                out = self._sanitize(fragment)
                # NOT `out == ""`: a wrapper's OPEN tag is emitted before the
                # skip window starts, so `<div><style>...` legitimately keeps
                # its `<div>`. The property is that nothing AFTER the
                # unterminated element comes back -- as markup or as text.
                self.assertNotIn(
                    "after", out,
                    "text after an unterminated script/style came back: %r"
                    % (out,))
                self.assertEqual(
                    [t for t in tags(out) if t != "div"], [],
                    "markup after an unterminated script/style came back: %r"
                    % (out,))

    def test_foreign_content_does_not_hide_safe_following_prose(self):
        # HTML5 parsing closes the SVG context before this paragraph. The old
        # HTMLParser-based sanitizer treated the rest as script text and lost it.
        out = self._sanitize('<svg><script></svg><p>after</p>')
        self.assertEqual(tags(out), ['p'])
        self.assertIn('after', out)

    def test_notice_formatting_attributes_survive(self):
        out = self._sanitize(
            '<p class="notice" title="Release" align="center">'
            '<font color="red">Update</font></p>'
            '<table width="400"><tr><td colspan="2" rowspan="3">Data</td></tr></table>'
            '<img src="https://example.com/i.png" alt="Preview" width="100" height="80">'
        )
        elements = dict(parse(out).elements)
        self.assertEqual(elements['p'], {'class': 'notice', 'title': 'Release', 'align': 'center'})
        self.assertEqual(elements['font'], {'color': 'red'})
        self.assertEqual(elements['table']['width'], '400')
        self.assertEqual(elements['td'], {'colspan': '2', 'rowspan': '3'})
        self.assertEqual(elements['img'], {
            'src': 'https://example.com/i.png', 'alt': 'Preview', 'width': '100', 'height': '80',
        })

    def test_notice_links_open_safely_regardless_of_input_attribute_order(self):
        for attrs in (
            'href="https://example.com/?a=1&amp;b=2" target="named" rel="opener"',
            'title="Docs" rel="opener" target="named" href="https://example.com/?a=1&amp;b=2"',
        ):
            with self.subTest(attrs=attrs):
                out = self._sanitize(f'<a {attrs}>Docs</a>')
                anchor = dict(parse(out).elements)['a']
                self.assertEqual(anchor['href'], 'https://example.com/?a=1&b=2')
                self.assertEqual(anchor['target'], '_blank')
                self.assertEqual(set(anchor['rel'].split()), {'noopener', 'noreferrer'})

    def test_notice_url_schemes_remain_limited_to_http_https_and_relative(self):
        for url in ('ftp://example.com', 'mailto:a@example.com', 'java&#9;script:alert`1`'):
            with self.subTest(url=url):
                out = self._sanitize(f'<a href="{url}">Link</a><img src="{url}">')
                for _, attrs in parse(out).elements:
                    self.assertNotIn('href', attrs)
                    self.assertNotIn('src', attrs)
        for url in ('http://example.com', 'https://example.com', '/relative', '#section'):
            with self.subTest(url=url):
                self.assertEqual(hrefs(self._sanitize(f'<a href="{url}">Link</a>')), [url])

    def test_hidden_element_contents_are_not_exposed_as_notice_text(self):
        for tag in ('script', 'style', 'iframe', 'object', 'svg', 'math',
                    'template', 'noscript', 'textarea', 'title'):
            with self.subTest(tag=tag):
                out = self._sanitize(f'<{tag}>hidden</{tag}><p>after</p>')
                self.assertNotIn('hidden', out)
                self.assertIn('after', out)

    def test_a_mixed_fragment_keeps_the_good_and_drops_the_bad(self):
        """One fragment carrying both, since a real wiki page would."""
        out = self._sanitize(
            '<p>Release <b>1.2</b></p>'
            '<script>window.__probe=1</script>'
            '<a href="https://example.com/notes">notes</a>'
            '<a href="%s">click</a>'
            '<img src="https://example.com/i.png" onerror="window.__probe=1">'
            % (SCHEME_PAYLOAD,)
        )
        self.assertNotIn("script", tags(out), out)
        self.assertEqual(handler_attrs(out), [], out)
        self.assertEqual(
            [h for h in hrefs(out) if h.startswith(("javascript:", "data:"))], [], out)
        self.assertIn("https://example.com/notes", hrefs(out), out)
        self.assertIn("b", tags(out), out)
        self.assertIn("img", tags(out), "the benign image was dropped: %r" % (out,))


class NoticeWiringTest(unittest.TestCase):
    """Check the notice route applies the sanitizer to its captured remote HTML."""

    def test_get_notice_passes_the_captured_fragment_through_the_sanitizer(self):
        """Verify the captured HTML is sanitized, not merely that the function is mentioned."""
        body = _function_source("get_notice")
        self.assertIn(
            "match.group(1)", body,
            "get_notice no longer captures the fragment the way this guard "
            "expects; re-derive it against the new shape rather than deleting "
            "the assertion.",
        )
        self.assertRegex(
            body, r"sanitize_html_fragment\s*\(\s*match\.group\(1\)\s*\)",
            "get_notice relays the captured wiki fragment without passing it "
            "through an allow-list normaliser. The client assigns the response "
            "body to innerHTML, so whatever the wiki page contains is what the "
            "browser builds. The call has to take the capture as its argument; "
            "naming the function elsewhere in the body is not wiring.",
        )
        self.assertNotRegex(
            body, re.compile(r"^\s*markdown_content\s*=\s*match\.group\(1\)\s*$",
                             re.MULTILINE),
            "the raw capture is still assigned directly; the sanitizer must sit "
            "on this assignment, not beside it.",
        )


# ---------------------------------------------------------------------------
# [D2] share-service URLs
# ---------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class ShareDialogUrlTest(unittest.TestCase):
    """Share-service URLs must use safe schemes and quoted attributes."""

    def _preamble(self) -> str:
        span = JS.lift_span(
            COMMON, "export const SAFE_URL_SCHEMES",
            "export const safeHref = (url) => sanitizeHTML(sanitizeUrl(url));")
        return "\n".join([
            JS.lift_declaration(COMMON, "export function sanitizeHTML("),
            span.replace("export ", ""),
        ])

    def _render(self, expression: str, bindings: str) -> str:
        return run_node(
            "%s\n%s\nconsole.log(JSON.stringify({markup: %s}));\n"
            % (self._preamble(), bindings, expression)
        )["markup"]

    def _assert_scheme_rejected(self, markup: str, label: str):
        bad = [h for h in hrefs(markup) if h.startswith(("javascript:", "data:"))]
        self.assertEqual(
            bad, [],
            "%s emits a service-chosen scheme as a clickable href: %r" % (label, markup),
        )
        self.assertEqual(handler_attrs(markup), [], markup)

    # --- comfyui-share-common.js, the fully service-controlled URL ----------
    def _common_expression(self) -> str:
        from js_lift import line_containing
        line = line_containing(JS.text(SHARE_COMMON),
                               'this.final_message.innerHTML = "Your art has been shared:')
        return line.split("innerHTML =", 1)[1].strip().rstrip(";")

    def test_share_common_rejects_an_executing_scheme(self):
        # The href here is SINGLE-quoted, so the breakout variant uses `'`.
        for payload in (SCHEME_PAYLOAD, DATA_PAYLOAD, BREAKOUT_SINGLE_QUOTED):
            with self.subTest(payload=payload):
                markup = self._render(
                    self._common_expression(),
                    "const response_json = {comfyworkflows: {url: %s}};" % (_json(payload),))
                self._assert_scheme_rejected(markup, "comfyui-share-common.js")

    def test_share_common_still_links_an_ordinary_url(self):
        """The leg a refuse-everything fix would fail."""
        markup = self._render(
            self._common_expression(),
            "const response_json = {comfyworkflows: {url: %s}};" % (_json(BENIGN_URL),))
        self.assertIn(
            BENIGN_URL, hrefs(markup),
            "an ordinary https URL must still become a working link: %r" % (markup,))

    def test_every_share_anchor_severs_the_opener(self):
        """Check opener isolation without imposing an order on rel tokens."""
        cases = [
            ("comfyui-share-common.js", self._common_expression(),
             "const response_json = {comfyworkflows: {url: %s}};" % (_json(BENIGN_URL),)),
            ("comfyui-share-youml.js", self._youml_expression(),
             "const messagePrefix = 'shared.';\nconst recipePageUrl = %s;" % (_json(BENIGN_URL),)),
            ("comfyui-share-openart.js", self._openart_expression(),
             "const url = %s;" % (_json(BENIGN_URL),)),
            ("comfyui-share-copus.js", self._copus_expression(),
             "const url = %s;" % (_json(BENIGN_URL),)),
        ]
        for name, expression, bindings in cases:
            with self.subTest(file=name):
                markup = self._render(expression, bindings)
                anchors = [attrs for tag, attrs in parse(markup).elements if tag == "a"]
                self.assertTrue(anchors, "no anchor produced by %s: %r" % (name, markup))
                for attrs in anchors:
                    self.assertEqual(
                        attrs.get("target"), "_blank",
                        "%s: this guard is about _blank anchors; the target "
                        "changed, so re-derive it: %r" % (name, markup))
                    self.assertIn(
                        "rel", attrs,
                        "%s opens a service-chosen page in a new tab without "
                        "rel, so that page keeps a reference to this window: %r"
                        % (name, markup))
                    rel = attrs["rel"].lower().split()
                    self.assertIn("noopener", rel, markup)
                    self.assertIn("noreferrer", rel, markup)

    # --- comfyui-share-youml.js, also fully service-controlled --------------
    def _youml_expression(self) -> str:
        span = JS.lift_span(SHARE_YOUML, "this.message.innerHTML = `${messagePrefix}",
                            "visit it on YouML</a>`;")
        return span.split("innerHTML =", 1)[1].strip().rstrip(";")

    def test_share_youml_rejects_an_executing_scheme(self):
        # The href here is DOUBLE-quoted, so the breakout variant uses `"`.
        for payload in (SCHEME_PAYLOAD, DATA_PAYLOAD, BREAKOUT_DOUBLE_QUOTED):
            with self.subTest(payload=payload):
                markup = self._render(
                    self._youml_expression(),
                    "const messagePrefix = 'Workflow has been shared.';\n"
                    "const recipePageUrl = %s;" % (_json(payload),))
                self._assert_scheme_rejected(markup, "comfyui-share-youml.js")

    # --- openart / copus: an id is interpolated into a URL PATH -------------
    # The scheme is hardcoded, so these cannot carry javascript:. What they CAN
    # carry is a quote: the id is a service-returned string dropped inside a
    # double-quoted attribute, so `"` closes it and the rest is markup. That is a
    # different failure from the two above and is asserted as such.
    def _openart_expression(self) -> str:
        from js_lift import line_containing
        line = line_containing(JS.text(SHARE_OPENART),
                               "this.message.innerHTML = `Workflow has been shared successfully.")
        return line.split("innerHTML =", 1)[1].strip().rstrip(";")

    def _copus_expression(self) -> str:
        from js_lift import line_containing
        line = line_containing(JS.text(SHARE_COPUS),
                               "this.message.innerHTML = `Workflow has been shared successfully.")
        return line.split("innerHTML =", 1)[1].strip().rstrip(";")

    def test_openart_id_cannot_break_out_of_the_href_attribute(self):
        markup = self._render(
            self._openart_expression(),
            'const url = "https://openart.ai/workflows/-/-/" + '
            '%s;' % (_json('x" onmouseover="window.__probe=1'),))
        self.assertEqual(handler_attrs(markup), [], markup)

    def test_copus_id_cannot_break_out_of_the_href_attribute(self):
        markup = self._render(
            self._copus_expression(),
            'const url = "https://example.invalid/work/" + '
            '%s;' % (_json('x" onmouseover="window.__probe=1'),))
        self.assertEqual(handler_attrs(markup), [], markup)


# ---------------------------------------------------------------------------
# [D3] the snapshot name
# ---------------------------------------------------------------------------
@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class SnapshotNameTest(unittest.TestCase):
    """Snapshot filenames must remain inert text in status messages."""

    def _render(self, name: str) -> str:
        line = _unique_line(JS.text(SNAPSHOT), "self.updateMessage(`<BR><font color=")
        expression = _call_argument(line, "self.updateMessage(")
        return run_node(
            "%s\nconst target = {name: %s};\n"
            "console.log(JSON.stringify({markup: %s}));\n"
            % (JS.lift_declaration(COMMON, "export function sanitizeHTML("),
               _json(name), expression)
        )["markup"]

    def test_a_crafted_snapshot_name_renders_as_text(self):
        markup = self._render(TEXT_PAYLOAD)
        self.assertEqual(handler_attrs(markup), [], markup)
        self.assertNotIn("img", tags(markup), markup)

    def test_an_ordinary_snapshot_name_still_reads_normally(self):
        markup = self._render("2026-09-07_backup")
        self.assertIn("2026-09-07_backup", markup)


# ---------------------------------------------------------------------------
# [D4] rel=noopener, and the defensive escapes
# ---------------------------------------------------------------------------
class ServerAnchorRelTest(unittest.TestCase):
    """Converted [a/text](url) links must isolate the opener and remain usable."""

    @classmethod
    def setUpClass(cls):
        cls.manager_util = load_manager_util()
        # staticmethod, or attribute access binds it and passes `self`
        # as the markdown argument.
        cls.convert = staticmethod(load_markdown_functions(cls.manager_util)["convert_markdown_to_html"])

    def test_a_markdown_link_carries_rel_noopener_noreferrer(self):
        out = self.convert("see [a/the docs](https://example.com/docs)")
        anchors = [attrs for tag, attrs in parse(out).elements if tag == "a"]
        self.assertTrue(anchors, "no anchor was produced at all: %r" % (out,))
        for attrs in anchors:
            with self.subTest(attrs=attrs):
                self.assertIn(
                    "rel", attrs,
                    "the anchor opens a new tab without rel: %r. The opened page "
                    "keeps a reference to this window." % (out,),
                )
                rel = attrs["rel"].lower().split()
                self.assertIn("noopener", rel, out)
                self.assertIn("noreferrer", rel, out)

    def test_the_link_still_works(self):
        out = self.convert("see [a/the docs](https://example.com/docs)")
        self.assertIn("https://example.com/docs", hrefs(out), out)


class ClientAnchorAndStateTest(unittest.TestCase):
    """External-link isolation and rendering of unrecognised pack states."""

    @classmethod
    def setUpClass(cls):
        cls.source = JS.text(MANAGER)

    def test_the_title_link_severs_the_opener(self):
        marker = "link.target = '_blank';"
        index = _unique_index(self.source, marker)
        # max(0, ...) because a negative start would wrap to the END of the
        # string and silently hand back an unrelated window.
        window = self.source[max(0, index - 400):index + 400]
        self.assertRegex(
            window, r"link\.rel\s*=",
            "the title link opens a new tab without setting rel, so the pack's "
            "own repository page keeps a reference to this window.",
        )
        rel = re.search(r"link\.rel\s*=\s*['\"]([^'\"]*)['\"]", window)
        self.assertIsNotNone(rel, "link.rel is set from a non-literal: %r" % (window,))
        tokens = rel.group(1).lower().split()
        # Membership, not token order: 'noreferrer noopener' is the same thing,
        # and demanding one spelling would false-RED a correct fix. Matches how
        # ServerAnchorRelTest checks the server-side anchor.
        self.assertIn("noopener", tokens, window)
        self.assertIn("noreferrer", tokens, window)

    @unittest.skipIf(NODE is None, "node is required")
    def test_selection_survives_unrecognised_and_prototype_names(self):
        sanitize = JS.lift_declaration(COMMON, "export function sanitizeHTML(")
        buttons = JS.lift_declaration(MANAGER, "\n\tgetActionButtons(")
        render = JS.lift_declaration(MANAGER, "\n\trenderSelected()")
        for state in ['not-a-known-install-group', 'constructor', '__proto__', TEXT_PAYLOAD, 'enabled']:
            with self.subTest(state=state):
                result = run_node(sanitize + "\nconst manager = {" + buttons + "," + render + """,
                    grid: {hasMask: false, getSelectedRows: () => [{action: STATE, hash: 'fixture'}]},
                    getFilterItem: () => null,
                    showSelection(html) { this.html = html; }
                };
                manager.renderSelected();
                console.log(JSON.stringify({html: manager.html,
                    buttons: manager.getActionButtons(STATE, {version: 'unknown'}, true)}));
                """.replace('STATE', _json(state)))
                self.assertIn('Selected <b>1</b>', result['html'])
                self.assertIn(state, unescape(result['html']))
                self.assertFalse(handler_attrs(result['html']))
                self.assertNotIn('img', tags(result['html']))
                if state == 'enabled':
                    self.assertIn('<button', result['buttons'])
                else:
                    self.assertEqual(result['buttons'], '')


def _json(value) -> str:
    import json
    return json.dumps(value)


def _unique_index(source: str, marker: str) -> int:
    """Index of `marker`, refusing to guess when it is not unique.

    js_lift.line_containing takes the FIRST occurrence silently. Every marker
    here is unique today; this makes a future second occurrence fail loudly
    instead of pinning whichever copy happens to come first.
    """
    count = source.count(marker)
    assert count == 1, "marker %r occurs %d times; disambiguate it" % (marker, count)
    return source.index(marker)


def _unique_line(source: str, marker: str) -> str:
    """The single source line holding `marker`, with the same uniqueness rule."""
    index = _unique_index(source, marker)
    start = source.rfind("\n", 0, index) + 1
    return source[start:source.index("\n", index)]


def _call_argument(line: str, call_marker: str) -> str:
    """The argument text of `call_marker(...)`, dropping exactly one `)` and `;`.

    NOT `.rstrip(");")`: rstrip takes a CHARACTER SET, so it eats every trailing
    `)`, `;` and `"`. A fix spelled `updateMessage(escape(`...`));` would lose a
    closing paren it needs and become a node syntax error -- which pytest would
    show as this guard failing, i.e. the fix would look like the defect.
    """
    text = line.split(call_marker, 1)[1].rstrip()
    if text.endswith(";"):
        text = text[:-1].rstrip()
    assert text.endswith(")"), "unexpected call shape: %r" % (line.strip(),)
    return text[:-1]


if __name__ == "__main__":
    unittest.main()
