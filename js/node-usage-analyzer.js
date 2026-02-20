import { app } from "../../scripts/app.js";
import { $el } from "../../scripts/ui.js";
import {
	manager_instance,
	fetchData, md5, show_message, customAlert, infoToast, showTerminal,
	storeColumnWidth, restoreColumnWidth, loadCss, uninstallNodes,
	analyzeWorkflowUsage, sizeToBytes, createFlyover, createUIStateManager
} from "./common.js";
import { api } from "../../scripts/api.js";

// https://cenfun.github.io/turbogrid/api.html
import TG from "./turbogrid.esm.js";

loadCss("./node-usage-analyzer.css");

const gridId = "model";

const pageHtml = `
<div class="nu-manager-header">
	<div class="nu-manager-status"></div>
	<input type="text" class="nu-manager-keywords" placeholder="Filter keywords..." />
	<div class="nu-flex-auto"></div>
</div>
<div class="nu-manager-grid"></div>
<div class="nu-manager-selection"></div>
<div class="nu-manager-message"></div>
<div class="nu-manager-footer">
	<button class="nu-manager-back">
		<svg class="arrow-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
			<path d="M2 8H18M2 8L8 2M2 8L8 14" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
		</svg>
		Back
	</button>
	<button class="nu-manager-refresh">Refresh</button>
	<button class="nu-manager-stop">Stop</button>
	<div class="nu-flex-auto"></div>
</div>
`;

export class NodeUsageAnalyzer {
	static instance = null;

	static SortMode = {
		BY_PACKAGE: 'by_package'
	};

	constructor(app, manager_dialog) {
		this.app = app;
		this.manager_dialog = manager_dialog;
		this.id = "nu-manager";

		this.filter = '';
		this.type = '';
		this.base = '';
		this.keywords = '';

		this.init();

		// Initialize shared UI state manager
		this.ui = createUIStateManager(this.element, {
			selection: ".nu-manager-selection",
			message: ".nu-manager-message",
			status: ".nu-manager-status",
			refresh: ".nu-manager-refresh",
			stop: ".nu-manager-stop"
		});

		api.addEventListener("cm-queue-status", this.onQueueStatus);
	}

	init() {
		this.element = $el("div", {
			parent: document.body,
			className: "comfy-modal nu-manager"
		});
		this.element.innerHTML = pageHtml;
		this.bindEvents();
		this.initGrid();
	}

	bindEvents() {
		const eventsMap = {
			".nu-manager-selection": {
				click: (e) => {
					const target = e.target;
					const mode = target.getAttribute("mode");
					if (mode === "install") {
						this.installModels(this.selectedModels, target);
					} else if (mode === "uninstall") {
						this.uninstallModels(this.selectedModels, target);
					}
				}
			},

			".nu-manager-refresh": {
				click: () => {
					app.refreshComboInNodes();
				}
			},

			".nu-manager-stop": {
				click: () => {
					api.fetchApi('/manager/queue/reset');
					infoToast('Cancel', 'Remaining tasks will stop after completing the current task.');
				}
			},

			".nu-manager-back": {
				click: (e) => {
					this.close()
					manager_instance.show();
				}
			}
		};
		Object.keys(eventsMap).forEach(selector => {
			const target = this.element.querySelector(selector);
			if (target) {
				const events = eventsMap[selector];
				if (events) {
					Object.keys(events).forEach(type => {
						target.addEventListener(type, events[type]);
					});
				}
			}
		});
	}

	// ===========================================================================================

