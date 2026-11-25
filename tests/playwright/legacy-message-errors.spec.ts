import { test, expect, type Page } from '@playwright/test';
import {
  waitForComfyUI, openManagerMenu, openCustomNodesManager, openModelManager,
  routeNodeList, routeModelList, makePack, makeModel, serverSanitizeTag, XSS_PAYLOAD,
} from './helpers';

/** The grid replaces the status line with its row count as soon as it redraws, so record the
 *  texts that the manager passes to it; read them from `window.__statuses`. */
async function recordStatuses(page: Page, file: string, exported: string) {
  await page.evaluate(async ({ file, exported }) => {
    const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
    const manager = module[exported].instance;
    const showStatus = manager.showStatus.bind(manager);
    (window as any).__statuses = [];
    manager.showStatus = (msg: string, color?: string) => {
      (window as any).__statuses.push(msg);
      showStatus(msg, color);
    };
  }, { file, exported });
}

for (const kind of ['nodes', 'models']) {
  const prefix = kind === 'nodes' ? 'cn' : 'cmm';
  const file = kind === 'nodes' ? 'custom-nodes-manager' : 'model-manager';
  const exported = kind === 'nodes' ? 'CustomNodesManager' : 'ModelManager';

  for (const failure of ['network', 'http', 'json', 'shape']) {
    test(`${kind}: ${failure} batch failure clears pending controls`, async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(String(error)));
      await page.goto('/');
      await waitForComfyUI(page);
      if (kind === 'nodes') {
        await routeNodeList(page, { victim: makePack('victim', { version: 'unknown' }) });
      } else {
        await routeModelList(page, [makeModel('victim')]);
      }
      await page.route('**/v2/manager/queue/batch', async route => {
        if (failure === 'network') return route.abort('failed');
        if (failure === 'http') return route.fulfill({ status: 500, json: { failed: [] } });
        if (failure === 'json') return route.fulfill({ contentType: 'application/json', body: 'invalid' });
        return route.fulfill({ json: { failed: {} } });
      });
      await openManagerMenu(page);
      await (kind === 'nodes' ? openCustomNodesManager(page) : openModelManager(page));
      await page.locator(`.${prefix}-manager-grid .${prefix}-btn-install`).first().click();
      await expect(page.locator(`.${prefix}-manager-message`)).toContainText('Failed to submit installation request');
      await expect(page.locator(`.${prefix}-manager-stop`)).toBeHidden();
      await expect(page.locator(`.${prefix}-btn-loading`)).toHaveCount(0);
      expect(await page.evaluate(async ({ file, exported }) => {
        const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
        const manager = module[exported].instance;
        // The Model Manager keeps one pending install for each batch.
        return manager.install_contexts ? manager.install_contexts.size > 0 : !!manager.install_context;
      }, { file, exported })).toBe(false);
      expect(errors).toEqual([]);
    });
  }

  test(`${kind}: rejected batch names and unknown IDs reach both error displays safely`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto('/');
    await waitForComfyUI(page);
    const title = serverSanitizeTag('Pack &amp; Friends ' + XSS_PAYLOAD);
    if (kind === 'nodes') {
      await routeNodeList(page, { victim: makePack('victim', { title, version: 'unknown' }) });
    } else {
      await routeModelList(page, [makeModel(title)]);
    }
    await page.route('**/v2/manager/queue/batch', async route => {
      const batch = route.request().postDataJSON();
      const items = batch[kind === 'nodes' ? 'install' : 'install_model'];
      expect(items[0].id).toBeTruthy();
      // The socket event may arrive before the HTTP rejection response.
      await page.evaluate(async () => {
        const { api } = await import('/scripts/api.js');
        api.dispatchEvent(new CustomEvent('cm-queue-status', { detail: { status: 'all-done' } }));
      });
      await route.fulfill({ json: { failed: [items[0].id, XSS_PAYLOAD] } });
    });
    await openManagerMenu(page);
    await (kind === 'nodes' ? openCustomNodesManager(page) : openModelManager(page));
    if (kind === 'models') {
      await page.locator('.cmm-manager-type').evaluate(select => select.setAttribute('disabled', ''));
    }
    await page.locator(`.${prefix}-manager-grid .${prefix}-btn-install`).first().click();
    const message = page.locator(`.${prefix}-manager-message`);
    await expect(message).toContainText('[FAIL] Pack & Friends ' + XSS_PAYLOAD);
    await expect(message).toContainText('[FAIL] ' + XSS_PAYLOAD);
    expect(await message.locator('img').count()).toBe(0);
    const dialog = await page.evaluate(async () => {
      const { app } = await import('/scripts/app.js');
      return { text: app.ui.dialog.element.textContent, images: app.ui.dialog.element.querySelectorAll('img').length };
    });
    expect(dialog.text).toContain('[FAIL] Pack & Friends ' + XSS_PAYLOAD);
    expect(dialog.text).toContain('[FAIL] ' + XSS_PAYLOAD);
    expect(dialog.images).toBe(0);
    await expect(page.locator(`.${prefix}-manager-stop`)).toBeHidden();
    await expect(page.locator(`.${prefix}-btn-loading`)).toHaveCount(0);
    if (kind === 'models') {
      await expect(page.locator('.cmm-manager-type')).toBeDisabled();
    }
    expect(await page.evaluate(async ({ file, exported }) => {
      const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
      const manager = module[exported].instance;
      return manager.install_contexts ? manager.install_contexts.size > 0 : !!manager.install_context;
    }, { file, exported })).toBe(false);
    expect(await page.evaluate(() => (window as any).__xss_fired)).toBeUndefined();
    expect(errors).toEqual([]);
  });

  for (const rejectedCount of [0, 1]) {
    test(`${kind}: ${rejectedCount} rejections keep accepted work pending until completion`, async ({ page }) => {
      await page.goto('/');
      await waitForComfyUI(page);
      if (kind === 'nodes') {
        await routeNodeList(page, {
          first: makePack('first', { version: 'unknown' }),
          second: makePack('second', { version: 'unknown' }),
        });
      } else {
        await routeModelList(page, [makeModel('first'), makeModel('second')]);
      }
      let completion: Record<string, unknown>;
      await page.route('**/v2/manager/queue/batch', async route => {
        const batch = route.request().postDataJSON();
        const items = batch[kind === 'nodes' ? 'install' : 'install_model'];
        const result = Object.fromEntries(items.slice(rejectedCount).map(item => [item.ui_id, 'success']));
        completion = { status: 'batch-done', batch_id: batch.batch_id,
          nodepack_result: kind === 'nodes' ? result : {}, model_result: kind === 'models' ? result : {},
          done_count: items.length - rejectedCount, total_count: items.length - rejectedCount };
        await route.fulfill({ json: { failed: items.slice(0, rejectedCount).map(item => item.id) } });
      });
      await openManagerMenu(page);
      await (kind === 'nodes' ? openCustomNodesManager(page) : openModelManager(page));
      await page.evaluate(async ({ file, exported, kind, prefix }) => {
        const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
        const manager = module[exported].instance;
        const button = manager.element.querySelector(`.${prefix}-btn-install`);
        if (kind === 'nodes') {
          await manager.installNodes(Object.values(manager.custom_nodes).map((item: any) => item.hash),
            { target: button, label: 'Install', mode: 'install' });
        } else {
          await manager.installModels(manager.modelList, button);
        }
      }, { file, exported, kind, prefix });
      await expect(page.locator(`.${prefix}-manager-stop`)).toBeVisible();
      expect(await page.evaluate(async ({ file, exported }) => {
        const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
        const manager = module[exported].instance;
        // The Model Manager keeps one pending install for each batch.
        return manager.install_contexts ? manager.install_contexts.size > 0 : !!manager.install_context;
      }, { file, exported })).toBe(true);

      // A batch that carries no result for this manager is another manager's batch.
      await page.evaluate(async detail => {
        const { api } = await import('/scripts/api.js');
        api.dispatchEvent(new CustomEvent('cm-queue-status', { detail }));
      }, { status: 'batch-done', batch_id: 'another-batch', nodepack_result: kind === 'nodes' ? {} : { other: 'success' },
        model_result: kind === 'models' ? {} : { other: 'success' }, done_count: 1, total_count: 1 });
      expect(await page.evaluate(async ({ file, exported }) => {
        const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
        const manager = module[exported].instance;
        // The Model Manager keeps one pending install for each batch.
        return manager.install_contexts ? manager.install_contexts.size > 0 : !!manager.install_context;
      }, { file, exported })).toBe(true);

      await recordStatuses(page, file, exported);
      await page.evaluate(async detail => {
        const { api } = await import('/scripts/api.js');
        api.dispatchEvent(new CustomEvent('cm-queue-status', { detail }));
      }, completion!);
      await expect(page.locator(`.${prefix}-manager-stop`)).toBeHidden();
      await expect(page.locator(`.${prefix}-btn-loading`)).toHaveCount(0);
      expect(await page.evaluate(() => (window as any).__statuses)).toContain(
        `Install ${2 - rejectedCount} ${kind === 'nodes' ? 'custom node(s)' : 'models'} successfully`);
      expect(await page.evaluate(async ({ file, exported }) => {
        const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
        const manager = module[exported].instance;
        // The Model Manager keeps one pending install for each batch.
        return manager.install_contexts ? manager.install_contexts.size > 0 : !!manager.install_context;
      }, { file, exported })).toBe(false);
    });
  }

  test(`${kind}: HTML messages preserve names and assign color through the DOM`, async ({ page }) => {
    await page.goto('/');
    await waitForComfyUI(page);
    const wire = serverSanitizeTag('Pack &amp; Friends <Flux>');
    const result = await page.evaluate(async ({ file, exported, prefix, wire }) => {
      const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
      const manager = Object.create(module[exported].prototype);
      manager.element = document.createElement('div');
      manager.element.innerHTML = `<div class="${prefix}-manager-message"></div><div class="${prefix}-manager-status"></div>`;
      document.body.append(manager.element);
      manager.showMessage(wire, 'rgb(1, 2, 3)');
      manager.showStatus(wire, '"><img src=x onerror="window.__xss_fired=1">');
      const [message, status] = manager.element.children;
      const result = { message: message.textContent, status: status.textContent,
        color: message.style.color, children: status.children.length };
      manager.showMessage('done');
      return { ...result, resetColor: message.style.color };
    }, { file, exported, prefix, wire });
    expect(result).toEqual({ message: 'Pack & Friends <Flux>', status: 'Pack & Friends <Flux>',
      color: 'rgb(1, 2, 3)', children: 0, resetColor: '' });
  });
}

