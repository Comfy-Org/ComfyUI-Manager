"""The legacy UI tells the user when the restart that another extension asked for is refused.

Found while reviewing #3435.

An extension asks through `cm.try-install-custom-node` for a node pack that is disabled; the
legacy UI asks the user whether to enable it and restart. The cases run the shipped cm-api.js
and common.js in Chromium against stand-ins for ComfyUI's scripts; no ComfyUI server is used.

Browser cases require Playwright and its Chromium install.
"""
import os
from pathlib import Path

import pytest

from test_grid_highlight_escaping import browser  # noqa: F401 -- fixture

JS = Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "comfyui_manager" / "js"))
EXTENSION = "http://manager.test/extensions/comfyui-manager-legacy/"

SCRIPTS = {
    # Answers every request with the status set for its path, 200 by default, and records the path.
    "api.js": """
        class Api extends EventTarget {
            async fetchApi(path) {
                window.requested.push(path);
                return {status: window.statuses[path] ?? 200, text: async () => ''};
            }
        }
        export const api = new Api();
    """,
    # `show_message` in common.js shows its text in this dialog.
    "app.js": """
        const element = document.createElement('div');
        element.id = 'comfy-dialog';
        document.body.append(element);
        export const app = {ui: {dialog: {element, show(html) { element.innerHTML = html; }}}};
    """,
    "ui.js": "export const $el = () => null; export class ComfyDialog {}",
}


@pytest.fixture
def page(browser):  # noqa: F811
    page = browser.new_page()

    def route(request):
        url = request.request.url
        name = url.rsplit("/", 1)[-1]
        if url == "http://manager.test/":
            request.fulfill(body="<body></body>", content_type="text/html")
        elif url.startswith(EXTENSION) and (JS / name).is_file():
            request.fulfill(path=str(JS / name), content_type="text/javascript")
        elif url == "http://manager.test/scripts/" + name and name in SCRIPTS:
            request.fulfill(body=SCRIPTS[name], content_type="text/javascript")
        else:
            request.abort()

    page.route("**/*", route)
    page.goto("http://manager.test/")
    yield page
    page.close()


def ask_for_disabled_pack(page, statuses):
    """Deliver the request for a disabled pack and confirm the dialog that asks to enable it and restart."""
    page.evaluate("""async ({statuses, module}) => {
        window.requested = [];
        window.statuses = statuses;
        await import(module);
        const { api } = await import('/scripts/api.js');
        api.dispatchEvent(new CustomEvent('cm-api-try-install-customnode', {detail: {
            sender: 'Some Pack', msg: 'needed for the detector nodes',
            target: {title: 'Other Pack', installed: 'Disabled', files: ['https://github.com/someone/other-pack']},
        }}));
    }""", {"statuses": statuses, "module": EXTENSION + "cm-api.js"})
    question = page.get_by_text("Would you like to enable it and reboot?")
    question.wait_for()
    assert "'Some Pack' extension requires the installation of the 'Other Pack' extension" in question.inner_text()
    page.get_by_role("button", name="Confirm").click()


def test_a_refused_restart_is_reported(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    ask_for_disabled_pack(page, {"/v2/manager/reboot": 403})

    page.locator("#comfy-dialog").get_by_text(
        "This action is not allowed with this security level configuration.").wait_for(timeout=5000)
    assert page.evaluate("window.requested")[-1] == "/v2/manager/reboot"
    assert errors == []


def test_an_accepted_restart_is_announced(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    ask_for_disabled_pack(page, {})

    page.locator("#comfy-dialog").get_by_text("Rebooting...").wait_for(timeout=5000)
    assert page.evaluate("window.requested")[-1] == "/v2/manager/reboot"
    assert errors == []
