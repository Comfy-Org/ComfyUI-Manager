"""Exercise Manager's search overrides with the shipped TurboGrid in Chromium.

Browser cases require Playwright and its Chromium install. All requests are
intercepted locally; no ComfyUI server or external services are used.
"""
import os
from pathlib import Path

import pytest

JS = Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js"))


@pytest.mark.parametrize("filename", ["custom-nodes-manager.js", "model-manager.js"])
def test_searching_managers_use_the_safe_grid(filename):
    source = (JS / filename).read_text()
    assert 'import ManagerGrid from "./manager-grid.js"' in source
    assert "new ManagerGrid(container)" in source
    assert 'from "./turbogrid.esm.js"' not in source


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as driver:
        if not Path(driver.chromium.executable_path).exists():
            pytest.skip("install Chromium with: playwright install chromium")
        instance = driver.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    page = browser.new_page()

    def route(request):
        name = request.request.url.rsplit("/", 1)[-1]
        if name in {"manager-grid.js", "turbogrid.esm.js"}:
            request.fulfill(path=str(JS / name), content_type="text/javascript")
        elif request.request.url == "http://manager.test/":
            request.fulfill(
                body='<div id="grid" style="width:800px;height:300px"></div>',
                content_type="text/html",
            )
        else:
            request.abort()

    page.route("**/*", route)
    page.goto("http://manager.test/")
    page.evaluate("""async () => {
        const {default: ManagerGrid} = await import('/manager-grid.js');
        window.grid = new ManagerGrid(document.getElementById('grid'));
        grid.setData({columns: [{id: 'name', name: 'Name'}], rows: []});
        grid.render();
    }""")
    page.wait_for_function("window.grid.options !== undefined")
    yield page
    page.close()


@pytest.mark.parametrize("keyword", ["before", "img", "after"])
def test_highlighting_keeps_all_text_inert(page, keyword):
    text = 'before <img src="/bad.png" onerror="window.__probe=1"> & after'
    result = page.evaluate("""({text, keyword}) => {
        const cell = document.createElement('div');
        cell.id = 'cell';
        cell.textContent = text;
        document.body.append(cell);
        grid.highlightKeywordsSync([cell], [keyword]);
        return {text: cell.textContent, marks: [...cell.querySelectorAll('mark')].map(x => x.textContent),
                images: cell.querySelectorAll('img').length};
    }""", {"text": text, "keyword": keyword})
    assert result == {"text": text, "marks": [keyword], "images": 0}
    assert page.evaluate("window.__probe === undefined")


def test_keyword_order_continues_across_text_nodes(page):
    result = page.evaluate("""() => {
        const cell = document.createElement('div');
        cell.innerHTML = '<b>Alpha</b> beta Alpha beta <svg><text>Alpha</text></svg><textarea>beta</textarea>';
        grid.highlightKeywordsSync([cell], ['alpha', 'beta']);
        return [...cell.querySelectorAll('mark')].map(x => x.textContent);
    }""")
    assert result == ["Alpha", "beta", "Alpha", "beta"]


def test_search_cache_does_not_execute_html(page):
    result = page.evaluate("""() => {
        const row = {description: '<img src="/bad.png" onerror="window.__probe=1"><b>Alpha</b> &amp; Beta'};
        const matched = grid.highlightKeywordsFilter(row, ['description'], 'alpha & beta');
        return {matched, text: row.tg_text_description, highlight: row.tg_highlight_description};
    }""")
    assert result == {"matched": True, "text": "Alpha & Beta", "highlight": True}
    page.wait_for_timeout(50)
    assert page.evaluate("window.__probe === undefined")


def test_search_preserves_order_columns_and_empty_query(page):
    result = page.evaluate("""() => {
        const row = {name: 'Alpha Beta', description: 'Gamma', missing: null, count: 0};
        const columns = ['name', 'description', 'missing', 'count'];
        const ordered = grid.highlightKeywordsFilter(row, columns, ' ALPHA   beta ');
        const reversed = grid.highlightKeywordsFilter(row, columns, 'beta alpha');
        const acrossColumns = grid.highlightKeywordsFilter(row, columns, 'alpha gamma');
        const zero = grid.highlightKeywordsFilter(row, columns, '0');
        const empty = grid.highlightKeywordsFilter(row, columns, '');
        return {ordered, reversed, acrossColumns, zero, empty,
                flags: columns.map(column => row['tg_highlight_' + column])};
    }""")
    assert result == {"ordered": True, "reversed": False, "acrossColumns": False,
                      "zero": True, "empty": True, "flags": [None] * 4}


