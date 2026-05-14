/**
 * E2E tests: UI-driven install/uninstall effect verification.
 *
 * Contract: LEGACY UI tests must drive the action via UI elements (no direct API calls).
 * Effect is observed through backend state (queue/status, installed list) and/or UI badges.
 *
 * Requires ComfyUI running with --enable-manager-legacy-ui on PORT.
 * Test pack: ComfyUI_SigmoidOffsetScheduler (ltdrdata's test pack).
 */

import { test, expect } from '@playwright/test';
import { waitForComfyUI, openManagerMenu, clickMenuButton } from './helpers';

const PACK_CNR_ID = 'comfyui_sigmoidoffsetscheduler';

async function waitForAllDone(page: import('@playwright/test').Page, timeoutMs = 90_000): Promise<void> {
  // Three-phase polling with DETERMINISTIC baseline:
  //   Phase 0 — snapshot baseline. To make the baseline deterministic across
  //             runs (and immune to leaking history from prior tests in the
  //             session), we FETCH the baseline immediately after the caller
  //             has triggered the UI action. The caller is expected to have
  //             called /v2/manager/queue/reset at the start of its test flow
  //             so that done_count starts at 0 for this test's session.
  //   Phase 1 — wait for task acceptance:
  //             total_count > 0 OR is_processing=true OR done_count > baseline
  //   Phase 2 — wait for drain (total_count === 0 && is_processing=false)
  const deadline = Date.now() + timeoutMs;

  // Phase 0: baseline. If fetch fails, treat as 0 but log so the test signal
  // isn't silently degraded.
  let baselineDone = 0;
  const baselineResp = await page.request
    .get('/v2/manager/queue/status')
    .catch(() => null);
  if (baselineResp && baselineResp.ok()) {
    const baseline = await baselineResp.json();
    baselineDone = baseline?.done_count ?? 0;
  } else {
    console.warn('[waitForAllDone] baseline fetch failed — treating as 0');
  }

  // Phase 1: task acceptance
  const acceptDeadline = Math.min(Date.now() + 15_000, deadline);
  let accepted = false;
  while (Date.now() < acceptDeadline) {
    const status = await page.request
      .get('/v2/manager/queue/status')
      .then((r) => r.json())
      .catch(() => null);
    if (
      status &&
      ((status.total_count ?? 0) > 0 ||
        status.is_processing === true ||
        (status.done_count ?? 0) > baselineDone)
    ) {
      accepted = true;
      break;
    }
    await page.waitForTimeout(500);
  }
  if (!accepted) {
    throw new Error('Queue never accepted the task (empty queue for 15s after UI action)');
  }

  // Phase 2: drain
  while (Date.now() < deadline) {
    const status = await page.request
      .get('/v2/manager/queue/status')
      .then((r) => r.json())
      .catch(() => null);
    if (status && status.is_processing === false && (status.total_count ?? 0) === 0) {
      return;
    }
    await page.waitForTimeout(1_500);
  }
  throw new Error(`Queue did not drain within ${timeoutMs}ms`);
}

async function isPackInstalled(page: import('@playwright/test').Page): Promise<boolean> {
  const resp = await page.request.get('/v2/customnode/installed');
  if (!resp.ok()) return false;
  const data = await resp.json();
  for (const pkg of Object.values<unknown>(data)) {
    if (
      pkg &&
      typeof pkg === 'object' &&
      (pkg as { cnr_id?: string }).cnr_id?.toLowerCase() === PACK_CNR_ID
    ) {
      return true;
    }
  }
  return false;
}

