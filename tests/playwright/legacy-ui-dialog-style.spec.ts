/**
 * E2E tests: the Manager dialogs bring their own styles.
 *
 * The ComfyUI frontend no longer ships the PrimeVue dialog styles. A dialog
 * that relies on them has no background, and its buttons lie over the canvas.
 *
 * Requires ComfyUI running with --enable-manager-legacy-ui on PORT.
 */

import { test, expect, type Page } from '@playwright/test';
import { waitForComfyUI, openManagerMenu, clickMenuButton } from './helpers';

const TRANSPARENT = 'rgba(0, 0, 0, 0)';
const DIALOGS: [string, string | null, string][] = [
  ['Manager menu', null, '#cm-manager-dialog'],
  ['Custom Nodes Manager', 'Custom Nodes Manager', '#cn-manager-dialog'],
  ['Model Manager', 'Model Manager', '#cmm-manager-dialog'],
  ['Snapshot Manager', 'Snapshot Manager', '#snapshot-manager-dialog'],
];

async function open(page: Page, button: string | null, selector: string) {
  await openManagerMenu(page);
  if (button) await clickMenuButton(page, button);
  await page.waitForSelector(selector, { timeout: 15_000 });
  return page.locator(selector).last();
}

function background(locator: ReturnType<Page['locator']>) {
  return locator.evaluate((element) => getComputedStyle(element).backgroundColor);
}

test.describe('Dialog styles', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
  });

  for (const [name, button, selector] of DIALOGS) {
    test(`${name} has a background and dims the page behind it`, async ({ page }) => {
      const dialog = await open(page, button, selector);

      expect(await background(dialog)).not.toBe(TRANSPARENT);
      expect(await background(dialog.locator('xpath=..'))).not.toBe(TRANSPARENT);
    });

    test(`${name} is closed by its close button`, async ({ page }) => {
      const dialog = await open(page, button, selector);

      await dialog.getByRole('button', { name: 'Close' }).click();

      await expect(dialog).toBeHidden();
    });
  }
});
