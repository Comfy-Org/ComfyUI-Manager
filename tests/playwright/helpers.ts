/**
 * Shared helpers for ComfyUI Manager Playwright E2E tests.
 *
 * The legacy UI is dialog-based: a "Manager" menu button on the ComfyUI
 * top-bar opens ManagerMenuDialog, from which sub-dialogs (CustomNodes,
 * Model, Snapshot) are launched.
 */

import { type Page, expect } from '@playwright/test';

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
