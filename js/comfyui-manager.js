import { api } from "../../scripts/api.js";
import { app } from "../../scripts/app.js";
import { $el, ComfyDialog } from "../../scripts/ui.js";
import {
	SUPPORTED_OUTPUT_NODE_TYPES,
	ShareDialog,
	ShareDialogChooser,
	getPotentialOutputsAndOutputNodes,
	showOpenArtShareDialog,
	showShareDialog,
	showYouMLShareDialog
} from "./comfyui-share-common.js";
import { OpenArtShareDialog } from "./comfyui-share-openart.js";
import {
	free_models, install_pip, install_via_git_url, manager_instance,
	rebootAPI, setManagerInstance, show_message, customAlert, customPrompt,
	infoToast, showTerminal, setNeedRestart
} from "./common.js";
import { ComponentBuilderDialog, getPureName, load_components, set_component_policy } from "./components-manager.js";
import { CustomNodesManager } from "./custom-nodes-manager.js";
import { ModelManager } from "./model-manager.js";
import { SnapshotManager } from "./snapshot.js";

let manager_version = await getVersion();

var docStyle = document.createElement('style');
docStyle.innerHTML = `
.comfy-toast {
	position: fixed;
	bottom: 20px;
	left: 50%;
	transform: translateX(-50%);
	background-color: rgba(0, 0, 0, 0.7);
	color: white;
	padding: 10px 20px;
	border-radius: 5px;
	z-index: 1000;
	transition: opacity 0.5s;
}

.comfy-toast-fadeout {
	opacity: 0;
}

#cm-manager-dialog {
	width: 1000px;
	height: 455px;
	box-sizing: content-box;
	z-index: 1000;
	overflow-y: auto;
}

.cb-widget {
	width: 400px;
	height: 25px;
	box-sizing: border-box;
	z-index: 1000;
	margin-top: 10px;
	margin-bottom: 5px;
}

.cb-widget-input {
	width: 305px;
	height: 25px;
	box-sizing: border-box;
}
.cb-widget-input:disabled {
	background-color: #444444;
	color: white;
}

.cb-widget-input-label {
	width: 90px;
	height: 25px;
	box-sizing: border-box;
	color: white;
	text-align: right;
	display: inline-block;
	margin-right: 5px;
}

.cm-menu-container {
	column-gap: 20px;
	display: flex;
	flex-wrap: wrap;
	justify-content: center;
	box-sizing: content-box;
}

.cm-menu-column {
	display: flex;
	flex-direction: column;
	flex: 1 1 auto;
	width: 300px;
	box-sizing: content-box;
}

.cm-title {
	background-color: black;
	text-align: center;
	height: 40px;
	width: calc(100% - 10px);
	font-weight: bold;
	justify-content: center;
	align-content: center;
	vertical-align: middle;
}

#custom-nodes-grid a {
	color: #5555FF;
	font-weight: bold;
	text-decoration: none;
}

#custom-nodes-grid a:hover {
	color: #7777FF;
	text-decoration: underline;
}

#external-models-grid a {
	color: #5555FF;
	font-weight: bold;
	text-decoration: none;
}

#external-models-grid a:hover {
	color: #7777FF;
	text-decoration: underline;
}

#alternatives-grid a {
	color: #5555FF;
	font-weight: bold;
	text-decoration: none;
}

#alternatives-grid a:hover {
	color: #7777FF;
	text-decoration: underline;
}

.cm-notice-board {
	width: 290px;
	height: 230px;
	overflow: auto;
	color: var(--input-text);
	border: 1px solid var(--descrip-text);
	padding: 5px 10px;
	overflow-x: hidden;
	box-sizing: content-box;
}

.cm-notice-board > ul {
	display: block;
	list-style-type: disc;
	margin-block-start: 1em;
	margin-block-end: 1em;
	margin-inline-start: 0px;
	margin-inline-end: 0px;
	padding-inline-start: 40px;
}

.cm-conflicted-nodes-text {
	background-color: #CCCC55 !important;
	color: #AA3333 !important;
	font-size: 10px;
	border-radius: 5px;
	padding: 10px;
}

.cm-warn-note {
	background-color: #101010 !important;
	color: #FF3800 !important;
	font-size: 13px;
	border-radius: 5px;
	padding: 10px;
	overflow-x: hidden;
	overflow: auto;
}

.cm-info-note {
	background-color: #101010 !important;
	color: #FF3800 !important;
	font-size: 13px;
	border-radius: 5px;
	padding: 10px;
	overflow-x: hidden;
	overflow: auto;
}
`;

function is_legacy_front() {
    let compareVersion = '1.2.49';
    try {
        const frontendVersion = window['__COMFYUI_FRONTEND_VERSION__'];
        if (typeof frontendVersion !== 'string') {
            return false;
        }

        function parseVersion(versionString) {
            const parts = versionString.split('.').map(Number);
            return parts.length === 3 && parts.every(part => !isNaN(part)) ? parts : null;
        }

        const currentVersion = parseVersion(frontendVersion);
        const comparisonVersion = parseVersion(compareVersion);

        if (!currentVersion || !comparisonVersion) {
            return false;
        }

        for (let i = 0; i < 3; i++) {
            if (currentVersion[i] > comparisonVersion[i]) {
                return false;
            } else if (currentVersion[i] < comparisonVersion[i]) {
                return true;
            }
        }

        return false;
    } catch {
        return true;
    }
}

document.head.appendChild(docStyle);

var update_comfyui_button = null;
var switch_comfyui_button = null;
var update_all_button = null;
var restart_stop_button = null;
var update_policy_combo = null;