for (const outcome of ['success', 'failure']) {
  test(`models: only the active batch can update progress and complete (${outcome})`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(String(error)));
    await page.goto('/');
    await waitForComfyUI(page);
    await routeModelList(page, [makeModel('victim')]);

    let batch: { batch_id: string; install_model: { ui_id: string }[] };
    await page.route('**/v2/manager/queue/batch', async route => {
      batch = route.request().postDataJSON();
      await route.fulfill({ json: { failed: [] } });
    });
    await openManagerMenu(page);
    await openModelManager(page);
    await page.evaluate(async () => {
      const { ModelManager } = await import('/extensions/comfyui-manager-legacy/model-manager.js');
      const manager = ModelManager.instance;
      const button = manager.element.querySelector('.cmm-btn-install');
      await manager.installModels(manager.modelList, button);
    });
    await expect(page.locator('.cmm-manager-stop')).toBeVisible();

    const target = batch!.install_model[0].ui_id;
    const status = (batchId: string, state: string, modelResult: Record<string, string>) => ({
      status: state, batch_id: batchId, ui_target: 'model_manager', target,
      model_result: modelResult, done_count: 1, total_count: 1,
    });
    const dispatch = async (detail: ReturnType<typeof status>) => {
      await page.evaluate(async value => {
        const { api } = await import('/scripts/api.js');
        api.dispatchEvent(new CustomEvent('cm-queue-status', { detail: value }));
      }, detail);
    };
    const state = () => page.evaluate(async hash => {
      const { ModelManager } = await import('/extensions/comfyui-manager-legacy/model-manager.js');
      const manager = ModelManager.instance;
      const pending = manager.install_contexts ? manager.install_contexts.size > 0 : !!manager.install_context;
      return { pending, refresh: !!manager.grid.getRowItemBy('hash', hash)?.refresh };
    }, target);

    await dispatch(status('other-batch', 'in_progress', {}));
    expect(await state()).toEqual({ pending: true, refresh: false });
    await dispatch(status('other-batch', 'batch-done', { [target]: 'success' }));
    await expect(page.locator('.cmm-manager-stop')).toBeVisible();
    expect(await state()).toEqual({ pending: true, refresh: false });

    await dispatch(status(batch!.batch_id, 'in_progress', {}));
    expect(await state()).toEqual({ pending: true, refresh: true });
    const result = { [target]: outcome === 'success' ? 'success' : 'download failed' };
    await recordStatuses(page, 'model-manager', 'ModelManager');
    await dispatch(status(batch!.batch_id, 'batch-done', result));
    await expect(page.locator('.cmm-manager-stop')).toBeHidden();
    expect((await state()).pending).toBe(false);
    const statuses = await page.evaluate(() => (window as any).__statuses);
    const refresh = "To apply the installed model, please click the 'Refresh' button.";
    if (outcome === 'success') {
      expect(statuses).toContain('Install 1 models successfully');
      await expect(page.locator('.cmm-manager-message')).toContainText(refresh);
    } else {
      await expect(page.locator('.cmm-manager-message')).toContainText('download failed');
      await expect(page.locator('.cmm-manager-message')).not.toContainText(refresh);
    }

    await dispatch(status(batch!.batch_id, 'batch-done', { [target]: 'success' }));
    expect((await state()).pending).toBe(false);
    expect(errors).toEqual([]);
  });
}