def test_custom_text_generator_and_cache_keys(page):
    result = page.evaluate("""() => {
        Object.assign(grid.options.highlightKeywords, {
            textKey: 'text_', highlightKey: 'mark_',
            textGenerator: (row, column) => row[column].label
        });
        const row = {name: {label: '<b>Model</b> &lt;Flux&gt;'}};
        const matched = grid.highlightKeywordsFilter(row, ['name'], 'model <flux>');
        return {matched, text: row.text_name, highlight: row.mark_name};
    }""")
    assert result == {"matched": True, "text": "Model <Flux>", "highlight": True}


def test_grid_render_search_and_clear_keep_names_readable(page):
    page.evaluate("""() => {
        window.query = 'flux';
        grid.setOption({rowFilter: row => grid.highlightKeywordsFilter(row, ['name'], window.query)});
        grid.setData({columns: [{id: 'name', name: 'Name'}], rows: [
            {name: 'Model &lt;Flux&gt; &lt;img src=x onerror=window.__probe=1&gt;'},
            {name: 'Other Model'}
        ]});
        grid.render();
    }""")
    page.wait_for_function("document.querySelectorAll('#grid mark').length === 1")
    assert page.locator("#grid mark").all_text_contents() == ["Flux"]
    assert page.evaluate("grid.viewRows.length") == 1
    assert page.locator("#grid img").count() == 0
    assert 'Model <Flux> <img src=x onerror=window.__probe=1>' in page.locator("#grid").inner_text()

    page.evaluate("window.query = 'other'; grid.update()")
    page.wait_for_function("document.querySelector('#grid mark')?.textContent === 'Other'")
    assert page.evaluate("grid.viewRows.length") == 1

    page.evaluate("window.query = ''; grid.update()")
    page.wait_for_function("grid.viewRows.length === 2 && !document.querySelector('#grid mark')")
    assert page.locator("#grid img").count() == 0
    assert page.evaluate("window.__probe === undefined")


@pytest.mark.parametrize("filename,column,value,query,nonmatching", [
    ("custom-nodes-manager.js", "title", "Pack &lt;Flux&gt;", "<flux>", "&lt;flux&gt;"),
    ("custom-nodes-manager.js", "description", "Notes &lt;Flux&gt;", "<flux>", "&lt;flux&gt;"),
    ("custom-nodes-manager.js", "author", "Writer &lt;Alias&gt;", "&lt;alias&gt;", "<alias>"),
    ("custom-nodes-manager.js", "author", "Writer <Alias>", "<alias>", "&lt;alias&gt;"),
    ("model-manager.js", "name", "Model &lt;Flux&gt;", "<flux>", "&lt;flux&gt;"),
    ("model-manager.js", "description", "<b>Notes</b> &lt;Flux&gt;", "<flux>", "&lt;flux&gt;"),
    ("model-manager.js", "filename", "model &lt;Flux&gt;", "&lt;flux&gt;", "<flux>"),
    ("model-manager.js", "type", "Type <Flux>", "<flux>", "&lt;flux&gt;"),
])
def test_manager_search_matches_visible_text(page, filename, column, value, query, nonmatching):
    source = (JS / filename).read_text()
    init_body = source.split("\tinitGrid() {", 1)[1].split("\n\t}\n", 1)[0]
    common = (JS / "common.js").read_text()
    sanitizer = common.split("export function sanitizeHTML(str) {", 1)[1].split("\n}", 1)[0]
    escape_cell = "undefined"
    if filename == "model-manager.js":
        escape_cell = source.split("const escapeCell = ", 1)[1].split(";", 1)[0]
    page.evaluate("""({init_body, sanitizer, escape_cell, column, value, query}) => {
        const sanitizeHTML = new Function('str', sanitizer);
        const escapeCell = new Function('sanitizeHTML', `return (${escape_cell})`)(sanitizeHTML);
        const initGrid = new Function('ManagerGrid', 'createFlyover', 'gridId', 'sanitizeHTML', 'escapeCell',
            `return function initGrid() {${init_body}}`)(grid.constructor, () => ({}), 'review', sanitizeHTML, escapeCell);
        const element = document.createElement('div');
        element.innerHTML = '<div id="tested-grid" class="cn-manager-grid cmm-manager-grid" style="width:800px;height:300px"></div>';
        document.body.append(element);
        window.manager = {element, keywords: query, showStatus() {}, handleFlyoverHover() {}, createFlyover: () => ({}), hasAlternatives: () => false};
        initGrid.call(manager);
        manager.grid.setData({columns: [{id: column, name: column}], rows: [{[column]: value}]});
        manager.grid.render();
    }""", {"init_body": init_body, "sanitizer": sanitizer, "escape_cell": escape_cell,
            "column": column, "value": value, "query": query})
    page.wait_for_function("manager.grid.viewRows !== undefined")
    assert page.evaluate("manager.grid.viewRows.length") == 1
    page.evaluate("query => {manager.keywords=query;}", nonmatching)
    assert not page.evaluate("manager.grid.options.rowFilter(manager.grid.data.rows[0])")
