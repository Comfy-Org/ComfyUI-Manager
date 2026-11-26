import os
from pathlib import Path

import pytest

from test_grid_highlight_escaping import browser  # noqa: F401 -- fixture

JS = Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js"))
EXTENSION = "http://manager.test/extensions/comfyui-manager/"
CONTENT_TYPES = {".js": "text/javascript", ".css": "text/css"}

REPOSITORY = "https://github.com/silveroxides/ComfyUI_SigmoidOffsetScheduler"
TITLE = "ComfyUI Sigmoid Offset Scheduler"
NODE = "SigmoidOffsetScheduler"
SPELLINGS = ["ComfyUI_SigmoidOffsetScheduler", "comfyui_sigmoidoffsetscheduler"]
SPELLING_IDS = ["registry case", "lowercase, saved earlier"]

SCRIPTS = {
    "api.js": """
        export const api = {
            addEventListener() {},
            getNodeDefs: async () => ({}),
            getSystemStats: async () => ({system: {comfyui_version: '0.3.60'}}),
            async fetchApi(path) {
                const answer = window.server[path.split('?')[0]];
                if(answer === undefined) return {status: 404, statusText: 'Not Found'};
                return {status: 200, json: async () => structuredClone(answer)};
            }
        };
    """,
    "app.js": """
        const dialog = document.createElement('div');
        dialog.className = 'comfy-modal';
        export const app = {
            graph: {_nodes: [], extra: {}},
            extensions: [],
            registerExtension(extension) { this.extensions.push(extension); },
            ui: {
                settings: {settingsValues: {'Comfy.ColorPalette': 'dark'}},
                dialog: {element: dialog, show(html) { dialog.innerHTML = html; document.body.append(dialog); }},
            },
        };
    """,
    "ui.js": """
        export function $el(tag, props, children) {
            if(Array.isArray(props)) [props, children] = [{}, props];
            const names = tag.split('.');
            const element = document.createElement(names.shift());
            element.classList.add(...names);
            const {parent, style, ...rest} = props ?? {};
            Object.assign(element.style, style);
            Object.assign(element, rest);
            element.append(...(children ?? []));
            parent?.append(element);
            return element;
        }
        export class ComfyDialog {}
    """,
}


def pack(key, title, state, repository):
    return {"id": key, "title": title, "author": "author", "description": "nodes", "repository": repository,
            "reference": repository, "files": [repository], "install_type": "cnr", "version": "1.1.1",
            "cnr_latest": "1.1.1", "state": state, "stars": 10, "last_update": "2025-01-01 00:00:00"}


def node_packs(state):
    return {
        "ComfyUI_SigmoidOffsetScheduler": pack("ComfyUI_SigmoidOffsetScheduler", TITLE, state, REPOSITORY),
        "comfyui-other-pack": pack("comfyui-other-pack", "Other Pack", "not-installed",
                                   "https://github.com/someone/comfyui-other-pack"),
    }


@pytest.fixture
def page(browser):  # noqa: F811
    page = browser.new_page(viewport={"width": 1600, "height": 900})

    def route(request):
        url = request.request.url
        name = url.rsplit("/", 1)[-1]
        if url == "http://manager.test/":
            request.fulfill(body="<body></body>", content_type="text/html")
        elif url.startswith(EXTENSION) and (JS / name).is_file():
            request.fulfill(path=str(JS / name), content_type=CONTENT_TYPES.get((JS / name).suffix, "text/plain"))
        elif url == "http://manager.test/scripts/" + name and name in SCRIPTS:
            request.fulfill(body=SCRIPTS[name], content_type="text/javascript")
        else:
            request.abort()

    page.route("**/*", route)
    page.errors = []
    page.on("pageerror", lambda error: page.errors.append(str(error)))
    page.goto("http://manager.test/")
    yield page
    page.close()


