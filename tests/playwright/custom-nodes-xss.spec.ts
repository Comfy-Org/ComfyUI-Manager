/**
 * Browser-level XSS regression suite for the Custom Nodes manager UI.
 *
 * Every row feeds hostile node-pack metadata through a stubbed registry
 * response and asserts the value renders as INERT TEXT: the payload is visible
 * as literal characters, no element is constructed from it, and its `onerror`
 * never runs. The three checks are made together because they fail
 * differently — see `expectInert` in ./helpers.ts.
 *
 * NOT EVERY ROW CLOSES A LIVE HOLE, and the distinction matters when reading a
 * failure. `version`/`cnr_latest`, `author`, `stars` and `last_update` are
 * served unsanitized and sit in always-visible columns, so opening the manager
 * is the whole exploit; so are node names from `/v2/customnode/getmappings`,
 * a route that sanitizes nothing. Those fields are escaped ON THE CLIENT and
 * their rows target that escape.
 *
 * `title` / `name` / `description` are different: `populate_markdown` ->
 * `sanitize_tag` escapes them SERVER-SIDE, and the client renders them as-is
 * on purpose. Escaping them again is not free safety — `sanitizeHTML` also maps
 * `&`, so a second pass turns the server's `&lt;` into `&amp;lt;` and the pack
 * `ComfyUI-<Impact-Pack>` reaches the user as literal `ComfyUI-&lt;Impact-Pack&gt;`.
 * The rows targeting those fields assert the SERVER->CLIENT CHAIN, not an
 * independent client guarantee.
 *
 * CAVEAT: `page.route()` REPLACES the HTTP response, so every fixture here
 * bypasses `populate_markdown`. For the raw fields that is exactly what a live
 * server delivers. For the server-escaped fields it is NOT, so those rows pass
 * their payload through `serverSanitizeTag` first — the real transform, read
 * out of `manager_util.py` — and assert on the wire form the server would
 * actually have emitted.
 *
 * Requires ComfyUI running with --enable-manager-legacy-ui on PORT (see
 * tests/playwright/README.md).
 */

import { test, expect } from '@playwright/test';
import {
  waitForComfyUI,
  openManagerMenu,
  openCustomNodesManager,
  routeNodeList,
  routeMappings,
  routeAlternatives,
  makePack,
  expectInert,
  serverSanitizeTag,
  serverPopulateMarkdown,
  serverInstallDenialRestartClause,
  XSS_PAYLOAD,
  XSS_PAYLOAD_NOSPACE,
} from './helpers';

const GRID = '.cn-manager-grid';
const FLYOVER = '.cn-flyover';

/** Collect page errors so the rows that assert "did not throw" can see them. */
function trackPageErrors(page: import('@playwright/test').Page) {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  return errors;
}