type PostedBatch = { batch_id: string; install_model: { ui_id: string }[] };

/** Answer the Model Manager's question whether the queue is running. The batch request is replaced
 *  in these cases, so the real server never has the batch in its queue. */
async function routeQueueStatus(page: Page, isProcessing: boolean) {
  await page.route('**/v2/manager/queue/status', route => route.fulfill({
    json: { total_count: 0, done_count: 0, in_progress_count: 0, is_processing: isProcessing },
  }));
}

/** Keep the Model Manager's checks of the queue, so that a case can wait until they have finished. */
async function recordQueueChecks(page: Page) {
  await page.evaluate(async () => {
    const { ModelManager } = await import('/extensions/comfyui-manager-legacy/model-manager.js');
    const manager = ModelManager.instance;
    const check = manager.endDroppedInstalls.bind(manager);
    (window as any).__queueChecks = [];
    manager.endDroppedInstalls = () => {
      const finished = check();
      (window as any).__queueChecks.push(finished);
      return finished;
    };
  });
}

/** Resolve once every check of the queue that was started has handled its answer. */
async function queueChecked(page: Page) {
  await page.evaluate(async () => {
    const checks = (window as any).__queueChecks;
    if (checks.length === 0) throw new Error('The queue was not checked');
    await Promise.all(checks);
  });
}

