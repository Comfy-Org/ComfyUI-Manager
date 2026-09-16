// Stand-in for ComfyUI's `scripts/app.js`, for tests/test_batch_404_dialog_guard.py.
//
// `app.ui.dialog.show()` is the sink the manager's error text actually reaches
// in the browser, so it is what the guard measures: every call is recorded and
// the harness prints what the user would have been shown.
export const shown = [];
export const app = {
	ui: {
		dialog: {
			show(msg) { shown.push(msg); },
			element: { style: {} },
		},
	},
	extensionManager: { toast: { add() {} } },
	registerExtension() {},
};
