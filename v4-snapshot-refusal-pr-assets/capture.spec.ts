// Throwaway capture script: not part of any PR. SIDE=red|green names the JS being served.
import * as fs from 'fs';
import * as path from 'path';
import { test, expect, type Page, type Locator } from '@playwright/test';
import {
  waitForComfyUI, openManagerMenu, clickMenuButton, openCustomNodesManager, openModelManager,
  routeNodeList, routeMappings, routeModelList, makePack, makeModel,
} from '../../wt/tests/playwright/helpers';

const SIDE = process.env.SIDE!;
const OUT = path.resolve(__dirname, '..', 'screens');
test.use({ viewport: { width: 1440, height: 900 } });

async function box(locator: Locator) {
  const b = await locator.first().boundingBox();
  return b && { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
}
const RUN = process.env.RUN || '1';
async function shot(page: Page, name: string, record: Record<string, unknown>) {
  const file = `${name}.${SIDE}.png`;
  if (RUN === '1') {
    await page.screenshot({ path: path.join(OUT, file) });
    fs.writeFileSync(path.join(OUT, `${name}.${SIDE}.json`), JSON.stringify({ file, side: SIDE, ...record }, null, 1));
  }
  fs.writeFileSync(path.join(OUT, `${name}.${SIDE}.run${RUN}.json`), JSON.stringify({ side: SIDE, run: RUN, ...record }, null, 1));
}

test('3434 node preview', async ({ page }) => {
  await page.goto('/');
  await waitForComfyUI(page);
  await routeNodeList(page, { h: makePack('h', { title: 'Prompt Tools' }) });
  await routeMappings(page, { 'https://github.com/example/h': [['LoRA Tag Loader'], { title_aux: 'Prompt Tools' }] });
  await page.route('**/object_info', (route) => route.fulfill({ json: {
    'LoRA Tag Loader': {
      name: 'LoRA Tag Loader <beta>',
      description: 'Reads <lora:name:weight> tags & returns the prompt without them.',
      input: { required: {
        'image <RGB>': ['IMAGE'],
        'prompt': ['STRING', { default: '<lora:detail:0.8>, 1girl & fennec ears' }],
        'notes <optional>': ['STRING', { multiline: true }],
        'max tags <int>': ['INT', { default: 3 }],
      } },
      input_order: { required: ['image <RGB>', 'prompt', 'notes <optional>', 'max tags <int>'] },
      output: ['STRING'], output_name: ['text<out>'], output_is_list: [false],
    },
  } }));
  const definitions = page.waitForResponse('**/object_info');
  await openManagerMenu(page);
  await openCustomNodesManager(page);
  await definitions;
  const nodesCell = page.locator('.cn-manager-grid .cn-pack-nodes').first();
  await expect(nodesCell).toBeVisible({ timeout: 15_000 });
  await nodesCell.click();
  await page.waitForSelector('.cn-flyover', { state: 'visible', timeout: 10_000 });
  await page.locator('.cn-flyover .cn-nodes-name').first().hover();
  const preview = page.locator('.cn-preview');
  await expect(preview).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(500);
  const observed = await preview.evaluate((el) => ({
    text: (el as HTMLElement).innerText.split('\n').map((line) => line.trim()).filter(Boolean),
    elementsBuiltFromTheDefinition: [...el.querySelectorAll('*')]
      .filter((e) => !/(^|\s)cn-/.test((e as HTMLElement).className || '') && e.tagName !== 'BR' && e.tagName !== 'DIV')
      .map((e) => e.tagName.toLowerCase()),
  }));
  await shot(page, '3434-preview', { boxes: { preview: await box(preview) }, observed });
});

test('3436 refused restore', async ({ page }) => {
  await page.goto('/');
  await waitForComfyUI(page);
  const before: string[] = (await (await page.request.get('/v2/snapshot/getlist')).json()).items;
  expect((await page.request.post('/v2/snapshot/save')).ok()).toBe(true);
  const after: string[] = (await (await page.request.get('/v2/snapshot/getlist')).json()).items;
  const name = after.find((n) => !before.includes(n))!;
  await openManagerMenu(page);
  await clickMenuButton(page, 'Snapshot Manager');
  await page.waitForSelector('#snapshot-manager-dialog', { timeout: 10_000 });
  const row = page.locator('#snapshot-manager-dialog tr', { hasText: name }).first();
  await expect(row).toBeVisible();
  // The snapshot disappears from the disk after the list was shown, so the server refuses the restore.
  expect((await page.request.post(`/v2/snapshot/remove?target=${encodeURIComponent(name)}`)).ok()).toBe(true);
  const response = page.waitForResponse('**/v2/snapshot/restore**');
  await row.locator('button:has-text("Restore")').click();
  const answered = await response;
  const answer = { status: answered.status(), body: await answered.text() };
  await page.waitForTimeout(1_000);
  const dialog = await page.evaluateHandle(async () => (await import('/scripts/app.js')).app.ui.dialog.element);
  const dialogText = await dialog.evaluate((el: HTMLElement) => el.innerText.replace(/\s*Close\s*$/, '').trim());
  await shot(page, '3436-restore-message', {
    boxes: { message: await box(page.locator('.comfy-modal:visible').last()) },
    observed: { serverAnswer: answer, message: dialogText.replace(name, '<snapshot name>') },
  });
  await page.locator('.comfy-modal:visible button:has-text("Close")').last().click();
  await page.waitForTimeout(500);
  const box_ = page.locator('#snapshot-manager-dialog #custom-download-message');
  await box_.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await shot(page, '3436-restore-after', {
    boxes: { notice: await box(box_) },
    observed: { restartButtons: await page.locator('#cm-reboot-button2').count(),
                messageArea: (await box_.innerText()).trim() },
  });
});

for (const kind of ['models', 'nodes']) {
  test(`3437 ${kind} batch`, async ({ page }) => {
    const prefix = kind === 'nodes' ? 'cn' : 'cmm';
    const file = kind === 'nodes' ? 'custom-nodes-manager' : 'model-manager';
    const exported = kind === 'nodes' ? 'CustomNodesManager' : 'ModelManager';
    await page.goto('/');
    await waitForComfyUI(page);
    if (kind === 'nodes') {
      await routeNodeList(page, { first: makePack('first', { version: 'unknown' }), second: makePack('second', { version: 'unknown' }) });
    } else {
      await routeModelList(page, [makeModel('first'), makeModel('second')]);
    }
    let batch: any;
    await page.route('**/v2/manager/queue/batch', async (route) => {
      batch = route.request().postDataJSON();
      await route.fulfill({ json: { failed: [] } });
    });
    await openManagerMenu(page);
    await (kind === 'nodes' ? openCustomNodesManager(page) : openModelManager(page));
    await page.evaluate(async ({ file, exported, kind, prefix }) => {
      const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
      const manager = module[exported].instance;
      const showStatus = manager.showStatus.bind(manager);
      (window as any).__statuses = [];
      manager.showStatus = (msg: string, color?: string) => { (window as any).__statuses.push(msg); showStatus(msg, color); };
      const button = manager.element.querySelector(`.${prefix}-btn-install`);
      if (kind === 'nodes') {
        await manager.installNodes(Object.values(manager.custom_nodes).map((item: any) => item.hash),
          { target: button, label: 'Install', mode: 'install' });
      } else {
        await manager.installModels(manager.modelList, button);
      }
    }, { file, exported, kind, prefix });
    await expect(page.locator(`.${prefix}-manager-stop`)).toBeVisible();
    const state = () => page.evaluate(async ({ file, exported, prefix }) => {
      const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
      const manager = module[exported].instance;
      const visible = (selector: string) => {
        const el = manager.element.querySelector(selector) as HTMLElement | null;
        return !!el && getComputedStyle(el).display !== 'none';
      };
      return {
        installPending: !!manager.install_context,
        stopButtonShown: visible(`.${prefix}-manager-stop`),
        message: (manager.element.querySelector(`.${prefix}-manager-message`) as HTMLElement).innerText.trim(),
        statusMessages: [...(window as any).__statuses],
      };
    }, { file, exported, prefix });
    const dispatch = (detail: unknown) => page.evaluate(async (detail) => {
      const { api } = await import('/scripts/api.js');
      api.dispatchEvent(new CustomEvent('cm-queue-status', { detail }));
    }, detail);
    const items = batch[kind === 'nodes' ? 'install' : 'install_model'];
    await page.evaluate(() => { (window as any).__statuses = []; });

    // 1. another batch finishes first: it carries no result for this manager
    await dispatch({ status: 'batch-done', batch_id: 'another-batch', done_count: 1, total_count: 1,
      nodepack_result: kind === 'nodes' ? {} : { other: 'success' }, model_result: kind === 'models' ? {} : { other: 'success' } });
    await page.waitForTimeout(700);
    const afterOther = await state();
    if (kind === 'models') {
      // Starting an install opens ComfyUI's log panel; close it again, on both sides, before the capture.
      await page.evaluate(async () => {
        const { app } = await import('/scripts/app.js');
        const panel = app.extensionManager.bottomPanel;
        if (panel.bottomPanelVisible) panel.toggleBottomPanelTab(panel.activeBottomPanelTab.id);
      });
      await page.waitForTimeout(400);
      await shot(page, '3437-models-other-batch', {
        boxes: { footer: await box(page.locator('.cmm-manager-footer, .cmm-manager-message').first()),
                 grid: await box(page.locator('.cmm-manager-grid')) },
        observed: afterOther });
    }
    // 2. this manager's own batch finishes
    await page.evaluate(() => { (window as any).__statuses = []; });
    await dispatch({ status: 'batch-done', batch_id: batch.batch_id, done_count: 2, total_count: 2,
      nodepack_result: kind === 'nodes' ? Object.fromEntries(items.map((i: any) => [i.ui_id, 'success'])) : {},
      model_result: kind === 'models' ? Object.fromEntries(items.map((i: any) => [i.ui_id, 'success'])) : {} });
    await page.waitForTimeout(700);
    const afterOwn = await state();
    fs.writeFileSync(path.join(OUT, `3437-${kind}.${SIDE}.run${RUN}.json`), JSON.stringify({ side: SIDE, run: RUN, afterOther, afterOwn }, null, 1));
  });
}