test.describe('grid render sinks', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  test('hostile title renders inert through the server escape', async ({ page }) => {
    // NOT defence-in-depth, and the fixture is what says so. `title` is in the
    // populate_markdown set, so the SERVER escape is the one defence and the
    // client deliberately renders the value as-is — escaping it a second time
    // printed `&lt;` to every user (see the double-escape row below).
    //
    // The fixture is therefore the server's own sanitize_tag OUTPUT, lifted
    // from manager_util.py. A raw payload here would assert the opposite of the
    // design and fail by construction, on a wire form the live server cannot
    // emit; what this row asserts is that the form it DOES emit stays inert
    // once the client renders it.
    await routeNodeList(page, {
      hostile: makePack('hostile', { title: serverSanitizeTag(XSS_PAYLOAD) }),
    });
    await openManagerMenu(page);
    await openCustomNodesManager(page);

    await expectInert(page, GRID, XSS_PAYLOAD, 'img', 'title');
  });

  // This row needs a WIDER VIEWPORT THAN THE REST, so it gets its own describe.
  //
  // turbogrid virtualises columns horizontally: at the config's default
  // viewport the `.cn-pack-stars` and `.cn-pack-last-update` BODY CELLS are
  // not in the DOM at all — a dump returned `stars: []`, `lastUpdate: []`
  // with `rowCount: 4`, while the HEADER showed both columns. The row's
  // `last_update` leg then failed leg 1 (presence) with legs 2 and 3 passing,
  // which is expectInert's own signature for "the payload never rendered",
  // i.e. the row was reporting the viewport, not the sink. Measured: at
  // 2600x1000 both cells render and both are inert. Pin the viewport so this
  // row asserts on the sink it names.
  test.describe('wide viewport — stars/last_update are column-virtualised', () => {
    test.use({ viewport: { width: 2600, height: 1000 } });

    test('hostile version/author/stars/last_update render inert (LIVE no-user-action)', async ({ page }) => {
      // The four fields that carry the no-user-action property: served
      // unsanitized AND in always-visible columns, so opening the manager is
      // the whole exploit.
      await routeNodeList(page, {
        p1: makePack('p1', { version: XSS_PAYLOAD, cnr_latest: XSS_PAYLOAD }),
        p2: makePack('p2', { author: XSS_PAYLOAD }),
        // `stars` must be a NON-number to reach the raw fall-through
        // (`if (typeof stars === 'number') return stars.toLocaleString()`).
        p3: makePack('p3', { stars: XSS_PAYLOAD }),
        // `last_update` is cut at the first space, so the payload must be
        // space-free or the row would pass for the wrong reason.
        p4: makePack('p4', { last_update: XSS_PAYLOAD_NOSPACE }),
      });
      await openManagerMenu(page);
      await openCustomNodesManager(page);

      // PRECONDITION — the two virtualised columns must actually have body
      // cells before their legs mean anything. Without this the row can go
      // pass again the moment a layout change hides them, on a fixture that
      // proved nothing (the same vacuous-pass shape the tags row guards against).
      await expect(
        page.locator(`${GRID} .cn-pack-stars`).first(),
        'precondition: no .cn-pack-stars body cell rendered — the stars column is virtualised away at this viewport, so its leg would pass vacuously.',
      ).toBeVisible({ timeout: 15_000 });
      await expect(
        page.locator(`${GRID} .cn-pack-last-update`).first(),
        'precondition: no .cn-pack-last-update body cell rendered — the last_update column is virtualised away at this viewport, so its leg would pass vacuously.',
      ).toBeVisible({ timeout: 15_000 });

      await expectInert(page, GRID, XSS_PAYLOAD, 'img', 'version/cnr_latest');
      await expectInert(page, GRID, XSS_PAYLOAD, 'img', 'author');
      await expectInert(page, GRID, XSS_PAYLOAD_NOSPACE, 'img', 'last_update');
    });
  });

  test('hostile tags render inert once the alternatives column is shown (LIVE, gated)', async ({ page }) => {
    // The alternatives column is `invisible: !this.hasAlternatives()`, so this
    // row MUST establish the gate. Without the precondition assertion below it
    // passes vacuously against a grid that never rendered the column at all.
    await routeNodeList(page, { alt1: makePack('alt1') });
    await routeAlternatives(page, {
      alt1: {
        id: 'alt1',
        title: 'alt1',
        description: 'alternative description',
        tags: XSS_PAYLOAD,
      },
    });
    await openManagerMenu(page);
    await openCustomNodesManager(page);

    // ESTABLISH THE GATE. `hasAlternatives()` is `this.filter ===
    // ShowMode.ALTERNATIVES`, so the column exists ONLY while the filter
    // dropdown is on "Alternatives of A1111" — selecting it is also what
    // triggers getAlternatives() and therefore the `:1903` tag loop. Without
    // this step the fixture is never fetched, nothing renders, and the row
    // would report a failure that has nothing to do with the sink.
    const filterSelect = page.locator('select.cn-manager-filter').first();
    await expect(filterSelect).toBeVisible({ timeout: 10_000 });
    await filterSelect.selectOption({ label: 'Alternatives of A1111' });

    // PRECONDITION — assert on `.cn-tag-list` SPECIFICALLY, the div the tag
    // loop emits. An earlier draft accepted `.cn-pack-desc` too, which the
    // description column also carries: it matched, the row failed on a
    // different leg, and it looked like a reproduction. That is the vacuous
    // vacuous pass this row has to guard against, arriving as a vacuous
    // FAILURE instead.
    await expect(
      page.locator(`${GRID} .cn-tag-list`).first(),
      'precondition: no .cn-tag-list rendered, so the alternatives tag sink was never exercised — the row proves nothing about the sink.',
    ).toBeVisible({ timeout: 15_000 });

    await expectInert(page, GRID, XSS_PAYLOAD, 'img', 'tags');
  });

  test('a server-escaped title renders decoded (no double-escape)', async ({ page }) => {
    // THE REGRESSION GUARD FOR THE DOUBLE-ESCAPE FIX, and it only guards
    // anything because the fixture is the WIRE form.
    //
    // The earlier shape of this row fed the RAW authored title straight to the
    // grid. That is input the live server cannot deliver — getlist runs every
    // pack through populate_markdown -> sanitize_tag first — and the row passed
    // either way: escaped once, `<3` comes back as `<3`; not escaped at
    // all, `<3` is not a tag start so it renders as text too. It asserted
    // nothing about the chain it was named for.
    //
    // Now the fixture is the OUTPUT of the server's own sanitize_tag, read out
    // of manager_util.py at run time (serverSanitizeTag) rather than re-typed,
    // so what enters the client is exactly what the server would have emitted:
    // wire form in, authored text out. A client that escapes the field a second
    // time prints the entity and BOTH legs below flip.
    //
    // page.route still carries it: the escaped fields originate in third-party
    // registry data (no live pack title contains an angle bracket), so this is
    // the only deterministic way to place a known value in the grid. What
    // page.route replaces is the TRANSPORT — the transform is the real one.
    const AUTHORED = 'Tom & Jerry <3';
    const ON_THE_WIRE = serverSanitizeTag(AUTHORED);
    expect(
      ON_THE_WIRE,
      'serverSanitizeTag returned its input unchanged, so the fixture is NOT the ' +
      'wire form and this row is back to proving nothing. Check that sanitize_tag ' +
      'in comfyui_manager/common/manager_util.py still escapes < and >.',
    ).not.toBe(AUTHORED);

    await routeNodeList(page, { legit: makePack('legit', { title: ON_THE_WIRE }) });
    await openManagerMenu(page);
    await openCustomNodesManager(page);

    const text = (await page.locator(GRID).first().textContent()) ?? '';
    const diagnostic =
      `authored: ${JSON.stringify(AUTHORED)}\n` +
      `on the wire (server sanitize_tag output): ${JSON.stringify(ON_THE_WIRE)}\n` +
      `grid text (first 300 chars): ${JSON.stringify(text.slice(0, 300))}`;

    expect(
      text,
      `the server-escaped title did not render as the author wrote it. The client ` +
      `escaped an ALREADY-escaped value, so sanitizeHTML mapped the server's & to ` +
      `&amp; and the entity reached the user as literal text.\n${diagnostic}`,
    ).toContain(AUTHORED);
    expect(
      text,
      `the wire form is visible in the grid as literal text — that IS the ` +
      `double-escape. A field in the populate_markdown set (title/name/description) ` +
      `must reach innerHTML AS-IS.\n${diagnostic}`,
    ).not.toContain(ON_THE_WIRE);
  });

  test('missing title/version/author renders without throwing', async ({ page }) => {
    // Expected to PASS — `sanitizeHTML(undefined)` raises TypeError inside a
    // render path, so the escape MUST be sanitizeHTML(String(v)).
    // This row is what turns that mistake into a visible failure.
    const errors = trackPageErrors(page);
    const bare = makePack('bare');
    delete (bare as Record<string, unknown>).title;
    delete (bare as Record<string, unknown>).version;
    delete (bare as Record<string, unknown>).author;
    await routeNodeList(page, { bare });
    await openManagerMenu(page);
    await openCustomNodesManager(page);

    await expect(page.locator(GRID).first()).toBeVisible();
    expect(
      errors,
      `the grid threw while rendering a row with absent title/version/author — sanitizeHTML(undefined) raises TypeError, so the escape must pass String(v). pageerrors: ${errors.join(' | ')}`,
    ).toEqual([]);
  });

  test('composed-HTML description keeps rendering as markup (anti-regression)', async ({ page }) => {
    // MANDATORY anti-regression. `description` is SERVER-COMPOSED HTML; the
    // cheapest way to pass every other row here is to blind-escape the grid,
    // which would print literal <a href=...> / <B> to every user. This row
    // guards the ESCAPING, not the defect — it is expected to pass both before
    // and after, and must never be forced to fail.
    const composed = serverPopulateMarkdown({ description: 'See [a/the docs](https://example.com/x) for **details**' }).description;
    await routeNodeList(page, { doc: makePack('doc', { description: composed }) });
    await openManagerMenu(page);
    await openCustomNodesManager(page);

    const anchors = await page.locator(`${GRID} a[href="https://example.com/x"]`).count();
    expect(
      anchors,
      'the composed-HTML description no longer renders as markup — a working <a href> is gone, so the description column was blind-escaped. That is a regression, not a fix.',
    ).toBeGreaterThan(0);

    const bold = await page.locator(`${GRID} b, ${GRID} B`).count();
    expect(
      bold,
      'the composed-HTML description lost its <B> markup — the column was escaped wholesale.',
    ).toBeGreaterThan(0);
  });
});