let share_option = 'all';
var is_updating = false;


// copied style from https://github.com/pythongosssss/ComfyUI-Custom-Scripts
const style = `
#workflowgallery-button {
	width: 310px;
	height: 27px;
	padding: 0px !important;
	position: relative;
	overflow: hidden;
	font-size: 17px !important;
}
#cm-nodeinfo-button {
	width: 310px;
	height: 27px;
	padding: 0px !important;
	position: relative;
	overflow: hidden;
	font-size: 17px !important;
}
#cm-manual-button {
	width: 310px;
	height: 27px;
	position: relative;
	overflow: hidden;
}

.cm-button {
	width: 310px;
	height: 30px;
	position: relative;
	overflow: hidden;
	font-size: 17px !important;
}

.cm-button-red {
	width: 310px;
	height: 30px;
	position: relative;
	overflow: hidden;
	font-size: 17px !important;
	background-color: #500000 !important;
	color: white !important;
}


.cm-button-orange {
	width: 310px;
	height: 30px;
	position: relative;
	overflow: hidden;
	font-size: 17px !important;
	font-weight: bold;
	background-color: orange !important;
	color: black !important;
}

.cm-experimental-button {
	width: 290px;
	height: 30px;
	position: relative;
	overflow: hidden;
	font-size: 17px !important;
}

.cm-experimental {
	width: 310px;
	border: 1px solid #555;
	border-radius: 5px;
	padding: 10px;
	align-items: center;
	text-align: center;
	justify-content: center;
	box-sizing: border-box;
}

.cm-experimental-legend {
	margin-top: -20px;
	margin-left: 50%;
	width:auto;
	height:20px;
	font-size: 13px;
	font-weight: bold;
	background-color: #990000;
	color: #CCFFFF;
	border-radius: 5px;
	text-align: center;
	transform: translateX(-50%);
	display: block;
}

.cm-menu-combo {
	cursor: pointer;
	width: 310px;
	box-sizing: border-box;
}

.cm-small-button {
	width: 120px;
	height: 30px;
	position: relative;
	overflow: hidden;
	box-sizing: border-box;
	font-size: 17px !important;
}

#cm-install-customnodes-button {
	width: 200px;
	height: 30px;
	position: relative;
	overflow: hidden;
	box-sizing: border-box;
	font-size: 17px !important;
}

.cm-search-filter {
	width: 200px;
	height: 30px !important;
	position: relative;
	overflow: hidden;
	box-sizing: border-box;
}

.cb-node-label {
	width: 400px;
	height:28px;
	color: black;
	background-color: #777777;
	font-size: 18px;
	text-align: center;
	font-weight: bold;
}

#cm-close-button {
	width: calc(100% - 65px);
	bottom: 10px;
	position: absolute;
	overflow: hidden;
}

#cm-save-button {
	width: calc(100% - 65px);
	bottom:40px;
	position: absolute;
	overflow: hidden;
}
#cm-save-button:disabled {
	background-color: #444444;
}

.pysssss-workflow-arrow-2 {
	position: absolute;
	top: 0;
	bottom: 0;
	right: 0;
	font-size: 12px;
	display: flex;
	align-items: center;
	width: 24px;
	justify-content: center;
	background: rgba(255,255,255,0.1);
	content: "▼";
}
.pysssss-workflow-arrow-2:after {
	content: "▼";
 }
 .pysssss-workflow-arrow-2:hover {
	filter: brightness(1.6);
	background-color: var(--comfy-menu-bg);
 }
.pysssss-workflow-popup-2 ~ .litecontextmenu {
	transform: scale(1.3);
}
#workflowgallery-button-menu {
	z-index: 10000000000 !important;
}
#cm-manual-button-menu {
	z-index: 10000000000 !important;
}
`;

async function init_share_option() {
	api.fetchApi('/manager/share_option')
		.then(response => response.text())
		.then(data => {
			share_option = data || 'all';
		});
}

async function init_notice(notice) {
	api.fetchApi('/manager/notice')
		.then(response => response.text())
		.then(data => {
			notice.innerHTML = data;
		})
}

await init_share_option();


async function set_inprogress_mode() {
	update_comfyui_button.disabled = true;
	update_comfyui_button.style.backgroundColor = "gray";

	update_all_button.disabled = true;
	update_all_button.style.backgroundColor = "gray";

	switch_comfyui_button.disabled = true;
	switch_comfyui_button.style.backgroundColor = "gray";

	restart_stop_button.innerText = 'Stop';
}


async function reset_action_buttons() {
	const isElectron = 'electronAPI' in window;

	if(isElectron) {
		update_all_button.innerText = "Update All Custom Nodes";
	}
	else {
		update_all_button.innerText = "Update All";
	}

	update_comfyui_button.innerText = "Update ComfyUI";
	switch_comfyui_button.innerText = "Switch ComfyUI";
	restart_stop_button.innerText = 'Restart';

	update_comfyui_button.disabled = false;
	update_all_button.disabled = false;
	switch_comfyui_button.disabled = false;

	update_comfyui_button.style.backgroundColor = "";
	update_all_button.style.backgroundColor = "";
	switch_comfyui_button.style.backgroundColor = "";
}

async function updateComfyUI() {
	let prev_text = update_comfyui_button.innerText;
	update_comfyui_button.innerText = "Updating ComfyUI...";

	set_inprogress_mode();

	const response = await api.fetchApi('/manager/queue/update_comfyui');

	showTerminal();

	is_updating = true;
	await api.fetchApi('/manager/queue/start');
}

