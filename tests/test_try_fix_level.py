import ast
import asyncio
import json
import logging
import os
import runpy
import threading
import traceback
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

from legacy_html_testutil import PACKAGE
from test_grid_highlight_escaping import browser  # noqa: F401 -- fixture

SERVER = PACKAGE / "legacy/manager_server.py"
MESSAGES = runpy.run_path(str(PACKAGE / "common/security_messages.py"))
NAMES = {"is_allowed_security_level", "TaskBatch", "finalize_temp_queue_batch", "queue_batch", "_queue_start",
         "_fix_custom_node", "task_worker"}
JS = Path(os.environ.get("MANAGER_JS_DIR") or (PACKAGE / "js"))
EXTENSION = "http://manager.test/extensions/comfyui-manager/"
CONTENT_TYPES = {".js": "text/javascript", ".css": "text/css"}

LEVELS = ["strong", "normal", "normal-", "weak"]
LISTENERS = ["loopback", "personal_cloud", "public"]
PACK = {"id": "comfyui-ollama", "title": "comfyui-ollama", "author": "Stav Sapir", "description": "Ollama nodes",
        "repository": "https://github.com/stavsap/comfyui-ollama", "reference": "https://github.com/stavsap/comfyui-ollama",
        "files": ["https://github.com/stavsap/comfyui-ollama"], "install_type": "git-clone", "version": "nightly",
        "active_version": "nightly", "cnr_latest": "2.1.0", "state": "enabled", "import-fail": True,
        "update-state": "false", "stars": 879, "last_update": "2025-10-23 17:02:46"}


def fix_allowed(security_level, listener):
    return security_level == "weak" and listener != "public" or security_level == "normal-" and listener == "loopback"


ALLOWED = [(level, listener) for level in LEVELS for listener in LISTENERS if fix_allowed(level, listener)]
REFUSED = [(level, listener) for level in LEVELS for listener in LISTENERS if not fix_allowed(level, listener)]


def legacy_server(security_level, listener, history):
    fixed, sent = [], []

    async def reload(mode):
        pass

    core = SimpleNamespace(
        get_config=lambda: {"security_level": security_level,
                            "network_mode": "personal_cloud" if listener == "personal_cloud" else "public"},
        unified_manager=SimpleNamespace(reload=reload, unified_fix=lambda name, version: fixed.append(name) or SimpleNamespace(result=True)))
    update_check_done = threading.Event()
    update_check_done.set()
    namespace = {
        "web": web, "json": json, "os": os, "asyncio": asyncio, "threading": threading, "logging": logging,
        "traceback": traceback, "routes": SimpleNamespace(post=lambda path: lambda handler: handler),
        "manager_security": SimpleNamespace(reject_non_json_post=lambda request: None), "core": core,
        "is_local_mode": listener == "loopback", "context": SimpleNamespace(manager_batch_history_path=str(history)),
        "PromptServer": SimpleNamespace(instance=SimpleNamespace(send_sync=lambda name, data: sent.append(data))),
        "temp_queue_batch": [], "task_batch_queue": deque(), "tasks_in_progress": set(),
        "task_worker_lock": threading.Lock(), "task_worker_thread": None, "update_check_done": update_check_done,
        **{name: text for name, text in MESSAGES.items() if name.startswith("SECURITY_MESSAGE_")},
    }
    nodes = [node for node in ast.parse(SERVER.read_text(encoding="utf-8")).body if getattr(node, "name", None) in NAMES]
    assert {node.name for node in nodes} == NAMES
    exec(compile(ast.Module(nodes, []), str(SERVER), "exec"), namespace)

    async def body(batch):
        return batch

    def send(batch):
        sent.clear()
        answer = asyncio.run(namespace["queue_batch"](SimpleNamespace(json=lambda: body(batch))))
        namespace["task_worker_thread"].join(5)
        return json.loads(answer.text), list(sent)

    return send, fixed


@pytest.mark.parametrize("security_level, listener", ALLOWED)
def test_try_fix_runs_at_a_level_that_allows_it(tmp_path, security_level, listener):
    send, fixed = legacy_server(security_level, listener, tmp_path)

    answer, sent = send({"batch_id": "the batch", "fix": [dict(PACK, ui_id="the row")]})

    assert answer == {"failed": []}
    assert fixed == ["comfyui-ollama"]
    assert [event["nodepack_result"] for event in sent if event["status"] == "batch-done"] == [{"the row": "success"}]


