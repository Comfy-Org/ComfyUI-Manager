"""Exercise the legacy notice sanitizer and its endpoint without network access."""
from __future__ import annotations

import asyncio
import re
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from aiohttp import web

import pytest

from legacy_html_testutil import PACKAGE, load_functions, load_renderer

sanitize = load_renderer()['html_utils'].sanitize_html_fragment


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def _tags(html):
    p = _Tags()
    p.feed(html)
    p.close()
    return p.tags


@pytest.mark.parametrize("payload", [
    '<script>alert(1)</script>',
    '<img src=x onerror=alert(1)>',
    '<a href="javascript:alert(1)">x</a>',
    '<a href="&#106;avascript:alert(1)">x</a>',
    '<a href="java&Tab;script:alert(1)">x</a>',
    '<svg onload=alert(1)></svg>',
    '<iframe src="//evil"></iframe>',
    '<p onclick="alert(1)">x</p>',
    '<details open ontoggle=alert(1)>x</details>',
    '<style>*{background:url(//evil)}</style>',
])
def test_script_bearing_markup_is_removed(payload):
    out = sanitize(payload)
    for tag, attrs in _tags(out):
        assert tag not in ("script", "svg", "iframe", "style"), out
        assert not any(k.startswith("on") for k in attrs), out
        for k in ("href", "src"):
            v = attrs.get(k)
            assert v is None or not v.lower().lstrip().startswith(("javascript", "data", "vbscript")), out
    # Script-bearing markup must be gone entirely, as tags AND as raw text.
    assert "<script" not in out.lower()
    assert "onerror" not in out.lower() and "onload" not in out.lower() and "onclick" not in out.lower()


def test_script_content_is_dropped_not_escaped():
    assert "alert" not in sanitize('<p>a<script>alert(1)</script>b</p>')
    assert sanitize('<p>a<script>alert(1)</script>b</p>') == "<p>ab</p>"


def test_formatting_markup_survives():
    src = '<h2>News</h2><p>See <a href="https://example.com/x?a=1&amp;b=2" title="t">docs</a> and <b>bold</b><br>line</p><ul><li>one</li></ul>'
    out = sanitize(src)
    parsed = _tags(out)
    assert [tag for tag, _ in parsed] == ['h2', 'p', 'a', 'b', 'br', 'ul', 'li']
    link = next(attrs for tag, attrs in parsed if tag == 'a')
    assert link == {'href': 'https://example.com/x?a=1&b=2', 'title': 't',
                    'target': '_blank', 'rel': 'noopener noreferrer'}


def test_text_nodes_are_escaped():
    assert sanitize('a &lt;b&gt; c') == 'a &lt;b&gt; c'
    assert sanitize('<p>1 < 2</p>') == '<p>1 &lt; 2</p>'


def test_unknown_harmless_tag_keeps_content():
    assert sanitize('<custom-tag><em>x</em></custom-tag>') == '<em>x</em>'


def test_relative_and_https_urls_kept():
    out = sanitize('<a href="/wiki/x">r</a><a href="https://a.b/c">s</a>')
    hrefs = [attrs["href"] for tag, attrs in _tags(out) if tag == "a"]
    assert hrefs == ["/wiki/x", "https://a.b/c"]


def test_script_body_ends_at_first_close_tag_like_a_browser():
    # Script content is raw text up to the FIRST </script>, exactly as the
    # browser parses it; what follows is ordinary text and stays visible.
    assert sanitize('<script><script>x</script>y</script><i>z</i>') == 'y<i>z</i>'


@pytest.mark.parametrize('prefix', ['<embed>', '<svg/>', '<svg><script></svg>'])
def test_hidden_element_does_not_swallow_following_notice(prefix):
    assert sanitize(prefix + '<p>after</p>') == '<p>after</p>'


@pytest.mark.parametrize('url', ['ftp://host/file', 'mailto:user@example.com', 'data:text/html,evil'])
def test_other_url_schemes_are_removed(url):
    out = sanitize(f'<a href="{url}">link</a><img src="{url}">')
    assert all('href' not in attrs and 'src' not in attrs for _, attrs in _tags(out))


def test_notice_layout_attributes_survive_without_inline_scripts_or_css():
    out = sanitize('<font color="red">alert</font><p class="note" align="center" style="color:red">'
                   '<img src="https://example.com/a.png" width="40" height="20" onerror="boom()"></p>')
    assert _tags(out) == [('font', {'color': 'red'}), ('p', {'class': 'note', 'align': 'center'}),
                         ('img', {'src': 'https://example.com/a.png', 'width': '40', 'height': '20'})]


def test_notice_endpoint_sanitizes_remote_content_and_retains_local_version_footer():
    response = MagicMock(status=200)
    response.text = AsyncMock(return_value='<div class="markdown-body"><embed><p>News '
        '<a href="https://example.com" onclick="boom()">link</a><script>boom()</script></p></div>')
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=session)
    namespace = load_functions(PACKAGE / 'legacy/manager_server.py', {'get_notice'}, {
        'routes': web.RouteTableDef(), 're': re, 'web': web,
        'html_utils': load_renderer()['html_utils'],
        'aiohttp': SimpleNamespace(ClientSession=lambda **kwargs: client, TCPConnector=lambda **kwargs: None),
        'os': SimpleNamespace(environ={'__COMFYUI_DESKTOP_VERSION__': '1.0'}),
        'core': SimpleNamespace(version_str='4.2.1'),
    })
    result = asyncio.run(namespace['get_notice'](None))
    assert result.status == 200
    assert 'News' in result.text and 'ComfyUI: 1.0 [Desktop]' in result.text and 'Manager: 4.2.1' in result.text
    assert 'boom' not in result.text and '<embed' not in result.text
    link = next(attrs for tag, attrs in _tags(result.text) if tag == 'a')
    assert link == {'href': 'https://example.com', 'target': '_blank', 'rel': 'noopener noreferrer'}