test.describe('URL / scheme sink', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  test('the title link href carries no javascript: scheme (LIVE, click-gated)', async ({ page }) => {
    // `link.href = <registry URL>` with no scheme allow-list. This is the
    // client-side twin of the server composer's scheme-trust hole.
    //
    // Asserted on the href PROPERTY, not on rendered text: the
    // rendered label is the pack title and would look perfectly innocent while
    // the anchor still carries a javascript: target.
    await routeNodeList(page, {
      evil: makePack('evil', {
        repository: 'javascript:window.__xss_fired=1',
        reference: 'javascript:window.__xss_fired=1',
      }),
    });
    await openManagerMenu(page);
    await openCustomNodesManager(page);

    const hrefs = await page.locator(`${GRID} a`).evaluateAll(
      (els) => els.map((e) => (e as HTMLAnchorElement).href),
    );

    // PRECONDITION — the row asserts that no anchor carries a bad scheme, and
    // a grid with NO anchors satisfies that having tested nothing. Pin that at
    // least one anchor rendered before reading anything into the result below.
    expect(
      hrefs.length,
      `precondition: the grid rendered no anchors at all, so the href assertion below would pass over an empty list and prove nothing about the URL sink. Observed ${hrefs.length} anchors.`,
    ).toBeGreaterThan(0);

    // ASSERTED AGAINST THE ALLOW-LIST, not against a list of dangerous schemes.
    const allowed = ['http:', 'https:'];
    const offending = hrefs.filter((h) => {
      const scheme = new URL(h).protocol;
      return scheme !== null && !allowed.includes(scheme);
    });
    expect(
      offending,
      `the title link's href PROPERTY carries a scheme outside the allow-list — a ` +
      `registry-controlled URL reached href unfiltered, so one click executes it. ` +
      `sanitizeUrl admits ${JSON.stringify(allowed)}; observed anchors: ` +
      `${JSON.stringify(hrefs.slice(0, 10))}`,
    ).toEqual([]);
  });
});

