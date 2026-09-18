/**
 * Browser-level XSS regression suite for the Model Manager UI.
 *
 * Same contract as custom-nodes-xss.spec.ts: `name` / `description` are
 * escaped by the server (populate_markdown) and rendered as-is; every other
 * model-list field is raw and must be escaped on the client. Rows assert the
 * payload is visible as literal text, constructs no element, and never runs.
 *
 * Requires ComfyUI running with --enable-manager-legacy-ui on PORT.
 */

import { test, expect } from '@playwright/test';
import {
  waitForComfyUI,
  openManagerMenu,
  openModelManager,
  routeModelList,
  makeModel,
  expectInert,
  serverSanitizeTag,
  XSS_PAYLOAD,
} from './helpers';

const DIALOG = '#cmm-manager-dialog';
const GRID = '.cmm-manager-grid';

function trackPageErrors(page: import('@playwright/test').Page) {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  return errors;
}

/** Records every innerHTML write to elements carrying `className`. */
async function captureInnerHTMLWrites(page: import('@playwright/test').Page, className: string, slot: string) {
  await page.evaluate(({ className, slot }) => {
    const w = window as unknown as Record<string, any>;
    w[slot] = [];
    const desc = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML')!;
    Object.defineProperty(Element.prototype, 'innerHTML', {
      configurable: true,
      get() { return desc.get!.call(this); },
      set(value) {
        try {
          if ((this as Element).classList?.contains(className)) w[slot].push(String(value));
        } catch { /* never break the page under test */ }
        desc.set!.call(this, value);
      },
    });
  }, { className, slot });
}

async function analyseWrites(page: import('@playwright/test').Page, slot: string, payload: string) {
  return page.evaluate(({ slot, payload }) => {
    const w = window as unknown as Record<string, any>;
    const writes: string[] = w[slot] ?? [];
    const probe = document.createElement('div');
    const parsed = writes.map((html) => {
      probe.innerHTML = html;
      return { text: probe.textContent ?? '', imgs: probe.querySelectorAll('img').length };
    });
    return {
      writes,
      carrying: parsed.filter((p) => p.text.includes(payload)).length,
      imgs: parsed.reduce((n, p) => n + p.imgs, 0),
      fired: w.__xss_fired,
      liveImgs: document.querySelectorAll('img[src="x"]').length,
    };
  }, { slot, payload });
}

test.describe('model grid render sinks', () => {
  // Columns are virtualised horizontally; pin a wide viewport so every body
  // cell this suite asserts on is actually in the DOM.
  test.use({ viewport: { width: 2600, height: 1000 } });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  test('hostile raw fields render inert (LIVE no-user-action)', async ({ page }) => {
    await routeModelList(page, [
      makeModel('m1', { type: XSS_PAYLOAD, base: XSS_PAYLOAD }),
      makeModel('m2', { save_path: XSS_PAYLOAD, filename: XSS_PAYLOAD }),
      // a non-parsable size falls through to the raw branch of the formatter
      makeModel('m3', { size: XSS_PAYLOAD }),
    ]);
    await openManagerMenu(page);
    await openModelManager(page);

    // The dialog covers the grid AND the type/base filter dropdowns, which are
    // built from the same raw values.
    await expectInert(page, DIALOG, XSS_PAYLOAD, 'img', 'type/base/save_path/filename/size');
  });

  test('a server-escaped name renders decoded (no double-escape)', async ({ page }) => {
    const AUTHORED = 'Tom & Jerry <3';
    const ON_THE_WIRE = serverSanitizeTag(AUTHORED);
    expect(ON_THE_WIRE).not.toBe(AUTHORED);
    // makeModel derives filename/reference/url/description from the name;
    // those are RAW columns and would carry the wire form literally, so give
    // them values that do not contain the name.
    await routeModelList(page, [makeModel(ON_THE_WIRE, {
      filename: 'legit.safetensors', reference: 'https://example.com/legit',
      url: 'https://example.com/legit.safetensors', description: 'a legit model',
    })]);
    await openManagerMenu(page);
    await openModelManager(page);

    const text = (await page.locator(GRID).first().textContent()) ?? '';
    expect(text, 'the server-escaped name was escaped a second time').toContain(AUTHORED);
    expect(text, 'the wire form is visible as literal text').not.toContain(ON_THE_WIRE);
  });

  test('missing raw fields render without throwing', async ({ page }) => {
    const errors = trackPageErrors(page);
    const bare = makeModel('bare') as Record<string, unknown>;
    delete bare.type; delete bare.base; delete bare.save_path; delete bare.filename; delete bare.size; delete bare.reference;
    await routeModelList(page, [bare]);
    await openManagerMenu(page);
    await openModelManager(page);
    await expect(page.locator(GRID).first()).toBeVisible();
    expect(errors, `pageerrors: ${errors.join(' | ')}`).toEqual([]);
  });
});

