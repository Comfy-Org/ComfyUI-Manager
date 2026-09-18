"""Exercise the full legacy populate_markdown path, including readable URLs."""
from html.parser import HTMLParser

import pytest

from legacy_html_testutil import load_renderer

RENDERER = load_renderer()


def compose(text):
    item = {'description': text}
    RENDERER['populate_markdown'](item)
    return item['description']


class Elements(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.elements = []
        self.text = ''
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, text):
        self.text += text


def anchor(markup):
    parsed = Elements(markup)
    assert [tag for tag, _ in parsed.elements] == ['a']
    attrs = parsed.elements[0][1]
    assert set(attrs) == {'href', 'target', 'rel'}
    assert attrs['target'] == '_blank'
    assert set(attrs['rel'].split()) == {'noopener', 'noreferrer'}
    return attrs


@pytest.mark.parametrize('url', [
    "' onmouseover='alert`1`", '" onclick="alert`1`',
    'https://example.com/a\"><img src=x onerror=alert`1`>',
])
def test_attribute_breakout_is_inert(url):
    assert anchor(compose(f'[a/link]({url})'))['href'] == url


@pytest.mark.parametrize('url', [
    'javascript:alert`1`', 'JaVaScRiPt:alert`1`', 'data:text/html,evil',
    'vbscript:msgbox`1`', 'ftp://host/file', 'mailto:user@example.com',
    'java\tscript:alert`1`', 'java\nscript:alert`1`', '\x01javascript:alert`1`',
])
def test_disallowed_schemes_are_rejected(url):
    assert anchor(compose(f'[a/link]({url})'))['href'] == '#'


@pytest.mark.parametrize('url,expected', [
    ('https://example.com/?q=<Flux>', 'https://example.com/?q=<Flux>'),
    ('https://example.com/?a=1&amp;b=2', 'https://example.com/?a=1&b=2'),
    ('https://example.com/?a=1&notebook=2&copy=3', 'https://example.com/?a=1&notebook=2&copy=3'),
    ('https://example.com/?q=&notit;', 'https://example.com/?q=&notit;'),
    ('https://example.com/?q=&#60;Flux&#x3e;', 'https://example.com/?q=<Flux>'),
    ('https://example.com/?q=&amp;lt;', 'https://example.com/?q=&lt;'),
    ('https://example.com/a**b**c', 'https://example.com/a**b**c'),
    ('https://example.com/%%white%%', 'https://example.com/%%white%%'),
    ('https://example.com/[w/note]', 'https://example.com/[w/note]'),
    ('https://example.com/a\nb', 'https://example.com/a\nb'),
    ('http://example.com/x', 'http://example.com/x'),
    ('./docs/readme.md', './docs/readme.md'), ('#section', '#section'), ('//host/path', '//host/path'),
    ('&amp;#106;avascript:alert`1`', '&#106;avascript:alert`1`'),
    ('&#106avascript:alert`1`', '&#106avascript:alert`1`'),
])
def test_href_survives_entity_decoding_and_formatting(url, expected):
    assert anchor(compose(f'[a/link]({url})'))['href'] == expected


def test_labels_prose_and_notes_keep_their_formatting():
    out = compose('<img src=x> [w/Read [a/**<Flux>**](https://example.com)]\n%%white%% [i/info]')
    parsed = Elements(out)
    assert [tag for tag, _ in parsed.elements] == ['p', 'a', 'b', 'br', 'font', 'p']
    assert parsed.text == '<img src=x> Read <Flux>white info'
    assert "class='cm-warn-note'" in out and "class='cm-info-note'" in out


@pytest.mark.parametrize('label', ['a <b> tag', 'a &lt;b&gt; tag', 'a\x00 <b> tag'])
def test_link_label_is_escaped_once(label):
    out = compose(f'[a/{label}](https://example.com)')
    anchor(out)
    assert Elements(out).text == 'a <b> tag'


def test_source_cannot_forge_a_href_placeholder():
    out = compose('\x00H0\x00 [a/link](https://example.com)')
    assert out.count('https://example.com') == 1
    assert anchor(out)['href'] == 'https://example.com'


def test_name_and_title_preserve_existing_server_contract():
    item = {'name': 'Name <Flux>', 'title': 'Pack <Flux>'}
    RENDERER['populate_markdown'](item)
    assert item == {'name': 'Name &lt;Flux&gt;', 'title': 'Pack &lt;Flux&gt;'}


@pytest.mark.parametrize('url', [
    '&#106;avascript:alert`1`', '&#0000106;avascript:alert`1`',
    '&#x6A;avascript:alert`1`', '&#X6A;avascript:alert`1`',
    'ja&#118;ascript:alert`1`', 'jav&#x61;script:alert`1`',
    '&#100;ata:text/html;base64,PHNjcmlwdD4=', 'java&Tab;script:alert`1`',
    '&#118;bscript:msgbox`1`',
])
def test_entity_obfuscated_schemes_are_rejected(url):
    assert anchor(compose(f'[a/link]({url})'))['href'] == '#'