test.describe('flyover sinks', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  /** Open the node flyover by clicking the Nodes cell of the first row.
   *
   *  Targets `.cn-pack-nodes` specifically — that div is emitted ONLY by the
   *  `nodes` column formatter, and only when `rowItem.nodes` is truthy. The
   *  grid's onClick handler routes to `showNodes` on `columnItem.id ===
   *  "nodes"`, so any looser selector (e.g. "a cell containing a digit") lands
   *  on the ID column, silently never opens the flyover, and turns the row
   *  into a timeout that LOOKS like a failed assertion. Waiting for this
   *  element first therefore doubles as a precondition that the getmappings
   *  fixture actually produced a node count. */
  async function openFlyover(page: import('@playwright/test').Page) {
    const nodesCell = page.locator(`${GRID} .cn-pack-nodes`).first();
    await expect(
      nodesCell,
      'flyover precondition: no .cn-pack-nodes cell rendered, so the getmappings fixture did not attach a node count to the pack — the flyover cannot open and the row would time out for a fixture reason, not a defect.',
    ).toBeVisible({ timeout: 15_000 });
    await nodesCell.click();
    await page.waitForSelector(FLYOVER, { state: 'visible', timeout: 10_000 });
  }

  test('flyover pack title renders inert through the server escape', async ({ page }) => {
    // Same contract as the grid title row: `title` is server-escaped, the
    // client renders it as-is, so the fixture must be the WIRE form.
    await routeNodeList(page, { h: makePack('h', { title: serverSanitizeTag(XSS_PAYLOAD) }) });
    await routeMappings(page, {
      'https://github.com/example/h': [['NodeA'], { title_aux: 'h' }],
    });
    await openManagerMenu(page);
    await openCustomNodesManager(page);
    await openFlyover(page);

    await expectInert(page, FLYOVER, XSS_PAYLOAD, 'img', 'flyover title');
  });

  test('flyover node NAME renders inert (LIVE, click-gated)', async ({ page }) => {
    // `/v2/customnode/getmappings` performs NO sanitization —
    // `populate_markdown` is never called on that route — so
    // this node name is genuinely RAW, not defence-in-depth.
    await routeNodeList(page, { h: makePack('h') });
    await routeMappings(page, {
      'https://github.com/example/h': [[XSS_PAYLOAD], { title_aux: 'h' }],
    });
    await openManagerMenu(page);
    await openCustomNodesManager(page);
    await openFlyover(page);

    await expectInert(page, FLYOVER, XSS_PAYLOAD, 'img', 'flyover node name');
  });
});

