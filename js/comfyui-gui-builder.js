import { $el } from "../../scripts/ui.js";
import { loadCss } from "./common.js";

loadCss("./comfyui-gui-builder.css");

function normalizeContent(content) {
	const tmp = document.createElement('div');
	if (typeof content === 'string') {
		tmp.innerHTML = content;
		return Array.from(tmp.childNodes);
	}
	if (content instanceof Node) {
		return content;
	}
	return content;
}

export function createSettingsCombo(label, content) {
	const settingItem = $el("div.setting-item", {}, [
		$el("div.flex.flex-row.items-center.gap-2",[
				$el("div.form-label.flex.grow.items-center", [
					$el("span.cm-ui-muted", { textContent: label },)
				]),
				$el("div.form-input.flex.justify-end",
					[content]
				)
			]
		)
	]);
	return settingItem;
}

export function buildGuiFrame(dialogId, title, iconClass, content, owner) {
	const dialog_mask = $el("div.cm-ui-overlay.fixed.inset-0.flex.items-center.justify-center", {
		parent: document.body,
		onclick: (e) => {
			if (e.target === dialog_mask) {
				owner.close();
			}
		}
	});

	const header_actions = $el("div.flex.items-center");

	$el("button.cm-ui-button.cm-ui-close", {
			parent: header_actions,
			type: "button",
			ariaLabel: "Close",
			onclick: () => owner.close(),
			innerHTML: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M8.01186 7.00933L12.27 2.75116C12.341 2.68501 12.398 2.60524 12.4375 2.51661C12.4769 2.42798 12.4982 2.3323 12.4999 2.23529C12.5016 2.13827 12.4838 2.0419 12.4474 1.95194C12.4111 1.86197 12.357 1.78024 12.2884 1.71163C12.2198 1.64302 12.138 1.58893 12.0481 1.55259C11.9581 1.51625 11.8617 1.4984 11.7647 1.50011C11.6677 1.50182 11.572 1.52306 11.4834 1.56255C11.3948 1.60204 11.315 1.65898 11.2488 1.72997L6.99067 5.98814L2.7325 1.72997C2.59553 1.60234 2.41437 1.53286 2.22718 1.53616C2.03999 1.53946 1.8614 1.61529 1.72901 1.74767C1.59663 1.88006 1.5208 2.05865 1.5175 2.24584C1.5142 2.43303 1.58368 2.61419 1.71131 2.75116L5.96948 7.00933L1.71131 11.2675C1.576 11.403 1.5 11.5866 1.5 11.7781C1.5 11.9696 1.576 12.1532 1.71131 12.2887C1.84679 12.424 2.03043 12.5 2.2219 12.5C2.41338 12.5 2.59702 12.424 2.7325 12.2887L6.99067 8.03052L11.2488 12.2887C11.3843 12.424 11.568 12.5 11.7594 12.5C11.9509 12.5 12.1346 12.424 12.27 12.2887C12.4053 12.1532 12.4813 11.9696 12.4813 11.7781C12.4813 11.5866 12.4053 11.403 12.27 11.2675L8.01186 7.00933Z" fill="currentColor"></path></svg>'
		}
	);

	const dialog_header = $el("div.cm-ui-header.flex.items-center.justify-between.gap-2",
		[
			$el("div", [
				$el("div",
					{
						id: "frame-title-container",
					},
					[
						$el("h2.px-4", [
							$el(iconClass, {
								style: {
									"font-size": "1.25rem",
									"margin-right": ".5rem"
								}
							}),
							$el("span", { textContent: title })
						])
					]
					)
				]),
			header_actions
		]
	);

	const contentFrame = $el("div.cm-ui-content.min-h-0", {}, normalizeContent(content));
	$el("div.cm-ui-dialog.global-dialog.flex.flex-col", {
			id: dialogId,
			parent: dialog_mask,
			style: {
				'display': 'flex',
				'flex-direction': 'column',
				'pointer-events': 'auto',
				'margin': '0px',
			},
			role: 'dialog',
			ariaModal: 'true',
		},
		[ dialog_header, contentFrame ]
	);
	return dialog_mask;
}

export function buildGuiFrameCustomHeader(dialogId, customHeader, content, owner) {
	const dialog_mask = $el("div.cm-ui-overlay.fixed.inset-0.flex.items-center.justify-center", {
		parent: document.body,
		onclick: (e) => {
			if (e.target === dialog_mask) {
				owner.close();
			}
		}
	});

	const header_actions = $el("div.flex.items-center");

	$el("button.cm-ui-button.cm-ui-close", {
			parent: header_actions,
			type: "button",
			ariaLabel: "Close",
			onclick: () => owner.close(),
			innerHTML: '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M8.01186 7.00933L12.27 2.75116C12.341 2.68501 12.398 2.60524 12.4375 2.51661C12.4769 2.42798 12.4982 2.3323 12.4999 2.23529C12.5016 2.13827 12.4838 2.0419 12.4474 1.95194C12.4111 1.86197 12.357 1.78024 12.2884 1.71163C12.2198 1.64302 12.138 1.58893 12.0481 1.55259C11.9581 1.51625 11.8617 1.4984 11.7647 1.50011C11.6677 1.50182 11.572 1.52306 11.4834 1.56255C11.3948 1.60204 11.315 1.65898 11.2488 1.72997L6.99067 5.98814L2.7325 1.72997C2.59553 1.60234 2.41437 1.53286 2.22718 1.53616C2.03999 1.53946 1.8614 1.61529 1.72901 1.74767C1.59663 1.88006 1.5208 2.05865 1.5175 2.24584C1.5142 2.43303 1.58368 2.61419 1.71131 2.75116L5.96948 7.00933L1.71131 11.2675C1.576 11.403 1.5 11.5866 1.5 11.7781C1.5 11.9696 1.576 12.1532 1.71131 12.2887C1.84679 12.424 2.03043 12.5 2.2219 12.5C2.41338 12.5 2.59702 12.424 2.7325 12.2887L6.99067 8.03052L11.2488 12.2887C11.3843 12.424 11.568 12.5 11.7594 12.5C11.9509 12.5 12.1346 12.424 12.27 12.2887C12.4053 12.1532 12.4813 11.9696 12.4813 11.7781C12.4813 11.5866 12.4053 11.403 12.27 11.2675L8.01186 7.00933Z" fill="currentColor"></path></svg>'
		}
	);

	const _customHeader = normalizeContent(customHeader);
	const dialog_header = $el("div.cm-ui-header.flex.items-center.justify-between.gap-2",
		[
			$el("div", [
				$el("div",
					{
						id: "frame-title-container",
					},
					Array.isArray(_customHeader) ? _customHeader : [_customHeader]
					)
				]),
			header_actions
		]
	);

	const contentFrame = $el("div.cm-ui-content.min-h-0", {}, normalizeContent(content));
	$el("div.cm-ui-dialog.global-dialog.flex.flex-col", {
			id: dialogId,
			parent: dialog_mask,
			style: {
				'display': 'flex',
				'flex-direction': 'column',
				'pointer-events': 'auto',
				'margin': '0px',
			},
			role: 'dialog',
			ariaModal: 'true',
		},
		[ dialog_header, contentFrame ]
	);
	return dialog_mask;
}
