"""RED->GREEN guard for the unescaped-innerHTML regression in the legacy Manager UI.

A node pack `description` is markdown-transformed server-side and then written to
innerHTML by the client. `convert_markdown_to_html`'s `replace_a` interpolated the
captured URL RAW into a single-quoted href, and the URL pattern is `([^)]+)` — so a
URL carrying a single quote closed the attribute and injected an event handler.
No `<` or `>` is needed, which is why the upstream `<`/`>` escaping did not stop it.

IMPORT DISCIPLINE (load-bearing, see tests/conftest.py):
  - `glob/` has NO `__init__.py`, so `import glob.manager_util` is not a package
    import, and putting `glob/` on sys.path would SHADOW the stdlib `glob` module
    and break pytest itself. manager_util is therefore loaded by FILE LOCATION
    under a private module name — it is the real module, really executed.
  - `glob/manager_server.py` starts a network thread at import and needs the
    ComfyUI stack, so it is NEVER imported. `convert_markdown_to_html` is
    AST-extracted and executed in an isolated namespace instead — the same
    technique tests/test_csrf_content_type_helper.py already uses in this repo.
"""
import unittest

from manager_test_utils import load_manager_util, load_markdown_functions


def _parse_anchors(html):
    """Return one dict of attributes per <a> tag, using a real HTML parser."""
    from html.parser import HTMLParser

    class _Collector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.anchors = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.anchors.append(dict(attrs))

    collector = _Collector()
    collector.feed(html)
    collector.close()
    return collector.anchors


def _parse_element_names(html):
    """Return the tag name of every element the HTML actually produces."""
    from html.parser import HTMLParser

    class _Collector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.names = []

        def handle_starttag(self, tag, attrs):
            self.names.append(tag)

    collector = _Collector()
    collector.feed(html)
    collector.close()
    return collector.names


MANAGER_UTIL = load_manager_util()
CONVERT = load_markdown_functions(MANAGER_UTIL)["convert_markdown_to_html"]

# Synthetic stand-in for the crafted payload. It keeps a LEGITIMATE https scheme
# on purpose: a scheme allow-list alone does not stop this one, so the test pins
# the attribute ESCAPING rather than the allow-list.
BREAKOUT_URL = "https://example.com/x' onmouseover='alert`1`"
BREAKOUT_MD = f"[a/click me]({BREAKOUT_URL})"


class TestAttributeBreakout(unittest.TestCase):
    def test_quote_in_url_cannot_close_the_href_attribute(self):
        html = CONVERT(BREAKOUT_MD)
        self.assertNotIn(
            "' onmouseover='", html,
            f"URL quote escaped the href attribute and injected a handler: {html!r}",
        )

    def test_transformed_anchor_exposes_no_event_handler_attribute(self):
        # Parsed, not regex-matched: after the fix the payload text still LIVES
        # inside the href value (harmlessly, as an odd URL), so a naive
        # /\son[a-z]+=/ scan would flag the fixed output too. What actually
        # matters is which ATTRIBUTES the anchor ends up carrying.
        html = CONVERT(BREAKOUT_MD)
        anchors = _parse_anchors(html)
        self.assertEqual(len(anchors), 1, f"expected one anchor, got {html!r}")
        names = set(anchors[0])
        self.assertEqual(
            names, {"href", "target", "rel"},
            f"unexpected attribute(s) on the anchor: {sorted(names)} in {html!r}",
        )

    def test_legit_link_still_renders_a_usable_anchor(self):
        html = CONVERT("see [a/the docs](https://example.com/guide?a=1&b=2) please")
        self.assertIn("<a href='https://example.com/guide?a=1&amp;b=2'", html)
        self.assertIn(">the docs</a>", html)
        self.assertIn("target='_blank'", html)

    def test_link_text_is_escaped_once(self):
        for label in ["a <b> tag", "a &lt;b&gt; tag"]:
            with self.subTest(label=label):
                html = CONVERT(f"[a/{label}](https://example.com)")
                self.assertIn("&lt;b&gt;", html)
                self.assertNotIn("&amp;lt;", html)

    def test_prose_and_link_labels_are_safe_inside_formatted_notes(self):
        item = {"description": '<img src=x> [w/Read [a/**<Flux>**](https://example.com/?q=<Flux>)]\n<img src=y>'}
        load_markdown_functions(MANAGER_UTIL)["populate_markdown"](item)
        html = item["description"]
        self.assertEqual(_parse_element_names(html), ["p", "a", "b", "br"])
        self.assertIn("<B>&lt;Flux&gt;</B>", html)
        self.assertIn("&lt;img src=x&gt;", html)
        self.assertIn("&lt;img src=y&gt;", html)
        self.assertEqual(_parse_anchors(html)[0]["href"], "https://example.com/?q=<Flux>")