// ===========================================================================
// selection bar
// ===========================================================================

test.describe('selection bar', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  for (const state of ['not-a-known-install-group', 'constructor', '__proto__']) {
    test(`an unrecognised pack state still renders the selection bar: ${state}`, async ({ page }) => {
      const errors = trackPageErrors(page);
      await routeNodeList(page, { odd: makePack('odd', { state }) });
      await openManagerMenu(page);
      await openCustomNodesManager(page);

      const checkbox = page.locator(`${GRID} .tg-body .tg-row .tg-checkbox`).first();
      await expect(checkbox).toBeVisible({ timeout: 15_000 });
      await checkbox.click();

      const bar = page.locator('.cn-manager-selection').first();
      await expect(bar).toContainText('Selected');
      await expect(bar).toContainText(state);
      await expect(bar.locator('button')).toHaveCount(0);
      expect(errors).toEqual([]);
    });
  }
});

// ===========================================================================
// Install status uses the same server-composed names as the grid.
// ===========================================================================

test.describe('install status sink', () => {
  for (const [source, visible] of [
    [XSS_PAYLOAD, XSS_PAYLOAD],
    ['Pack &amp; Friends <Flux>', 'Pack & Friends <Flux>'],
    ['Pack &amp;lt;Flux&amp;gt;', 'Pack &lt;Flux&gt;'],
  ]) {
    test(`server title remains readable and inert: ${source}`, async ({ page }) => {
      await page.goto('/');
      await waitForComfyUI(page);
      await routeNodeList(page, { victim: makePack('victim', {
        title: serverSanitizeTag(source), version: 'unknown',
      }) });
      await page.route('**/v2/manager/queue/batch', route => route.fulfill({
        status: 200, contentType: 'application/json', body: '{"failed": []}',
      }));
      await openManagerMenu(page);
      await openCustomNodesManager(page);
      await page.locator(`${GRID} .cn-btn-install`).first().click();
      await expectInert(page, '.cn-manager-status', visible, 'img', 'install title');
      const status = page.locator('.cn-manager-status');
      await expect(status).toContainText(visible);
    });
  }
});

// ===========================================================================
// batch error dialog
// ===========================================================================

