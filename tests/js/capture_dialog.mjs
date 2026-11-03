// Harness for tests/test_batch_404_dialog_guard.py — see that file for the
// contract this serves.
//
// Drives a batch path of the SHIPPED client through a 404 response and prints,
// as a single JSON line on stdout, the text the user would have been shown.
//
//   usage: node --preserve-symlinks capture_dialog.mjs <install|uninstall> [body]
//
// The client under test is reached through `./pkg/js`, which the Python side
// points at whichever tree it wants to measure. Running under
// `--preserve-symlinks` keeps module resolution inside this sandbox, so the
// client's own `../../scripts/*.js` imports land on the stand-ins next to this
// file while the file EXECUTED is the real one from the tree being measured.
// Only the network and the browser are stood in for; no client code is copied
// or reimplemented here.
import './dom.mjs';
import { setRoutes } from './scripts/api.js';
import { shown } from './scripts/app.js';

const site = process.argv[2];
const body = process.argv[3] || 'A security error has occurred. Please check the terminal logs';

if (site !== 'install' && site !== 'uninstall') {
	console.error(`capture_dialog: expected site 'install' or 'uninstall', got ${JSON.stringify(site)}`);
	process.exit(2);
}

const denied = async () => ({
	status: 404,
	async text() { return body; },
	async json() { throw new Error('the 404 body is not JSON'); },
});

setRoutes({
	'/manager/queue/status': async () => ({
		status: 200,
		async json() { return { is_processing: false, done_count: 0, total_count: 0 }; },
	}),
	'/manager/queue/reset': async () => ({ status: 200, async text() { return ''; } }),
	'/manager/queue/install': denied,
	'/manager/queue/uninstall': denied,
});

const PACK = 'comfyui-some-pack';
let callback = null;

if (site === 'uninstall') {
	const { uninstallNodes } = await import('./pkg/js/common.js');
	await uninstallNodes(
		[{ title: PACK, name: PACK, version: 'unknown', files: [`https://github.com/x/${PACK}`] }],
		{ title: PACK, onError: (m) => { callback = m; } }
	);
} else {
	const { CustomNodesManager } = await import('./pkg/js/custom-nodes-manager.js');
	const item = {
		hash: 'h1',
		title: PACK,
		originalData: { id: PACK, version: 'unknown', files: [`https://github.com/x/${PACK}`] },
	};
	// installNodes is a method, so it is invoked through the real prototype with
	// stand-in collaborators; the body that runs is the shipped one.
	const self = {
		channel: 'default',
		mode: 'cache',
		showError: (m) => { if (m) callback = m; },
		showStatus: () => {},
		focusInstall: () => true,
		grid: {
			getRowItemBy: () => item,
			scrollRowIntoView: () => {},
			onNextUpdated: () => {},
			updateCell: () => {},
		},
	};
	const btn = { target: { classList: { add() {}, remove() {} } }, label: 'Install', mode: 'install' };
	await CustomNodesManager.prototype.installNodes.call(self, ['h1'], btn, PACK, 'latest');
}

console.log(JSON.stringify({
	site,
	server_body: body,
	dialog: shown.join('\n'),
	callback,
}));
