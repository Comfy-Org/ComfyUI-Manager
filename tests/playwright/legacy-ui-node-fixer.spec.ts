/**
 * E2E test: "Fix node (recreate)" in the node context menu (js/node_fixer.js).
 *
 * Recreating a node must leave one copy of it, wired as the original was. The
 * entry passed the new node's id to `LGraphNode.connect()`, which looks a
 * target up by id only when the id is a number. Where node ids are strings it
 * threw `findInputSlot is not a function` and left the wired original plus an
 * unwired replacement on the canvas.
 *
 * Honesty boundary: where the frontend issues numeric ids (1.45.15, which the
 * E2E environment pins), the "string" row rewrites the ids to strings itself.
 * That reproduces the failing call but is a simulation, and it reaches into
 * `graph._nodes_by_id`. Where ids are already strings (1.57.6) the rewrite
 * changes nothing and both rows run the real thing.
 *
 * Requires ComfyUI running with --enable-manager-legacy-ui on PORT.
 */

import { test, expect } from '@playwright/test';
import { waitForComfyUI } from './helpers';

for (const stringIds of [false, true]) {
  test(`Fix node (recreate) leaves one wired node — ${stringIds ? 'string' : 'frontend-issued'} node ids`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/');
    await waitForComfyUI(page);
    await page.waitForFunction(() => !!(window as any).LiteGraph?.registered_node_types?.KSampler);

    // CheckpointLoaderSimple -> KSampler -> VAEDecode
    const original = await page.evaluate((stringIds) => {
      const { app, LiteGraph } = window as any;
      const graph = app.canvas.graph;
      graph.clear();
      const add = (type: string, x: number) => {
        const node = LiteGraph.createNode(type);
        node.pos = [x, 150];
        graph.add(node);
        return node;
      };
      const loader = add('CheckpointLoaderSimple', 50);
      const sampler = add('KSampler', 500);
      const decoder = add('VAEDecode', 900);
      loader.connect(0, sampler, 'model');
      sampler.connect(0, decoder, 'samples');

      if (stringIds) {
        const toStringId = (node: any) => {
          delete graph._nodes_by_id[node.id];
          node.id = String(node.id);
          graph._nodes_by_id[node.id] = node;
        };
        graph.nodes.forEach(toStringId);
        for (const link of graph.links.values()) {
          link.origin_id = String(link.origin_id);
          link.target_id = String(link.target_id);
        }
        // The menu entry adds the replacement; it needs a string id as well.
        const graphAdd = graph.add.bind(graph);
        graph.add = (node: any, ...rest: unknown[]) => {
          const result = graphAdd(node, ...rest);
          toStringId(node);
          return result;
        };
      }

      app.canvas.ds.offset = [0, 0];
      app.canvas.ds.scale = 1;
      // The canvas finds the node under the pointer among the nodes it last drew.
      app.canvas.draw(true, true);
      // A point on the KSampler's title bar.
      return { id: sampler.id, x: sampler.pos[0] + 60, y: sampler.pos[1] - LiteGraph.NODE_TITLE_HEIGHT / 2 };
    }, stringIds);

    await page.mouse.click(original.x, original.y, { button: 'right' });
    await page.locator('.litecontextmenu .litemenu-entry', { hasText: 'Fix node (recreate)' }).click();

    const samplers = await page.evaluate((originalId) => {
      const graph = (window as any).app.canvas.graph;
      return graph.nodes.filter((node: any) => node.type === 'KSampler').map((node: any) => ({
        recreated: node.id !== originalId,
        model: node.getInputNode(node.findInputSlot('model'))?.type ?? null,
        latent: (node.getOutputNodes(0) ?? []).map((target: any) => target.type),
      }));
    }, original.id);

    // One comparison, so a failure shows the thrown error and the leftover node together.
    expect({ errors, samplers }).toEqual({
      errors: [],
      samplers: [{ recreated: true, model: 'CheckpointLoaderSimple', latent: ['VAEDecode'] }],
    });
  });
}
