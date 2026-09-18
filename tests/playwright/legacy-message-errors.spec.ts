import { test, expect } from '@playwright/test';
import {
  waitForComfyUI, openManagerMenu, openCustomNodesManager, openModelManager,
  routeNodeList, routeModelList, makePack, makeModel, serverSanitizeTag, XSS_PAYLOAD,
} from './helpers';

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
        return !!module[exported].instance.install_context;
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
      return !!module[exported].instance.install_context;
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
        return !!module[exported].instance.install_context;
      }, { file, exported })).toBe(true);

      await page.evaluate(async detail => {
        const { api } = await import('/scripts/api.js');
        api.dispatchEvent(new CustomEvent('cm-queue-status', { detail }));
      }, completion!);
      await expect(page.locator(`.${prefix}-manager-stop`)).toBeHidden();
      await expect(page.locator(`.${prefix}-btn-loading`)).toHaveCount(0);
      expect(await page.evaluate(async ({ file, exported }) => {
        const module = await import(`/extensions/comfyui-manager-legacy/${file}.js`);
        return !!module[exported].instance.install_context;
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
        () => manager.getAlternatives(),
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
  expect(results).toHaveLength(3);
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
