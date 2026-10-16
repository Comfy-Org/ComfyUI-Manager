// Run with: node --test tests/test_node_conflicts.cjs
// Exercise the actual UI method without importing ComfyUI or starting a server.
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');

const source = readFileSync(path.join(__dirname, '../js/custom-nodes-manager.js'), 'utf8');
const start = source.indexOf('\tasync loadNodes(node_packs) {');
const end = source.indexOf('\n\trenderSelected()', start);
assert.ok(start >= 0 && end > start, 'loadNodes method boundaries must exist');
const method = source.slice(start, end);

async function load(packs, data = { A: [['Shared'], {}], B: [['Shared'], {}] }) {
    const manager = vm.runInNewContext(`({ showStatus() {}, ${method} })`, {
        manager_instance: { datasrc_combo: { value: 'cache' } },
        fetchData: async () => ({ data }),
        console,
    });
    await manager.loadNodes(packs);
}

function pack(key, state) {
    return { key, state, title: key, hash: key };
}

for (const inactive of ['not-installed', 'disabled']) {
    test(`enabled pack ignores ${inactive} peer; inactive pack retains preview`, async () => {
        const packs = { A: pack('A', 'enabled'), B: pack('B', inactive) };
        await load(packs);
        assert.equal(packs.A.conflicts, 0);
        assert.equal(packs.A.potentialConflicts, 0);
        assert.equal(packs.B.conflicts, 0);
        assert.equal(packs.B.potentialConflicts, 1);
        assert.equal(packs.B.nodesMap.Shared.potentialConflicts[0].key, 'A');
        assert.equal(packs.B.nodes, 1);
    });
}

test('two enabled packs have symmetric conflicts, not potential conflicts', async () => {
    const packs = { A: pack('A', 'enabled'), B: pack('B', 'enabled') };
    await load(packs);
    for (const key of ['A', 'B']) {
        assert.equal(packs[key].conflicts, 1);
        assert.equal(packs[key].potentialConflicts, 0);
        assert.equal(packs[key].nodesMap.Shared.conflicts.length, 1);
        assert.notEqual(packs[key].nodesMap.Shared.conflicts[0].key, key);
    }
});

test('inactive catalog packs do not conflict with each other', async () => {
    const packs = { A: pack('A', 'disabled'), B: pack('B', 'not-installed') };
    await load(packs);
    for (const p of Object.values(packs)) {
        assert.equal(p.conflicts, 0);
        assert.equal(p.potentialConflicts, 0);
        assert.equal(p.nodesList.length, 1);
    }
});

test('mixed catalog only lists enabled peers and deduplicates node names', async () => {
    const packs = { A: pack('A', 'enabled'), B: pack('B', 'enabled'), C: pack('C', 'disabled') };
    await load(packs, { A: [['Shared', 'Shared', 'Unique'], {}], B: [['Shared'], {}], C: [['Shared'], {}] });
    assert.equal(packs.A.nodes, 2);
    assert.equal(packs.A.conflicts, 1);
    assert.equal(packs.A.nodesMap.Shared.conflicts.length, 1);
    assert.equal(packs.A.nodesMap.Shared.conflicts[0].key, 'B');
    assert.equal(packs.C.conflicts, 0);
    assert.equal(packs.C.potentialConflicts, 1);
    assert.equal(packs.C.nodesMap.Shared.potentialConflicts.length, 2);
});

test('reload after disabling a peer clears previous active conflicts', async () => {
    const packs = { A: pack('A', 'enabled'), B: pack('B', 'enabled') };
    await load(packs);
    packs.B.state = 'disabled';
    await load(packs);
    assert.equal(packs.A.conflicts, 0);
    assert.equal(packs.A.nodesMap.Shared.conflicts, undefined);
    assert.equal(packs.B.conflicts, 0);
    assert.equal(packs.B.potentialConflicts, 1);
    packs.B.state = 'enabled';
    await load(packs);
    assert.equal(packs.B.conflicts, 1);
    assert.equal(packs.B.potentialConflicts, 0);
});

test('a single enabled pack and unrelated catalog mapping have no conflicts', async () => {
    const packs = { A: pack('A', 'enabled') };
    await load(packs);
    assert.equal(packs.A.conflicts, 0);
    assert.equal(packs.A.potentialConflicts, 0);
});

test('URL basename and title fallback still resolve pack mappings', async () => {
    const packs = { A: pack('A', 'enabled'), B: pack('B', 'disabled') };
    await load(packs, { 'https://example.invalid/A': [['Shared'], {}], other: [['Shared'], { title_aux: 'B' }] });
    assert.equal(packs.A.conflicts, 0);
    assert.equal(packs.B.potentialConflicts, 1);
});
