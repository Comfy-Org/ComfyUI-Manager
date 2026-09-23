"""Render actual update-completion handlers in an isolated browser."""
from pathlib import Path

import pytest

from js_lift import JsSource

JS = JsSource(Path(__file__).resolve().parent.parent / "js")


@pytest.mark.parametrize("status", ["success", "failed"])
def test_update_results_preserve_links_titles_and_missing_url_labels(status):
    playwright = pytest.importorskip("playwright.sync_api")
    helpers = JS.lift_declaration("common.js", "export function sanitizeHTML(")
    helpers += JS.lift_span(
        "common.js", "export const SAFE_URL_SCHEMES",
        "export const safeHref = (url) => sanitizeHTML(sanitizeUrl(url));",
    ).replace("export ", "")
    helpers += JS.lift_declaration("common.js", "export function show_message(")
    handler = JS.lift_declaration("comfyui-manager.js", "async function onQueueStatus(")
    url = "https://example.test/guide?q=O'Reilly&lang=en"
    title = "Guide <draft> & notes"
    fallback_id = "Pack <draft>"

    with playwright.sync_playwright() as driver:
        if not Path(driver.chromium.executable_path).exists():
            pytest.skip("install Chromium with: playwright install chromium")
        browser = driver.chromium.launch()
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content('<div id="dialog"></div>')
        page.add_script_tag(content="""
            let is_updating = true;
            function reset_action_buttons() {}
            function setNeedRestart() {}
            function infoToast() {}
            const app = {ui: {dialog: {
                element: document.getElementById('dialog'),
                show(message) { this.element.innerHTML = message; }
            }}};
        """ + helpers + handler)
        page.evaluate("event => onQueueStatus(event)", {"detail": {
            "status": "done", "nodepack_result": {
                "comfyui": "skip",
                "pack-link": {"url": url, "title": title, "msg": status},
                fallback_id: {"msg": status},
            },
        }})
        items = page.locator("#dialog li")
        assert items.all_text_contents() == [title, fallback_id]
        assert items.nth(0).locator("a").get_attribute("href") == url
        assert set(items.nth(0).locator("a").evaluate("node => node.getAttributeNames()")) == {
            "href", "target", "rel",
        }
        assert items.nth(0).locator("a").get_attribute("rel") == "noopener noreferrer"
        assert items.nth(1).locator("a").count() == 0
        assert page.locator("#dialog draft").count() == 0
        browser.close()
