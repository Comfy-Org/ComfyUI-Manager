/**
 * E2E tests: Legacy Snapshot Manager dialog.
 *
 * Tests UI-driven save and remove operations.
 * Requires ComfyUI running with --enable-manager-legacy-ui on PORT.
 */

import { test, expect } from '@playwright/test';
import { waitForComfyUI, openManagerMenu, clickMenuButton } from './helpers';

const SNAPSHOT_ROW_SELECTOR = '#snapshot-manager-dialog tr, #snapshot-manager-dialog li';

async function getSnapshotNames(page: import('@playwright/test').Page): Promise<string[]> {
  const resp = await page.request.get('/v2/snapshot/getlist');
  if (!resp.ok()) return [];
  const data = await resp.json();
  return Array.isArray(data?.items) ? data.items : [];
}

test.describe('Snapshot Manager', () => {
  // Track snapshots created during each test so afterEach can clean them up.
  // Prevents test-run accumulation on disk across runs.
  const createdDuringTest = new Set<string>();

  test.beforeEach(async ({ page }) => {
    createdDuringTest.clear();
    await page.goto('/');
    await waitForComfyUI(page);
    await openManagerMenu(page);
  });

  test.afterEach(async ({ page }) => {
    // Cleanup snapshots newly created during the test to avoid state leak.
    for (const name of createdDuringTest) {
      await page.request.post(`/v2/snapshot/remove?target=${encodeURIComponent(name)}`);
    }
  });

  test('opens snapshot manager from Manager menu', async ({ page }) => {
    await clickMenuButton(page, 'Snapshot Manager');

    // Snapshot manager should appear
    await page.waitForSelector('#snapshot-manager-dialog', {
      timeout: 10_000,
    });
  });

  test('SS1 Save button creates a new snapshot row', async ({ page }) => {
    await clickMenuButton(page, 'Snapshot Manager');
    await page.waitForSelector('#snapshot-manager-dialog', { timeout: 10_000 });

    // Baseline snapshot names (not row count — more reliable)
    const namesBefore = await getSnapshotNames(page);

    // Click Save button (UI-driven). Hard fail if the button doesn't exist.
    const saveBtn = page
      .locator('#snapshot-manager-dialog button:has-text("Save"), #snapshot-manager-dialog button:has-text("Create")')
      .first();
    await expect(saveBtn).toBeVisible({ timeout: 5_000 });

    await saveBtn.click();

    // Wait for new snapshot to appear in backend list (UI row count may lag)
    await expect
      .poll(async () => (await getSnapshotNames(page)).length, { timeout: 15_000 })
      .toBeGreaterThan(namesBefore.length);

    const namesAfter = await getSnapshotNames(page);
    const newNames = namesAfter.filter((n) => !namesBefore.includes(n));
    expect(newNames.length).toBeGreaterThanOrEqual(1);
    // Register for afterEach cleanup
    newNames.forEach((n) => createdDuringTest.add(n));

    // UI row count should also reflect the new snapshot
    const rowsAfter = await page.locator(SNAPSHOT_ROW_SELECTOR).count();
    expect(rowsAfter).toBeGreaterThan(0);
  });

  test('UI Remove button deletes a snapshot row', async ({ page }) => {
    // SETUP: create a snapshot via API so we have a deterministic target
    const saveResp = await page.request.post('/v2/snapshot/save');
    expect(saveResp.ok()).toBe(true);
    const namesAfterSave = await getSnapshotNames(page);
    expect(namesAfterSave.length).toBeGreaterThan(0);
    const targetName = namesAfterSave[0]; // desc-sorted — newest at [0]

    // Open the Snapshot Manager via UI
    await clickMenuButton(page, 'Snapshot Manager');
    await page.waitForSelector('#snapshot-manager-dialog', { timeout: 10_000 });

    // Locate the row containing our target snapshot
    const targetRow = page
      .locator(SNAPSHOT_ROW_SELECTOR, { hasText: targetName })
      .first();
    await expect(targetRow).toBeVisible({ timeout: 10_000 });

    // Click the Remove/Delete button inside that row (UI-driven)
    const removeBtn = targetRow.locator(
      'button:has-text("Remove"), button:has-text("Delete"), button[title*="emove" i], button[title*="elete" i]',
    );
    if (!(await removeBtn.first().isVisible({ timeout: 2_000 }).catch(() => false))) {
      // If the Remove UI is a right-click / hover / icon without text, register for
      // cleanup via the afterEach and report a specific failure so the test surfaces
      // the UI gap rather than pretending it verified deletion.
      createdDuringTest.add(targetName);
      throw new Error(
        'Remove/Delete button not found in snapshot row — ' +
        'UI regression or selector change; update selector to match current UI',
      );
    }

    // Accept confirmation dialog if the UI raises one
    page.once('dialog', async (d) => {
      await d.accept();
    });
    await removeBtn.first().click();

    // Effect verification: snapshot disappears from backend AND from UI
    await expect
      .poll(async () => (await getSnapshotNames(page)).includes(targetName), { timeout: 10_000 })
      .toBe(false);
    await expect(page.locator(SNAPSHOT_ROW_SELECTOR, { hasText: targetName })).toHaveCount(0);
  });
});