/** Start one install for each of the listed models, as clicking Install in their rows does one after
 *  the other; resolve with the id and the target of each batch that was posted. */
async function installEachModel(page: Page, onBatchPosted?: (batch: PostedBatch) => Promise<void>) {
  const batches: PostedBatch[] = [];
  await page.route('**/v2/manager/queue/batch', async route => {
    batches.push(route.request().postDataJSON());
    await onBatchPosted?.(batches.at(-1)!);
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
  return batches.map(batch => ({ id: batch.batch_id, target: batch.install_model[0].ui_id }));
}

async function dispatchQueueStatus(page: Page, detail: Record<string, unknown>) {
  await page.evaluate(async value => {
    const { api } = await import('/scripts/api.js');
    api.dispatchEvent(new CustomEvent('cm-queue-status', { detail: value }));
  }, detail);
}

/** How many installs are pending, and which of the given rows are marked as downloaded. */
async function modelInstallState(page: Page, targets: string[]) {
  return page.evaluate(async hashes => {
    const { ModelManager } = await import('/extensions/comfyui-manager-legacy/model-manager.js');
    const manager = ModelManager.instance;
    return {
      // A manager that keeps one install only has one pending at most.
      pending: manager.install_contexts ? manager.install_contexts.size : (manager.install_context ? 1 : 0),
      downloaded: hashes.map(hash => !!manager.grid.getRowItemBy('hash', hash)?.refresh),
    };
  }, targets);
}

test('models: each of two installs started in a row ends with its own batch', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.goto('/');
  await waitForComfyUI(page);
  await routeModelList(page, [makeModel('first'), makeModel('second')]);
  const [first, second] = await installEachModel(page);
  const targets = [first.target, second.target];
  await expect(page.locator('.cmm-manager-stop')).toBeVisible();
  await expect(page.locator('.cmm-btn-loading')).toHaveCount(2);
  expect(await modelInstallState(page, targets)).toEqual({ pending: 2, downloaded: [false, false] });

  const report = (batch: { id: string; target: string }, status: string) => dispatchQueueStatus(page, {
    status, batch_id: batch.id, ui_target: 'model_manager', target: batch.target,
    model_result: { [batch.target]: 'success' }, done_count: 1, total_count: 1,
  });
  await report(first, 'in_progress');
  await report(first, 'batch-done');
  await expect(page.locator('.cmm-manager-stop')).toBeVisible();
  await expect(page.locator('.cmm-btn-loading')).toHaveCount(1);
  expect(await modelInstallState(page, targets)).toEqual({ pending: 1, downloaded: [true, false] });

  await report(second, 'in_progress');
  await report(second, 'batch-done');
  await expect(page.locator('.cmm-manager-stop')).toBeHidden();
  await expect(page.locator('.cmm-btn-loading')).toHaveCount(0);
  expect(await modelInstallState(page, targets)).toEqual({ pending: 0, downloaded: [true, true] });
  expect(errors).toEqual([]);
});

test('models: a queue that ends without the batch returns the install to idle', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.goto('/');
  await waitForComfyUI(page);
  await routeModelList(page, [makeModel('first'), makeModel('second')]);
  // Stop empties the queue: the task that is running ends, and then only the end of the queue is reported.
  await routeQueueStatus(page, false);
  const [first, second] = await installEachModel(page);
  const targets = [first.target, second.target];
  await dispatchQueueStatus(page, { status: 'in_progress', batch_id: first.id, ui_target: 'model_manager', target: first.target });
  expect(await modelInstallState(page, targets)).toEqual({ pending: 2, downloaded: [true, false] });

  await dispatchQueueStatus(page, { status: 'all-done' });
  await expect(page.locator('.cmm-manager-stop')).toBeHidden();
  await expect(page.locator('.cmm-btn-loading')).toHaveCount(0);
  expect(await modelInstallState(page, targets)).toEqual({ pending: 0, downloaded: [true, false] });
  await expect(page.locator('.cmm-manager-message')).toContainText("To apply the installed model, please click the 'Refresh' button.");
  expect(errors).toEqual([]);
});