	initGrid() {
		const container = this.element.querySelector(".nu-manager-grid");
		const grid = new TG.Grid(container);
		this.grid = grid;

		this.flyover = createFlyover(container, { context: this });

		grid.bind('onUpdated', (e, d) => {
			this.ui.showStatus(`${grid.viewRows.length.toLocaleString()} installed packages`);

		});

		grid.bind('onSelectChanged', (e, changes) => {
			this.renderSelected();
		});

		grid.bind("onColumnWidthChanged", (e, columnItem) => {
			storeColumnWidth(gridId, columnItem)
		});

		grid.bind('onClick', (e, d) => {
			const { rowItem } = d;
			const target = d.e.target;
			const mode = target.getAttribute("mode");

			if (mode === "install") {
				this.installModels([rowItem], target);
				return;
			}

			if (mode === "uninstall") {
				this.uninstallModels([rowItem], target);
				return;
			}

			// Handle click on usage count
			if (d.columnItem.id === "used_in_count" && rowItem.used_in_count > 0) {
				this.showUsageDetails(rowItem);
				return;
			}

		});

		grid.setOption({
			theme: 'dark',

			selectVisible: true,
			selectMultiple: true,
			selectAllVisible: true,

			textSelectable: true,
			scrollbarRound: true,

			frozenColumn: 1,
			rowNotFound: "No Results",

			rowHeight: 40,
			bindWindowResize: true,
			bindContainerResize: true,

			cellResizeObserver: (rowItem, columnItem) => {
				const autoHeightColumns = ['name', 'description'];
				return autoHeightColumns.includes(columnItem.id)
			}
		});

	}

	renderGrid() {

		// update theme
		const colorPalette = this.app.ui.settings.settingsValues['Comfy.ColorPalette'];
		Array.from(this.element.classList).forEach(cn => {
			if (cn.startsWith("nu-manager-")) {
				this.element.classList.remove(cn);
			}
		});
		this.element.classList.add(`nu-manager-${colorPalette}`);

		const options = {
			theme: colorPalette === "light" ? "" : "dark"
		};

		const rows = this.modelList || [];

		const columns = [{
			id: 'title',
			name: 'Title',
			width: 200,
			minWidth: 100,
			maxWidth: 500,
			classMap: 'nu-pack-name',
			formatter: function (name, rowItem, columnItem, cellNode) {
				return `<a href=${rowItem.reference} target="_blank"><b>${name}</b></a>`;
			}
		}, {
			id: 'used_in_count',
			name: 'Used in',
			width: 100,
			formatter: function (usedCount, rowItem, columnItem) {
				if (!usedCount || usedCount === 0) {
					return '0';
				}
				const plural = usedCount > 1 ? 's' : '';
				return `<div class="cn-pack-nodes" style="cursor: pointer;">${usedCount} workflow${plural}</div>`;
			}
		}, {
			id: 'action',
			name: 'Action',
			width: 160,
			minWidth: 140,
			maxWidth: 200,
			sortable: false,
			align: 'center',
			formatter: function (action, rowItem, columnItem) {
				// Only show uninstall button for installed packages
				if (rowItem.originalData && rowItem.originalData.state && rowItem.originalData.state !== "not-installed") {
					return `<div class="cn-install-buttons"><button class="nu-btn-uninstall" mode="uninstall">Uninstall</button></div>`;
				}
				return '';
			}
		}];

		restoreColumnWidth(gridId, columns);

		this.grid.setData({
			options,
			rows,
			columns
		});

		this.grid.render();

	}

	updateGrid() {
		if (this.grid) {
			this.grid.update();
		}
	}


	showUsageDetails(rowItem) {
		const workflowList = rowItem.workflowDetails;
		if (!workflowList || workflowList.length === 0) {
			return;
		}

		let titleHtml = `<div class="cn-nodes-pack">${rowItem.title}</div>`;

		const list = [];
		list.push(`<div class="cn-nodes-list">`);

		workflowList.forEach((workflow, i) => {
			list.push(`<div class="cn-nodes-row">`);
			list.push(`<div class="cn-nodes-sn">${i + 1}</div>`);
			list.push(`<div class="cn-nodes-name">${workflow.filename}</div>`);
			list.push(`<div class="cn-nodes-details">${workflow.nodeCount} node${workflow.nodeCount > 1 ? 's' : ''}</div>`);
			list.push(`</div>`);
		});

		list.push("</div>");
		const bodyHtml = list.join("");

		this.flyover.show(titleHtml, bodyHtml);
	}

