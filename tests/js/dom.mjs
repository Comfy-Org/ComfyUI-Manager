// Minimal DOM stand-in for tests/test_batch_404_dialog_guard.py.
//
// Enough for the confirm modal js/common.js builds, and it AUTO-CLICKS the
// Confirm button so `customConfirm()` resolves in a headless run. Nothing the
// guard measures is reimplemented here — this only stands in for the browser.
function makeEl(tag) {
	return {
		tagName: String(tag).toUpperCase(),
		style: {},
		children: [],
		textContent: '',
		innerHTML: '',
		_handlers: {},
		classList: { add() {}, remove() {}, contains() { return false; } },
		addEventListener(type, fn) { (this._handlers[type] ||= []).push(fn); },
		removeEventListener() {},
		appendChild(child) { this.children.push(child); return child; },
		removeChild(child) {
			const i = this.children.indexOf(child);
			if (i >= 0) this.children.splice(i, 1);
			return child;
		},
		remove() {},
		setAttribute() {},
		querySelector() { return null; },
		querySelectorAll() { return []; },
		click() { (this._handlers.click || []).forEach((fn) => fn({})); },
	};
}

function walk(el, out = []) {
	out.push(el);
	for (const c of el.children || []) walk(c, out);
	return out;
}

const body = makeEl('body');
const realAppend = body.appendChild.bind(body);
body.appendChild = (child) => {
	realAppend(child);
	// The confirm modal resolves on a click; fire it so the flow continues.
	const buttons = walk(child).filter((e) => e.tagName === 'BUTTON');
	const confirmBtn = buttons.find((e) => /confirm|yes|ok/i.test(e.textContent || ''));
	if (confirmBtn) {
		setTimeout(() => confirmBtn.click(), 0);
	} else if (buttons.length) {
		// A dialog with buttons, none of which this stub recognizes: the client
		// would wait forever on customConfirm() and node would hang until the
		// caller's subprocess timeout, surfacing as a multi-minute mystery
		// rather than a diagnosis. Name what was seen and stop now.
		console.error(
			'capture_dialog: no confirm button matched /confirm|yes|ok/i, so the '
			+ 'client would block on customConfirm(). Buttons seen: '
			+ JSON.stringify(buttons.map((b) => b.textContent))
			+ '. Update the pattern in tests/js/dom.mjs if the button was reworded.'
		);
		process.exit(3);
	}
	return child;
};

globalThis.document = {
	body,
	head: makeEl('head'),
	createElement: makeEl,
	createTextNode: (t) => ({ textContent: t }),
	querySelector: () => null,
	querySelectorAll: () => [],
	addEventListener() {},
	getElementById: () => null,
};
globalThis.window = { addEventListener() {}, location: { href: 'http://localhost:8188/' } };
globalThis.navigator = { userAgent: 'node', clipboard: { writeText: async () => {} } };
