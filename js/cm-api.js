import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";
import { sleep, customConfirm, customAlert, handle403Response, show_message, sanitizeHTML, md5 } from "./common.js";

// Enable a disabled node pack as the Enable button of the Custom Nodes Manager does: find the pack
// in the node list, put it in the queue, and wait until the queue has finished it.
// Returns undefined when the pack was enabled, or the reason when it was not.
async function enableNodePack(target) {
	const list = await api.fetchApi(`/customnode/getlist?mode=cache&skip_update=true`);
	if(list.status != 200) {
		return `Failed to get the custom node list (${list.status}).`;
	}

	const { channel, node_packs } = await list.json();
	const key = Object.keys(node_packs).find((k) => {
		const pack = node_packs[k];
		return pack.state == 'disabled' && pack.files?.some((url) => target.files.includes(url));
	});
	if(key == undefined) {
		return 'It is not in the custom node list as a disabled node pack. Please enable it in the Custom Nodes Manager.';
	}

	const ui_id = md5(key);  // the id of this pack's row in the Custom Nodes Manager

	const status = await api.fetchApi('/manager/queue/status');
	if((await status.json()).is_processing) {
		return 'There are already tasks in progress. Please try again after it is completed.';
	}

	// Once the queue is started its next report ends the wait; it is without the pack when
	// something else has emptied the queue.
	let listener, started = false;
	const result = new Promise((resolve) => {
		listener = (event) => {
			if(event.detail.status != 'done') {
				return;
			}

			if(ui_id in event.detail.nodepack_result) {
				resolve(event.detail.nodepack_result[ui_id]);
			}
			else if(started) {
				resolve('The queue finished without this node pack. Please try again.');
			}
		};
	});

	// A node pack from the registry is enabled while the install request is handled, and reported then.
	api.addEventListener("cm-queue-status", listener);
	try {
		await api.fetchApi('/manager/queue/reset', { method: 'POST' });

		const response = await api.fetchApi(`/manager/queue/install`, {
									method: 'POST',
									headers: { 'Content-Type': 'application/json' },
									body: JSON.stringify({
										...node_packs[key],
										channel,
										mode: 'cache',
										ui_id,
										skip_post_install: true
									})
								});

		if(response.status == 403) {
			return 'This action is not allowed with this security level configuration.';
		}
		if(response.status != 200) {
			return `The request was refused (${response.status}). Please check the terminal log.`;
		}

		started = true;
		await api.fetchApi('/manager/queue/start', { method: 'POST' });

		// A report that does not reach the page would leave the listener in place, and a later report
		// for the same row, such as its Disable, would then restart ComfyUI unasked.
		const message = await Promise.race([result, sleep(60000).then(() =>
			'The queue did not report the result. Please check the node pack in the Custom Nodes Manager.')]);
		if(message != 'success') {
			return String(message);
		}
	}
	finally {
		api.removeEventListener("cm-queue-status", listener);
	}
}

async function tryInstallCustomNode(event) {
	const target = event.detail.target;

	let msg = '-= [ComfyUI Manager] extension installation request =-\n\n';
	msg += `The '${event.detail.sender}' extension requires the installation of the '${target.title}' extension. `;

	if(target.installed == 'Disabled') {
		msg += 'However, the extension is currently disabled. Would you like to enable it and reboot?'
	}
	else {
		msg += 'However, it seems that the extension is in an import-fail state or is not compatible with the current version. Please address this issue.';
	}

	msg += `\n\nRequest message:\n${event.detail.msg}`;

	// The server sends this request only for a node pack that is installed: it is disabled, or it failed to load.
	if(target.installed != 'Disabled') {
		customAlert(msg);
		return;
	}

	const res = await customConfirm(msg);
	if(res) {
		const title = sanitizeHTML(String(target.title));

		await sleep(300);
		app.ui.dialog.show(`Enabling... '${title}'`);

		const failure = await enableNodePack(target).catch((exception) => String(exception));
		if(failure != undefined) {
			show_message(`Failed to enable '${title}'.<BR><BR>${sanitizeHTML(failure)}`);
			return false;
		}

		let response;
		try {
			response = await api.fetchApi("/manager/reboot", { method: 'POST' });
		}
		catch(exception) {
			// The server restarts without answering.
		}

		if(response?.status == 403) {
			await handle403Response(response);
			return false;
		}

		await sleep(300);

		app.ui.dialog.show(`Rebooting...`);
	}
}

api.addEventListener("cm-api-try-install-customnode", tryInstallCustomNode);
