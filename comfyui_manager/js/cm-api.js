import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";
import { sleep, customConfirm, customAlert, show_message, sanitizeHTML, generateUUID, md5 } from "./common.js";

// Enable a disabled node pack as the Enable button of the Custom Nodes Manager does: find the pack
// in the node list, put it in the queue, and wait until the queue has finished it.
// Returns { failure }, the reason, when the pack was not enabled, and otherwise { busy }: whether
// the queue still holds other work.
async function enableNodePack(target) {
	const list = await api.fetchApi(`/v2/customnode/getlist?mode=cache&skip_update=true`);
	if(list.status != 200) {
		return { failure: `Failed to get the custom node list (${list.status}).` };
	}

	const { channel, node_packs } = await list.json();
	const key = Object.keys(node_packs).find((k) => {
		const pack = node_packs[k];
		return pack.state == 'disabled' && pack.files?.some((url) => target.files.includes(url));
	});
	if(key == undefined) {
		return { failure: 'It is not in the custom node list as a disabled node pack. Please enable it in the Custom Nodes Manager.' };
	}

	// Behind other work the pack would be enabled at some later time, after the wait below has ended.
	const status = await api.fetchApi('/v2/manager/queue/status');
	if((await status.json()).is_processing) {
		return { failure: 'There are already tasks in progress. Please try again after it is completed.' };
	}

	const batch_id = generateUUID();
	const ui_id = md5(key);  // the id of this pack's row in the Custom Nodes Manager

	// Once the batch is in the queue, 'all-done' without its report ends the wait: something else,
	// such as another tab, has emptied the queue.
	let listener, queued = false;
	const result = new Promise((resolve) => {
		listener = (event) => {
			const report = event.detail;
			if(report.status == 'batch-done' && report.batch_id == batch_id) {
				resolve(report);
			}
			else if(report.status == 'all-done' && queued) {
				resolve({ nodepack_result: {} });
			}
		};
	});

	// The queue may report the batch before the request below is answered.
	api.addEventListener("cm-queue-status", listener);
	try {
		const response = await api.fetchApi(`/v2/manager/queue/batch`, {
									method: 'POST',
									headers: { 'Content-Type': 'application/json' },
									body: JSON.stringify({
										batch_id,
										install: [{
											...node_packs[key],
											channel,
											mode: 'cache',
											ui_id,
											skip_post_install: true
										}]
									})
								});

		if(response.status != 200) {
			return { failure: `The request was refused (${response.status}). Please check the terminal log.` };
		}

		const { failed } = await response.json();
		if(failed.length > 0) {
			return { failure: 'The request was refused. Please check the terminal log.' };
		}

		// A report that does not reach the page would leave the listener in place, and the batch,
		// run at some later time, would then restart ComfyUI unasked.
		queued = true;
		const report = await Promise.race([result, sleep(60000)]);
		if(report == undefined) {
			return { failure: 'The queue did not report the result. Please check the node pack in the Custom Nodes Manager.' };
		}

		const message = report.nodepack_result[ui_id] ?? 'The queue finished without this node pack. Please try again.';
		if(message != 'success') {
			return { failure: String(message) };
		}

		return { busy: report.remaining_batch_count > 1 };  // the count includes this batch
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

		const { failure, busy } = await enableNodePack(target).catch((exception) => ({ failure: String(exception) }));
		if(failure != undefined) {
			show_message(`Failed to enable '${title}'.<BR><BR>${sanitizeHTML(failure)}`);
			return false;
		}

		// A restart would cut off the work that was queued behind the pack.
		if(busy) {
			show_message(`'${title}' is enabled.<BR><BR>Other tasks are still in progress. Please restart ComfyUI after they are completed.`);
			return false;
		}

		let response;
		try {
			response = await api.fetchApi("/v2/manager/reboot", { method: 'POST' });
		}
		catch(exception) {
			// The server restarts without answering.
		}

		if(response?.status == 403) {
			show_message('This action is not allowed with this security level configuration.');
			return false;
		}

		await sleep(300);

		app.ui.dialog.show(`Rebooting...`);
	}
}

api.addEventListener("cm-api-try-install-customnode", tryInstallCustomNode);
