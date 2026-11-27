import os
from pathlib import Path

import pytest

from test_grid_highlight_escaping import browser  # noqa: F401 -- fixture

JS = Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "comfyui_manager" / "js"))
EXTENSION = "http://manager.test/extensions/comfyui-manager-legacy/"
CONTENT_TYPES = {".js": "text/javascript", ".css": "text/css"}

BATCH = "/v2/manager/queue/batch"
RESET = "/v2/manager/queue/reset"
STATUS = "/v2/manager/queue/status"
TITLES = ["String Join Tools", "ComfyUI-PromptUtilities", "String Join (Multi)"]

SCRIPTS = {
    "api.js": """
        class Api extends EventTarget {
            async getNodeDefs() { return {}; }
            async fetchApi(route, options) {
                const path = route.split('?')[0];
                requested.push({path, method: options?.method ?? 'GET', body: options?.body ? JSON.parse(options.body) : null});
                await during[path]?.();
                const answer = server[path];
                if(answer === undefined) return {status: 404, statusText: 'Not Found'};
                return {status: 200, json: async () => structuredClone(answer)};
            }
        }
        export const api = new Api();
    """,
    "app.js": """
        export const app = {
            graph: {_nodes: [], extra: {}},
            registerExtension() {},
            ui: {settings: {settingsValues: {}}, dialog: {element: document.createElement('div'), show() {}}},
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


def pack(title):
    key = title.lower().replace(" ", "-")
    repository = "https://github.com/someone/" + key
    return {"id": key, "title": title, "author": "someone", "description": "nodes", "repository": repository,
            "reference": repository, "files": [repository], "install_type": "cnr", "version": "1.0.0",
            "cnr_latest": "1.0.0", "state": "not-installed", "stars": 10, "last_update": "2025-01-01 00:00:00"}


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
    page.evaluate("""async ({module, packs}) => {
        window.requested = [];
        window.during = {};
        window.server = {
            '/v2/customnode/getlist': {channel: 'default', node_packs: Object.fromEntries(packs.map(pack => [pack.id, pack]))},
            '/v2/customnode/getmappings': {},
            '/v2/manager/queue/batch': {failed: []},
            '/v2/manager/queue/reset': '',
        };
        const {app} = await import('/scripts/app.js');
        const {setManagerInstance} = await import(new URL('common.js', module).href);
        setManagerInstance({datasrc_combo: {value: 'cache'}});
        const {CustomNodesManager} = await import(module);
        CustomNodesManager.instance = new CustomNodesManager(app, null);
        CustomNodesManager.instance.show(CustomNodesManager.ShowMode.NORMAL);
    }""", {"module": EXTENSION + "custom-nodes-manager.js", "packs": [pack(title) for title in TITLES]})
    page.wait_for_function("document.querySelector('.cn-manager-status').textContent == '3 custom nodes'")
    yield page
    page.close()


def queue_is_running(page, running):
    page.evaluate("running => server['%s'] = {total_count: 0, done_count: 0, in_progress_count: 0, is_processing: running}"
                  % STATUS, running)


def install_all(page):
    page.locator(".cn-manager-grid .tg-select-icon-all").click()
    page.locator(".cn-manager-selection button[mode='install']").click()
    page.wait_for_function("requested.some(request => request.path == '%s')" % BATCH)
    batch = page.evaluate("requested.find(request => request.path == '%s').body" % BATCH)
    return batch["batch_id"], [item["ui_id"] for item in batch["install"]]


def report(page, detail):
    page.evaluate("""async (detail) => {
        const { api } = await import('/scripts/api.js');
        api.dispatchEvent(new CustomEvent('cm-queue-status', {detail}));
        await new Promise(resolve => setTimeout(resolve));
    }""", detail)


def installed(page, batch_id, targets):
    for done, target in enumerate(targets, 1):
        report(page, {"status": "in_progress", "target": target, "batch_id": batch_id, "ui_target": "nodepack_manager",
                      "total_count": len(TITLES), "done_count": done})


def finish(page, batch_id, targets):
    installed(page, batch_id, targets)
    report(page, {"status": "batch-done", "nodepack_result": dict.fromkeys(targets, "success"), "model_result": {},
                  "total_count": len(TITLES), "done_count": len(TITLES), "batch_id": batch_id, "remaining_batch_count": 1})
    report(page, {"status": "all-done"})


def shown(page):
    return page.evaluate("""() => {
        const rows = [...document.querySelectorAll('.cn-manager-grid .tg-body .tg-row')];
        return {
            rows: rows.filter(row => row.querySelector('.cn-pack-name')).map(row => {
                const right = rows.find(other => other.getAttribute('row') == row.getAttribute('row') && other != row);
                const action = right.querySelector('.cn-install-buttons, font');
                return [row.querySelector('.cn-pack-name').innerText.trim(), action.innerText.trim(), !!action.querySelector('.cn-btn-loading')];
            }),
            stop: document.querySelector('.cn-manager-stop').checkVisibility(),
            restart: document.querySelector('.cn-manager-restart').checkVisibility(),
        };
    }""")


@pytest.mark.parametrize("done", [1, 0], ids=["after-the-first-install", "before-the-batch-started"])
def test_stop_returns_the_rows_that_were_not_installed_to_install(page, done):
    queue_is_running(page, False)
    batch_id, targets = install_all(page)
    assert shown(page)["stop"] is True

    page.locator(".cn-manager-stop").click()
    page.wait_for_function("requested.some(request => request.path == '%s' && request.method == 'POST')" % RESET)
    installed(page, batch_id, targets[:done])
    report(page, {"status": "all-done"})

    assert shown(page) == {
        "rows": [[title, "Restart Required" if i < done else "Install", False] for i, title in enumerate(TITLES)],
        "stop": False, "restart": done > 0}
    assert page.errors == []


def test_the_end_of_an_earlier_queue_leaves_a_running_install_waiting(page):
    queue_is_running(page, True)
    batch_id, targets = install_all(page)

    report(page, {"status": "all-done"})
    assert shown(page) == {"rows": [[title, "Install", True] for title in TITLES], "stop": True, "restart": False}

    finish(page, batch_id, targets)
    assert shown(page) == {"rows": [[title, "Restart Required", False] for title in TITLES], "stop": False, "restart": True}
    assert page.errors == []


def test_the_end_of_an_earlier_queue_while_the_install_is_being_queued_leaves_it_waiting(page):
    queue_is_running(page, False)
    page.evaluate("""() => during['%s'] = async () => {
        const { api } = await import('/scripts/api.js');
        api.dispatchEvent(new CustomEvent('cm-queue-status', {detail: {status: 'all-done'}}));
        await new Promise(resolve => setTimeout(resolve));
    }""" % BATCH)
    batch_id, targets = install_all(page)
    page.wait_for_function("document.querySelector('.cn-manager-stop').checkVisibility()", timeout=5000)
    assert shown(page) == {"rows": [[title, "Install", True] for title in TITLES], "stop": True, "restart": False}

    finish(page, batch_id, targets)
    assert shown(page) == {"rows": [[title, "Restart Required", False] for title in TITLES], "stop": False, "restart": True}
    assert page.errors == []