test.describe('batch error dialog', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  test('server-authored batch failure text renders inert (LIVE)', async ({ page }) => {
    // REAL CONSUMPTION PATH, not a synthetic fixture. The chain exercised here
    // is the production one end to end on the client side:
    //   real Install click -> real POST /v2/manager/queue/batch
    //   -> real `cm-queue-status` batch-done event on ComfyUI's api
    //   -> real onQueueStatus -> onQueueCompleted -> errorMsg += v (:1604)
    //   -> real showError (:1613) -> showMessage -> .cn-manager-message
    //      .innerHTML (:2091)
    // Only the SERVER's two responses are stubbed, which is exactly what
    // Tier A is for — the attacker-controlled value enters at `result[hash]`,
    // the same slot a real queue result fills.
    let capturedBatchId = '';
    await page.route('**/v2/manager/queue/batch', async (route) => {
      capturedBatchId = route.request().postDataJSON()?.batch_id ?? '';
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"failed": []}' });
    });
    // `version: 'unknown'` is load-bearing, not filler. The grid click handler
    // routes install through a VERSION SELECTOR dialog when
    // `item.originalData.version != 'unknown'` (:555), and the batch POST only
    // happens after a version is chosen. The unknown-version shape takes the
    // direct `installNodes` path (:559), which is the same branch the Python
    // e2e rows drive, and keeps this test on the error-render path it is about
    // instead of on version-picker UI.
    await routeNodeList(page, {
      victim: makePack('victim', { state: 'not-installed', version: 'unknown' }),
    });

    await openManagerMenu(page);
    await openCustomNodesManager(page);

    const installBtn = page.locator(`${GRID} .cn-btn-install`).first();
    await expect(
      installBtn,
      'precondition: no .cn-btn-install rendered, so the batch flow was never entered and install_context/batch_id were never set — the queue event would be dropped by onQueueCompleted and the row would prove nothing.',
    ).toBeVisible({ timeout: 15_000 });
    await installBtn.click();

    // CAPTURE THE SINK'S WRITES, because the settled element cannot be read.
    //
    // onQueueCompleted writes the error into .cn-manager-message via
    // showError (:1613) and then OVERWRITES the same element with the restart
    // notice via showMessage (:1620) — inside ONE synchronous handler. So by
    // the time any assertion runs, the element holds "To apply the
    // installed/updated... restart ComfyUI", and the value under test is
    // gone. A MutationObserver does not help: its callback is a microtask and
    // both writes land before it runs (measured — it reports only the final
    // state). Wrapping the innerHTML SETTER records each write at the moment
    // it happens, which is the only way to assert on what the sink actually
    // received. Installed here rather than via addInitScript because the
    // writes under test all happen after this point.
    await page.evaluate(() => {
      const w = window as unknown as Record<string, any>;
      w.__cnMessageWrites = [];
      const desc = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML')!;
      Object.defineProperty(Element.prototype, 'innerHTML', {
        configurable: true,
        get() {
          return desc.get!.call(this);
        },
        set(value) {
          try {
            if ((this as Element).classList?.contains('cn-manager-message')) {
              w.__cnMessageWrites.push(String(value));
            }
          } catch {
            /* never let the probe break the page under test */
          }
          desc.set!.call(this, value);
        },
      });
    });

    await expect
      .poll(() => capturedBatchId, {
        timeout: 15_000,
        message: 'precondition: the client never POSTed /v2/manager/queue/batch, so no batch_id exists to address the completion event to.',
      })
      .not.toBe('');

    // Deliver the completion event exactly as the server does over the socket.
    await page.evaluate(
      ({ batchId, payload }) => {
        const api = (window as unknown as Record<string, any>).comfyAPI.api.api;
        api.dispatchEvent(
          new CustomEvent('cm-queue-status', {
            detail: { status: 'batch-done', batch_id: batchId, nodepack_result: [payload] },
          }),
        );
      },
      { batchId: capturedBatchId, payload: XSS_PAYLOAD },
    );

    // The write carrying the payload must arrive, and arrive inert. The three
    // legs are the same ones expectInert applies, evaluated against the value
    // the sink RECEIVED rather than against the element's settled content:
    //   leg 1 presence  — the payload is there as literal text;
    //   leg 2 structure — parsing that write constructs no <img>;
    //   leg 3 execution — window.__xss_fired never set (document-wide).
    const sink = await page.evaluate((payload) => {
      const w = window as unknown as Record<string, any>;
      const writes: string[] = w.__cnMessageWrites ?? [];
      // Parse each write the way the browser did, in a detached element.
      const probe = document.createElement('div');
      const parsed = writes.map((html) => {
        probe.innerHTML = html;
        return { html, text: probe.textContent ?? '', imgs: probe.querySelectorAll('img').length };
      });
      return {
        writes,
        carrying: parsed.filter((p) => p.text.includes(payload)),
        imgsAnywhere: parsed.reduce((n, p) => n + p.imgs, 0),
        firedGlobal: w.__xss_fired,
        liveImgs: document.querySelectorAll('img[src="x"]').length,
      };
    }, XSS_PAYLOAD);

    const diagnostic =
      `queue failure text — writes observed at .cn-manager-message: ${JSON.stringify(sink.writes)}`;

    expect(
      sink.carrying.length,
      `precondition: no write to .cn-manager-message carried the payload at all, so the sink was never exercised and the row proves nothing — check that onQueueCompleted reached showError. ${diagnostic}`,
    ).toBeGreaterThan(0);
    expect(
      sink.imgsAnywhere,
      `a write to .cn-manager-message parsed into a live <img> — the server-authored queue text reached innerHTML AS MARKUP. ${diagnostic}`,
    ).toBe(0);
    expect(
      sink.liveImgs,
      `an <img src=x> from the payload is live in the document. ${diagnostic}`,
    ).toBe(0);
    expect(
      sink.firedGlobal,
      `the payload EXECUTED (window.__xss_fired is set). ${diagnostic}`,
    ).toBeUndefined();
  });
});