class TestDescriptionUrlRoundTrip(unittest.TestCase):
    def test_description_urls_are_escaped_once(self):
        populate = load_markdown_functions(MANAGER_UTIL)["populate_markdown"]
        cases = [
            ("https://example.com/?q=<Flux>", "https://example.com/?q=<Flux>"),
            ("https://example.com/?a=1&amp;b=2", "https://example.com/?a=1&b=2"),
            ("https://example.com/?q=&lt;Flux&gt;", "https://example.com/?q=<Flux>"),
            ("https://example.com/?q=&#60;Flux&#x3e;", "https://example.com/?q=<Flux>"),
            ("https://example.com/?a=1&notebook=2&copy=3", "https://example.com/?a=1&notebook=2&copy=3"),
            ("https://example.com/?q=&notit;", "https://example.com/?q=&notit;"),
            ("https://example.com/?q=&amp;lt;", "https://example.com/?q=&lt;"),
            ("https://example.com/a**b**c?x=1&amp;y=2", "https://example.com/a**b**c?x=1&y=2"),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                item = {"description": f"[a/link]({url})"}
                populate(item)
                anchors = _parse_anchors(item["description"])
                self.assertEqual(anchors[0]["href"], expected)
                self.assertEqual(_parse_element_names(item["description"]), ["a"])

    def test_decoded_entities_cannot_bypass_url_or_attribute_checks(self):
        populate = load_markdown_functions(MANAGER_UTIL)["populate_markdown"]
        for url in ["javascript&#58;alert`1`", "&#106;avascript:alert`1`", "java&Tab;script:alert`1`"]:
            with self.subTest(url=url):
                item = {"description": f"[a/link]({url})"}
                populate(item)
                self.assertEqual(_parse_anchors(item["description"])[0]["href"], "#")

        url = "https://example.com/x&#39; onmouseover=&#39;alert`1`"
        item = {"description": f"[a/link]({url})"}
        populate(item)
        anchor = _parse_anchors(item["description"])[0]
        self.assertEqual(anchor["href"], "https://example.com/x' onmouseover='alert`1`")
        self.assertEqual(set(anchor), {"href", "target", "rel"})


class TestEscapedHrefSurvivesTheLaterPasses(unittest.TestCase):
    """The escaper's output must still be intact by the time it is returned.

    replace_a runs before the %%..%% / **..** / [w/..] / [i/..] passes, and those
    passes used to rewrite the INSIDE of the href it had just secured — putting
    <font>/<B>/<p> markup and fresh single quotes back into the attribute. That
    both corrupted legitimate URLs and undid the escaping.
    """

    def test_percent_markers_in_a_url_leave_the_href_intact(self):
        html = CONVERT("[a/t](https://e.com/%%A%%)")
        self.assertIn("href='https://e.com/%%A%%'", html)
        self.assertNotIn("<font", html)

    def test_bold_markers_in_a_url_leave_the_href_intact(self):
        html = CONVERT("[a/t](https://e.com/a**b**c)")
        self.assertIn("href='https://e.com/a**b**c'", html)
        self.assertNotIn("<B>", html)

    def test_note_markers_in_a_url_leave_the_href_intact(self):
        html = CONVERT("[a/t](https://e.com/[w/A])")
        self.assertIn("href='https://e.com/[w/A]'", html)
        self.assertNotIn("cm-warn-note", html)

    def test_no_element_leaks_out_of_a_url(self):
        # Parsed rather than string-matched: the anchor must be the ONLY element.
        html = CONVERT("[a/t](https://e.com/%%A%%and**B**)")
        self.assertEqual(_parse_element_names(html), ["a"])

    def test_nested_markdown_in_the_LINK_TEXT_still_renders(self):
        # Protecting the href must not cost the label. Moving the anchor
        # substitution last would have escaped these into visible mojibake.
        self.assertIn("<B>bold</B>", CONVERT("[a/**bold** text](https://e.com)"))
        self.assertIn("<font color='white'>hi</font>", CONVERT("[a/%%hi%% there](https://e.com)"))

    def test_markup_outside_a_link_is_unaffected(self):
        html = CONVERT("%%white%% and **bold** and [w/warn]")
        self.assertIn("<font color='white'>white</font>", html)
        self.assertIn("<B>bold</B>", html)
        self.assertIn("cm-warn-note", html)

    def test_the_newline_pass_cannot_reach_inside_the_href(self):
        # The newline substitution is the LAST thing convert_markdown_to_html
        # does, so restoring the href before it let '<BR>' be injected into the
        # attribute the escaper had secured. Not exploitable — '<BR>' carries no
        # quote — but it is the same class of breach this function exists to fix,
        # so the invariant is pinned all the way to the returned string.
        html = CONVERT("[a/t](https://e.com/a\nb)")
        anchors = _parse_anchors(html)
        self.assertEqual(len(anchors), 1)
        self.assertNotIn("<BR>", anchors[0]["href"])
        self.assertEqual(_parse_element_names(html), ["a"])

    def test_newlines_outside_a_link_still_become_line_breaks(self):
        html = CONVERT("first\nsecond")
        self.assertIn("<BR>", html)

    def test_a_forged_placeholder_in_the_input_cannot_hijack_restoration(self):
        html = CONVERT("\x00H0\x00 [a/t](https://e.com/real)")
        self.assertIn("href='https://e.com/real'", html)
        self.assertEqual(html.count("https://e.com/real"), 1)


class TestUrlSchemeAllowlist(unittest.TestCase):
    def test_helpers_are_public_on_manager_util(self):
        self.assertTrue(callable(getattr(MANAGER_UTIL, "escape_html_attribute", None)))
        self.assertTrue(callable(getattr(MANAGER_UTIL, "sanitize_url", None)))

    def test_dangerous_schemes_are_rejected(self):
        for bad in [
            "javascript:alert`1`",
            "JaVaScRiPt:alert`1`",
            "  javascript:alert`1`",
            "java\tscript:alert`1`",
            "java\nscript:alert`1`",
            "\x01javascript:alert`1`",
            "data:text/html;base64,PHNjcmlwdD4=",
            "vbscript:msgbox",
        ]:
            with self.subTest(bad=bad):
                self.assertEqual(MANAGER_UTIL.sanitize_url(bad), "#")

    def test_safe_urls_pass_through(self):
        for good in [
            "https://example.com/a?b=1",
            "http://example.com",
            "HTTPS://Example.COM/Path",
            "/relative/path",
            "relative/path",
            "#in-page-anchor",
            "//protocol-relative/path",
            # A relative link may legitimately contain '&'. An earlier version
            # rejected this shape while guarding against an entity-hidden colon;
            # the guarantee comes from the escape layer instead (below), so the
            # rejection was redundant and only broke real links.
            "a&b/c",
            "docs/page?x=1&y=2",
        ]:
            with self.subTest(good=good):
                self.assertEqual(MANAGER_UTIL.sanitize_url(good), good)

    def test_entity_hidden_colon_is_inert_after_escaping(self):
        # Asserted on the POST-ESCAPE href, because that is where the safety
        # actually comes from: sanitize_url returns these unchanged (they have no
        # real colon, so they read as relative), and escape_html_attribute then
        # escapes the '&'. Entity decoding in an attribute is single-pass, so
        # what the browser ends up with is a literal string, never a scheme.
        for hidden in ["javascript&#58;alert`1`", "&#x6a;avascript:alert`1`",
                       "&#106;avascript:alert`1`"]:
            with self.subTest(hidden=hidden):
                href = MANAGER_UTIL.escape_html_attribute(MANAGER_UTIL.sanitize_url(hidden))
                self.assertIn("&amp;", href)
                self.assertNotIn("&#58;", href)
                self.assertNotIn("&#x6a;", href)
                self.assertNotIn("&#106;", href)

    def test_entity_hidden_colon_in_markdown_produces_no_live_scheme(self):
        html = CONVERT("[a/click](javascript&#58;alert`1`)")
        anchors = _parse_anchors(html)
        self.assertEqual(len(anchors), 1)
        # The parser decodes entities exactly as a browser would; after that the
        # href must NOT be a javascript: URL.
        self.assertFalse(anchors[0]["href"].lower().startswith("javascript:"))

    def test_dangerous_scheme_in_markdown_does_not_reach_the_href(self):
        html = CONVERT("[a/click](javascript:alert`1`)")
        self.assertNotIn("javascript:", html.lower())
        self.assertIn("href='#'", html)


class TestAttributeEscaper(unittest.TestCase):
    def test_escapes_all_five_characters(self):
        self.assertEqual(
            MANAGER_UTIL.escape_html_attribute("""&<>"'"""),
            "&amp;&lt;&gt;&quot;&#x27;",
        )

    def test_ampersand_is_escaped_first_and_only_once(self):
        self.assertEqual(MANAGER_UTIL.escape_html_attribute("a&b"), "a&amp;b")

    def test_non_string_input_is_coerced(self):
        self.assertEqual(MANAGER_UTIL.escape_html_attribute(None), "None")


class TestServerTitleTransformIsTheOnlyUpstreamControl(unittest.TestCase):
    """Pin the server-side facts that the bare flyover title sinks rest on.

    js/custom-nodes-manager.js says, at both flyover pack-title sinks, that the
    title is already escaped by populate_markdown and so must NOT be escaped
    again at the client (a second escape would double-escape a legitimate
    <>-title into mojibake). That comment is a load-bearing claim about THIS
    file's subject: it is the whole reason those two sinks are bare. These
    cases make the claim machine-checked, so if the server side ever stops
    covering `title` the suite says so, instead of leaving a comment asserting
    a protection that is gone.
    """

    def test_populate_markdown_escapes_the_title_before_it_reaches_the_client(self):
        # The specific link the sink comments name. This is the case that fails
        # if someone drops `title` from populate_markdown, which is the drift
        # the bare sinks are actually exposed to.
        populate_markdown = load_markdown_functions(MANAGER_UTIL)["populate_markdown"]
        pack = {"title": "Nodes for <Flux> workflows"}
        populate_markdown(pack)
        self.assertEqual(pack["title"], "Nodes for &lt;Flux&gt; workflows")

    def test_sanitize_tag_escapes_angle_brackets(self):
        self.assertEqual(MANAGER_UTIL.sanitize_tag("<img>"), "&lt;img&gt;")

    def test_sanitize_tag_does_not_escape_quotes_or_ampersand(self):
        # Documented limit, not a defect: both title interpolations are in
        # element-text position, where quotes are inert. It IS the reason a
        # title moving into attribute position would need escaping.
        self.assertEqual(MANAGER_UTIL.sanitize_tag("\"a\" & 'b'"), "\"a\" & 'b'")


if __name__ == "__main__":
    unittest.main()
