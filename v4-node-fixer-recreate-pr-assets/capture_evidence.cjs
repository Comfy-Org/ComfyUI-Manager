// Captures the Red/Green screens for "Fix node (recreate)".
// Same steps on both sides; only the served node_fixer.js differs.
//
// usage: node capture_evidence.cjs <playwright-core dir> <base url> <label> <out dir>
//   label: "red" or "green" (names the output files only)
//
// Steps:
//   1. build CheckpointLoaderSimple -> KSampler -> VAEDecode on an empty canvas
//   2. capture                                           -> <label>-1-before.png
//   3. right-click the KSampler title, click "Fix node (recreate)"
//   4. capture                                           -> <label>-2-clicked.png
//   5. click an empty spot of the canvas (closes a context menu left open)
//   6. drag whatever node is at the KSampler title 290px down
//   7. capture                                           -> <label>-3-moved.png
// Step 6 is there because the replacement is created exactly on top of the
// original, so a leftover original cannot be seen without moving the top node.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const [pwDir, baseURL, label, outDir] = process.argv.slice(2);
const { chromium } = require(pwDir);
const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const DRAG_DY = 290;

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: 'en-US' })).newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  await page.goto(baseURL, { waitUntil: 'load' });
  await page.waitForFunction(() => !!window.LiteGraph?.registered_node_types?.KSampler, { timeout: 60_000 });
  await page.waitForTimeout(4000);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);

  const served = await page.evaluate(async () => {
    const text = await (await fetch('/extensions/comfyui-manager-legacy/node_fixer.js')).text();
    return { text, line: text.split('\n').find((l) => l.includes('src_node.connect')).trim() };
  });

  const original = await page.evaluate(() => {
    const { app, LiteGraph } = window;
    const graph = app.canvas.graph;
    graph.clear();
    const add = (type, x) => { const n = LiteGraph.createNode(type); n.pos = [x, 150]; graph.add(n); return n; };
    const loader = add('CheckpointLoaderSimple', 50);
    const sampler = add('KSampler', 500);
    const decoder = add('VAEDecode', 900);
    loader.connect(0, sampler, 'model');
    sampler.connect(0, decoder, 'samples');
    app.canvas.ds.offset = [0, 0];
    app.canvas.ds.scale = 1;
    app.canvas.draw(true, true);
    return { id: sampler.id, idType: typeof sampler.id, x: sampler.pos[0] + 60, y: sampler.pos[1] - LiteGraph.NODE_TITLE_HEIGHT / 2 };
  });
  await page.waitForTimeout(500);

  const readNodes = () => page.evaluate((originalId) => {
    const { app, LiteGraph } = window;
    return app.canvas.graph.nodes.map((n) => ({
      id: n.id, type: n.type,
      isOriginal: n.id === originalId,
      inputsFrom: Object.fromEntries(n.inputs.filter((i) => i.link != null)
        .map((i) => [i.name, n.getInputNode(n.findInputSlot(i.name))?.type ?? null])),
      outputsTo: (n.outputs?.[0] ? n.getOutputNodes(0) ?? [] : []).map((t) => t.type),
      // client-space box including the title bar (canvas at 0,0, scale 1)
      box: [n.pos[0], n.pos[1] - LiteGraph.NODE_TITLE_HEIGHT, n.size[0], n.size[1] + LiteGraph.NODE_TITLE_HEIGHT].map(Math.round),
    }));
  }, original.id);

  const shot = async (name) => {
    const file = path.join(outDir, name);
    await page.screenshot({ path: file });
    return { file: name, sha256: sha256(fs.readFileSync(file)) };
  };

  const before = { nodes: await readNodes(), capture: await shot(`${label}-1-before.png`) };

  await page.mouse.click(original.x, original.y, { button: 'right' });
  await page.locator('.litecontextmenu .litemenu-entry', { hasText: 'Fix node (recreate)' }).click();
  await page.waitForTimeout(500);
  const clicked = {
    contextMenuOpen: await page.locator('.litecontextmenu').count() > 0,
    nodes: await readNodes(),
    capture: await shot(`${label}-2-clicked.png`),
  };

  await page.mouse.click(1000, 520);
  await page.waitForTimeout(300);
  await page.mouse.move(original.x, original.y);
  await page.mouse.down();
  await page.mouse.move(original.x, original.y + DRAG_DY, { steps: 15 });
  await page.mouse.up();
  await page.mouse.move(40, 760);
  await page.waitForTimeout(700);

  const after = { nodes: await readNodes(), capture: await shot(`${label}-3-moved.png`) };

  const result = {
    label,
    capturedAt: new Date().toISOString(),
    baseURL,
    frontend: await page.evaluate(() => window.__COMFYUI_FRONTEND_VERSION__ ?? null),
    viewport: [1280, 800],
    nodeFixer: { sha256: sha256(Buffer.from(served.text, 'utf-8')), connectLine: served.line },
    originalSampler: { id: original.id, idType: original.idType },
    dragDy: DRAG_DY,
    pageErrors,
    before,
    clicked,
    after,
  };
  fs.writeFileSync(path.join(outDir, `${label}.json`), JSON.stringify(result, null, 2) + '\n');
  await browser.close();
  console.log(JSON.stringify({
    label, frontend: result.frontend, idType: original.idType, line: served.line, pageErrors, menuOpenAfterClick: clicked.contextMenuOpen,
    after: after.nodes.map((n) => `${n.type}#${n.id}${n.isOriginal ? '(original)' : ''} in=${JSON.stringify(n.inputsFrom)} out=${JSON.stringify(n.outputsTo)} box=${n.box}`),
  }, null, 1));
})().catch((e) => { console.error(e); process.exit(1); });
