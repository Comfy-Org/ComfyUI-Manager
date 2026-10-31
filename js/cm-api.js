import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";
import { sleep, customConfirm, customAlert, handle403Response, sanitizeHTML, show_message } from "./common.js";

async function tryInstallCustomNode(event) {
	// Two representations of the dependency title: dialogs that render HTML
	// (app.ui.dialog.show) get the escaped form, while customConfirm's
	// textContent fallback must keep the plain form or entities show up
	// literally (CodeRabbit review on this PR).
	const targetTitlePlain = String(event.detail.target.title ?? "");
	const targetTitle = sanitizeHTML(targetTitlePlain);
	let msg = '-= [ComfyUI Manager] extension installation request =-\n\n';
	msg += `The '${event.detail.sender}' extension requires the installation of the '${targetTitlePlain}' extension. `;

	if(event.detail.target.installed == 'Disabled') {
		msg += 'However, the extension is currently disabled. Would you like to enable it and reboot?'
	}
	else if(event.detail.target.installed == 'True') {
		msg += 'However, it seems that the extension is in an import-fail state or is not compatible with the current version. Please address this issue.';
	}
	else {
		msg += `Would you like to install it and reboot?`;
	}

	msg += `\n\nRequest message:\n${event.detail.msg}`;

	if(event.detail.target.installed == 'True') {
		customAlert(msg);
		return;
	}
	const res = await customConfirm(msg);
	if(res) {
		if(event.detail.target.installed == 'Disabled') {
			const response = await api.fetchApi(`/customnode/toggle_active`, {
										method: 'POST',
										headers: { 'Content-Type': 'application/json' },
										body: JSON.stringify(event.detail.target)
									});
		}
		else {
			await sleep(300);
			app.ui.dialog.show(`Installing... '${targetTitle}'`);

			const response = await api.fetchApi(`/customnode/install`, {
										method: 'POST',
										headers: { 'Content-Type': 'application/json' },
										body: JSON.stringify(event.detail.target)
									});

			if(response.status == 403) {
				await handle403Response(response);
				return false;
			}
			else if(response.status == 400) {
				let msg = await response.text();
				show_message(sanitizeHTML(msg));
				return false;
			}
		}

		let response = await api.fetchApi("/manager/reboot", { method: 'POST' });
		if(response.status == 403) {
			await handle403Response(response);
			return false;
		}

		await sleep(300);

		app.ui.dialog.show(`Rebooting...`);
	}
}

api.addEventListener("cm-api-try-install-customnode", tryInstallCustomNode);
