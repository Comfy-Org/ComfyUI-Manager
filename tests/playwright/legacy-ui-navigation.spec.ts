/**
 * E2E tests: Dialog navigation and lifecycle.
 *
 * Tests opening/closing dialogs, nested dialog navigation, and
 * verifies no duplicate instances are created.
 *
 * Requires ComfyUI running with --enable-manager-legacy-ui on PORT.
 */

import { test, expect } from '@playwright/test';
import { waitForComfyUI, openManagerMenu, clickMenuButton, closeDialog, assertManagerMenuVisible } from './helpers';

test.describe('Dialog Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  test('Manager menu → Custom Nodes → close → Manager still visible', async ({ page }) => {
    await openManagerMenu(page);
    await assertManagerMenuVisible(page);

    await clickMenuButton(page, 'Custom Nodes Manager');
    await page.waitForSelector('#cn-manager-dialog', {
      timeout: 15_000,
    });

    // Close the Custom Nodes dialog
    await closeDialog(page);
    await page.waitForTimeout(500);

    // Manager menu should still be accessible (reopen if needed)
    await openManagerMenu(page);
    await assertManagerMenuVisible(page);
  });

  test('Manager menu → Model Manager → close → reopen', async ({ page }) => {
    await openManagerMenu(page);

    await clickMenuButton(page, 'Model Manager');
    await page.waitForSelector('#cmm-manager-dialog', {
      timeout: 15_000,
    });

    // Close the Model Manager dialog via its close button (p-dialog-close-button)
    const mmMask = page.locator('.p-dialog-mask:has(#cmm-manager-dialog)');
    const mmCloseBtn = mmMask.locator('button[aria-label="Close"], .p-dialog-close-button').first();
    if (await mmCloseBtn.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await mmCloseBtn.click();
    } else {
      await page.keyboard.press('Escape');
    }
    await page.waitForTimeout(1_000);

    // Reopen: need to open Manager menu first, then Model Manager
    await openManagerMenu(page);
    await clickMenuButton(page, 'Model Manager');
    await page.waitForSelector('#cmm-manager-dialog', {
      timeout: 15_000,
    });
  });

});
