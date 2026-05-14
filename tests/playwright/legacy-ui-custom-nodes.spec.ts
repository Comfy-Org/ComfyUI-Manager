/**
 * E2E tests: Legacy Custom Nodes Manager dialog.
 *
 * Tests the TurboGrid-based custom node list, filters, search,
 * and basic row interactions.
 *
 * Requires ComfyUI running with --enable-manager-legacy-ui on PORT.
 */

import { test, expect } from '@playwright/test';
import { waitForComfyUI, openManagerMenu, clickMenuButton } from './helpers';

test.describe('Custom Nodes Manager', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
    await openManagerMenu(page);
  });

  test('opens from Manager menu and renders grid', async ({ page }) => {
    await clickMenuButton(page, 'Custom Nodes Manager');

    // Wait for the custom nodes dialog to appear
    await page.waitForSelector('#cn-manager-dialog', {
      timeout: 10_000,
    });

    // The grid should be present
    const grid = page.locator('.cn-manager-grid, .tg-body').first();
    await expect(grid).toBeVisible({ timeout: 15_000 });
  });

  test('loads custom node list (non-empty)', async ({ page }) => {
    await clickMenuButton(page, 'Custom Nodes Manager');
    await page.waitForSelector('.cn-manager-grid, .tg-body', { timeout: 15_000 });

    // Wait for data to load — grid rows should appear
    await page.waitForFunction(
      () => {
        const rows = document.querySelectorAll('.tg-body .tg-row, .cn-manager-grid tr');
        return rows.length > 0;
      },
      { timeout: 30_000, polling: 1_000 },
    );

    const rows = page.locator('.tg-body .tg-row, .cn-manager-grid tr');
    const count = await rows.count();
    expect(count).toBeGreaterThan(0);
  });

  test('filter dropdown changes displayed nodes', async ({ page }) => {
    await clickMenuButton(page, 'Custom Nodes Manager');
    await page.waitForSelector('.cn-manager-grid, .tg-body', { timeout: 15_000 });

    // Wait for initial data load
    await page.waitForFunction(
      () => document.querySelectorAll('.tg-body .tg-row, .cn-manager-grid tr').length > 0,
      { timeout: 30_000, polling: 1_000 },
    );

    // Find the filter select (class: cn-manager-filter) and switch to "Installed"
    const filterSelect = page.locator('select.cn-manager-filter').first();
    // Hard-fail if filter UI missing — that's a regression, not a skip condition
    await expect(filterSelect).toBeVisible({ timeout: 5_000 });

    const initialCount = await page.locator('.tg-body .tg-row').count();
    await filterSelect.selectOption({ label: 'Installed' });
    // Wait for row count to actually CHANGE (state-based, not wall-clock).
    // If filter is broken and returns everything, this will fail within 10s.
    await expect
      .poll(async () => page.locator('.tg-body .tg-row').count(), { timeout: 10_000 })
      .not.toBe(initialCount);

    // Installed count should be <= total
    const filteredCount = await page.locator('.tg-body .tg-row').count();
    expect(filteredCount).toBeLessThanOrEqual(initialCount);
  });

  test('search input filters the grid', async ({ page }) => {
    await clickMenuButton(page, 'Custom Nodes Manager');
    await page.waitForSelector('.cn-manager-grid, .tg-body', { timeout: 15_000 });

    await page.waitForFunction(
      () => document.querySelectorAll('.tg-body .tg-row, .cn-manager-grid tr').length > 0,
      { timeout: 30_000, polling: 1_000 },
    );

    // Find search input
    const searchInput = page.locator('.cn-manager-keywords, input[type="text"][placeholder*="earch"], input[type="search"]').first();
    await expect(searchInput).toBeVisible({ timeout: 5_000 });

    const initialCount = await page.locator('.tg-body .tg-row, .cn-manager-grid tr').count();
    await searchInput.fill('ComfyUI-Manager');
    // State-based wait: count must actually narrow (or become 0)
    await expect
      .poll(
        async () => page.locator('.tg-body .tg-row, .cn-manager-grid tr').count(),
        { timeout: 10_000 },
      )
      .toBeLessThan(initialCount);

    const filteredCount = await page.locator('.tg-body .tg-row, .cn-manager-grid tr').count();
    expect(filteredCount).toBeLessThanOrEqual(initialCount);
  });

  test('footer buttons are present', async ({ page }) => {
    // Wave3 WI-U Cluster H target 4: strengthen from OR-of-2 to AND-of-all-
    // always-visible-admin-buttons. js/custom-nodes-manager.js:26-34 defines 6
    // footer buttons, but `.cn-manager-restart` and `.cn-manager-stop` are
    // `display: none` by default in custom-nodes-manager.css:47-62 (shown only
    // via showRestart()/showStop() — conditional on restart-required /
    // task-running state). In a clean Manager state, neither is visible.
    //
    // The 4 ALWAYS-visible footer admin buttons are:
    //   - "Install via Git URL" — primary install entrypoint
    //   - "Used In Workflow"    — filter to workflow-referenced nodes
    //   - "Check Update"        — refresh available-update list
    //   - "Check Missing"       — scan for missing nodes
    //
    // We assert all 4 are visible (AND semantics). Hidden-by-default Restart/
    // Stop are checked structurally — exist in DOM but may be hidden.
    await clickMenuButton(page, 'Custom Nodes Manager');
    await page.waitForSelector('#cn-manager-dialog', {
      timeout: 15_000,
    });

    const dialog = page.locator('#cn-manager-dialog').last();

    // AND semantics: every always-visible footer button MUST be visible.
    const alwaysVisibleButtons = [
      'Install via Git URL',
      'Used In Workflow',
      'Check Update',
      'Check Missing',
    ];
    for (const label of alwaysVisibleButtons) {
      await expect(
        dialog.locator(`button:has-text("${label}")`).first(),
        `always-visible footer button "${label}" must be present and visible`,
      ).toBeVisible();
    }

    // Structural presence for conditional buttons — they exist in the DOM but
    // are hidden until showRestart()/showStop() toggles `display: block`.
    for (const cls of ['.cn-manager-restart', '.cn-manager-stop']) {
      await expect(
        dialog.locator(cls),
        `conditional footer button ${cls} must be present in DOM (may be hidden)`,
      ).toHaveCount(1);
    }
  });
});