test('models: a stopped queue that downloaded nothing asks for no refresh', async ({ page }) => {
  await page.goto('/');
  await waitForComfyUI(page);
  await routeModelList(page, [makeModel('victim')]);
  await routeQueueStatus(page, false);
  const [batch] = await installEachModel(page);
  await expect(page.locator('.cmm-manager-stop')).toBeVisible();

  await dispatchQueueStatus(page, { status: 'all-done' });
  await expect(page.locator('.cmm-manager-stop')).toBeHidden();
  await expect(page.locator('.cmm-btn-loading')).toHaveCount(0);
  expect(await modelInstallState(page, [batch.target])).toEqual({ pending: 0, downloaded: [false] });
  await expect(page.locator('.cmm-manager-message')).toHaveText('');
  await expect(page.locator('.cmm-manager-refresh')).toBeHidden();
});

test('models: the end of an earlier queue does not end an install that is being queued', async ({ page }) => {
  await page.goto('/');
  await waitForComfyUI(page);
  await routeModelList(page, [makeModel('victim')]);
  // The report of the queue that ran before reaches the page while the batch is still being posted.
  // The batch is then added to the queue and runs.
  await routeQueueStatus(page, true);
  let asked = 0;
  page.on('request', request => { if (request.url().endsWith('/v2/manager/queue/status')) asked++; });
  const [batch] = await installEachModel(page, async () => {
    await recordQueueChecks(page);
    await dispatchQueueStatus(page, { status: 'all-done' });
  });
  await queueChecked(page);
  expect(asked).toBe(1);
  await expect(page.locator('.cmm-manager-stop')).toBeVisible();
  expect(await modelInstallState(page, [batch.target])).toEqual({ pending: 1, downloaded: [false] });
});