function showVersionSelectorDialog(versions, current, onSelect) {
		const dialog = new ComfyDialog();
		dialog.element.style.zIndex = 1100;
		dialog.element.style.width = "300px";
		dialog.element.style.padding = "0";
		dialog.element.style.backgroundColor = "#2a2a2a";
		dialog.element.style.border = "1px solid #3a3a3a";
		dialog.element.style.borderRadius = "8px";
		dialog.element.style.boxSizing = "border-box";
		dialog.element.style.overflow = "hidden";

		const contentStyle = {
			width: "300px",
			display: "flex",
			flexDirection: "column",
			alignItems: "center",
			padding: "20px",
			boxSizing: "border-box",
			gap: "15px"
		};

		let selectedVersion = versions[0];

		const versionList = $el("select", {
			multiple: true,
			size: Math.min(10, versions.length),
			style: {
				width: "260px",
				height: "auto",
				backgroundColor: "#383838",
				color: "#ffffff",
				border: "1px solid #4a4a4a",
				borderRadius: "4px",
				padding: "5px",
				boxSizing: "border-box"
			}
		},
		versions.map((v, index) => $el("option", {
			value: v,
			textContent: v,
			selected: v === current
		}))
		);

		versionList.addEventListener('change', (e) => {
			selectedVersion = e.target.value;
			Array.from(e.target.options).forEach(opt => {
				opt.selected = opt.value === selectedVersion;
			});
		});

		const content = $el("div", {
			style: contentStyle
		}, [
			$el("h3", {
				textContent: "Select Version",
				style: {
					color: "#ffffff",
					backgroundColor: "#1a1a1a",
					padding: "10px 15px",
					margin: "0 0 10px 0",
					width: "260px",
					textAlign: "center",
					borderRadius: "4px",
					boxSizing: "border-box",
					whiteSpace: "nowrap",
					overflow: "hidden",
					textOverflow: "ellipsis"
				}
			}),
			versionList,
			$el("div", {
				style: {
					display: "flex",
					justifyContent: "space-between",
					width: "260px",
					gap: "10px"
				}
			}, [
				$el("button", {
					textContent: "Cancel",
					onclick: () => dialog.close(),
					style: {
						flex: "1",
						padding: "8px",
						backgroundColor: "#4a4a4a",
						color: "#ffffff",
						border: "none",
						borderRadius: "4px",
						cursor: "pointer",
						whiteSpace: "nowrap",
						overflow: "hidden",
						textOverflow: "ellipsis"
					}
				}),
				$el("button", {
					textContent: "Select",
					onclick: () => {
						if (selectedVersion) {
							onSelect(selectedVersion);
							dialog.close();
						} else {
							customAlert("Please select a version.");
						}
					},
					style: {
						flex: "1",
						padding: "8px",
						backgroundColor: "#4CAF50",
						color: "#ffffff",
						border: "none",
						borderRadius: "4px",
						cursor: "pointer",
						whiteSpace: "nowrap",
						overflow: "hidden",
						textOverflow: "ellipsis"
					}
				}),
			])
		]);

		dialog.show(content);
}

async function switchComfyUI() {
	switch_comfyui_button.disabled = true;
	switch_comfyui_button.style.backgroundColor = "gray";
	
	let res = await api.fetchApi(`/comfyui_manager/comfyui_versions`, { cache: "no-store" });

	switch_comfyui_button.disabled = false;
	switch_comfyui_button.style.backgroundColor = "";

	if(res.status == 200) {
		let obj = await res.json();

		let versions = [];
		let default_version;

		for(let v of obj.versions) {
			default_version = v;
			versions.push(v);
		}

		showVersionSelectorDialog(versions, obj.current, async (selected_version) => {
			if(selected_version == 'nightly') {
				update_policy_combo.value = 'nightly-comfyui';
				api.fetchApi('/manager/policy/update?value=nightly-comfyui');
			}
			else {
				update_policy_combo.value = 'stable-comfyui';
				api.fetchApi('/manager/policy/update?value=stable-comfyui');
			}

			let response = await api.fetchApi(`/comfyui_manager/comfyui_switch_version?ver=${selected_version}`, { cache: "no-store" });
			if (response.status == 200) {
				infoToast(`ComfyUI version is switched to ${selected_version}`);
			}
			else {
				customAlert('Failed to switch ComfyUI version.');
			}
		});
	}
	else {
		customAlert('Failed to fetch ComfyUI versions.');
	}
}