test.describe('model URL sinks', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  test('name and download links carry no scheme outside the allow-list', async ({ page }) => {
    await routeModelList(page, [
      makeModel('evil', {
        reference: 'javascript:window.__xss_fired=1',
        url: 'javascript:window.__xss_fired=1',
      }),
      // an unquoted href used to let a space inject attributes
      makeModel('inject', { reference: 'https://example.com/x onmouseover=window.__xss_fired=1' }),
      // a quoted href must not be closed early by a quote inside a URL that
      // still parses as https (sanitizeUrl keeps the raw string)
      makeModel('quote', { reference: 'https://example.com/x" onmouseover="window.__xss_fired=1' }),
      makeModel('quote2', { url: 'https://example.com/y" onmouseover="window.__xss_fired=1' }),
    ]);
    await openManagerMenu(page);
    await openModelManager(page);

    const anchors = await page.locator(`${GRID} a`).evaluateAll((els) =>
      els.map((e) => ({ href: (e as HTMLAnchorElement).href, attrs: e.getAttributeNames() })),
    );
    expect(anchors.length, 'precondition: no anchors rendered').toBeGreaterThan(0);

    const allowed = ['http:', 'https:'];
    const offending = anchors.filter((a) => {
      const s = new URL(a.href).protocol;
      return s !== null && !allowed.includes(s);
    });
    expect(offending, `anchor href carries a scheme outside ${JSON.stringify(allowed)}`).toEqual([]);

    const injected = anchors.filter((a) => a.attrs.some((n) => n.startsWith('on')));
    expect(injected, 'an anchor gained an event-handler attribute from the URL').toEqual([]);
    // hover the rows so an injected onmouseover would fire if present
    for (const row of await page.locator(`${GRID} .tg-body .tg-row`).all()) {
      await row.hover();
    }
    const fired = await page.evaluate(() => (window as unknown as Record<string, unknown>).__xss_fired);
    expect(fired, 'a handler injected through a URL EXECUTED').toBeUndefined();
  });
});

test.describe('model status and error sinks', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  test('install status and batch failure text render inert', async ({ page }) => {
    const onTheWire = serverSanitizeTag(XSS_PAYLOAD);
    expect(onTheWire).not.toBe(XSS_PAYLOAD);
    await routeModelList(page, [makeModel(onTheWire)]);
    await page.route('**/v2/manager/queue/batch', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"failed": []}' });
    });
    await openManagerMenu(page);
    await openModelManager(page);

    await captureInnerHTMLWrites(page, 'cmm-manager-status', '__cmmStatusWrites');
    await captureInnerHTMLWrites(page, 'cmm-manager-message', '__cmmMessageWrites');

    const installBtn = page.locator(`${GRID} .cmm-btn-install`).first();
    await expect(installBtn, 'precondition: no install button rendered').toBeVisible({ timeout: 15_000 });
    await installBtn.click();

    // Status line preserves the server-composed name.
    const status = await analyseWrites(page, '__cmmStatusWrites', XSS_PAYLOAD);
    expect(status.writes.length, 'precondition: nothing written to the status line').toBeGreaterThan(0);
    expect(status.imgs, `status write parsed into <img>: ${JSON.stringify(status.writes)}`).toBe(0);
    expect(status.carrying, 'status line does not carry the name as literal text').toBeGreaterThan(0);

    // Batch completion: server-authored failure text reaches the message sink.
    await page.evaluate((payload) => {
      const api = (window as unknown as Record<string, any>).comfyAPI.api.api;
      api.dispatchEvent(new CustomEvent('cm-queue-status', {
        detail: { status: 'batch-done', model_result: { x: payload }, done_count: 1, total_count: 1 },
      }));
    }, XSS_PAYLOAD);

    const message = await analyseWrites(page, '__cmmMessageWrites', XSS_PAYLOAD);
    expect(message.carrying, `precondition: no message write carried the payload: ${JSON.stringify(message.writes)}`).toBeGreaterThan(0);
    expect(message.imgs, `message write parsed into <img>: ${JSON.stringify(message.writes)}`).toBe(0);
    expect(message.liveImgs, 'an <img src=x> from the payload is live').toBe(0);
    expect(message.fired, 'the payload EXECUTED').toBeUndefined();
  });
});

test.describe('model keyword highlight re-render', () => {
  test.use({ viewport: { width: 2600, height: 1000 } });

  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  test('a keyword matching inside an escaped raw field stays inert after highlight', async ({ page }) => {
    // The keyword must match VISIBLE text (see the custom-nodes row).
    const payload = XSS_PAYLOAD + 'PWN_type';
    await routeModelList(page, [makeModel('m', { type: payload })]);
    await openManagerMenu(page);
    await openModelManager(page);

    const search = page.locator('.cmm-manager-keywords').first();
    await expect(search, 'precondition: search box not rendered').toBeVisible();
    await search.fill('PWN');

    // The type column has no classMap, so narrow to the cell carrying the payload text.
    await expect(
      page.locator(`${GRID} .tg-cell`).filter({ hasText: 'PWN_type' }).locator('mark').first(),
      'precondition: no highlight marker rendered in the type cell, so the re-render path was never exercised',
    ).toBeVisible({ timeout: 10_000 });

    await expectInert(page, DIALOG, payload, 'img', 'type after keyword highlight');
  });
});