test('models: an install that was dropped while it was being queued returns to idle', async ({ page }) => {
  await page.goto('/');
  await waitForComfyUI(page);
  await routeModelList(page, [makeModel('victim')]);
  // Stop emptied the queue after the batch was added to it, and the end of the queue is reported
  // before the answer to the batch request arrives.
  await routeQueueStatus(page, false);
  const [batch] = await installEachModel(page, () => dispatchQueueStatus(page, { status: 'all-done' }));
  await expect(page.locator('.cmm-manager-stop')).toBeHidden();
  await expect(page.locator('.cmm-btn-loading')).toHaveCount(0);
  expect(await modelInstallState(page, [batch.target])).toEqual({ pending: 0, downloaded: [false] });
});

test('models: the end of an earlier queue does not end an install that is running', async ({ page }) => {
  await page.goto('/');
  await waitForComfyUI(page);
  await routeModelList(page, [makeModel('victim')]);
  // The report of the queue that ran before reaches the page after the answer to the batch request.
  await routeQueueStatus(page, true);
  const [batch] = await installEachModel(page);
  await recordQueueChecks(page);
  await dispatchQueueStatus(page, { status: 'all-done' });
  await queueChecked(page);
  await expect(page.locator('.cmm-manager-stop')).toBeVisible();
  await expect(page.locator('.cmm-btn-loading')).toHaveCount(1);
  expect(await modelInstallState(page, [batch.target])).toEqual({ pending: 1, downloaded: [false] });

  await dispatchQueueStatus(page, { status: 'batch-done', batch_id: batch.id,
    model_result: { [batch.target]: 'success' }, done_count: 1, total_count: 1 });
  await expect(page.locator('.cmm-manager-stop')).toBeHidden();
  expect(await modelInstallState(page, [batch.target])).toEqual({ pending: 0, downloaded: [false] });
});

test('models: an install stays pending when the queue cannot be asked', async ({ page }) => {
  await page.goto('/');
  await waitForComfyUI(page);
  await routeModelList(page, [makeModel('victim')]);
  // Without an answer the queue may still be running the batch.
  await page.route('**/v2/manager/queue/status', route => route.fulfill({ status: 500, body: 'error' }));
  const [batch] = await installEachModel(page);
  await recordQueueChecks(page);
  await dispatchQueueStatus(page, { status: 'all-done' });
  await queueChecked(page);
  await expect(page.locator('.cmm-manager-stop')).toBeVisible();
  expect(await modelInstallState(page, [batch.target])).toEqual({ pending: 1, downloaded: [false] });

  // The next report of the end of the queue that can be checked ends it.
  await page.unroute('**/v2/manager/queue/status');
  await routeQueueStatus(page, false);
  await dispatchQueueStatus(page, { status: 'all-done' });
  await expect(page.locator('.cmm-manager-stop')).toBeHidden();
  expect(await modelInstallState(page, [batch.target])).toEqual({ pending: 0, downloaded: [false] });
});

