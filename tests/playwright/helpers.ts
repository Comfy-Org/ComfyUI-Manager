/**
 * Shared helpers for ComfyUI Manager Playwright E2E tests.
 *
 * The legacy UI is dialog-based: a "Manager" menu button on the ComfyUI
 * top-bar opens ManagerMenuDialog, from which sub-dialogs (CustomNodes,
 * Model, Snapshot) are launched.
 */

import * as fs from 'fs';
import { execFileSync } from 'child_process';
import * as path from 'path';
import { type Page, expect } from '@playwright/test';

/** Repository root, resolved from this file (tests/playwright/helpers.ts). */
const REPO_ROOT = path.resolve(__dirname, '..', '..');

/** Wait for the ComfyUI page to be fully loaded (queue ready). */
export async function waitForComfyUI(page: Page) {
  // ComfyUI shows the canvas once the app is ready.  Wait for the
  // system_stats endpoint to respond — same check the Python E2E uses.
  await page.waitForFunction(
    async () => {
      try {
        const r = await fetch('/system_stats');
        return r.ok;
      } catch {
        return false;
      }
    },
    { timeout: 30_000, polling: 1_000 },
  );
  // Give the extensions a moment to register their menu items.
  await page.waitForTimeout(3_000);

  // Close any overlay that might be covering the toolbar.
  // Press Escape to dismiss popups/modals/sidebars.
  await page.keyboard.press('Escape');
  await page.waitForTimeout(1_000);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
}

/** Open the Manager Menu dialog via the top-bar button. */
export async function openManagerMenu(page: Page) {
  // The legacy UI registers a "Manager" button via ComfyButton (new style)
  // or a plain <button> (old style).  The new-style button uses the
  // "puzzle" icon and has tooltip "ComfyUI Manager" / content "Manager".
  //
  // ComfyButton renders as a structure like:
  //   <button class="comfyui-button" title="ComfyUI Manager">
  //     <span class="icon">...</span>
  //     <span>Manager</span>
  //   </button>
  //
  // We try multiple selectors to handle both old and new ComfyUI layouts.
  const selectors = [
    'button[title="ComfyUI Manager"]',            // new-style ComfyButton
    'button.comfyui-button:has-text("Manager")',   // new-style fallback
    'button:has-text("Manager")',                   // old-style plain button
  ];

  for (const sel of selectors) {
    const btn = page.locator(sel).first();
    if (await btn.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await btn.click();
      await page.waitForSelector('#cm-manager-dialog, .comfy-modal', { timeout: 10_000 });
      return;
    }
  }

  // Last resort: find any button with "Manager" in tooltip or text via DOM
  const found = await page.evaluate(() => {
    const buttons = document.querySelectorAll('button');
    for (const btn of buttons) {
      const text = btn.textContent?.toLowerCase() || '';
      const title = btn.getAttribute('title')?.toLowerCase() || '';
      if (text.includes('manager') || title.includes('manager')) {
        (btn as HTMLElement).click();
        return true;
      }
    }
    return false;
  });

  if (found) {
    // Wait for the dialog by polling for the element in DOM
    await page.waitForFunction(
      () => !!document.getElementById('cm-manager-dialog'),
      { timeout: 10_000, polling: 500 },
    );
    return;
  }

  await page.screenshot({ path: 'test-results/debug-manager-btn-not-found.png' });
  throw new Error('Could not find Manager button in ComfyUI toolbar');
}

/** Click a button inside the Manager Menu dialog by its visible text. */
export async function clickMenuButton(page: Page, text: string) {
  const dialog = page.locator('#cm-manager-dialog').first();
  await dialog.locator(`button:has-text("${text}")`).click();
}

/** Close the topmost dialog via its X (close) button or Escape. */
export async function closeDialog(page: Page) {
  // Try clicking close buttons on visible dialogs. The manager-menu dialog
  // (`#cm-manager-dialog`) is a ComfyDialog with `.p-dialog-close-button` (X),
  // while sub-dialogs use `.cm-close-btn`. Try both.
  for (const sel of [
    '#cn-manager-dialog button.cm-close-btn',
    '#cmm-manager-dialog button.cm-close-btn',
    '#snapshot-manager-dialog button.cm-close-btn',
    '#cm-manager-dialog button.cm-close-btn',
    '#cm-manager-dialog .p-dialog-close-button',
    '.cm-close-btn',
    '.p-dialog-close-button',
  ]) {
    const btn = page.locator(sel).last();
    if (await btn.isVisible({ timeout: 500 }).catch(() => false)) {
      await btn.click();
      await page.waitForTimeout(300);
      return;
    }
  }
  // Fallback: press Escape (ComfyDialog may not honor this reliably)
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
}

/** Assert the Manager Menu dialog is visible and contains expected sections. */
export async function assertManagerMenuVisible(page: Page) {
  const dialog = page.locator('#cm-manager-dialog').first();
  await expect(dialog).toBeVisible();
}

// ---------------------------------------------------------------------------
// XSS fixtures. Additive — nothing above is changed.
// ---------------------------------------------------------------------------