async function onQueueStatus(event) {
	const isElectron = 'electronAPI' in window;

	if(event.detail.status == 'in_progress') {
		set_inprogress_mode();
		update_all_button.innerText = `in progress.. (${event.detail.done_count}/${event.detail.total_count})`;
	}
	else if(event.detail.status == 'done') {
		reset_action_buttons();

		if(!is_updating)  {
			return;
		}

		is_updating = false;

		let success_list = [];
		let failed_list = [];
		let comfyui_state = null;

		for(let k in event.detail.nodepack_result){
			let v = event.detail.nodepack_result[k];

			if(k == 'comfyui') {
				comfyui_state = v;
				continue;
			}

			if(v.msg == 'success') {
				success_list.push(k);
			}
			else if(v.msg != 'skip')
				failed_list.push(k);
		}

		let msg = "";
		
		if(success_list.length == 0 && comfyui_state.startsWith('skip')) {
			if(failed_list.length == 0) {
				msg += "You are already up to date.";
			}
		}
		else {
			msg = "To apply the updates, you need to <button class='cm-small-button' id='cm-reboot-button5'>RESTART</button> ComfyUI.<hr>";

			if(comfyui_state == 'success-nightly') {
				msg += "ComfyUI has been updated to latest nightly version.<BR><BR>";
				infoToast("ComfyUI has been updated to the latest nightly version.");
			}
			else if(comfyui_state.startsWith('success-stable')) {
				const ver = comfyui_state.split("-").pop();
				msg += `ComfyUI has been updated to ${ver}.<BR><BR>`;
				infoToast(`ComfyUI has been updated to ${ver}`);
			}
			else if(comfyui_state == 'skip') {
				msg += "ComfyUI is already up to date.<BR><BR>"
			}
			else if(comfyui_state != null) {
				msg += "Failed to update ComfyUI.<BR><BR>"
			}

			if(success_list.length > 0) {
				msg += "The following custom nodes have been updated:<ul>";
				for(let x in success_list) {
					let k = success_list[x];
					let url = event.detail.nodepack_result[k].url;
					let title = event.detail.nodepack_result[k].title;
					if(url) {
						msg += `<li><a href='${url}' target='_blank'>${title}</a></li>`;
					}
					else {
						msg += `<li>${k}</li>`;
					}
				}
				msg += "</ul>";
			}

			setNeedRestart(true);
		}
		
		if(failed_list.length > 0) {
			msg += '<br>The update for the following custom nodes has failed:<ul>';
			for(let x in failed_list) {
				let k = failed_list[x];
				let url = event.detail.nodepack_result[k].url;
				let title = event.detail.nodepack_result[k].title;
				if(url) {
					msg += `<li><a href='${url}' target='_blank'>${title}</a></li>`;
				}
				else {
					msg += `<li>${k}</li>`;
				}
			}

			msg += '</ul>'
		}

		show_message(msg);

		const rebootButton = document.getElementById('cm-reboot-button5');
		rebootButton?.addEventListener("click",
			function() {
				if(rebootAPI()) {
					manager_dialog.close();
				}
			});
	}
}

api.addEventListener("cm-queue-status", onQueueStatus);


async function updateAll(update_comfyui) {
	update_all_button.innerText = "Updating...";

	set_inprogress_mode();

	var mode = manager_instance.datasrc_combo.value;

	showTerminal();

	if(update_comfyui) {
		update_all_button.innerText = "Updating ComfyUI...";
		await api.fetchApi('/manager/queue/update_comfyui');
	}

	const response = await api.fetchApi(`/manager/queue/update_all?mode=${mode}`);

	if (response.status == 401) {
		customAlert('Another task is already in progress. Please stop the ongoing task first.');
	}
	else if(response.status == 200) {
		is_updating = true;
		await api.fetchApi('/manager/queue/start');
	}
}

function newDOMTokenList(initialTokens) {
	const tmp = document.createElement(`div`);

	const classList = tmp.classList;
	if (initialTokens) {
		initialTokens.forEach(token => {
		classList.add(token);
		});
	}

	return classList;
	}

/**
 * Check whether the node is a potential output node (img, gif or video output)
 */
const isOutputNode = (node) => {
	return SUPPORTED_OUTPUT_NODE_TYPES.includes(node.type);
}

function restartOrStop() {
	if(restart_stop_button.innerText == 'Restart'){
		rebootAPI();
	}
	else {
		api.fetchApi('/manager/queue/reset');
		infoToast('Cancel', 'Remaining tasks will stop after completing the current task.');
	}
}

// -----------
class ManagerMenuDialog extends ComfyDialog {
	createControlsMid() {
		let self = this;
		const isElectron = 'electronAPI' in window;
		
		update_comfyui_button =
			$el("button.cm-button", {
				type: "button",
				textContent: "Update ComfyUI",
				style: {
					display: isElectron ? 'none' : 'block'
				},
				onclick:
					() => updateComfyUI()
			});

		switch_comfyui_button =
			$el("button.cm-button", {
				type: "button",
				textContent: "Switch ComfyUI",
				style: {
					display: isElectron ? 'none' : 'block'
				},
				onclick:
					() => switchComfyUI()
			});

		restart_stop_button =
			$el("button.cm-button-red", {
				type: "button",
				textContent: "Restart",
				onclick: () => restartOrStop()
			});

		if(isElectron) {
			update_all_button =
				$el("button.cm-button", {
					type: "button",
					textContent: "Update All Custom Nodes",
					onclick:
						() => updateAll(false)
				});
		}
		else {
			update_all_button =
				$el("button.cm-button", {
					type: "button",
					textContent: "Update All",
					onclick:
						() => updateAll(true)
				});
		}

		const res =
			[
				$el("button.cm-button", {
					type: "button",
					textContent: "Custom Nodes Manager",
					onclick:
						() => {
							if(!CustomNodesManager.instance) {
								CustomNodesManager.instance = new CustomNodesManager(app, self);
							}
							CustomNodesManager.instance.show(CustomNodesManager.ShowMode.NORMAL);
						}
				}),

				$el("button.cm-button", {
					type: "button",
					textContent: "Install Missing Custom Nodes",
					onclick:
						() => {
							if(!CustomNodesManager.instance) {
								CustomNodesManager.instance = new CustomNodesManager(app, self);
							}
							CustomNodesManager.instance.show(CustomNodesManager.ShowMode.MISSING);
						}
				}),

				$el("button.cm-button", {
					type: "button",
					textContent: "Custom Nodes In Workflow",
					onclick:
						() => {
							if(!CustomNodesManager.instance) {
								CustomNodesManager.instance = new CustomNodesManager(app, self);
							}
							CustomNodesManager.instance.show(CustomNodesManager.ShowMode.IN_WORKFLOW);
						}
				}),
				
				$el("br", {}, []),
				$el("button.cm-button", {
					type: "button",
					textContent: "Model Manager",
					onclick:
						() => {
							if(!ModelManager.instance) {
								ModelManager.instance = new ModelManager(app, self);
							}
							ModelManager.instance.show();
						}
				}),

				$el("button.cm-button", {
					type: "button",
					textContent: "Install via Git URL",
					onclick: async () => {
						var url = await customPrompt("Please enter the URL of the Git repository to install", "");

						if (url !== null) {
							install_via_git_url(url, self);
						}
					}
				}),

				$el("br", {}, []),
				update_all_button,
				update_comfyui_button,
				switch_comfyui_button,
				// fetch_updates_button,

				$el("br", {}, []),
				restart_stop_button,
			];

		return res;
	}