	renderSelected() {
		const selectedList = this.grid.getSelectedRows();
		if (!selectedList.length) {
			this.ui.showSelection("");
			return;
		}

		const installedSelected = selectedList.filter(item =>
			item.originalData && item.originalData.state && item.originalData.state !== "not-installed"
		);

		if (installedSelected.length === 0) {
			this.ui.showSelection(`<span>Selected <b>${selectedList.length}</b> packages (none can be uninstalled)</span>`);
			return;
		}

		this.selectedModels = installedSelected;

		this.ui.showSelection(`
			<div class="nu-selected-buttons">
				<span>Selected <b>${installedSelected.length}</b> installed packages</span>
				<button class="nu-btn-uninstall" mode="uninstall">Uninstall Selected</button>
			</div>
		`);
	}

	// ===========================================================================================

	async installModels(list, btn) {
		let stats = await api.fetchApi('/manager/queue/status');

		stats = await stats.json();
		if (stats.is_processing) {
			customAlert(`[ComfyUI-Manager] There are already tasks in progress. Please try again after it is completed. (${stats.done_count}/${stats.total_count})`);
			return;
		}

		btn.classList.add("nu-btn-loading");
		this.ui.showError("");

		let needRefresh = false;
		let errorMsg = "";

		await api.fetchApi('/manager/queue/reset');

		let target_items = [];

		for (const item of list) {
			this.grid.scrollRowIntoView(item);
			target_items.push(item);


			this.ui.showStatus(`Install ${item.name} ...`);

			const data = item.originalData;
			data.ui_id = item.hash;

			const res = await api.fetchApi(`/manager/queue/install_model`, {
				method: 'POST',
				body: JSON.stringify(data)
			});

			if (res.status != 200) {
				errorMsg = `'${item.name}': `;

				if (res.status == 403) {
					errorMsg += `This action is not allowed with this security level configuration.\n`;
				} else {
					errorMsg += await res.text() + '\n';
				}

				break;
			}
		}

		this.install_context = { btn: btn, targets: target_items };

		if (errorMsg) {
			this.ui.showError(errorMsg);
			show_message("[Installation Errors]\n" + errorMsg);

			// reset
			for (let k in target_items) {
				const item = target_items[k];
				this.grid.updateCell(item, "installed");
			}
		}
		else {
			await api.fetchApi('/manager/queue/start');
			this.ui.showStop();
			showTerminal();
		}
	}

	async uninstallModels(list, btn) {
		btn.classList.add("nu-btn-loading");
		this.ui.showError("");

		const result = await uninstallNodes(list, {
			title: list.length === 1 ? list[0].title || list[0].name : `${list.length} custom nodes`,
			channel: 'default',
			mode: 'default',
			onProgress: (msg) => {
				this.showStatus(msg);
			},
			onError: (errorMsg) => {
				this.showError(errorMsg);
			},
			onSuccess: (targets) => {
				this.showStatus(`Uninstalled ${targets.length} custom node(s) successfully`);
				this.showMessage(`To apply the uninstalled custom nodes, please restart ComfyUI and refresh browser.`, "red");
				// Update the grid to reflect changes
				for (let item of targets) {
					if (item.originalData) {
						item.originalData.state = "not-installed";
					}
					this.grid.updateRow(item);
				}
			}
		});

		if (result.success) {
			this.showStop();
		}

		btn.classList.remove("nu-btn-loading");
	}