// ===========================================================================
// client-side 403 denial text
// ===========================================================================

// The selectors below are load-bearing and were arrived at the hard way.
// `.p-dialog input` matches the Custom Nodes SEARCH box
// (`.cn-manager-keywords`, in `.p-dialog-header`) before it matches the prompt
// field, so a `.first()` on it silently types the URL into the search box:
// install_via_git_url is never called, the denial modal never renders, and the
// row fails as though the client produced nothing. Targeting
// `.prompt-dialog-content input` hits the prompt on the first attempt.
//
// The general lesson: a selector that matches SOMETHING makes a broken fixture
// look like a product failure, and only checking WHAT it matched tells the two
// apart.
test.describe('403 denial text', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
    await routeNodeList(page, { p: makePack('p') });
  });

  /** Drive the REAL "Install via Git URL" entry point: footer button ->
   *  customPrompt (ComfyUI's PrimeVue dialog) -> install_via_git_url ->
   *  the 403 arm at common.js:254. */
  async function installViaGitUrl(page: import('@playwright/test').Page, url: string) {
    // The REAL entry point, driven exactly as a user does it: footer button ->
    // customPrompt (common.js:149 -> app.extensionManager.dialog.prompt) ->
    // install_via_git_url -> the 403 arm at common.js:254.
    //
    // `.prompt-dialog-content input` is the load-bearing selector. A broader
    // `.p-dialog input` matches the Custom Nodes SEARCH box first, which is
    // silent: the URL lands in the search field, no request is made, and the
    // row fails at the denial assertion as though the client rendered nothing.
    await page.locator('.cn-manager-install-url').first().click();
    const input = page.locator('.prompt-dialog-content input').first();
    await expect(
      input,
      'precondition: the customPrompt dialog never rendered its input, so install_via_git_url was never called and the 403 arm was never reached — the row would prove nothing.',
    ).toBeVisible({ timeout: 10_000 });
    await input.fill(url);
    await input.press('Enter');
  }

  /** The denial modal is `app.ui.dialog.element` (`show_message` ->
   *  `app.ui.dialog.show`, common.js:98). Several `.comfy-modal` nodes exist,
   *  so filter by the denial copy rather than taking `.first()`. */
  function denialDialog(page: import('@playwright/test').Page) {
    return page.locator('.comfy-modal').filter({ hasText: /config\.ini/ }).first();
  }

  const MALFORMED = [
    { label: 'empty body', body: '' },
    { label: 'non-JSON', body: 'not json' },
    { label: 'JSON null', body: 'null' },
    { label: 'JSON array', body: '[]' },
    { label: 'reason is a number', body: '{"reason": 42}' },
    { label: 'unknown reason code', body: '{"reason": "unknown_flag"}' },
  ];

  for (const variant of MALFORMED) {
    test(`403 with ${variant.label} falls back without throwing`, async ({ page }) => {
      // The client PARSES the 403 body to learn which condition failed, and
      // `res.json()` resolves for far more than an object: `null`, `[]`,
      // `"str"` and `3` all parse cleanly. `null.reason` would throw inside the
      // render path, while `[].reason` and `{"reason":42}` yield `undefined`
      // and would put the literal string "undefined" in front of the user.
      // `install_denial_message` guards each of those shapes and falls back to
      // the calling endpoint's own condition; this row is what holds that
      // guard in place, one variant per malformed shape.
      const errors: string[] = [];
      page.on('pageerror', (e) => errors.push(String(e)));

      await page.route('**/v2/customnode/install/git_url', async (route) => {
        await route.fulfill({ status: 403, contentType: 'application/json', body: variant.body });
      });

      await openManagerMenu(page);
      await openCustomNodesManager(page);
      await installViaGitUrl(page, 'https://github.com/example/pack');

      const dialog = denialDialog(page);
      await expect(
        dialog,
        `${variant.label}: the denial dialog did not render its fallback text. A 403 whose body cannot be interpreted is STILL a denial and must still be explained.`,
      ).toBeVisible({ timeout: 10_000 });

      const text = (await dialog.textContent()) ?? '';
      expect(
        text,
        `${variant.label}: the rendered denial text contains the literal string "undefined" — a malformed body leaked through the reason lookup. text: ${text.slice(0, 300)}`,
      ).not.toContain('undefined');
      expect(
        errors,
        `${variant.label}: the 403 handler threw. pageerrors: ${errors.join(' | ')}`,
      ).toEqual([]);
    });
  }

  test('the denial text is SELECTED BY the server reason code', async ({ page }) => {
    // CROSS-WIRED ON PURPOSE. Each install arm has its own denial text, so a
    // per-endpoint check cannot tell a server-DERIVED selection from a
    // hand-maintained constant that happens to match the endpoint it sits on.
    // Answering the git_url endpoint with the PIP reason code separates them:
    // a client that reads the server's reason names allow_pip_install, and a
    // client that prints a per-call-site literal names the other flag no
    // matter what the server said. That drift is what this row catches.
    await page.route('**/v2/customnode/install/git_url', async (route) => {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ reason: 'allow_pip_install' }),
      });
    });

    await openManagerMenu(page);
    await openCustomNodesManager(page);
    await installViaGitUrl(page, 'https://github.com/example/pack');

    const dialog = denialDialog(page);
    await expect(dialog).toBeVisible({ timeout: 10_000 });
    const text = (await dialog.textContent()) ?? '';

    expect(
      text,
      `the server said reason="allow_pip_install" and the client must name THAT condition. Observed text names the other flag, i.e. the message is a hand-maintained constant per call site rather than being selected from the server's reason code. text: ${text.slice(0, 400)}`,
    ).toContain('allow_pip_install');
  });

  test('the denial text states the SERVER\'s restart requirement', async ({ page }) => {
    // THE STANDING GUARD FOR A HAND-MAINTAINED COPY. Only the reason CODE is
    // derived from the server; the wording lives in js/common.js, and nothing
    // makes the two move together. They had already come apart: the server
    // constants say the flag and network_mode are read once at STARTUP, so a
    // user who edits config.ini and retries is denied identically — and the
    // client text omitted it, leaving that user with a correct edit and no hint
    // that a restart is what is missing.
    //
    // The expected sentence is READ OUT of the server constants
    // (serverInstallDenialRestartClause), not typed here, so this row cannot
    // become a third copy that drifts on its own. Reword the server and the
    // client must follow; drop it from the server and this row says so.
    const restartClause = serverInstallDenialRestartClause();

    await page.route('**/v2/customnode/install/git_url', async (route) => {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ reason: 'allow_git_url_install' }),
      });
    });

    await openManagerMenu(page);
    await openCustomNodesManager(page);
    await installViaGitUrl(page, 'https://github.com/example/pack');

    const dialog = denialDialog(page);
    await expect(dialog).toBeVisible({ timeout: 10_000 });
    const text = (await dialog.textContent()) ?? '';

    expect(
      text,
      `the client denial text does not state the restart requirement the SERVER states. ` +
      `A user who edits config.ini and retries is denied identically, with nothing in ` +
      `the UI saying a restart is what is missing.\n` +
      `expected (from SECURITY_MESSAGE_FLAG_*): ${JSON.stringify(restartClause)}\n` +
      `observed dialog text: ${JSON.stringify(text.slice(0, 600))}`,
    ).toContain(restartClause);
  });
});