def open_list(page, mode, packs, nodes, registered, mapped=True):
    server = {
        "/customnode/getlist": {"channel": "default", "node_packs": packs},
        "/customnode/getmappings": {REPOSITORY: [[NODE], {"title_aux": TITLE}]} if mapped else {},
    }
    page.evaluate("""async ({module, mode, server, nodes, registered}) => {
        window.server = server;
        window.LiteGraph = {registered_node_types: Object.fromEntries(registered.map(type => [type, {type}]))};
        const {app} = await import('/scripts/app.js');
        app.graph._nodes = nodes;
        const {setManagerInstance} = await import(new URL('common.js', module).href);
        setManagerInstance({datasrc_combo: {value: 'cache'}});
        const {CustomNodesManager} = await import(module);
        window.manager = new CustomNodesManager(app, null);
        manager.show(CustomNodesManager.ShowMode[mode]);
    }""", {"module": EXTENSION + "custom-nodes-manager.js", "mode": mode, "server": server, "nodes": nodes,
           "registered": registered})
    page.wait_for_function("/^[\\d,]+ custom nodes$/.test(document.querySelector('.cn-manager-status').textContent)")
    return page.evaluate("""() => ({
        rows: [...document.querySelectorAll('.cn-manager-grid .tg-body .cn-pack-name')].map(cell => cell.innerText.trim()),
        status: document.querySelector('.cn-manager-status').textContent,
        message: document.querySelector('.comfy-modal')?.innerText ?? '',
    })""")


def workflow_node(cnr_id):
    return {"type": NODE, "properties": {"cnr_id": cnr_id, "ver": "1.1.1"}}


@pytest.mark.parametrize("cnr_id", SPELLINGS, ids=SPELLING_IDS)
def test_in_workflow_lists_the_installed_nodepack_of_a_node(page, cnr_id):
    shown = open_list(page, "IN_WORKFLOW", node_packs("enabled"), [workflow_node(cnr_id)], [NODE])

    assert shown == {"rows": [TITLE], "status": "1 custom nodes", "message": ""}
    assert page.errors == []


@pytest.mark.parametrize("mapped", [True, False], ids=["node in the node map", "node not in the node map"])
@pytest.mark.parametrize("cnr_id", SPELLINGS, ids=SPELLING_IDS)
def test_missing_lists_the_nodepack_of_an_unknown_node_without_saying_it_is_not_in_the_registry(page, cnr_id, mapped):
    shown = open_list(page, "MISSING", node_packs("not-installed"), [workflow_node(cnr_id)], [], mapped)

    assert shown == {"rows": [TITLE], "status": "1 custom nodes", "message": ""}
    assert page.errors == []


@pytest.mark.parametrize("cnr_id", ["comfyui-nowhere", 123], ids=["text", "number"])
def test_missing_says_which_id_of_the_workflow_no_nodepack_has(page, cnr_id):
    node = {"type": "NowhereNode", "properties": {"cnr_id": cnr_id, "ver": "1.0.0"}}

    shown = open_list(page, "MISSING", node_packs("not-installed"), [node], [])

    assert shown["rows"] == []
    assert "Failed to find the following ComfyRegistry list." in shown["message"]
    assert str(cnr_id) in shown["message"]
    assert page.errors == []


def with_core_lookalike(packs, state):
    packs["Comfy-Core"] = pack("Comfy-Core", "Core Lookalike", state, "https://github.com/someone/Comfy-Core")
    return packs


def test_missing_does_not_offer_a_nodepack_named_as_the_core_for_a_built_in_node(page):
    node = {"type": "NewBuiltInNode", "properties": {"cnr_id": "comfy-core", "ver": "0.3.60"}}

    shown = open_list(page, "MISSING", with_core_lookalike(node_packs("not-installed"), "not-installed"), [node], [])

    assert shown["rows"] == []
    assert "comfy-core" in shown["message"]
    assert page.errors == []


def new_node_properties(page, folder, cnr_id):
    installed = {folder: {"ver": "1.1.1", "cnr_id": cnr_id, "aux_id": None, "enabled": True}}
    return page.evaluate("""async ({module, server, python_module}) => {
        window.server = server;
        const {app} = await import('/scripts/app.js');
        await import(module);
        const extension = app.extensions.find(extension => extension.nodeCreated);
        await extension.init();
        class Node {}
        Node.nodeData = {python_module};
        const node = new Node();
        extension.nodeCreated(node);
        return node.properties;
    }""", {"module": EXTENSION + "workflow-metadata.js", "server": {"/customnode/installed": installed},
           "python_module": "custom_nodes." + folder})


def test_a_new_node_takes_the_id_of_its_nodepack_as_the_installed_list_spells_it(page):
    properties = new_node_properties(page, "ComfyUI_SigmoidOffsetScheduler", "ComfyUI_SigmoidOffsetScheduler")

    assert properties == {"cnr_id": "ComfyUI_SigmoidOffsetScheduler", "ver": "1.1.1"}


@pytest.mark.parametrize("cnr_id", ["comfy-core", "Comfy-Core"])
def test_a_new_node_of_a_nodepack_that_names_itself_as_the_core_takes_no_id(page, cnr_id):
    assert new_node_properties(page, "core-lookalike", cnr_id) == {}