	createControlsLeft() {
		const isElectron = 'electronAPI' in window;

		let self = this;

		// db mode
		this.datasrc_combo = document.createElement("select");
		this.datasrc_combo.setAttribute("title", "Configure where to retrieve node/model information. If set to 'local,' the channel is ignored, and if set to 'channel (remote),' it fetches the latest information each time the list is opened.");
		this.datasrc_combo.className = "cm-menu-combo";
		this.datasrc_combo.appendChild($el('option', { value: 'cache', text: 'DB: Channel (1day cache)' }, []));
		this.datasrc_combo.appendChild($el('option', { value: 'local', text: 'DB: Local' }, []));
		this.datasrc_combo.appendChild($el('option', { value: 'remote', text: 'DB: Channel (remote)' }, []));

		api.fetchApi('/manager/db_mode')
			.then(response => response.text())
			.then(data => { this.datasrc_combo.value = data; });

		this.datasrc_combo.addEventListener('change', function (event) {
			api.fetchApi(`/manager/db_mode?value=${event.target.value}`);
		});

		// preview method
		let preview_combo = document.createElement("select");
		preview_combo.setAttribute("title", "Configure how latent variables will be decoded during preview in the sampling process.");
		preview_combo.className = "cm-menu-combo";
		preview_combo.appendChild($el('option', { value: 'auto', text: 'Preview method: Auto' }, []));
		preview_combo.appendChild($el('option', { value: 'taesd', text: 'Preview method: TAESD (slow)' }, []));
		preview_combo.appendChild($el('option', { value: 'latent2rgb', text: 'Preview method: Latent2RGB (fast)' }, []));
		preview_combo.appendChild($el('option', { value: 'none', text: 'Preview method: None (very fast)' }, []));

		api.fetchApi('/manager/preview_method')
			.then(response => response.text())
			.then(data => { preview_combo.value = data; });

		preview_combo.addEventListener('change', function (event) {
			api.fetchApi(`/manager/preview_method?value=${event.target.value}`);
		});

		// channel
		let channel_combo = document.createElement("select");
		channel_combo.setAttribute("title", "Configure the channel for retrieving data from the Custom Node list (including missing nodes) or the Model list.");
		channel_combo.className = "cm-menu-combo";
		api.fetchApi('/manager/channel_url_list')
			.then(response => response.json())
			.then(async data => {
				try {
					let urls = data.list;
					for (let i in urls) {
						if (urls[i] != '') {
							let name_url = urls[i].split('::');
							channel_combo.appendChild($el('option', { value: name_url[0], text: `Channel: ${name_url[0]}` }, []));
						}
					}

					channel_combo.addEventListener('change', function (event) {
						api.fetchApi(`/manager/channel_url_list?value=${event.target.value}`);
					});

					channel_combo.value = data.selected;
				}
				catch (exception) {

				}
			});


		// share
		let share_combo = document.createElement("select");
		share_combo.setAttribute("title", "Hide the share button in the main menu or set the default action upon clicking it. Additionally, configure the default share site when sharing via the context menu's share button.");
		share_combo.className = "cm-menu-combo";
		const share_options = [
			['none', 'None'],
			['openart', 'OpenArt AI'],
			['youml', 'YouML'],
			['matrix', 'Matrix Server'],
			['comfyworkflows', 'ComfyWorkflows'],
			['copus', 'Copus'],
			['all', 'All'],
		];
		for (const option of share_options) {
			share_combo.appendChild($el('option', { value: option[0], text: `Share: ${option[1]}` }, []));
		}

		api.fetchApi('/manager/share_option')
			.then(response => response.text())
			.then(data => {
				share_combo.value = data || 'all';
				share_option = data || 'all';
			});

		share_combo.addEventListener('change', function (event) {
			const value = event.target.value;
			share_option = value;
			api.fetchApi(`/manager/share_option?value=${value}`);
			const shareButton = document.getElementById("shareButton");
			if (value === 'none') {
				shareButton.style.display = "none";
			} else {
				shareButton.style.display = "inline-block";
			}
		});

		let component_policy_combo = document.createElement("select");
		component_policy_combo.setAttribute("title", "When loading the workflow, configure which version of the component to use.");
		component_policy_combo.className = "cm-menu-combo";
		component_policy_combo.appendChild($el('option', { value: 'workflow', text: 'Component: Use workflow version' }, []));
		component_policy_combo.appendChild($el('option', { value: 'higher', text: 'Component: Use higher version' }, []));
		component_policy_combo.appendChild($el('option', { value: 'mine', text: 'Component: Use my version' }, []));
		api.fetchApi('/manager/policy/component')
			.then(response => response.text())
			.then(data => {
				component_policy_combo.value = data;
				set_component_policy(data);
			});

		component_policy_combo.addEventListener('change', function (event) {
			api.fetchApi(`/manager/policy/component?value=${event.target.value}`);
			set_component_policy(event.target.value);
		});

		update_policy_combo = document.createElement("select");

		if(isElectron)
			update_policy_combo.style.display = 'none';
		
		update_policy_combo.setAttribute("title", "Sets the policy to be applied when performing an update.");
		update_policy_combo.className = "cm-menu-combo";
		update_policy_combo.appendChild($el('option', { value: 'stable-comfyui', text: 'Update: ComfyUI Stable Version' }, []));
		update_policy_combo.appendChild($el('option', { value: 'nightly-comfyui', text: 'Update: ComfyUI Nightly Version' }, []));
		api.fetchApi('/manager/policy/update')
			.then(response => response.text())
			.then(data => {
				update_policy_combo.value = data;
			});

		update_policy_combo.addEventListener('change', function (event) {
			api.fetchApi(`/manager/policy/update?value=${event.target.value}`);
		});

		return [
			$el("br", {}, []),
			this.datasrc_combo,
			channel_combo,
			preview_combo,
			share_combo,
			component_policy_combo,
			update_policy_combo,
			$el("br", {}, []),

			$el("br", {}, []),
			$el("filedset.cm-experimental", {}, [
					$el("legend.cm-experimental-legend", {}, ["EXPERIMENTAL"]),
					$el("button.cm-experimental-button", {
						type: "button",
						textContent: "Snapshot Manager",
						onclick:
							() => {
								if(!SnapshotManager.instance)
								SnapshotManager.instance = new SnapshotManager(app, self);
								SnapshotManager.instance.show();
							}
					}),
					$el("button.cm-experimental-button", {
						type: "button",
						textContent: "Install PIP packages",
						onclick:
							async () => {
								var url = await customPrompt("Please enumerate the pip packages to be installed.\n\nExample: insightface opencv-python-headless>=4.1.1\n", "");

								if (url !== null) {
									install_pip(url, self);
								}
							}
					})
				]),
		];
	}