test.describe('UI-driven install/uninstall', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  test('LB1 Install button triggers install effect', async ({ page }) => {
    // Reset queue at start for deterministic done_count baseline in waitForAllDone
    await page.request.post('/v2/manager/queue/reset');

    // Precondition: pack must NOT be installed. If the seed pack is already
    // installed (prior pytest runs, pre-seeded E2E environment), the
    // "Not Installed" filter applied below would correctly exclude its row and
    // `packRow.toBeVisible` would fail with "element(s) not found". Uninstall
    // via API as test SETUP (not verification) — mirrors LB2's inverse pattern
    // that API-installs if the pack is absent. queue/batch is used here (not
    // queue/task) because queue/batch is the legacy manager_server endpoint
    // for task enqueueing; queue/task is glob-only — under
    // --enable-manager-legacy-ui (which this spec requires) POST /queue/task
    // falls through to aiohttp's GET-only static catch-all and returns 405.
    if (await isPackInstalled(page)) {
      const queueResp = await page.request.post('/v2/manager/queue/batch', {
        data: JSON.stringify({
          batch_id: 'lb1-setup-uninstall',
          uninstall: [{
            id: 'ComfyUI_SigmoidOffsetScheduler',
            ui_id: 'lb1-setup-uninstall',
            version: '1.0.1',
            selected_version: 'latest',
            mode: 'local',
            channel: 'default',
          }],
        }),
        headers: { 'Content-Type': 'application/json' },
      });
      expect(queueResp.ok()).toBe(true);
      await page.request.post('/v2/manager/queue/start');
      await waitForAllDone(page, 60_000);
      // Hard fail if setup itself couldn't uninstall the pack
      expect(await isPackInstalled(page)).toBe(false);
    }

    // UI flow: open Manager → Custom Nodes Manager
    await openManagerMenu(page);
    await clickMenuButton(page, 'Custom Nodes Manager');
    await page.waitForSelector('#cn-manager-dialog', { timeout: 15_000 });

    // Wait for grid to populate before applying filter (avoids race on empty grid)
    await expect(page.locator('.tg-body .tg-row').first()).toBeVisible({ timeout: 30_000 });
    const initialRowCount = await page.locator('.tg-body .tg-row').count();

    // Filter to Not Installed to make install buttons visible. Wait for
    // filtered row count to actually change (DOM state, not wall-clock).
    const filterSelect = page.locator('select.cn-manager-filter').first();
    if (await filterSelect.isVisible().catch(() => false)) {
      await filterSelect.selectOption({ value: 'not-installed' });
      await expect
        .poll(async () => page.locator('.tg-body .tg-row').count(), { timeout: 10_000 })
        .not.toBe(initialRowCount);
    }

    // Search for the specific test pack. Wait for search to narrow results.
    // Search matches title/author/description per custom-nodes-manager.js:605
    // (NOT id). The pack's title is "ComfyUI Sigmoid Offset Scheduler" (with
    // spaces), so "SigmoidOffsetScheduler" (no spaces) would miss — use
    // "Sigmoid Offset Scheduler" to match the title substring.
    const searchInput = page
      .locator('.cn-manager-keywords, input[type="search"], input[type="text"][placeholder*="earch"]')
      .first();
    if (await searchInput.isVisible().catch(() => false)) {
      await searchInput.fill('Sigmoid Offset Scheduler');
      // Wait for search to settle — row count stabilizes
      await expect
        .poll(async () => page.locator('.tg-body .tg-row').count(), { timeout: 10_000 })
        .toBeLessThanOrEqual(5);
    }

    // Scope button to the row containing the pack name (not arbitrary first row).
    // Row DOM renders the title column, which reads "ComfyUI Sigmoid Offset
    // Scheduler" — match the substring that appears there, not the id.
    // TurboGrid splits each logical row into TWO DOM .tg-row elements (left
    // frozen-column pane with the title + right scrollable-column pane with
    // Version/Action/etc.). The Install button lives in the right pane, so
    // filtering by title-text picks the left pane which has no Install button.
    // Use `.tg-body` scope + `button[mode="install"]` directly, then assert
    // only one such button exists (single search result narrows to 1 row).
    const packRow = page.locator('.tg-body .tg-row', { hasText: 'Sigmoid Offset Scheduler' }).first();
    await expect(packRow).toBeVisible({ timeout: 10_000 });
    const installBtn = page.locator('.tg-body button[mode="install"]').first();
    // Hard fail if the Install button isn't visible in the filtered result
    await expect(installBtn).toBeVisible({ timeout: 5_000 });

    await installBtn.click();
    // Version selector dialog appears
    const selectBtn = page.locator('.comfy-modal button:has-text("Select")').first();
    await selectBtn.waitFor({ timeout: 10_000 });
    await selectBtn.click();

    // Effect verification: wait for queue to drain then check installed state
    await waitForAllDone(page, 120_000);
    const installed = await isPackInstalled(page);
    expect(installed).toBe(true);
  });

  test('LB2 Uninstall button triggers uninstall effect', async ({ page }) => {
    // Reset queue at start for deterministic done_count baseline in waitForAllDone
    await page.request.post('/v2/manager/queue/reset');

    // Precondition: pack must be installed. Install via API as test SETUP
    // (not verification). This makes LB2 independent of LB1 — hard-failing
    // on a UI bug rather than skipping on a missing precondition. queue/batch
    // is the legacy manager_server endpoint (see LB1 comment above); install
    // is async, so waitForAllDone is still required after queue/start.
    const preinstalled = await isPackInstalled(page);
    if (!preinstalled) {
      await page.request.post('/v2/manager/queue/reset');
      const queueResp = await page.request.post('/v2/manager/queue/batch', {
        data: JSON.stringify({
          batch_id: 'lb2-setup-install',
          install: [{
            id: 'ComfyUI_SigmoidOffsetScheduler',
            ui_id: 'lb2-setup-install',
            version: '1.0.1',
            selected_version: 'latest',
            mode: 'remote',
            channel: 'default',
          }],
        }),
        headers: { 'Content-Type': 'application/json' },
      });
      expect(queueResp.ok()).toBe(true);
      const queueBody = await queueResp.json();
      expect(queueBody.failed ?? []).toEqual([]);
      await page.request.post('/v2/manager/queue/start');
      // Poll the terminal state directly: isPackInstalled returning true is
      // the unambiguous success signal. Using waitForAllDone here is racy —
      // fast-path installs (pack already on disk / cached CNR artifacts) can
      // complete before waitForAllDone's Phase 0 baseline fetch runs, leaving
      // Phase 1 unable to distinguish "already done" from "never queued".
      // Polling isPackInstalled avoids that ambiguity entirely.
      await expect.poll(() => isPackInstalled(page), { timeout: 120_000 }).toBe(true);
    }

    await openManagerMenu(page);
    await clickMenuButton(page, 'Custom Nodes Manager');
    await page.waitForSelector('#cn-manager-dialog', { timeout: 15_000 });

    await expect(page.locator('.tg-body .tg-row').first()).toBeVisible({ timeout: 30_000 });
    const initialRowCount = await page.locator('.tg-body .tg-row').count();

    // Filter to Installed to make Uninstall buttons visible
    const filterSelect = page.locator('select.cn-manager-filter').first();
    if (await filterSelect.isVisible().catch(() => false)) {
      await filterSelect.selectOption({ label: 'Installed' });
      await expect
        .poll(async () => page.locator('.tg-body .tg-row').count(), { timeout: 10_000 })
        .not.toBe(initialRowCount);
    }

    // Search matches title/author/description per custom-nodes-manager.js:605
    // (NOT id). Pack title is "ComfyUI Sigmoid Offset Scheduler" (spaces) —
    // use the space-separated form to match (WI-CC pattern).
    const searchInput = page
      .locator('.cn-manager-keywords, input[type="search"], input[type="text"][placeholder*="earch"]')
      .first();
    if (await searchInput.isVisible().catch(() => false)) {
      await searchInput.fill('Sigmoid Offset Scheduler');
      await expect
        .poll(async () => page.locator('.tg-body .tg-row').count(), { timeout: 10_000 })
        .toBeLessThanOrEqual(5);
    }

    // Scope packRow visibility to the specific pack title, but the Uninstall
    // button lives in the right-pane .tg-row (TurboGrid dual-pane rendering),
    // which is NOT a child of the title-bearing left-pane row. Scope the
    // button lookup to the grid body + search-narrowed result set (WI-CC pattern).
    const packRow = page.locator('.tg-body .tg-row', { hasText: 'Sigmoid Offset Scheduler' }).first();
    await expect(packRow).toBeVisible({ timeout: 10_000 });
    const uninstallBtn = page.locator('.tg-body button[mode="uninstall"]').first();
    await expect(uninstallBtn).toBeVisible({ timeout: 5_000 });

    await uninstallBtn.click();

    // A confirmation dialog appears — custom-nodes-manager.js uses
    // `customConfirm` (PrimeVue p-dialog), not `.comfy-modal`. The dialog
    // is the last-opened one (on top of manager-menu + CustomNodes dialogs);
    // its Confirm button accessible name has a leading space (icon + text),
    // so match by visible text substring rather than exact name.
    const confirmDialog = page.locator('dialog[open], [role="dialog"]').last();
    const confirmBtn = confirmDialog.locator('button:has-text("Confirm"), button:has-text("Yes"), button:has-text("OK")').first();
    if (await confirmBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await confirmBtn.click();
    }

    // Poll isPackInstalled directly — the uninstall queue drains fast enough
    // that waitForAllDone's Phase 0/1 baseline-vs-done race can miss
    // acceptance. isPackInstalled==false is the unambiguous terminal signal.
    await expect.poll(() => isPackInstalled(page), { timeout: 60_000 }).toBe(false);
  });
});
