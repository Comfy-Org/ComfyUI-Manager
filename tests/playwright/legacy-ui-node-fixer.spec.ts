/**
 * E2E test: "Fix node (recreate)" in the node context menu (js/node_fixer.js).
 *
 * Recreating a node must leave one copy of it, wired as the original was.
 *
 * String node ids: the entry passed the new node's id to
 * `LGraphNode.connect()`, which looks a target up by id only when the id is a
 * number. Where node ids are strings it threw `findInputSlot is not a
 * function` and left the wired original plus an unwired replacement.
 *
 * Subgraphs: the entry read links and nodes from the root graph. A subgraph
 * keeps its own, and its inputs and outputs are not nodes of it, so inside a
 * subgraph the entry threw and left the same two nodes.
 *
 * The entry exists for nodes whose definition changed, so two rows give the
 * original an input the new node cannot take over, one it does not have and
 * one it has with another type: that link is dropped, the rest is kept.
 *
 * Honesty boundary: where the frontend issues numeric ids (1.45.15, which the
 * E2E environment pins), the "string node ids" row rewrites the ids to strings
 * itself. That reproduces the failing call but is a simulation, and it reaches
 * into `graph._nodes_by_id`. Where ids are already strings (1.57.6) the
 * rewrite changes nothing and that row runs the real thing.
 *
 * Requires ComfyUI running with --enable-manager-legacy-ui on PORT.
 */

import { test, expect } from '@playwright/test';
import { waitForComfyUI } from './helpers';

// Each case builds CheckpointLoaderSimple + CLIPTextEncode -> KSampler ->
// VAEDecode in the root graph and recreates the KSampler. `subgraph` lists the
// nodes that are moved into a subgraph first; the test then works inside that
// subgraph. `links` is what the KSampler must be wired to before the click, at
// the least. `dropped` names an input of the KSampler that is typed MODEL and
// fed by the subgraph's `model` input before the click; a new KSampler either
// has no input of that name or has it with another type.
const toNodes = {
  inputs: { model: 'CheckpointLoaderSimple.MODEL', positive: 'CLIPTextEncode.CONDITIONING' },
  outputs: ['VAEDecode.samples'],
};
const toSubgraph = {
  inputs: { model: 'subgraph input.model', positive: 'subgraph input.positive' },
  outputs: ['subgraph output.LATENT'],
};
const cases = [
  { name: 'frontend-issued node ids', links: toNodes },
  { name: 'string node ids', stringIds: true, links: toNodes },
  {
    name: 'inside a subgraph',
    subgraph: ['CheckpointLoaderSimple', 'CLIPTextEncode', 'KSampler', 'VAEDecode'],
    links: toNodes,
  },
  { name: 'linked to the inputs and outputs of a subgraph', subgraph: ['KSampler'], links: toSubgraph },
  {
    name: 'an input the new node lacks, linked to an input of a subgraph',
    subgraph: ['KSampler'],
    dropped: 'legacy_model',
    links: { ...toSubgraph, inputs: { ...toSubgraph.inputs, legacy_model: 'subgraph input.model' } },
  },
  {
    name: 'an input whose type changed, linked to an input of a subgraph',
    subgraph: ['KSampler'],
    dropped: 'negative',
    links: { ...toSubgraph, inputs: { ...toSubgraph.inputs, negative: 'subgraph input.model' } },
  },
];

