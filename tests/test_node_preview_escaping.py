"""The node preview shows a node definition as text.

Hovering over a node name in a pack's node list shows the node's name, inputs, default
values, outputs and description. They come from ComfyUI's node definitions and are
inserted as text: markup in a definition builds no element, and text between angle
brackets stays visible. The line breaks of a multi-line default are still line breaks.

The cases run the shipped `createNodePreview` of custom-nodes-manager.js in node.
"""
import json
import os
from html.parser import HTMLParser
from pathlib import Path

import pytest

from js_lift import NODE, JsSource, run_node, slice_braced

JS = JsSource(Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js")))

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to execute the lifted production JS")

FIELDS = ["name", "slot input", "text input", "text input without a default", "widget", "widget value",
          "text default", "output", "description"]


class Rendered(HTMLParser):
    """The elements and the text a browser would build from the preview."""

    def __init__(self, markup):
        super().__init__()
        self.tags = []
        self.text = ""
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    def handle_data(self, data):
        self.text += data


def preview(value_of):
    """Render a node whose definition holds `value_of(field)` in each field that the preview shows."""
    values = {field: value_of(field) for field in FIELDS}
    source = JS.text("custom-nodes-manager.js")
    script = """
        %s
        const app = {widgets: {STRING: 1, INT: 1}};
        const manager = {%s, %s};
        const v = %s;
        const html = manager.createNodePreview({
            name: v['name'], description: v['description'],
            input: {required: {
                [v['slot input']]: ['IMAGE'],
                [v['text input']]: ['STRING', {default: 'first line\\n' + v['text default']}],
                [v['text input without a default']]: ['STRING', {multiline: true}],
                [v['widget']]: ['INT', {default: v['widget value']}],
            }},
            input_order: {required: [v['slot input'], v['text input'], v['text input without a default'], v['widget']]},
            output: ['IMAGE'], output_name: [v['output']], output_is_list: [false],
        });
        console.log(JSON.stringify({html}));
    """ % (
        JS.lift_declaration("common.js", "export function sanitizeHTML("),
        slice_braced(source, "\n\tgetWidgetType(").strip(),
        slice_braced(source, "\n\tcreateNodePreview(").strip(),
        json.dumps(values),
    )
    return values, Rendered(run_node(script)["html"])


def test_markup_in_a_definition_builds_no_element():
    values, rendered = preview(lambda field: '%s <img src=x onerror="window.ran = true">' % field)

    assert "img" not in rendered.tags
    # the name of a text input is shown only when the input has no default
    for field in set(FIELDS) - {"text input"}:
        assert values[field] in rendered.text, field
    assert rendered.tags.count("br") == 1, "the line break of the two-line default"


def test_text_between_angle_brackets_stays_visible():
    values, rendered = preview(lambda field: "%s <lora:detail:0.8> & more" % field)

    assert set(rendered.tags) == {"div", "br"}, "the preview's own elements only"
    for field in set(FIELDS) - {"text input"}:
        assert values[field] in rendered.text, field