	createControlsRight() {
		const elts = [
				$el("button.cm-button", {
					id: 'cm-manual-button',
					type: "button",
					textContent: "Community Manual",
					onclick: () => { window.open("https://blenderneko.github.io/ComfyUI-docs/", "comfyui-community-manual"); }
				}, [
					$el("div.pysssss-workflow-arrow-2", {
						id: `cm-manual-button-arrow`,
						onclick: (e) => {
							e.preventDefault();
							e.stopPropagation();

							LiteGraph.closeAllContextMenus();
							const menu = new LiteGraph.ContextMenu(
								[
									{
										title: "ComfyUI Docs",
										callback: () => { window.open("https://docs.comfy.org/", "comfyui-official-manual"); },
									},
									{
										title: "Comfy Custom Node How To",
										callback: () => { window.open("https://github.com/chrisgoringe/Comfy-Custom-Node-How-To/wiki/aaa_index", "comfyui-community-manual1"); },
									},
									{
										title: "ComfyUI Guide To Making Custom Nodes",
										callback: () => { window.open("https://github.com/Suzie1/ComfyUI_Guide_To_Making_Custom_Nodes/wiki", "comfyui-community-manual2"); },
									},
									{
										title: "ComfyUI Examples",
										callback: () => { window.open("https://comfyanonymous.github.io/ComfyUI_examples", "comfyui-community-manual3"); },
									},
									{
										title: "Close",
										callback: () => {
											LiteGraph.closeAllContextMenus();
										},
									}
								],
								{
									event: e,
									scale: 1.3,
								},
								window
							);
							// set the id so that we can override the context menu's z-index to be above the comfyui manager menu
							menu.root.id = "cm-manual-button-menu";
							menu.root.classList.add("pysssss-workflow-popup-2");
						},
					})
				]),

				$el("button", {
					id: 'workflowgallery-button',
					type: "button",
					style: {
						...(localStorage.getItem("wg_last_visited") ? {height: '50px'} : {})
					},
					onclick: (e) => {
						const last_visited_site = localStorage.getItem("wg_last_visited")
						if (!!last_visited_site) {
							window.open(last_visited_site, last_visited_site);
						} else {
							this.handleWorkflowGalleryButtonClick(e)
						}
					},
				}, [
					$el("p", {
						textContent: 'Workflow Gallery',
						style: {
							'text-align': 'center',
							'color': 'var(--input-text)',
							'font-size': '18px',
							'margin': 0,
							'padding': 0,
						}
					}, [
						$el("p", {
							id: 'workflowgallery-button-last-visited-label',
							textContent: `(${localStorage.getItem("wg_last_visited") ? localStorage.getItem("wg_last_visited").split('/')[2] : ''})`,
							style: {
								'text-align': 'center',
								'color': 'var(--input-text)',
								'font-size': '12px',
								'margin': 0,
								'padding': 0,
							}
						})
					]),
					$el("div.pysssss-workflow-arrow-2", {
						id: `comfyworkflows-button-arrow`,
						onclick: this.handleWorkflowGalleryButtonClick
					})
				]),

				$el("button.cm-button", {
					id: 'cm-nodeinfo-button',
					type: "button",
					textContent: "Nodes Info",
					onclick: () => { window.open("https://ltdrdata.github.io/", "comfyui-node-info"); }
				}),
				$el("br", {}, []),
		];

		var textarea = document.createElement("div");
		textarea.className = "cm-notice-board";
		elts.push(textarea);

		init_notice(textarea);

		return elts;
	}