/**
 * The payload used by every XSS row. Assertions on it have THREE legs, because
 * a payload can be neutered in a way that also deletes it:
 *   (1) presence  — the container's textContent contains the literal payload
 *   (2) structure — no element the payload would have created exists
 *   (3) execution — window.__xss_fired is undefined after render
 */
export const XSS_PAYLOAD = '<img src=x onerror="window.__xss_fired=1">';

/** Space-free variant — the `last_update` formatter cuts its value at the
 *  first space with `.split(' ')[0]`, so a spaced payload would be truncated
 *  and the row would pass for the wrong reason. */
export const XSS_PAYLOAD_NOSPACE = '<img/src=x/onerror="window.__xss_fired=1">';

/** One `/v2/customnode/getlist` pack, shaped exactly like the live response
 *  (verified against the running server: {channel, node_packs: {id: item}}). */
export function makePack(id: string, overrides: Record<string, unknown> = {}) {
  return {
    author: 'author-' + id,
    description: 'description of ' + id,
    files: [`https://github.com/example/${id}`],
    install_type: 'git-clone',
    reference: `https://github.com/example/${id}`,
    repository: `https://github.com/example/${id}`,
    title: id,
    cnr_latest: '1.0.0',
    id,
    health: '-',
    state: 'not-installed',
    version: '1.0.0',
    'update-state': 'false',
    stars: 5,
    last_update: '2026-01-01 00:00:00',
    trust: false,
    ...overrides,
  };
}

/** Replace the pack list the grid renders from.
 *
 *  NOTE, because any result read from these fixtures depends on it:
 *  page.route() REPLACES the HTTP response, so the fixture BYPASSES
 *  populate_markdown. For
 *  RAW fields that is what a live server can actually deliver; for
 *  SERVER-ESCAPED fields it delivers input the live server currently cannot,
 *  so such a fixture must be pre-transformed with `serverSanitizeTag` below —
 *  otherwise the row asserts against a wire form that does not exist. */
export async function routeNodeList(page: Page, packs: Record<string, unknown>) {
  await page.route('**/customnode/getlist**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ channel: 'default', node_packs: packs }),
    });
  });
}

/** Seed `/v2/customnode/getmappings` — that route performs NO server-side
 *  sanitization, so the values it returns are genuinely raw. */
export async function routeMappings(page: Page, mappings: Record<string, unknown>) {
  await page.route('**/customnode/getmappings**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mappings),
    });
  });
}

/** Seed `/customnode/alternatives` — required to OPEN the alternatives column,
 *  which is `invisible: !this.hasAlternatives()`. Without this the alternatives
 *  column stays hidden and any test asserting on it passes vacuously. */
export async function routeAlternatives(page: Page, alts: Record<string, unknown>) {
  await page.route('**/customnode/alternatives**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(alts),
    });
  });
}

/** Open Manager menu -> Custom Nodes Manager and wait for the grid to fill. */
export async function openCustomNodesManager(page: Page) {
  await clickMenuButton(page, 'Custom Nodes Manager');
  await page.waitForSelector('#cn-manager-dialog', { timeout: 15_000 });
  await page.waitForSelector('.cn-manager-grid, .tg-body', { timeout: 15_000 });
  await page.waitForFunction(
    () => document.querySelectorAll('.tg-body .tg-row, .cn-manager-grid tr').length > 0,
    { timeout: 30_000, polling: 500 },
  );
}

/** The three legs, applied to one container. `payload` is the literal string
 *  the user must SEE; `createdSelector` is what the payload would have built. */
export async function expectInert(
  page: Page,
  containerSelector: string,
  payload: string,
  createdSelector: string,
  label: string,
) {
  // ALL THREE LEGS ARE EVALUATED BEFORE ANY ASSERTION FIRES, and that is
  // load-bearing rather than stylistic. Asserting presence first and
  // short-circuiting cannot distinguish the two ways leg 1 fails:
  //   - the payload was PARSED AS MARKUP (the defect) — textContent holds the
  //     rendered result, not the literal source, so presence fails; or
  //   - the payload NEVER RENDERED (a broken fixture) — presence fails too.
  // Those are opposite conclusions from an identical symptom, so a failure whose
  // message cannot tell them apart is not evidence of anything. The
  // diagnostic below reports all three observations on every failure.
  const text = (await page.locator(containerSelector).first().textContent()) ?? '';
  const created = await page.locator(`${containerSelector} ${createdSelector}`).count();
  const fired = await page.evaluate(() => (window as unknown as Record<string, unknown>).__xss_fired);

  const present = text.includes(payload);
  const diagnostic =
    `${label} — three-leg result in ${containerSelector}:\n` +
    `  leg 1 presence  : ${present ? 'PASS (payload visible as literal text)' : 'FAIL (payload not present as literal text)'}\n` +
    `  leg 2 structure : ${created === 0 ? 'PASS (no <' + createdSelector + '> constructed)' : `FAIL (${created} live <${createdSelector}> constructed — the value reached innerHTML AS MARKUP)`}\n` +
    `  leg 3 execution : ${fired === undefined ? 'PASS (window.__xss_fired unset)' : `FAIL (window.__xss_fired=${JSON.stringify(fired)} — the payload EXECUTED)`}\n` +
    `  READ IT THIS WAY: leg 2 or leg 3 failing = the sink is LIVE (this is the failure being demonstrated).\n` +
    `  leg 1 failing while legs 2 and 3 PASS = the payload never rendered at all — a BROKEN FIXTURE, not a defect;\n` +
    `  the row proves nothing in that state and must be fixed rather than reported.\n` +
    `  container text (first 300 chars): ${JSON.stringify(text.slice(0, 300))}`;

  expect(created, diagnostic).toBe(0);
  expect(fired, diagnostic).toBeUndefined();
  expect(present, diagnostic).toBe(true);
}

