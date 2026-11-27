import json
import os
from pathlib import Path

import pytest

from js_lift import NODE, JsSource, run_node, slice_braced

JS = JsSource(Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js")))

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required to execute the lifted production JS")

COMPONENT = {"packname": "a pack", "category": "", "nodes": [], "links": [], "external": []}


def load(status, body):
    source = JS.text("components-manager.js")
    script = """
        const registered = [];
        const app = {graph: {}};
        const api = {fetchApi: async () => ({status: %s, json: async () => JSON.parse(%s)})};
        const SEPARATOR = '/';
        const sleep = async () => {};
        const register_pack_map = () => {};
        class GroupNodeConfig {
            constructor(name, data) { this.name = name; }
            async registerType(category) { registered.push([this.name, category]); }
        }
        %s
        %s
        let failed = null;
        try { await load_components(); } catch(e) { failed = String(e); }
        console.log(JSON.stringify({groupNodes: app.graph.extra?.groupNodes ?? {}, registered, failed}));
    """ % (
        json.dumps(status), json.dumps(body),
        slice_braced(source, "function storeGroupNode(name, data, register=true)"),
        JS.lift_declaration("components-manager.js", "export async function load_components()"),
    )
    return run_node(script)


@pytest.mark.parametrize("status, body", [
    (403, '{"error": "comfyui_outdated"}'), (403, '{"error": "security_level"}'), (403, ""),
    (400, ""), (404, "404: Not Found"), (500, "<html><body>500 Internal Server Error</body></html>"),
    (502, "<html><body><h1>502 Bad Gateway</h1></body></html>"), (403, json.dumps({"a component": COMPONENT})),
], ids=["an outdated ComfyUI", "a security level", "403 without a body", "400 without a body", "404", "500 with a page",
        "502 from a proxy", "403 with a list"])
def test_an_answer_that_is_not_a_success_has_no_components(status, body):
    assert load(status, body) == {"groupNodes": {}, "registered": [], "failed": None}


def test_a_success_without_components_adds_nothing():
    assert load(200, "{}") == {"groupNodes": {}, "registered": [], "failed": None}


@pytest.mark.parametrize("names", [["a component"], ["a component", "error", "another"]], ids=["one", "three, one named error"])
def test_the_components_of_a_success_are_registered_as_before(names):
    loaded = load(200, json.dumps({name: COMPONENT for name in names}))

    assert loaded["failed"] is None
    assert list(loaded["groupNodes"]) == names
    assert loaded["registered"] == [[name, "a pack"] for name in names]