	constructor() {
		super();

		const close_button = $el("button", { id: "cm-close-button", type: "button", textContent: "Close", onclick: () => this.close() });

		const content =
				$el("div.comfy-modal-content",
					[
						$el("tr.cm-title", {}, [
								$el("font", {size:6, color:"white"}, [`ComfyUI Manager ${manager_version}`])]
							),
						$el("br", {}, []),
						$el("div.cm-menu-container",
							[
								$el("div.cm-menu-column", [...this.createControlsLeft()]),
								$el("div.cm-menu-column", [...this.createControlsMid()]),
								$el("div.cm-menu-column", [...this.createControlsRight()])
							]),

						$el("br", {}, []),
						close_button,
					]
				);

		content.style.width = '100%';
		content.style.height = '100%';

		this.element = $el("div.comfy-modal", { id:'cm-manager-dialog', parent: document.body }, [ content ]);
	}

	get isVisible() {
		return this.element?.style?.display !== "none";
	}

	show() {
		this.element.style.display = "block";
	}

	toggleVisibility() {
		if (this.isVisible) {
			this.close();
		} else {
			this.show();
		}
	}

	handleWorkflowGalleryButtonClick(e) {
		e.preventDefault();
		e.stopPropagation();
		LiteGraph.closeAllContextMenus();

		// Modify the style of the button so that the UI can indicate the last
		// visited site right away.
		const modifyButtonStyle = (url) => {
			const workflowGalleryButton = document.getElementById('workflowgallery-button');
			workflowGalleryButton.style.height = '50px';
			const lastVisitedLabel = document.getElementById('workflowgallery-button-last-visited-label');
			lastVisitedLabel.textContent = `(${url.split('/')[2]})`;
		}

		const menu = new LiteGraph.ContextMenu(
			[
				{
					title: "Share your art",
					callback: () => {
						if (share_option === 'openart') {
							showOpenArtShareDialog();
							return;
						} else if (share_option === 'matrix' || share_option === 'comfyworkflows') {
							showShareDialog(share_option);
							return;
						} else if (share_option === 'youml') {
							showYouMLShareDialog();
							return;
						}

						if (!ShareDialogChooser.instance) {
							ShareDialogChooser.instance = new ShareDialogChooser();
						}
						ShareDialogChooser.instance.show();
					},
				},
				{
					title: "Open 'openart.ai'",
					callback: () => {
						const url = "https://openart.ai/workflows/dev";
						localStorage.setItem("wg_last_visited", url);
						window.open(url, url);
						modifyButtonStyle(url);
					},
				},
				{
					title: "Open 'youml.com'",
					callback: () => {
						const url = "https://youml.com/?from=comfyui-share";
						localStorage.setItem("wg_last_visited", url);
						window.open(url, url);
						modifyButtonStyle(url);
					},
				},
				{
					title: "Open 'comfyworkflows.com'",
					callback: () => {
						const url = "https://comfyworkflows.com/";
						localStorage.setItem("wg_last_visited", url);
						window.open(url, url);
						modifyButtonStyle(url);
					},
				},
				{
					title: "Open 'esheep'",
					callback: () => {
						const url = "https://www.esheep.com";
						localStorage.setItem("wg_last_visited", url);
						window.open(url, url);
						modifyButtonStyle(url);
					},
				},
				{
					title: "Open 'Copus.io'",
					callback: () => {
						const url = "https://www.copus.io";
						localStorage.setItem("wg_last_visited", url);
						window.open(url, url);
						modifyButtonStyle(url);
					},
				},
				{
					title: "Close",
					callback: () => {
						LiteGraph.closeAllContextMenus();
					},
				}
			],
			{
				event: e,
				scale: 1.3,
			},
			window
		);
		// set the id so that we can override the context menu's z-index to be above the comfyui manager menu
		menu.root.id = "workflowgallery-button-menu";
		menu.root.classList.add("pysssss-workflow-popup-2");
	}
}

async function getVersion() {
	let version = await api.fetchApi(`/manager/version`);
	return await version.text();
}

