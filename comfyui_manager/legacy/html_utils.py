"""HTML rendering helpers used only by the legacy Manager UI."""
import re
from html import escape, unescape
from html.entities import html5


SAFE_URL_SCHEMES = frozenset({'http', 'https'})
_URL_SCHEME_NOISE = re.compile(r'[\x00-\x20\x7f]')
_URL_HEAD_DELIMITERS = ('/', '?', '#')


def escape_html_attribute(value):
    """Escape a value for a quoted HTML attribute."""
    return escape(str(value), quote=True)


_HTML_ENTITY = re.compile(r'&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);')
_HTML_TEXT_TOKEN = re.compile(_HTML_ENTITY.pattern + "|[&<>\"']")


def unescape_html_entities(text):
    """Decode complete entities once, leaving query keys such as &notebook intact."""
    def replace(match):
        entity = match.group(1)
        if entity.startswith('#'):
            return unescape(match.group(0))
        return html5.get(entity + ';', match.group(0))

    return _HTML_ENTITY.sub(replace, text)


def escape_html_text(value):
    """Escape HTML text without double-escaping existing entities."""
    return _HTML_TEXT_TOKEN.sub(
        lambda m: m.group(0) if m.group(1) else escape_html_attribute(m.group(0)),
        str(value),
    )


def sanitize_url(url):
    """Allow HTTP(S), relative URLs and anchors.

    HTML callers must also escape the result as an attribute."""
    raw = '' if url is None else str(url)
    probe = _URL_SCHEME_NOISE.sub('', raw)
    if not probe:
        return '#'

    cut = len(probe)
    for delimiter in _URL_HEAD_DELIMITERS:
        found = probe.find(delimiter)
        if found != -1:
            cut = min(cut, found)
    head = probe[:cut]

    if ':' in head:
        return raw.strip() if head.split(':', 1)[0].lower() in SAFE_URL_SCHEMES else '#'

    return raw.strip()


def sanitize_html_fragment(fragment):
    """Sanitize notice HTML, preserving its formatting and opening links safely."""
    # Keep nh3 loading within the legacy notice path.
    import nh3

    return nh3.clean(
        '' if fragment is None else str(fragment),
        tags=nh3.ALLOWED_TAGS | {'font'},
        attributes={
            **nh3.ALLOWED_ATTRIBUTES,
            '*': {'class', 'title', 'align', 'width', 'height'},
            'font': {'color'},
        },
        # These elements previously hid their contents from the notice.
        clean_content_tags={
            'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math',
            'template', 'noscript', 'textarea', 'title',
        },
        url_schemes=SAFE_URL_SCHEMES,
        set_tag_attribute_values={'a': {'target': '_blank'}},
    )