@pytest.mark.parametrize("security_level, listener", REFUSED)
def test_try_fix_at_a_level_that_does_not_allow_it_is_refused_and_not_queued(tmp_path, caplog, security_level, listener):
    send, fixed = legacy_server(security_level, listener, tmp_path)

    answer, sent = send({"batch_id": "the batch", "fix": [dict(PACK, ui_id="the row")]})

    assert answer == {"failed": ["comfyui-ollama"]}
    assert fixed == []
    assert [event["status"] for event in sent] == ["all-done"]
    assert caplog.messages == [MESSAGES["SECURITY_MESSAGE_HIGH_P"]]


SCRIPTS = {
    "api.js": """
        class Api extends EventTarget {
            getNodeDefs = async () => ({});
            async fetchApi(path, options) {
                const route = path.split('?')[0];
                if(route == '/v2/manager/queue/batch') {
                    const {answer, events} = await window.legacyServer(JSON.parse(options.body));
                    setTimeout(() => {
                        events.forEach((detail) => this.dispatchEvent(new CustomEvent('cm-queue-status', {detail})));
                        window.reported = true;
                    });
                    return {status: 200, json: async () => answer};
                }
                const answer = window.server[route];
                if(answer === undefined) return {status: 404, statusText: 'Not Found'};
                return {status: 200, json: async () => structuredClone(answer)};
            }
        }
        export const api = new Api();
    """,
    "app.js": """
        const dialog = document.createElement('div');
        dialog.className = 'comfy-modal';
        export const app = {
            graph: {_nodes: [], extra: {}},
            registerExtension() {},
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


def try_fix(page, send):
    def serve(batch):
        # Playwright's sync API keeps an event loop running in this thread, where asyncio.run cannot start another.
        replies = []
        server = threading.Thread(target=lambda: replies.append(send(batch)))
        server.start()
        server.join()
        answer, events = replies[0]
        return {"answer": answer, "events": events}

    page.expose_function("legacyServer", serve)
    page.evaluate("""async ({module, server}) => {
        window.server = server;
        const {app} = await import('/scripts/app.js');
        const {setManagerInstance} = await import(new URL('common.js', module).href);
        setManagerInstance({datasrc_combo: {value: 'cache'}});
        const {CustomNodesManager} = await import(module);
        window.manager = CustomNodesManager.instance = new CustomNodesManager(app, null);
        manager.show(CustomNodesManager.ShowMode.NORMAL);
    }""", {"module": EXTENSION + "custom-nodes-manager.js",
           "server": {"/v2/customnode/getlist": {"channel": "default", "node_packs": {"comfyui-ollama": PACK}},
                      "/v2/customnode/getmappings": {}}})
    page.wait_for_function("document.querySelector('.cn-manager-status').textContent == '1 custom nodes'")
    page.get_by_role("button", name="Try fix", exact=True).click()
    page.wait_for_function("window.reported && manager.install_context === undefined")
    return page.evaluate("""() => ({
        box: (document.querySelector('.comfy-modal')?.textContent ?? '').split(/\\s+/).filter(Boolean).join(' '),
        action: [...document.querySelectorAll('.cn-manager-grid .tg-body button, .cn-manager-grid .tg-body font')]
            .map((element) => element.textContent),
        restart: document.querySelector('.cn-manager-restart').checkVisibility(),
    })""")


def test_try_fix_at_the_default_level_is_refused_without_asking_for_a_restart(page, tmp_path):
    send, fixed = legacy_server("normal", "loopback", tmp_path)

    shown = try_fix(page, send)

    assert shown == {"box": "[Installation Errors] [FAIL] comfyui-ollama",
                     "action": ["IMPORT FAILED ↗", "Try fix", "Switch Ver", "Disable", "Uninstall"], "restart": False}
    assert fixed == []
    assert page.errors == []


def test_try_fix_at_a_level_that_allows_it_runs_and_asks_for_a_restart(page, tmp_path):
    send, fixed = legacy_server("normal-", "loopback", tmp_path)

    shown = try_fix(page, send)

    assert shown == {"box": "", "action": ["IMPORT FAILED ↗", "Restart Required"], "restart": True}
    assert fixed == ["comfyui-ollama"]
    assert page.errors == []
