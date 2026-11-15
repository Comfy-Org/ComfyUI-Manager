// Throwaway capture script: not part of the PR. SIDE=red|green names the JS being served, RUN the repetition.
// Two models are installed one after the other, as clicking Install in two rows does; the first batch then ends.
import * as fs from 'fs';
import * as path from 'path';
import { test, expect, type Page } from '@playwright/test';
import { waitForComfyUI, openManagerMenu, openModelManager, routeModelList, makeModel } from '../../wt/tests/playwright/helpers';

const SIDE = process.env.SIDE!;
const RUN = process.env.RUN || '1';
const OUT = path.resolve(__dirname, '..', 'screens2');
test.use({ viewport: { width: 1440, height: 900 } });

test('two installs in a row, the first batch ends', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  await page.goto('/');
  await waitForComfyUI(page);
  await routeModelList(page, [makeModel('first'), makeModel('second')]);
  const batches: any[] = [];
  await page.route('**/v2/manager/queue/batch', async (route) => {
    batches.push(route.request().postDataJSON());
    await route.fulfill({ json: { failed: [] } });
  });
  await openManagerMenu(page);
  await openModelManager(page);
  await page.evaluate(async () => {
    const { ModelManager } = await import('/extensions/comfyui-manager-legacy/model-manager.js');
    const manager = ModelManager.instance;
    for (const item of manager.modelList) {
      const button = manager.grid.getCellNode(item, 'installed').querySelector('button[mode="install"]');
      await manager.installModels([item], button);
    }
  });
  await expect(page.locator('.cmm-manager-stop')).toBeVisible();
  const [first, second] = batches.map((batch) => ({ id: batch.batch_id, target: batch.install_model[0].ui_id }));
  const dispatch = (detail: unknown) => page.evaluate(async (detail) => {
    const { api } = await import('/scripts/api.js');
    api.dispatchEvent(new CustomEvent('cm-queue-status', { detail }));
  }, detail);
  const state = () => page.evaluate(async ([firstTarget, secondTarget]) => {
    const { ModelManager } = await import('/extensions/comfyui-manager-legacy/model-manager.js');
    const manager = ModelManager.instance;
    const shown = (selector: string) => {
      const el = manager.element.querySelector(selector) as HTMLElement | null;
      return !!el && getComputedStyle(el).display !== 'none';
    };
    const cell = (hash: string) => manager.grid.getCellNode(manager.grid.getRowItemBy('hash', hash), 'installed') as HTMLElement;
    const rect = (el: Element) => { const r = el.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }; };
    return {
      observed: {
        installsPending: manager.install_contexts ? manager.install_contexts.size : (manager.install_context ? 1 : 0),
        stopButtonShown: shown('.cmm-manager-stop'),
        buttonsMarkedLoading: manager.element.querySelectorAll('.cmm-btn-loading').length,
        firstRow: cell(firstTarget).innerText.trim(),
        secondRow: cell(secondTarget).innerText.trim(),
        secondRowLoading: !!cell(secondTarget).querySelector('.cmm-btn-loading'),
        message: (manager.element.querySelector('.cmm-manager-message') as HTMLElement).innerText.trim(),
      },
      boxes: { firstRow: rect(cell(firstTarget)), secondRow: rect(cell(secondTarget)),
               footer: rect(manager.element.querySelector('.cmm-manager-footer')!) },
    };
  }, [first.target, second.target]);
  const report = (batch: { id: string; target: string }, status: string) => dispatch({
    status, batch_id: batch.id, ui_target: 'model_manager', target: batch.target,
    model_result: { [batch.target]: 'success' }, done_count: 1, total_count: 1, remaining_batch_count: 1 });

  const queued = await state();
  // the first model has been downloaded and its batch ends; the second is still downloading
  await report(first, 'in_progress');
  await report(first, 'batch-done');
  await page.waitForTimeout(700);
  // Starting an install opens ComfyUI's log panel; close it again, on both sides, before the capture.
  await page.evaluate(async () => {
    const { app } = await import('/scripts/app.js');
    const panel = app.extensionManager.bottomPanel;
    if (panel.bottomPanelVisible) panel.toggleBottomPanelTab(panel.activeBottomPanelTab.id);
  });
  await page.waitForTimeout(400);
  const afterFirst = await state();
  const name = 'model-batch-first-ended';
  if (RUN === '1') {
    await page.screenshot({ path: path.join(OUT, `${name}.${SIDE}.png`) });
    fs.writeFileSync(path.join(OUT, `${name}.${SIDE}.json`), JSON.stringify({ file: `${name}.${SIDE}.png`, side: SIDE, ...afterFirst }, null, 1));
  }
  // the second batch ends
  await report(second, 'in_progress');
  await report(second, 'batch-done');
  await page.waitForTimeout(700);
  const afterSecond = await state();
  fs.writeFileSync(path.join(OUT, `${name}.${SIDE}.run${RUN}.json`), JSON.stringify({ side: SIDE, run: RUN,
    queued: queued.observed, afterFirst: afterFirst.observed, afterSecond: afterSecond.observed, pageErrors: errors }, null, 1));
});