/** Run the shipped Python renderer, including its title/name/description contract. */
export function serverPopulateMarkdown(item: Record<string, unknown>): Record<string, any> {
  return JSON.parse(execFileSync(process.env.PYTHON || 'python3',
    [path.join(REPO_ROOT, 'tests', 'legacy_html_testutil.py')],
    { input: JSON.stringify(item), encoding: 'utf-8' }));
}

export function serverSanitizeTag(value: string): string {
  return serverPopulateMarkdown({ title: value }).title;
}

/** The RESTART clause both server install-denial constants state.
 *
 *  `js/common.js: INSTALL_DENIAL_MESSAGES` is a hand-written client copy of a
 *  fact the SERVER owns: the install flag and `network_mode` are read once at
 *  ComfyUI startup, so editing config.ini and retrying is denied identically
 *  until the server is restarted. Nothing makes the two texts move together, so
 *  the client copy is exactly the kind of thing that silently falls behind — it
 *  already had, which is why this helper exists.
 *
 *  Read from `SECURITY_MESSAGE_FLAG_GIT_URL` / `SECURITY_MESSAGE_FLAG_PIP` and
 *  cross-checked against each other, so the assertion is against the SERVER's
 *  wording rather than a third copy typed into the test. The word "restart" is
 *  only the search key; the whole asserted sentence comes from the source. */
export function serverInstallDenialRestartClause(): string {
  const srcPath = path.join(REPO_ROOT, 'comfyui_manager', 'legacy', 'manager_server.py');
  const src = fs.readFileSync(srcPath, 'utf-8');
  const names = ['SECURITY_MESSAGE_FLAG_GIT_URL', 'SECURITY_MESSAGE_FLAG_PIP'];
  const clauses = names.map((name) => {
    const m = new RegExp(`^${name}\\s*=\\s*"((?:[^"\\\\]|\\\\.)*)"`, 'm').exec(src);
    if (!m) {
      throw new Error(
        `serverInstallDenialRestartClause: ${name} not found as a double-quoted ` +
        `string literal in ${srcPath} — the server constant moved or changed shape.`,
      );
    }
    const sentence = m[1].split('. ').find((s) => /\brestart\b/i.test(s));
    if (!sentence) {
      throw new Error(
        `serverInstallDenialRestartClause: ${name} states no sentence mentioning a ` +
        'restart. Either the server dropped the fact (and the client copy should ' +
        'drop it too) or the wording changed — do not paper over it here.',
      );
    }
    return `${sentence.trim()}.`;
  });
  if (clauses[0] !== clauses[1]) {
    throw new Error(
      'serverInstallDenialRestartClause: the two server constants state DIFFERENT ' +
      `restart clauses, so there is no single fact to check the client against:\n` +
      `  ${names[0]}: ${JSON.stringify(clauses[0])}\n` +
      `  ${names[1]}: ${JSON.stringify(clauses[1])}`,
    );
  }
  return clauses[0];
}

// ---------------------------------------------------------------------------
// Model Manager fixtures.
// ---------------------------------------------------------------------------

/** One `/v2/externalmodel/getlist` model, shaped like the live response. */
export function makeModel(name: string, overrides: Record<string, unknown> = {}) {
  return {
    name,
    type: 'checkpoint',
    base: 'SD1.5',
    save_path: 'checkpoints',
    description: 'description of ' + name,
    reference: 'https://example.com/' + name,
    filename: name + '.safetensors',
    url: 'https://example.com/' + name + '.safetensors',
    size: '1.0MB',
    installed: 'False',
    ...overrides,
  };
}

/** Replace the model list the Model Manager grid renders from. */
export async function routeModelList(page: Page, models: Record<string, unknown>[]) {
  await page.route('**/externalmodel/getlist**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ models }),
    });
  });
}

/** Open Manager menu -> Model Manager and wait for the grid to fill. */
export async function openModelManager(page: Page) {
  await clickMenuButton(page, 'Model Manager');
  await page.waitForSelector('#cmm-manager-dialog', { timeout: 15_000 });
  await page.waitForSelector('.cmm-manager-grid, .tg-body', { timeout: 15_000 });
  await page.waitForFunction(
    () => document.querySelectorAll('.tg-body .tg-row, .cmm-manager-grid tr').length > 0,
    { timeout: 30_000, polling: 500 },
  );
}
