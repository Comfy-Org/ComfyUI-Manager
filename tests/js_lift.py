"""Lift real production JS out of the shipped files and execute it in node.

WHY LIFT RATHER THAN IMPORT: the manager's front-end modules pull in
``../../scripts/app.js`` and touch ``document`` at module scope, so node cannot
import them. WHY LIFT RATHER THAN RETYPE: a retyped copy of a formatter stops
tracking the formatter the moment someone edits it, and then the guard passes
while the shipped code regresses. Lifting keeps the executed bytes the shipped
bytes — if the production function changes, so does the text under test.

This mirrors tests/test_manager_markdown_escaping.py, which AST-extracts
``convert_markdown_to_html`` rather than importing manager_server.

Consumers point ``JsSource`` at a directory of .js files; an override directory
(e.g. one populated with ``git show <base>:js/foo.js``) makes the RED half of a
fix reproducible in one command.
"""
import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

NODE = shutil.which("node")


def _skip_literal(source: str, pos: int) -> int:
    """If a literal or comment starts at pos, return the index just past it.

    Returns pos unchanged when nothing starts there. Template literals are
    consumed whole, which is safe for brace counting because a `${...}`
    substitution is itself balanced. A lone `/` is read as a regex literal —
    sanitizeHTML's own `.replace(/'/g, ...)` hides an apostrophe inside one, and
    no scanned range uses `/` as division. Were that to change, the assertion
    below fails loudly rather than returning a wrong slice.
    """
    ch = source[pos]
    nxt = source[pos + 1] if pos + 1 < len(source) else ""
    if ch == "/" and nxt == "/":
        return source.index("\n", pos)
    if ch == "/" and nxt == "*":
        return source.index("*/", pos) + 2
    if ch not in "\"'`/":
        return pos
    cursor = pos + 1
    while cursor < len(source):
        if source[cursor] == "\\":
            cursor += 2
            continue
        if source[cursor] == ch:
            return cursor + 1
        cursor += 1
    raise AssertionError("unterminated literal at offset %d" % (pos,))


def slice_braced(source: str, start_marker: str) -> str:
    """Return start_marker plus the balanced {...} block that follows it."""
    start = source.index(start_marker)
    pos = source.index("{", start + len(start_marker))
    depth = 0
    while pos < len(source):
        skipped = _skip_literal(source, pos)
        if skipped != pos:
            pos = skipped
            continue
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[start:pos + 1]
        pos += 1
    raise AssertionError("unbalanced braces after %r" % (start_marker,))


def slice_object_entry(source: str, marker: str, indent: str = "\t\t") -> str:
    """Return one object literal out of a `}, {`-chained array, by id marker.

    These objects are literals inside an array, so the first `{` after the
    marker belongs to the NEXT entry — brace matching cannot be used. The entry
    instead ends at the first `}` sitting at the array's own indent.
    """
    start = source.index(marker)
    end = source.index("\n%s}" % indent, start)
    return source[start:end]


def line_containing(source: str, marker: str) -> str:
    """Return the single source line that holds `marker` (fails if absent)."""
    start = source.index(marker)
    line_start = source.rfind("\n", 0, start) + 1
    return source[line_start:source.index("\n", start)]


class JsSource:
    """The shipped .js files under test, read from `js_dir`."""

    def __init__(self, js_dir):
        self.js_dir = Path(js_dir)
        self._cache = {}

    def text(self, filename: str) -> str:
        if filename not in self._cache:
            self._cache[filename] = (self.js_dir / filename).read_text(encoding="utf-8")
        return self._cache[filename]

    def lift_declaration(self, filename: str, marker: str) -> str:
        """Lift an `export function`/`export const` declaration, minus `export`."""
        return slice_braced(self.text(filename), marker).replace("export ", "", 1)

    def lift_formatter(self, filename: str, anchor: str) -> str:
        """Lift the `formatter: ...` at `anchor` as a bare function expression."""
        block = slice_braced(self.text(filename), anchor)
        marker = "formatter:"
        return block[block.index(marker) + len(marker):].strip()

    def lift_span(self, filename: str, start_marker: str, end_marker: str) -> str:
        """Lift the source between two markers, end_marker included."""
        source = self.text(filename)
        start = source.index(start_marker)
        end = source.index(end_marker, start) + len(end_marker)
        return source[start:end]


def run_node(script: str) -> dict:
    """Execute an ES-module script and parse the single JSON object it prints."""
    assert NODE is not None, "node is required to execute the lifted production JS"
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, "node failed:\n%s" % (result.stderr,)
    return json.loads(result.stdout)


class Collector(HTMLParser):
    """Collects the tags and attributes a browser would actually build."""

    def __init__(self):
        super().__init__()
        self.tags = []
        self.attrs = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)

    handle_startendtag = handle_starttag


def parse(markup: str) -> Collector:
    collector = Collector()
    collector.feed(markup)
    collector.close()
    return collector


def event_handlers(markup: str):
    """Every on* attribute a browser would attach for this markup."""
    return [name for name, _ in parse(markup).attrs if name.lower().startswith("on")]