// ===========================================================================
// search-keyword highlight — the grid re-renders matched cells from
// textContent, which would undo the formatter escaping unless the bundle
// escapes every slice it splices (see tests/test_grid_highlight_escaping.py)
// ===========================================================================

test.describe('keyword highlight re-render', () => {
  test.use({ viewport: { width: 2600, height: 1000 } });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  test('a keyword matching inside an escaped raw field stays inert after highlight', async ({ page }) => {
    // The keyword must match VISIBLE text: the match cache decodes markup-
    // shaped values to their text, and a bare <img> has none.
    const payload = XSS_PAYLOAD + 'PWN_author';
    await routeNodeList(page, { p: makePack('p', { author: payload }) });
    await openManagerMenu(page);
    await openCustomNodesManager(page);

    const search = page.locator('.cn-manager-keywords').first();
    await expect(search, 'precondition: search box not rendered').toBeVisible();
    await search.fill('PWN');

    // PRECONDITION: the highlighter actually ran on the payload cell.
    await expect(
      page.locator(`${GRID} .cn-pack-author mark`).first(),
      'precondition: no highlight marker rendered in the author cell, so the re-render path was never exercised',
    ).toBeVisible({ timeout: 10_000 });

    await expectInert(page, GRID, payload, 'img', 'author after keyword highlight');
  });
});
