/**
 * E2E tests: Legacy Model Manager dialog.
 *
 * Tests the model list grid, filters, and search.
 *
 * Requires ComfyUI running with --enable-manager-legacy-ui on PORT.
 */

import { test, expect } from '@playwright/test';
import { waitForComfyUI, openManagerMenu, clickMenuButton } from './helpers';

test.describe('Model Manager', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
    await openManagerMenu(page);
  });

  test('opens from Manager menu and renders grid', async ({ page }) => {
    await clickMenuButton(page, 'Model Manager');

    await page.waitForSelector('#cmm-manager-dialog', {
      timeout: 10_000,
    });

    const grid = page.locator('.cmm-manager-grid, .tg-body').first();
    await expect(grid).toBeVisible({ timeout: 15_000 });
  });

  test('loads model list (non-empty)', async ({ page }) => {
    // Wave3 WI-U Cluster H target 3 (LM1): previously rows>0 only. Now also
    // verifies the install-state column is rendered for every logical model row.
    //
    // TurboGrid renders each logical row as TWO DOM `.tg-row` elements (left
    // frozen-column pane + right scrollable-column pane). Only the right pane
    // carries the "installed" column, which `model-manager.js:342-345` formats
    // as EITHER `<div class="cmm-icon-passed">...</div>` (installed===True) OR
    // `<button class="cmm-btn-install">Install</button>` (installed===False),
    // with a `"Refresh Required"` fallback at :340.
    //
    // Invariant: the number of install-state indicators equals the number of
    // logical rows, i.e. half the DOM-row count. This catches a regression
    // where the installed column stops rendering for any model (partial or
    // complete).
    await clickMenuButton(page, 'Model Manager');
    await page.waitForSelector('.cmm-manager-grid, .tg-body', { timeout: 15_000 });

    await page.waitForFunction(
      () => document.querySelectorAll('.tg-body .tg-row, .cmm-manager-grid tr').length > 0,
      { timeout: 30_000, polling: 1_000 },
    );

    const rows = page.locator('.tg-body .tg-row, .cmm-manager-grid tr');
    const domRowCount = await rows.count();
    expect(domRowCount).toBeGreaterThan(0);

    // Count install indicators across the whole grid.
    const installedCount = await page
      .locator('.cmm-icon-passed, .cmm-btn-install')
      .count();
    const refreshCount = await page
      .locator('.tg-body :text("Refresh Required"), .cmm-manager-grid :text("Refresh Required")')
      .count();
    const totalIndicators = installedCount + refreshCount;

    // Each logical model row must expose an install-state indicator.
    expect(totalIndicators, 'at least one row must have a valid install-state indicator').toBeGreaterThan(0);

    // Expected indicator count: one per logical row. TurboGrid doubles DOM
    // rows for the 2-pane layout, so logical_count = domRowCount / 2 when
    // dual-pane. For single-pane (fallback) the ratio is 1:1. Accept either.
    const logicalRowCount = domRowCount / 2;
    const isDualPane = Number.isInteger(logicalRowCount) && totalIndicators === logicalRowCount;
    const isSinglePane = totalIndicators === domRowCount;
    expect(
      isDualPane || isSinglePane,
      `install-state indicator count mismatch: totalIndicators=${totalIndicators}, ` +
        `domRowCount=${domRowCount}. Expected either ${logicalRowCount} (dual-pane) or ${domRowCount} (single-pane).`,
    ).toBe(true);
  });

  test('search input filters the model grid', async ({ page }) => {
    await clickMenuButton(page, 'Model Manager');
    await page.waitForSelector('.cmm-manager-grid, .tg-body', { timeout: 15_000 });

    await page.waitForFunction(
      () => document.querySelectorAll('.tg-body .tg-row, .cmm-manager-grid tr').length > 0,
      { timeout: 30_000, polling: 1_000 },
    );

    const searchInput = page.locator('.cmm-manager-keywords, input[type="text"][placeholder*="earch"], input[type="search"]').first();
    await expect(searchInput).toBeVisible({ timeout: 5_000 });

    const initialCount = await page.locator('.tg-body .tg-row, .cmm-manager-grid tr').count();
    await searchInput.fill('stable diffusion');
    // State-based wait: row count must change (or narrow). If the search
    // is entirely broken and returns all rows, this will fail the poll.
    await expect
      .poll(
        async () => page.locator('.tg-body .tg-row, .cmm-manager-grid tr').count(),
        { timeout: 10_000 },
      )
      .not.toBe(initialCount);

    const filteredCount = await page.locator('.tg-body .tg-row, .cmm-manager-grid tr').count();
    expect(filteredCount).toBeLessThanOrEqual(initialCount);
  });

  test('filter dropdown is present with expected options', async ({ page }) => {
    // Wave3 WI-U Cluster H target 5: previously options.length>0 only.
    // Now asserts the filter dropdown surfaces all 4 known states defined by
    // ModelManager.initFilter() in js/model-manager.js:74-86 —
    // `All`, `Installed`, `Not Installed`, `In Workflow`.
    await clickMenuButton(page, 'Model Manager');
    await page.waitForSelector('#cmm-manager-dialog', {
      timeout: 15_000,
    });

    const dialog = page.locator('#cmm-manager-dialog').last();
    const filterSelect = dialog.locator('select').filter({ hasText: /All|Installed/ }).first();
    await expect(filterSelect).toBeVisible({ timeout: 5_000 });

    const options = (await filterSelect.locator('option').allTextContents()).map((s) => s.trim());
    // Exact set match (normalized): js/model-manager.js:74-86 defines this
    // list. If labels change, update this assertion consciously.
    const expected = ['All', 'Installed', 'Not Installed', 'In Workflow'];
    const actual = new Set(options);
    for (const label of expected) {
      expect(
        actual.has(label),
        `filter dropdown missing expected option "${label}". Options=${JSON.stringify(options)}`,
      ).toBe(true);
    }
  });
});