for (const { name, stringIds = false, subgraph = [], dropped = '', links } of cases) {
  test(`Fix node (recreate) leaves one wired node — ${name}`, async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/');
    await waitForComfyUI(page);
    await page.waitForFunction(() => !!(window as any).LiteGraph?.registered_node_types?.KSampler);

    await page.evaluate(({ stringIds, subgraph, dropped }) => {
      const { app, LiteGraph } = window as any;
      const graph = app.canvas.graph;
      graph.clear();
      const add = (type: string, x: number, y: number) => {
        const node = LiteGraph.createNode(type);
        node.pos = [x, y];
        graph.add(node);
        return node;
      };
      const loader = add('CheckpointLoaderSimple', 50, 150);
      const prompt = add('CLIPTextEncode', 50, 350);
      const sampler = add('KSampler', 500, 150);
      const decoder = add('VAEDecode', 900, 150);
      loader.connect(0, sampler, 'model');
      prompt.connect(0, sampler, 'positive');
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

      if (subgraph.length) {
        const moved = new Set(graph.nodes.filter((node: any) => subgraph.includes(node.type)));
        const converted = graph.convertToSubgraph(moved);
        app.canvas.openSubgraph(converted.subgraph, converted.node);
        if (dropped) {
          const inner = converted.subgraph.nodes.find((node: any) => node.type === 'KSampler');
          const input = inner.inputs.find((slot: any) => slot.name === dropped) ?? inner.addInput(dropped, 'MODEL');
          input.type = 'MODEL';
          const model = converted.subgraph.inputNode.slots.find((slot: any) => slot.name === 'model');
          model.connect(input, inner);
        }
      }
    }, { stringIds, subgraph, dropped });
    // Opening a subgraph re-fits the view a moment later.
    if (subgraph.length) await page.waitForTimeout(1_500);

    // Every KSampler of the graph on screen, with the slots it is wired to. A
    // link to an input or output of the subgraph must be recorded on that slot
    // too: that record is what running and saving the workflow read.
    const readSamplers = () => page.evaluate(() => {
      const graph = (window as any).app.canvas.graph;
      const onSlot = (slot: any, link: any) =>
        `${slot.name}${slot.linkIds.includes(link.id) ? '' : ' (link not recorded on the slot)'}`;
      const origin = (link: any) => {
        if (link.origin_id === graph.inputNode?.id) {
          return `subgraph input.${onSlot(graph.inputNode.slots[link.origin_slot], link)}`;
        }
        const node = graph.getNodeById(link.origin_id);
        return `${node.type}.${node.outputs[link.origin_slot].name}`;
      };
      const target = (link: any) => {
        if (link.target_id === graph.outputNode?.id) {
          return `subgraph output.${onSlot(graph.outputNode.slots[link.target_slot], link)}`;
        }
        const node = graph.getNodeById(link.target_id);
        return `${node.type}.${node.inputs[link.target_slot].name}`;
      };
      return graph.nodes.filter((node: any) => node.type === 'KSampler').map((node: any) => ({
        id: node.id,
        inputs: Object.fromEntries(node.inputs.filter((input: any) => input.link != null)
          .map((input: any) => [input.name, origin(graph.links.get(input.link))])),
        outputs: (node.outputs[0].links ?? []).map((id: number) => target(graph.links.get(id))),
      }));
    });

    const [original] = await readSamplers();
    expect(original).toMatchObject(links);

    const title = await page.evaluate(() => {
      const { app, LiteGraph } = window as any;
      const sampler = app.canvas.graph.nodes.find((node: any) => node.type === 'KSampler');
      app.canvas.ds.scale = 1;
      app.canvas.ds.offset = [500 - sampler.pos[0], 150 - sampler.pos[1]];
      // The canvas finds the node under the pointer among the nodes it last drew.
      app.canvas.draw(true, true);
      return { x: 500 + 60, y: 150 - LiteGraph.NODE_TITLE_HEIGHT / 2 };
    });
    await page.mouse.click(title.x, title.y, { button: 'right' });
    await page.locator('.litecontextmenu .litemenu-entry', { hasText: 'Fix node (recreate)' }).click();

    const samplers = await readSamplers();
    const expected = { ...original, id: expect.anything(), inputs: { ...original.inputs } };
    delete expected.inputs[dropped];
    // One comparison, so a failure shows the thrown error and the leftover node together.
    expect({ errors, samplers }).toEqual({ errors: [], samplers: [expected] });
    expect(samplers[0].id).not.toBe(original.id);
  });
}