test('models: a batch that ends before its request is answered completes the install', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.goto('/');
  await waitForComfyUI(page);
  await routeModelList(page, [makeModel('victim')]);
  const [batch] = await installEachModel(page, posted => dispatchQueueStatus(page, {
    status: 'batch-done', batch_id: posted.batch_id,
    model_result: { [posted.install_model[0].ui_id]: 'download failed' }, done_count: 1, total_count: 1,
  }));
  await expect(page.locator('.cmm-manager-message')).toContainText('download failed');
  await expect(page.locator('.cmm-manager-stop')).toBeHidden();
  await expect(page.locator('.cmm-btn-loading')).toHaveCount(0);
  expect(await modelInstallState(page, [batch.target])).toEqual({ pending: 0, downloaded: [false] });
  expect(errors).toEqual([]);
});

test('nodes: lookup errors and missing row IDs remain literal text', async ({ page }) => {
  await page.goto('/');
  await waitForComfyUI(page);
  const results = await page.evaluate(async payload => {
    const { CustomNodesManager } = await import('/extensions/comfyui-manager-legacy/custom-nodes-manager.js');
    const common = await import('/extensions/comfyui-manager-legacy/common.js');
    const { api } = await import('/scripts/api.js');
    const manager = Object.create(CustomNodesManager.prototype);
    manager.element = document.createElement('div');
    manager.element.innerHTML = '<div class="cn-manager-message"></div><div class="cn-manager-status"></div>';
    document.body.append(manager.element);
    manager.grid = { getRowItemBy: () => undefined, updateCell: () => { throw new Error('Missing row updated'); } };
    const saved = api.fetchApi;
    const previousManager = common.manager_instance;
    common.setManagerInstance({ datasrc_combo: { value: 'cache' } });
    api.fetchApi = async () => ({ status: 500, statusText: payload });
    const results = [];
    try {
      for (const invoke of [
        () => manager.getMissingNodesLegacy({}, new Set()),
        () => manager.installNodes([payload], { target: document.createElement('button'), mode: 'install' }),
      ]) {
        await invoke();
        const message = manager.element.querySelector('.cn-manager-message');
        results.push({ text: message.textContent, images: message.querySelectorAll('img').length });
      }
    } finally {
      api.fetchApi = saved;
      common.setManagerInstance(previousManager);
    }
    return results;
  }, XSS_PAYLOAD);
  expect(results).toHaveLength(2);
  for (const result of results) {
    expect(result.text).toContain(XSS_PAYLOAD);
    expect(result.images).toBe(0);
  }
  expect(await page.evaluate(() => (window as any).__xss_fired)).toBeUndefined();
});

test('nodes: workflow registry IDs remain inert in the Missing Nodes dialog', async ({ page }) => {
  await page.goto('/');
  await waitForComfyUI(page);
  const result = await page.evaluate(async payload => {
    const { app } = await import('/scripts/app.js');
    const { CustomNodesManager } = await import('/extensions/comfyui-manager-legacy/custom-nodes-manager.js');
    const manager = Object.create(CustomNodesManager.prototype);
    manager.custom_nodes = {};
    manager.getMissingNodesLegacy = async () => {};
    const nodes = app.graph._nodes;
    try {
      app.graph._nodes = [{ type: 'MissingTestNode', properties: { cnr_id: payload } }];
      await manager.getMissingNodes();
    } finally {
      app.graph._nodes = nodes;
    }
    const dialog = app.ui.dialog.element;
    return { text: dialog.textContent, images: dialog.querySelectorAll('img').length };
  }, XSS_PAYLOAD + ' &amp; Registry');
  expect(result.images).toBe(0);
  expect(result.text).toContain(XSS_PAYLOAD + ' &amp; Registry');
  expect(await page.evaluate(() => (window as any).__xss_fired)).toBeUndefined();
});
