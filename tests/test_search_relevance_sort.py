"""Order of the rows the Custom Nodes Manager shows for a search, on the shipped grid in Chromium.

The search code is lifted from custom-nodes-manager.js and common.js and runs on the shipped
ManagerGrid. Browser cases require Playwright and its Chromium install. All requests are
intercepted locally; no ComfyUI server or external services are used.
"""
import os
from pathlib import Path

import pytest

from js_lift import JsSource, slice_braced, slice_object_entry

JS_DIR = Path(os.environ.get("MANAGER_JS_DIR") or (Path(__file__).resolve().parent.parent / "js"))
JS = JsSource(JS_DIR)
MANAGER = "custom-nodes-manager.js"

OPEN_GRID = """async (rows) => {
    const {default: ManagerGrid} = await import('/manager-grid.js');
    %(leven)s
    %(sanitize_html)s
    %(get_time_ago)s
    const manager = {
        keywords: '',
        filter: '',
        grid: new ManagerGrid(document.getElementById('grid')),
        hasAlternatives() { return false; },
        setDisabled() {},
        %(show_loading)s,
        %(hide_loading)s,
        %(update_grid)s,
        %(on_keywords_change)s,
        %(calculate_sort_score)s,
        setOptions() { const grid = this.grid; %(set_option)s); }
    };
    manager.setOptions();
    rows.forEach((row, index) => { row.id = index + 1; });
    manager.grid.setData({rows, columns: [
        {id: 'id', name: 'ID'}, {id: 'title', name: 'Title'}, {id: 'author', name: 'Author'},
        {id: 'description', name: 'Description'}, {%(nodes_column)s}, {%(stars_column)s}, {%(last_update_column)s}]});
    manager.grid.render();
    window.manager = manager;
}"""


def _open_grid_script():
    source = JS.text(MANAGER)
    return OPEN_GRID % {
        "leven": JS.lift_span("common.js", "const levenArray = [];", "\treturn result;\n}").replace("export ", ""),
        "sanitize_html": JS.lift_declaration("common.js", "export function sanitizeHTML("),
        "get_time_ago": JS.lift_span("common.js", "export function getTimeAgo(dateStr) {", "\n}").replace("export ", ""),
        "show_loading": slice_braced(source, "\tshowLoading() "),
        "hide_loading": slice_braced(source, "\thideLoading() "),
        "update_grid": slice_braced(source, "\tupdateGrid() "),
        "on_keywords_change": JS.lift_span(MANAGER, "\tonKeywordsChange(e) {", "\t\t}, 300);\n\t}"),
        "calculate_sort_score": JS.lift_span(
            MANAGER, "\tcalculateSortScore(rowItem, searchableColumns) {", "\t\treturn 1 / distance;\n\t}"),
        "set_option": slice_braced(source, "grid.setOption("),
        "nodes_column": slice_object_entry(source, 'id: "nodes"'),
        "stars_column": slice_object_entry(source, "id: 'stars'"),
        "last_update_column": slice_object_entry(source, "id: 'last_update'"),
    }


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
def open_grid(browser):
    page = browser.new_page()

    def route(request):
        name = request.request.url.rsplit("/", 1)[-1]
        if name in {"manager-grid.js", "turbogrid.esm.js"}:
            request.fulfill(path=str(JS_DIR / name), content_type="text/javascript")
        elif request.request.url == "http://manager.test/":
            request.fulfill(
                body='<div id="grid" style="width:900px;height:400px"></div>',
                content_type="text/html",
            )
        else:
            request.abort()

    page.route("**/*", route)
    page.goto("http://manager.test/")

    def open_with(rows):
        page.evaluate(_open_grid_script(), rows)
        page.wait_for_function("window.manager.grid.getViewRows().length === %d" % len(rows))
        return page

    yield open_with
    page.close()


def pack(title, stars=500):
    return {"title": title, "author": "author", "description": "nodes", "stars": stars}


def shown(page):
    return page.evaluate("() => manager.grid.getViewRows().map(row => row.title)")


def search(page, keywords):
    page.evaluate("(keywords) => manager.onKeywordsChange({target: {value: keywords}})", keywords)
    page.wait_for_function("(keywords) => manager.keywords === keywords", arg=keywords)
    return shown(page)


def click_header(page, name):
    page.click('.tg-header-item .tg-column-name:text-is("%s")' % name)
    return shown(page)


