"""RED->GREEN guard for "Fix node (recreate)" in js/node_fixer.js (#3126).

node_info_copy() re-wired each linked input with
``src_node.connect(link.origin_slot, dest.id, input.name)``. On current
frontends a NodeId is a string, and LGraphNode.connect() only looks a target up
by id when it is a NUMBER; anything else is used as the node itself, so the id
string reached ``target_node.findInputSlot(...)`` and threw. The menu callback
had already added the replacement node, so the throw skipped
``graph.remove(this)`` and left the wired original plus an unwired copy.

The graph and node below are stubs that keep the parts of the litegraph
contract this code depends on: string node ids, ``graph.links[id]`` lookup, an
input holding one link, and connect() resolving only a numeric target id.
node_info_copy() and the menu callback are the shipped code, lifted by
tests/js_lift.

REPRODUCE THE RED HALF against the pre-fix revision:
  mkdir -p /some/dir
  git show <base>:js/node_fixer.js > /some/dir/node_fixer.js
  MANAGER_JS_DIR=/some/dir pytest tests/test_node_fixer_recreate.py
"""
import os
import unittest
from pathlib import Path

from js_lift import NODE, JsSource, run_node

REPO_ROOT = Path(__file__).resolve().parent.parent
JS = JsSource(os.environ.get("MANAGER_JS_DIR") or (REPO_ROOT / "js"))

FIXER = "node_fixer.js"

STUB_GRAPH = """
const LAYOUT = {
    Loader: {inputs: [], outputs: [{name: 'MODEL', type: 'MODEL'}]},
    Sampler: {inputs: [{name: 'model', type: 'MODEL'}], outputs: [{name: 'LATENT', type: 'LATENT'}]},
    Decoder: {inputs: [{name: 'samples', type: 'LATENT'}], outputs: []},
};

class Graph {
    constructor() { this._nodes = []; this.links = {}; this.lastNodeId = 0; this.lastLinkId = 0; }
    add(node) {
        node.id = String(++this.lastNodeId);  // NodeId is a string on current frontends
        node.graph = this;
        this._nodes.push(node);
        return node;
    }
    getNodeById(id) { return this._nodes.find(node => node.id === id) ?? null; }
    removeLink(id) {
        const link = this.links[id];
        delete this.links[id];
        const output = this.getNodeById(link.origin_id)?.outputs[link.origin_slot];
        if (output) output.links = output.links.filter(x => x !== id);
        const input = this.getNodeById(link.target_id)?.inputs[link.target_slot];
        if (input?.link === id) input.link = null;
    }
    remove(node) {
        for (const input of node.inputs) if (input.link != null) this.removeLink(input.link);
        for (const output of node.outputs) for (const id of output.links ?? []) this.removeLink(id);
        this._nodes = this._nodes.filter(x => x !== node);
    }
    afterChange() {}
}

class Node {
    constructor(type) {
        this.type = type;
        this.pos = [0, 0];
        this.size = [100, 100];
        this.widgets = [];
        this.inputs = LAYOUT[type].inputs.map(slot => ({...slot, link: null}));
        this.outputs = LAYOUT[type].outputs.map(slot => ({...slot, links: null}));
    }
    findInputSlot(name) { return this.inputs.findIndex(input => input.name === name); }
    // As LGraphNode.connect: only a NUMBER target is looked up by id.
    connect(slot, target_node, target_slot) {
        if (typeof target_node === 'number') target_node = this.graph.getNodeById(String(target_node));
        if (!target_node) throw 'target node is null';
        const index = typeof target_slot === 'string' ? target_node.findInputSlot(target_slot) : target_slot;
        const input = target_node.inputs[index];
        if (input.link != null) this.graph.removeLink(input.link);
        const link = {id: ++this.graph.lastLinkId, origin_id: this.id, origin_slot: slot,
                      target_id: target_node.id, target_slot: index};
        this.graph.links[link.id] = link;
        (this.outputs[slot].links ??= []).push(link.id);
        input.link = link.id;
        return link;
    }
}

const LiteGraph = {createNode: type => new Node(type)};
globalThis.requestAnimationFrame = callback => callback();

const graph = new Graph();
const app = {graph, canvas: {graph, setDirty() {}}, registerExtension(ext) { this.extension = ext; }};

// Loader -> Sampler -> Decoder; the Sampler is the node being recreated.
const loader = graph.add(new Node('Loader'));
const sampler = graph.add(new Node('Sampler'));
const decoder = graph.add(new Node('Decoder'));
loader.connect(0, sampler, 'model');
sampler.connect(0, decoder, 0);

const origin_of = input => {
    const link = graph.links[input.link];
    return link ? [link.origin_id, link.origin_slot] : null;
};
"""


@unittest.skipIf(NODE is None, "node is required to execute the lifted production JS")
class NodeFixerRecreateTest(unittest.TestCase):

    def test_node_info_copy_rewires_inputs_and_outputs(self):
        result = run_node(
            "%s\n%s\n"
            "const fresh = graph.add(LiteGraph.createNode('Sampler'));\n"
            "let error = null;\n"
            "try { node_info_copy(sampler, fresh, true); } catch (e) { error = String(e); }\n"
            "console.log(JSON.stringify({error, fresh: fresh.id,\n"
            "    fresh_input: origin_of(fresh.inputs[0]), decoder_input: origin_of(decoder.inputs[0])}));\n"
            % (STUB_GRAPH, JS.lift_declaration(FIXER, "function node_info_copy("))
        )
        self.assertIsNone(result["error"], "node_info_copy threw: %s" % (result["error"],))
        # The Loader is node "1"; the copy must take over both sides of the Sampler.
        self.assertEqual(result["fresh_input"], ["1", 0], "input link was not re-created")
        self.assertEqual(result["decoder_input"], [result["fresh"], 0], "output link was not re-created")

    def test_recreate_menu_leaves_one_rewired_node(self):
        result = run_node(
            "%s\n%s\n%s\n%s\n"
            "const nodeType = function () {};\n"
            "nodeType.comfyClass = 'Sampler';\n"
            "nodeType.prototype.getExtraMenuOptions = function () { return []; };\n"
            "app.extension.beforeRegisterNodeDef(nodeType, {}, app);\n"
            "const options = [];\n"
            "nodeType.prototype.getExtraMenuOptions.call(sampler, app.canvas, options);\n"
            "let error = null;\n"
            "try { options.find(o => o.content === 'Fix node (recreate)').callback(); }\n"
            "catch (e) { error = String(e); }\n"
            "console.log(JSON.stringify({error,\n"
            "    nodes: graph._nodes.map(node => [node.id, node.type]),\n"
            "    links: Object.values(graph.links).map(l => [l.origin_id, l.origin_slot, l.target_id, l.target_slot])}));\n"
            % (STUB_GRAPH,
               JS.lift_declaration(FIXER, "function addMenuHandler("),
               JS.lift_declaration(FIXER, "function node_info_copy("),
               JS.lift_span(FIXER, "app.registerExtension({", "\n});"))
        )
        self.assertIsNone(result["error"], "Fix node (recreate) threw: %s" % (result["error"],))
        # The original Sampler ("2") is gone and its replacement ("4") took its links.
        self.assertEqual(result["nodes"], [["1", "Loader"], ["3", "Decoder"], ["4", "Sampler"]])
        self.assertEqual(sorted(result["links"]), [["1", 0, "4", 0], ["4", 0, "3", 0]])


if __name__ == "__main__":
    unittest.main()