app.registerExtension({
	name: "Comfy.ManagerMenu",

	aboutPageBadges: [
		{
			label: `ComfyUI-Manager ${manager_version}`,
			url: 'https://github.com/ltdrdata/ComfyUI-Manager',
			icon: 'pi pi-th-large'
		}
	],

	commands: [
	{
		id: "Comfy.Manager.Menu.ToggleVisibility",
		label: "Toggle Manager Menu Visibility",
		icon: "mdi mdi-puzzle",
		function: () => {
			if (!manager_instance) {
				setManagerInstance(new ManagerMenuDialog());
				manager_instance.show();
			} else {
				manager_instance.toggleVisibility();
			}
		},
	},
	{
		id: "Comfy.Manager.CustomNodesManager.ToggleVisibility",
		label: "Toggle Custom Nodes Manager Visibility",
		icon: "pi pi-server",
		function: () => {
			if (CustomNodesManager.instance?.isVisible) {
				CustomNodesManager.instance.close();
				return;
			}

			if (!manager_instance) {
				setManagerInstance(new ManagerMenuDialog());
			}
			if (!CustomNodesManager.instance) {
				CustomNodesManager.instance = new CustomNodesManager(app, self);
			}
			CustomNodesManager.instance.show(CustomNodesManager.ShowMode.NORMAL);
		},
	}
	],

	init() {
		$el("style", {
			textContent: style,
			parent: document.head,
		});
	},
	async setup() {
		let orig_clear = app.graph.clear;
		app.graph.clear = function () {
			orig_clear.call(app.graph);
			load_components();
		};

		load_components();

		const menu = document.querySelector(".comfy-menu");
		const separator = document.createElement("hr");

		separator.style.margin = "20px 0";
		separator.style.width = "100%";
		menu.append(separator);

		try {
			// new style Manager buttons
			// unload models button into new style Manager button
			let cmGroup = new (await import("../../scripts/ui/components/buttonGroup.js")).ComfyButtonGroup(
				new(await import("../../scripts/ui/components/button.js")).ComfyButton({
					icon: "puzzle",
					action: () => {
						if(!manager_instance)
							setManagerInstance(new ManagerMenuDialog());
						manager_instance.show();
					},
					tooltip: "ComfyUI Manager",
					content: "Manager",
					classList: "comfyui-button comfyui-menu-mobile-collapse primary"
				}).element,
				new(await import("../../scripts/ui/components/button.js")).ComfyButton({
					icon: "star",
					action: () => {
						if(!manager_instance)
							setManagerInstance(new ManagerMenuDialog());

                        if(!CustomNodesManager.instance) {
                            CustomNodesManager.instance = new CustomNodesManager(app, self);
                        }
                        CustomNodesManager.instance.show(CustomNodesManager.ShowMode.FAVORITES);
					},
					tooltip: "Show favorite custom node list"
				}).element,
				new(await import("../../scripts/ui/components/button.js")).ComfyButton({
					icon: "vacuum-outline",
					action: () => {
						free_models();
					},
					tooltip: "Unload Models"
				}).element,
				new(await import("../../scripts/ui/components/button.js")).ComfyButton({
					icon: "vacuum",
					action: () => {
						free_models(true);
					},
					tooltip: "Free model and node cache"
				}).element,
				new(await import("../../scripts/ui/components/button.js")).ComfyButton({
					icon: "share",
					action: () => {
						if (share_option === 'openart') {
							showOpenArtShareDialog();
							return;
						} else if (share_option === 'matrix' || share_option === 'comfyworkflows') {
							showShareDialog(share_option);
							return;
						} else if (share_option === 'youml') {
							showYouMLShareDialog();
							return;
						}

						if(!ShareDialogChooser.instance) {
							ShareDialogChooser.instance = new ShareDialogChooser();
						}
						ShareDialogChooser.instance.show();
					},
					tooltip: "Share"
				}).element
			);

			app.menu?.settingsGroup.element.before(cmGroup.element);
		}
		catch(exception) {
			console.log('ComfyUI is outdated. New style menu based features are disabled.');
		}

		// old style Manager button
		const managerButton = document.createElement("button");
		managerButton.textContent = "Manager";
		managerButton.onclick = () => {
				if(!manager_instance)
					setManagerInstance(new ManagerMenuDialog());
				manager_instance.show();
			}
		menu.append(managerButton);

		const shareButton = document.createElement("button");
		shareButton.id = "shareButton";
		shareButton.textContent = "Share";
		shareButton.onclick = () => {
			if (share_option === 'openart') {
				showOpenArtShareDialog();
				return;
			} else if (share_option === 'matrix' || share_option === 'comfyworkflows') {
				showShareDialog(share_option);
				return;
			} else if (share_option === 'youml') {
				showYouMLShareDialog();
				return;
			}

			if(!ShareDialogChooser.instance) {
				ShareDialogChooser.instance = new ShareDialogChooser();
			}
			ShareDialogChooser.instance.show();
		}
		// make the background color a gradient of blue to green
		shareButton.style.background = "linear-gradient(90deg, #00C9FF 0%, #92FE9D 100%)";
		shareButton.style.color = "black";

		// Load share option from local storage to determine whether to show
		// the share button.
		const shouldShowShareButton = share_option !== 'none';
		shareButton.style.display = shouldShowShareButton ? "inline-block" : "none";

		menu.append(shareButton);
	},

	async beforeRegisterNodeDef(nodeType, nodeData, app) {
		this._addExtraNodeContextMenu(nodeType, app);
	},

	_addExtraNodeContextMenu(node, app) {
		const origGetExtraMenuOptions = node.prototype.getExtraMenuOptions;
		node.prototype.cm_menu_added = true;
		node.prototype.getExtraMenuOptions = function (_, options) {
			origGetExtraMenuOptions?.apply?.(this, arguments);

			if (node.category.startsWith('group nodes>')) {
				options.push({
					content: "Save As Component",
					callback: (obj) => {
						if (!ComponentBuilderDialog.instance) {
							ComponentBuilderDialog.instance = new ComponentBuilderDialog();
						}
						ComponentBuilderDialog.instance.target_node = node;
						ComponentBuilderDialog.instance.show();
					}
				}, null);
			}

			if (isOutputNode(node)) {
				const { potential_outputs } = getPotentialOutputsAndOutputNodes([this]);
				const hasOutput = potential_outputs.length > 0;

				// Check if the previous menu option is `null`. If it's not,
				// then we need to add a `null` as a separator.
				if (options[options.length - 1] !== null) {
					options.push(null);
				}

				options.push({
					content: "🏞️ Share Output",
					disabled: !hasOutput,
					callback: (obj) => {
						if (!ShareDialog.instance) {
							ShareDialog.instance = new ShareDialog();
						}
						const shareButton = document.getElementById("shareButton");
						if (shareButton) {
							const currentNode = this;
							if (!OpenArtShareDialog.instance) {
								OpenArtShareDialog.instance = new OpenArtShareDialog();
							}
							OpenArtShareDialog.instance.selectedNodeId = currentNode.id;
							if (!ShareDialog.instance) {
								ShareDialog.instance = new ShareDialog(share_option);
							}
							ShareDialog.instance.selectedNodeId = currentNode.id;
							shareButton.click();
						}
					}
				}, null);
			}
		}
	},
});