def sorted_headers(page):
    return page.evaluate("() => [...document.querySelectorAll('.tg-column-sorted')].map(x => x.textContent.trim())")


def loading(page):
    return page.evaluate("() => getComputedStyle(document.querySelector('.tg-loading')).display !== 'none'")


FACE_PACKS = ["Interface Tools", "Unrelated", "FaceTools", "face2video", "Face Detailer", "FACE MASK", "face swap"]
BY_TITLE = ["Face Detailer", "FACE MASK", "face swap", "face2video", "FaceTools", "Interface Tools", "Unrelated"]


def test_a_search_orders_the_rows_by_how_the_keyword_matches(open_grid):
    page = open_grid([pack(title) for title in FACE_PACKS])
    assert search(page, "face") == [
        "face swap", "Face Detailer", "FACE MASK", "face2video", "FaceTools", "Interface Tools"]


@pytest.mark.parametrize("keywords", ["face mask", "face mask tools", "face mask tools set swap"])
def test_the_case_of_every_keyword_weighs_less_than_one_match_inside_a_word(open_grid, keywords):
    # a digit after the keyword is the lightest way of being inside a word
    page = open_grid([pack(keywords + "2"), pack(keywords.upper())])
    assert search(page, keywords) == [keywords.upper(), keywords + "2"]


@pytest.mark.parametrize("stars", [9000, 10000, 16860, 150000])
def test_more_stars_never_lower_a_row(open_grid, stars):
    page = open_grid([pack("Alpha Manager", 120), pack("Beta Manager", stars)])
    assert search(page, "Manager") == ["Beta Manager", "Alpha Manager"]


def test_a_row_without_a_star_count_is_ranked_by_its_text(open_grid):
    no_stars = pack("Interface Tools")
    del no_stars["stars"]
    page = open_grid([no_stars, pack("FaceTools", -1), pack("face swap")])
    assert search(page, "face") == ["face swap", "FaceTools", "Interface Tools"]


def test_rows_that_match_alike_stay_in_the_listed_order_whatever_was_searched_before(open_grid):
    page = open_grid([pack("face alpha"), pack("face beta"), pack("Unrelated")])
    search(page, "beta")
    assert search(page, "face") == ["face alpha", "face beta"]


def test_a_search_replaces_a_header_sort(open_grid):
    page = open_grid([pack(title) for title in FACE_PACKS])
    assert click_header(page, "Title") == BY_TITLE
    assert search(page, "face")[0] == "face swap"
    assert sorted_headers(page) == []


def test_clearing_the_search_brings_back_the_listed_order(open_grid):
    page = open_grid([pack(title) for title in FACE_PACKS])
    search(page, "face")
    assert search(page, "") == FACE_PACKS


def test_clearing_the_search_keeps_a_header_sort_made_during_it(open_grid):
    page = open_grid([pack(title) for title in FACE_PACKS])
    search(page, "face")
    click_header(page, "Title")
    assert search(page, "") == BY_TITLE
    assert sorted_headers(page) == ["Title"]


@pytest.mark.parametrize("header", ["Nodes", "★", "Last Update"])
def test_the_first_click_on_a_header_of_counts_lists_the_highest_first(open_grid, header):
    low = dict(pack("low", 1), nodes=1, last_update="2024-01-01 00:00:00")
    high = dict(pack("high", 9), nodes=9, last_update="2025-01-01 00:00:00")
    page = open_grid([low, high])
    assert click_header(page, header) == ["high", "low"]


def test_the_loading_of_a_search_ends_when_its_rows_are_shown(open_grid):
    page = open_grid([pack(title) for title in FACE_PACKS])
    page.evaluate("() => { manager.showLoading(); manager.hideLoading(); }")
    page.evaluate("() => manager.onKeywordsChange({target: {value: 'face'}})")
    assert loading(page)
    page.wait_for_function("manager.keywords === 'face'")
    assert not loading(page)


def test_a_search_that_is_still_waiting_leaves_the_loading_of_a_reload_on(open_grid):
    page = open_grid([pack(title) for title in FACE_PACKS])
    page.evaluate("() => { manager.onKeywordsChange({target: {value: 'face'}}); manager.showLoading(); }")
    page.wait_for_function("manager.keywords === 'face'")
    assert loading(page)
    page.evaluate("() => manager.hideLoading()")
    assert not loading(page)
