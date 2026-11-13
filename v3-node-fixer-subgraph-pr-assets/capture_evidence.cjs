// Captures the Red/Green screens for "Fix node (recreate)" inside a subgraph.
// Same steps on both sides; only the served node_fixer.js differs.
//
// usage: node capture_evidence.cjs <playwright-core dir> <base url> <label> <out dir>
//   label: "red" or "green" (names the output files only)
//
// Steps:
//   1. build CheckpointLoaderSimple + CLIPTextEncode -> KSampler -> VAEDecode on an empty canvas
//   2. convert the KSampler to a subgraph and open it; its links now go through
//      the subgraph's input and output nodes
//   3. capture                                           -> <label>-1-before.png
//   4. right-click the KSampler title, click "Fix node (recreate)"
//   5. capture                                           -> <label>-2-clicked.png
//   6. click an empty spot of the canvas (closes a context menu left open)
//   7. drag whatever node is at the KSampler title 290px down
//   8. capture                                           -> <label>-3-moved.png
// Step 7 is there because the replacement is created exactly on top of the
// original, so a leftover original cannot be seen without moving the top node.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const [pwDir, baseURL, label, outDir] = process.argv.slice(2);
const { chromium } = require(pwDir);
const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const DRAG_DY = 290;
// Where the KSampler is put, so that the subgraph's input and output nodes are on screen too.
const AT = [800, 330];

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'en-US' })).newPage();
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  await page.goto(baseURL, { waitUntil: 'load' });
  await page.waitForFunction(() => !!window.LiteGraph?.registered_node_types?.KSampler, { timeout: 60_000 });
  await page.waitForTimeout(4000);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);

  const served = await page.evaluate(async () => {
    const text = await (await fetch('/extensions/comfyui-manager/node_fixer.js')).text();
    return { text, line: text.split('\n').find((l) => l.includes('links[input.link]')).trim() };
  });

  await page.evaluate(() => {
    const { app, LiteGraph } = window;
    const graph = app.canvas.graph;
    graph.clear();
    const add = (type, x, y) => { const n = LiteGraph.createNode(type); n.pos = [x, y]; graph.add(n); return n; };
    const loader = add('CheckpointLoaderSimple', 50, 150);
    const prompt = add('CLIPTextEncode', 50, 350);
    const sampler = add('KSampler', 500, 150);
    const decoder = add('VAEDecode', 900, 150);
    loader.connect(0, sampler, 'model');
    prompt.connect(0, sampler, 'positive');
    sampler.connect(0, decoder, 'samples');
    const converted = graph.convertToSubgraph(new Set([sampler]));
    app.canvas.openSubgraph(converted.subgraph, converted.node);
  });
  await page.waitForTimeout(1500);
  const original = await page.evaluate((AT) => {
    const { app, LiteGraph } = window;
    const sampler = app.canvas.graph.nodes.find((n) => n.type === 'KSampler');
    app.canvas.ds.scale = 1;
    app.canvas.ds.offset = [AT[0] - sampler.pos[0], AT[1] - sampler.pos[1]];
    app.canvas.draw(true, true);
    return { id: sampler.id, idType: typeof sampler.id, x: AT[0] + 60, y: AT[1] - LiteGraph.NODE_TITLE_HEIGHT / 2 };
  }, AT);
  await page.waitForTimeout(500);

  const readNodes = () => page.evaluate((originalId) => {
    const { app, LiteGraph } = window;
    const graph = app.canvas.graph;
    const [ox, oy] = app.canvas.ds.offset;
    const origin = ({ origin_id, origin_slot }) => origin_id === graph.inputNode?.id
      ? `subgraph input.${graph.inputNode.slots[origin_slot].name}` : `${graph.getNodeById(origin_id).type}`;
    const target = ({ target_id, target_slot }) => target_id === graph.outputNode?.id
      ? `subgraph output.${graph.outputNode.slots[target_slot].name}` : `${graph.getNodeById(target_id).type}`;
    const rect = (r) => (r ? [r[0] + ox, r[1] + oy, r[2], r[3]].map(Math.round) : null);
    return {
      inSubgraph: graph !== app.graph,
      boundary: { input: rect(graph.inputNode?.boundingRect), output: rect(graph.outputNode?.boundingRect) },
      nodes: graph.nodes.map((n) => ({
        id: n.id, type: n.type, isOriginal: n.id === originalId,
        inputsFrom: Object.fromEntries(n.inputs.filter((i) => i.link != null).map((i) => [i.name, origin(graph.links.get(i.link))])),
        outputsTo: (n.outputs?.[0]?.links ?? []).map((id) => target(graph.links.get(id))),
        box: [n.pos[0] + ox, n.pos[1] + oy - LiteGraph.NODE_TITLE_HEIGHT, n.size[0], n.size[1] + LiteGraph.NODE_TITLE_HEIGHT].map(Math.round),
      })),
    };
  }, original.id);

  const shot = async (name) => {
    const file = path.join(outDir, name);
    await page.screenshot({ path: file });
    return { file: name, sha256: sha256(fs.readFileSync(file)) };
  };

  const before = { ...await readNodes(), capture: await shot(`${label}-1-before.png`) };

  await page.mouse.click(original.x, original.y, { button: 'right' });
  await page.locator('.litecontextmenu .litemenu-entry', { hasText: 'Fix node (recreate)' }).click();
  await page.waitForTimeout(500);
  const menu = page.locator('.litecontextmenu').first();
  const menuBox = await menu.count() ? await menu.boundingBox() : null;
  const clicked = {
    contextMenuOpen: !!menuBox,
    menuBox: menuBox ? [menuBox.x, menuBox.y, menuBox.width, menuBox.height].map(Math.round) : null,
    ...await readNodes(),
    capture: await shot(`${label}-2-clicked.png`),
  };

  await page.mouse.click(300, 760);
  await page.waitForTimeout(300);
  await page.mouse.move(original.x, original.y);
  await page.mouse.down();
  await page.mouse.move(original.x, original.y + DRAG_DY, { steps: 15 });
  await page.mouse.up();
  await page.mouse.move(40, 860);
  await page.waitForTimeout(700);

  const after = { ...await readNodes(), capture: await shot(`${label}-3-moved.png`) };

  const result = {
    label, capturedAt: new Date().toISOString(), baseURL,
    frontend: await page.evaluate(() => window.__COMFYUI_FRONTEND_VERSION__ ?? null),
    viewport: [1440, 900],
    nodeFixer: { sha256: sha256(Buffer.from(served.text, 'utf-8')), linkLookupLine: served.line },
    originalSampler: { id: original.id, idType: original.idType },
    dragDy: DRAG_DY, pageErrors, before, clicked, after,
  };
  fs.writeFileSync(path.join(outDir, `${label}.json`), JSON.stringify(result, null, 2) + '\n');
  await browser.close();
  console.log(JSON.stringify({
    label, frontend: result.frontend, line: served.line, pageErrors, inSubgraph: after.inSubgraph,
    menuOpenAfterClick: clicked.contextMenuOpen, menuBox: clicked.menuBox, boundary: after.boundary,
    after: after.nodes.map((n) => `${n.type}#${n.id}${n.isOriginal ? '(original)' : ''} in=${JSON.stringify(n.inputsFrom)} out=${JSON.stringify(n.outputsTo)} box=${n.box}`),
  }, null, 1));
})().catch((e) => { console.error(e); process.exit(1); });