	async onQueueStatus(event) {
		let self = NodeUsageAnalyzer.instance;

		if (event.detail.status == 'in_progress' && (event.detail.ui_target == 'model_manager' || event.detail.ui_target == 'nodepack_manager')) {
			const hash = event.detail.target;

			const item = self.grid.getRowItemBy("hash", hash);

			if (item) {
				item.refresh = true;
				self.grid.setRowSelected(item, false);
				item.selectable = false;
				self.grid.updateRow(item);
			}
		}
		else if (event.detail.status == 'done') {
			self.hideStop();
			self.onQueueCompleted(event.detail);
		}
	}

	async onQueueCompleted(info) {
		let result = info.model_result || info.nodepack_result;

		if (!result || result.length == 0) {
			return;
		}

		let self = NodeUsageAnalyzer.instance;

		if (!self.install_context) {
			return;
		}

		let btn = self.install_context.btn;

		self.hideLoading();
		btn.classList.remove("nu-btn-loading");

		let errorMsg = "";

		for (let hash in result) {
			let v = result[hash];

			if (v != 'success' && v != 'skip')
				errorMsg += v + '\n';
		}

		for (let k in self.install_context.targets) {
			let item = self.install_context.targets[k];
			if (info.model_result) {
				self.grid.updateCell(item, "installed");
			} else if (info.nodepack_result) {
				// Handle uninstall completion
				if (item.originalData) {
					item.originalData.state = "not-installed";
				}
				self.grid.updateRow(item);
			}
		}

		if (errorMsg) {
			self.showError(errorMsg);
			show_message("Operation Error:\n" + errorMsg);
		} else {
			if (info.model_result) {
				self.showStatus(`Install ${Object.keys(result).length} models successfully`);
				self.showRefresh();
				self.showMessage(`To apply the installed model, please click the 'Refresh' button.`, "red");
			} else if (info.nodepack_result) {
				self.showStatus(`Uninstall ${Object.keys(result).length} custom node(s) successfully`);
				self.showMessage(`To apply the uninstalled custom nodes, please restart ComfyUI and refresh browser.`, "red");
			}
		}

		infoToast('Tasks done', `[ComfyUI-Manager] All tasks in the queue have been completed.\n${info.done_count}/${info.total_count}`);
		self.install_context = undefined;
	}

	getModelList(models) {
		const typeMap = new Map();
		const baseMap = new Map();

		models.forEach((item, i) => {
			const { type, base, name, reference, installed } = item;
			// CRITICAL FIX: Do NOT overwrite originalData - it contains the needed state field!
			item.size = sizeToBytes(item.size);
			item.hash = md5(name + reference);

			if (installed === "True") {
				item.selectable = false;
			}

			typeMap.set(type, type);
			baseMap.set(base, base);

		});

		const typeList = [];
		typeMap.forEach(type => {
			typeList.push({
				label: type,
				value: type
			});
		});
		typeList.sort((a, b) => {
			const au = a.label.toUpperCase();
			const bu = b.label.toUpperCase();
			if (au !== bu) {
				return au > bu ? 1 : -1;
			}
			return 0;
		});
		this.typeList = [{
			label: "All",
			value: ""
		}].concat(typeList);


		const baseList = [];
		baseMap.forEach(base => {
			baseList.push({
				label: base,
				value: base
			});
		});
		baseList.sort((a, b) => {
			const au = a.label.toUpperCase();
			const bu = b.label.toUpperCase();
			if (au !== bu) {
				return au > bu ? 1 : -1;
			}
			return 0;
		});
		this.baseList = [{
			label: "All",
			value: ""
		}].concat(baseList);

		return models;
	}

	// ===========================================================================================

