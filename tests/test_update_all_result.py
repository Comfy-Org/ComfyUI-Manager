import os
from pathlib import Path

import pytest

from test_grid_highlight_escaping import browser  # noqa: F401 -- fixture

JS = Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js"))
EXTENSION = "http://manager.test/extensions/comfyui-manager/"

UPDATE_COMFYUI = "/manager/queue/update_comfyui"
UPDATE_ALL = "/manager/queue/update_all"
START = "/manager/queue/start"
REBOOT = "/manager/reboot"
ANSWERS = {
    "/manager/db_mode": "cache",
    "/manager/channel_url_list": {"list": ["default::https://example.invalid/channel"], "selected": "default"},
}

STAND_INS = {
    "scripts/api.js": """
        class Api extends EventTarget {
            async fetchApi(path, options) {
                const answer = window.answers[path.split('?')[0]] ?? '';
                window.requested.push({path, method: options?.method ?? 'GET', body: options?.body ? JSON.parse(options.body) : null});
                return {status: 200, json: async () => answer, text: async () => typeof answer == 'string' ? answer : JSON.stringify(answer)};
            }
        }
        export const api = new Api();
    """,
    "scripts/app.js": """
        import { ComfyDialog } from './ui.js';
        export const app = {
            ui: {dialog: new ComfyDialog()},
            registerExtension(extension) { window.extension = extension; },
        };
    """,
    "scripts/ui.js": """
        const style = document.createElement('style');
        style.textContent = '.comfy-modal { display: none; position: fixed; z-index: 100; top: 50%; left: 50%; transform: translate(-50%, -50%); padding: 20px; background: #353535; color: #ddd; }';
        document.head.append(style);

        export function $el(tag, propsOrChildren, children) {
            const [name, ...classes] = tag.split('.');
            const element = document.createElement(name);
            element.classList.add(...classes);
            if(typeof propsOrChildren == 'string') {
                propsOrChildren = {textContent: propsOrChildren};
            }
            else if(Array.isArray(propsOrChildren) || propsOrChildren instanceof Element) {
                children = propsOrChildren;
                propsOrChildren = {};
            }
            const {parent, $: callback, dataset, style, ...props} = propsOrChildren ?? {};
            Object.assign(element.style, style);
            Object.assign(element.dataset, dataset);
            Object.assign(element, props);
            if(children) {
                element.append(...[children].flat());
            }
            parent?.append(element);
            callback?.(element);
            return element;
        }

        export class ComfyDialog {
            constructor() {
                this.element = $el('div.comfy-modal', {parent: document.body}, [
                    $el('div.comfy-modal-content', [
                        $el('p', {$: (p) => (this.textElement = p)}),
                        $el('button', {type: 'button', textContent: 'Close', onclick: () => this.close()}),
                    ]),
                ]);
            }

            close() {
                this.element.style.display = 'none';
            }

            show(html) {
                this.textElement.innerHTML = html;
                this.element.style.display = 'flex';
            }
        }
    """,
    "extensions/core/groupNode.js": """
        export class GroupNodeConfig {}
        export class GroupNodeHandler {}
    """,
}

UPDATED = {"msg": "success", "title": "ComfyUI-TechsToolz", "url": "https://verify.invalid/packs/ComfyUI-TechsToolz"}
UP_TO_DATE = {"msg": "skip", "title": "ComfyUI-CyberUtils", "url": "https://verify.invalid/packs/ComfyUI-CyberUtils"}
FAILED = {"msg": "An error occurred while updating 'comfyui-glitchkit'.", "title": "ComfyUI-GlitchKit",
          "url": "https://verify.invalid/packs/ComfyUI-GlitchKit"}


@pytest.fixture
def page(browser):  # noqa: F811
    page = browser.new_page()

    def route(request):
        url = request.request.url
        name = url.rsplit("/", 1)[-1]
        stand_in = url.removeprefix("http://manager.test/")
        if url == "http://manager.test/":
            request.fulfill(body="<body></body>", content_type="text/html")
        elif url.startswith(EXTENSION) and (JS / name).is_file():
            request.fulfill(path=str(JS / name), content_type="text/css" if name.endswith(".css") else "text/javascript")
        elif stand_in in STAND_INS:
            request.fulfill(body=STAND_INS[stand_in], content_type="text/javascript")
        else:
            request.abort()

    page.route("**/*", route)
    page.add_init_script("""
        window.errors = [];
        addEventListener('error', (event) => errors.push(String(event.error ?? event.message)));
        addEventListener('unhandledrejection', (event) => errors.push(String(event.reason)));
    """)
    page.goto("http://manager.test/")
    yield page
    page.close()


