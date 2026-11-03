// Stand-in for ComfyUI's `scripts/api.js`, for tests/test_batch_404_dialog_guard.py.
//
// `fetchApi` is the network boundary. The harness installs per-scenario
// responses through setRoutes(); nothing here reaches a real server.
let routes = {};
export function setRoutes(r) { routes = r; }
export const api = {
	async fetchApi(path, options) {
		for (const key of Object.keys(routes)) {
			if (path.startsWith(key)) return routes[key](path, options);
		}
		return { status: 200, async json() { return {}; }, async text() { return ''; } };
	},
	addEventListener() {},
	removeEventListener() {},
	apiURL(p) { return p; },
};