	async loadData() {

		this.showLoading();
		this.showStatus(`Analyzing node usage ...`);

		const mode = manager_instance.datasrc_combo.value;

		const nodeListRes = await fetchData(`/customnode/getlist?mode=${mode}&skip_update=true`);
		if (nodeListRes.error) {
			this.showError("Failed to get custom node list.");
			this.hideLoading();
			return;
		}

		const { channel, node_packs } = nodeListRes.data;
		delete node_packs['comfyui-manager'];
		this.installed_custom_node_packs = node_packs;

		// Use the consolidated workflow analysis utility
		const result = await analyzeWorkflowUsage(node_packs);

		if (!result.success) {
			if (result.error.toString().includes('204')) {
				this.showMessage("No workflows were found for analysis.");
			} else {
				this.showError(result.error);
				this.hideLoading();
				return;
			}
		}

		// Transform node_packs into models format - ONLY INSTALLED PACKAGES
		const models = [];

		Object.keys(node_packs).forEach((packKey, index) => {
			const pack = node_packs[packKey];

			// Only include installed packages (filter out "not-installed" packages)
			if (pack.state === "not-installed") {
				return; // Skip non-installed packages
			}

			const usedCount = result.usageMap?.get(packKey) || 0;
			const workflowDetails = result.workflowDetailsMap?.get(packKey) || [];

			models.push({
				title: pack.title || packKey,
				reference: pack.reference || pack.files?.[0] || '#',
				used_in_count: usedCount,
				workflowDetails: workflowDetails,
				name: packKey,
				originalData: pack
			});
		});

		// Sort by usage count (descending) then by title
		models.sort((a, b) => {
			if (b.used_in_count !== a.used_in_count) {
				return b.used_in_count - a.used_in_count;
			}
			return a.title.localeCompare(b.title);
		});

		this.modelList = this.getModelList(models);

		this.renderGrid();

		this.hideLoading();

	}

	// ===========================================================================================

	showSelection(msg) {
		this.element.querySelector(".nu-manager-selection").innerHTML = msg;
	}

	showError(err) {
		this.showMessage(err, "red");
	}

	showMessage(msg, color) {
		if (color) {
			msg = `<font color="${color}">${msg}</font>`;
		}
		this.element.querySelector(".nu-manager-message").innerHTML = msg;
	}

	showStatus(msg, color) {
		if (color) {
			msg = `<font color="${color}">${msg}</font>`;
		}
		this.element.querySelector(".nu-manager-status").innerHTML = msg;
	}

	showLoading() {
		//		this.setDisabled(true);
		if (this.grid) {
			this.grid.showLoading();
			this.grid.showMask({
				opacity: 0.05
			});
		}
	}

	hideLoading() {
		//		this.setDisabled(false);
		if (this.grid) {
			this.grid.hideLoading();
			this.grid.hideMask();
		}
	}

	setDisabled(disabled) {
		const $close = this.element.querySelector(".nu-manager-close");
		const $refresh = this.element.querySelector(".nu-manager-refresh");
		const $stop = this.element.querySelector(".nu-manager-stop");

		const list = [
			".nu-manager-header input",
			".nu-manager-header select",
			".nu-manager-footer button",
			".nu-manager-selection button"
		].map(s => {
			return Array.from(this.element.querySelectorAll(s));
		})
			.flat()
			.filter(it => {
				return it !== $close && it !== $refresh && it !== $stop;
			});

		list.forEach($elem => {
			if (disabled) {
				$elem.setAttribute("disabled", "disabled");
			} else {
				$elem.removeAttribute("disabled");
			}
		});

		Array.from(this.element.querySelectorAll(".nu-btn-loading")).forEach($elem => {
			$elem.classList.remove("nu-btn-loading");
		});

	}

	showRefresh() {
		this.element.querySelector(".nu-manager-refresh").style.display = "block";
	}

	showStop() {
		this.element.querySelector(".nu-manager-stop").style.display = "block";
	}

	hideStop() {
		this.element.querySelector(".nu-manager-stop").style.display = "none";
	}

	setKeywords(keywords = "") {
		this.keywords = keywords;
		this.element.querySelector(".nu-manager-keywords").value = keywords;
	}

	show(sortMode) {
		this.element.style.display = "flex";
		this.setKeywords("");
		this.showSelection("");
		this.showMessage("");
		this.loadData();
	}

	close() {
		this.element.style.display = "none";
	}
}