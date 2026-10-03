// Stand-in for ComfyUI's `scripts/ui.js`, for tests/test_batch_404_dialog_guard.py.
// Import-time surface only — the guard never exercises these.
export function $el(tag, props = {}, children = []) {
	return { tag, props, children, style: {}, classList: { add() {}, remove() {} } };
}
export class ComfyDialog {
	constructor() { this.element = { style: {}, classList: { add() {}, remove() {} } }; }
	show() {}
	close() {}
}