def open_menu(page, electron=False):
    page.evaluate("""async ({module, answers, electron}) => {
        if(electron) {
            window.restarts = 0;
            window.electronAPI = {restartApp() { window.restarts++; }};
        }
        window.requested = [];
        window.answers = answers;
        await import(module);
        window.extension.commands.find((command) => command.id == 'Comfy.Manager.Menu.ToggleVisibility').function();
    }""", {"module": EXTENSION + "comfyui-manager.js", "answers": ANSWERS, "electron": electron})


def queue_requests(page):
    page.wait_for_function("requested.some((request) => request.path == '%s')" % START)
    return page.evaluate("requested.filter((request) => request.path.startsWith('/manager/queue/'))"
                         ".map((request) => [request.method, request.path, request.body])")


def report(page, detail):
    page.evaluate("""async (detail) => {
        const { api } = await import('/scripts/api.js');
        api.dispatchEvent(new CustomEvent('cm-queue-status', {detail}));
    }""", detail)


def finish(page, nodepack_result):
    total = len(nodepack_result)
    for done, target in enumerate(nodepack_result):
        report(page, {"status": "in_progress", "target": target, "ui_target": "main",
                      "total_count": total, "done_count": done})
    report(page, {"status": "done", "nodepack_result": nodepack_result, "model_result": {},
                  "total_count": total, "done_count": total})


def result(page):
    page.wait_for_function("errors.length > 0 || [...document.querySelectorAll('.comfy-modal')].some((box) => box.checkVisibility())",
                           timeout=5000)
    assert page.evaluate("errors") == []
    box = page.locator(".comfy-modal:visible .comfy-modal-content > p")
    return box.inner_text(), box.locator("li").all_inner_texts()


def test_update_all_shows_what_was_updated_with_comfyui(page):
    open_menu(page)
    page.get_by_role("button", name="Update All", exact=True).click()

    assert queue_requests(page) == [["POST", UPDATE_COMFYUI, None], ["POST", UPDATE_ALL, {"mode": "cache"}], ["POST", START, None]]

    finish(page, {"comfyui": "success-stable-v0.3.60", "comfyui-techstoolz": UPDATED, "comfyui-cyberutils": UP_TO_DATE,
                  "comfyui-glitchkit": FAILED})
    text, items = result(page)
    assert "To apply the updates, you need to RESTART ComfyUI." in text
    assert "ComfyUI has been updated to v0.3.60." in text
    assert "The following custom nodes have been updated:" in text
    assert "The update for the following custom nodes has failed:" in text
    assert items == ["ComfyUI-TechsToolz", "ComfyUI-GlitchKit"]

    page.get_by_role("button", name="RESTART", exact=True).click()
    page.get_by_text("Are you sure you'd like to reboot the server?").wait_for()
    page.get_by_role("button", name="Confirm").click()
    page.wait_for_function("requested.some((request) => request.method == 'POST' && request.path == '%s')" % REBOOT)


@pytest.mark.parametrize("nodepack_result, shown, items, restart", [
    ({"comfyui-techstoolz": UPDATED, "comfyui-cyberutils": UP_TO_DATE},
     "To apply the updates, you need to RESTART ComfyUI.", ["ComfyUI-TechsToolz"], True),
    ({"comfyui-cyberutils": UP_TO_DATE}, "You are already up to date.", [], False),
    ({"comfyui-glitchkit": FAILED, "comfyui-cyberutils": UP_TO_DATE},
     "The update for the following custom nodes has failed:", ["ComfyUI-GlitchKit"], False),
], ids=["updated", "up-to-date", "failed"])
def test_the_electron_button_shows_a_result_without_comfyui(page, nodepack_result, shown, items, restart):
    open_menu(page, electron=True)
    page.get_by_role("button", name="Update All Custom Nodes", exact=True).click()

    assert queue_requests(page) == [["POST", UPDATE_ALL, {"mode": "cache"}], ["POST", START, None]]

    finish(page, nodepack_result)
    text, listed = result(page)
    assert shown in text
    assert "ComfyUI has been updated" not in text
    assert "ComfyUI is already up to date" not in text
    assert "Failed to update ComfyUI" not in text
    assert listed == items
    assert page.get_by_role("button", name="RESTART", exact=True).count() == (1 if restart else 0)

    if restart:
        page.get_by_role("button", name="RESTART", exact=True).click()
        page.wait_for_function("window.restarts == 1")
        assert page.evaluate("errors") == []
