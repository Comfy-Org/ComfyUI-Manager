import { app } from "../../scripts/app.js";
import { $el } from "../../scripts/ui.js";
import { 
	manager_instance, rebootAPI, 
	fetchData, md5, icons, show_message, customAlert, infoToast, showTerminal,
	storeColumnWidth, restoreColumnWidth, loadCss, generateUUID,
	sanitizeHTML, sanitizeUrl
} from  "./common.js";

// Model names and descriptions are server-escaped; other fields are raw.

import { api } from "../../scripts/api.js";

// https://cenfun.github.io/turbogrid/api.html
import ManagerGrid from "./manager-grid.js";
import { buildGuiFrameCustomHeader,  createSettingsCombo } from "./comfyui-gui-builder.js";

loadCss("./model-manager.css");

const gridId = "model";
const escapeCell = (value) => sanitizeHTML(String(value ?? ""));

const pageHtml = `
<div class="cmm-manager cmm-manager-dark">
	<div class="cmm-manager-grid"></div>
	<div class="cmm-manager-selection"></div>
	<div class="cmm-manager-message"></div>
	<div class="cmm-manager-footer">
		<button class="cmm-manager-refresh p-button p-component">Refresh</button>
		<button class="cmm-manager-stop p-button p-component">Stop</button>
		<div class="cmm-flex-auto"></div>
	</div>
</div>
`;

export class ModelManager {
	static instance = null;

	constructor(app, manager_dialog) {
		this.app = app;
		this.manager_dialog = manager_dialog;
		this.id = "cmm-manager";

		this.filter = '';
		this.type = '';
		this.base = '';
		this.keywords = '';

		this.init();

		api.addEventListener("cm-queue-status", this.onQueueStatus);
	}

	init() {
		const header = $el("div.cmm-manager-header", {}, [
			createSettingsCombo("Filter", $el("select.cmm-manager-filter")),
			createSettingsCombo("Type", $el("select.cmm-manager-type")),
			createSettingsCombo("Base", $el("select.cmm-manager-base")),
			$el("input.cmm-manager-keywords.p-inputtext.p-component", { type: "search", placeholder: "Search" }),
			$el("div.cmm-manager-status"),
			$el("div.cmm-flex-auto")
		]);

		const frame = buildGuiFrameCustomHeader(
			'cmm-manager-dialog', // dialog id
			header, // custom header element
			pageHtml, // dialog content element
			this
		);	// send this so we can attach close functions

		this.element = frame;
		this.initFilter();
		this.bindEvents();
		this.initGrid();
	}

	initFilter() {
		
		this.filterList = [{
			label: "All",
			value: ""
		}, {
			label: "Installed",
			value: "installed"
		}, {
			label: "Not Installed",
			value: "not_installed"
		}, {
			label: "In Workflow",
			value: "in_workflow"
		}];

		this.typeList = [{
			label: "All",
			value: ""
		}];

		this.baseList = [{
			label: "All",
			value: ""
		}];

		this.updateFilter();
		
	}

	updateFilter() {
		const $filter  = this.element.querySelector(".cmm-manager-filter");
		const option = (item, current) => {
			const selected = item.value === current ? " selected" : "";
			return `<option value="${sanitizeHTML(String(item.value ?? ''))}"${selected}>${sanitizeHTML(String(item.label ?? ''))}</option>`;
		};
		$filter.innerHTML = this.filterList.map(item => option(item, this.filter)).join("");

		const $type  = this.element.querySelector(".cmm-manager-type");
		$type.innerHTML = this.typeList.map(item => option(item, this.type)).join("");

		const $base  = this.element.querySelector(".cmm-manager-base");
		$base.innerHTML = this.baseList.map(item => option(item, this.base)).join("");

	}

	bindEvents() {
		const eventsMap = {
			".cmm-manager-filter": {
				change: (e) => {
					this.filter = e.target.value;
					this.updateGrid();
				}
			},
			".cmm-manager-type": {
				change: (e) => {
					this.type = e.target.value;
					this.updateGrid();
				}
			},
			".cmm-manager-base": {
				change: (e) => {
					this.base = e.target.value;
					this.updateGrid();
				}
			},

			".cmm-manager-keywords": {
				input: (e) => {
					const keywords = `${e.target.value}`.trim();
					if (keywords !== this.keywords) {
						this.keywords = keywords;
						this.updateGrid();
					}
				},
				focus: (e) => e.target.select()
			},

			".cmm-manager-selection": {
				click: (e) => {
					const target = e.target;
					const mode = target.getAttribute("mode");
					if (mode === "install") {
						this.installModels(this.selectedModels, target);
					}
				}
			},

			".cmm-manager-refresh": {
				click: () => {
					app.refreshComboInNodes();
				}
			},

			".cmm-manager-stop": {
				click: () => {
					api.fetchApi('/v2/manager/queue/reset', { method: 'POST' });
					infoToast('Cancel', 'Remaining tasks will stop after completing the current task.');
				}
			},

			".cmm-manager-back": {
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
		const container = this.element.querySelector(".cmm-manager-grid");
		const grid = new ManagerGrid(container);
		this.grid = grid;
		
		grid.bind('onUpdated', (e, d) => {

			this.showStatus(`${grid.viewRows.length.toLocaleString()} external models`);

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
			}

        });

		grid.setOption({
			highlightKeywords: {
				textGenerator: (row, column) => ['name', 'description'].includes(column) ? row[column] : escapeCell(row[column])
			},
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
			},

			// updateGrid handler for filter and keywords
			rowFilter: (rowItem) => {

				const searchableColumns = ["name", "type", "base", "description", "filename", "save_path"];
				const models_extensions = ['.ckpt', '.pt', '.pt2', '.bin', '.pth', '.safetensors', '.pkl', '.sft'];

				let shouldShown = grid.highlightKeywordsFilter(rowItem, searchableColumns, this.keywords);

				if (shouldShown) {
					if(this.filter) {
						if (this.filter == "in_workflow") {
							rowItem.in_workflow = null;
							if (Array.isArray(app.graph._nodes)) {
								app.graph._nodes.forEach((item, i) => {
									if (Array.isArray(item.widgets_values)) {
										item.widgets_values.forEach((_item, i) => {
											if (rowItem.in_workflow === null && _item !== null && models_extensions.includes("." + _item.toString().split('.').pop())) {
												let filename = _item.match(/([^\/]+)(?=\.\w+$)/)[0];
												if (grid.highlightKeywordsFilter(rowItem, searchableColumns, filename)) {
													rowItem.in_workflow = "True";
													grid.highlightKeywordsFilter(rowItem, searchableColumns, "");
												}
											}
										});
									}
								});
							}
						}
						return ((this.filter == "installed" && rowItem.installed == "True") || (this.filter == "not_installed" && rowItem.installed == "False") || (this.filter == "in_workflow" && rowItem.in_workflow == "True"));
					}

					if(this.type && rowItem.type !== this.type) {
						return false;
					}

					if(this.base && rowItem.base !== this.base) {
						return false;
					}

				}

				return shouldShown;
			}
		});

	}

	renderGrid() {

		// update theme
		const colorPalette = this.app.ui.settings.settingsValues['Comfy.ColorPalette'];
		Array.from(this.element.classList).forEach(cn => {
			if (cn.startsWith("cmm-manager-")) {
				this.element.classList.remove(cn);
			}
		});
		this.element.classList.add(`cmm-manager-${colorPalette}`);

		const options = {
			theme: colorPalette === "light" ? "" : "dark"
		};

		const rows = this.modelList || [];

		const columns = [{
			id: 'id',
			name: 'ID',
			width: 50,
			align: 'center'
		}, {
			id: 'name',
			name: 'Name',
			width: 200,
			minWidth: 100,
			maxWidth: 500,
			classMap: 'cmm-node-name',
			formatter: function(name, rowItem, columnItem, cellNode) {
				// Names are server-escaped; raw references need URL and attribute handling.
				const href = sanitizeUrl(rowItem.reference);
				if (!href) {
					return `<b>${String(name ?? '')}</b>`;
				}
				return `<a href="${sanitizeHTML(href)}" target="_blank" rel="noopener noreferrer"><b>${String(name ?? '')}</b></a>`;
			}
		}, {
			id: 'installed',
			name: 'Install',
			width: 130,
			minWidth: 110,
			maxWidth: 200,
			sortable: false,
			align: 'center',
			formatter: (installed, rowItem, columnItem) => {
				if (rowItem.refresh) {
					return `<font color="red">Refresh Required</span>`;
				}
				if (installed === "True") {
					return `<div class="cmm-icon-passed">${icons.passed}</div>`;
				}
				return `<button class="cmm-btn-install p-button p-component" mode="install">Install</button>`;
			}
		}, {
			id: 'url',
			name: '',
			width: 50,
			sortable: false,
			align: 'center',
			formatter: (url, rowItem, columnItem) => {
				const href = sanitizeUrl(url);
				if (!href) {
					return '';
				}
				return `<a class="cmm-btn-download" tooltip="Download file" href="${sanitizeHTML(href)}" target="_blank" rel="noopener noreferrer">${icons.download}</a>`;
			}
		}, {
			id: 'size',
			name: 'Size',
			width: 100,
			formatter: (size) => {
				if (typeof size === "number") {
					return this.formatSize(size);
				}
				return sanitizeHTML(String(size ?? ''));
			}
		}, {
			id: 'type',
			name: 'Type',
			width: 100,
			formatter: escapeCell
		}, {
			id: 'base',
			name: 'Base',
			formatter: escapeCell
		}, {
			id: 'description',
			name: 'Description',
			width: 400,
			maxWidth: 5000,
			classMap: 'cmm-node-desc'  // composed HTML from the server (convert_markdown_to_html)
		}, {
			id: "save_path",
			name: 'Save Path',
			width: 200,
			formatter: escapeCell
		}, {
			id: 'filename',
			name: 'Filename',
			width: 200,
			formatter: escapeCell
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

	// ===========================================================================================

	renderSelected() {
		const selectedList = this.grid.getSelectedRows();
		if (!selectedList.length) {
			this.showSelection("");
			this.selectedModels = [];
			return;
		}

		this.selectedModels = selectedList;
		this.showSelection(`<span>Selected <b>${selectedList.length}</b> models <button class="cmm-btn-install p-button p-component" mode="install">Install</button>`);
	}

	focusInstall(item) {
		const cellNode = this.grid.getCellNode(item, "installed");
		if (cellNode) {
			const cellBtn = cellNode.querySelector(`button[mode="install"]`);
			if (cellBtn) {
				cellBtn.classList.add("cmm-btn-loading");
				return true
			}
		}
	}

	async installModels(list, btn) {
		btn.classList.add("cmm-btn-loading");
		this.showError("");

		let errorMsg = "";

		let target_items = [];

		let batch = {};

		for (const item of list) {
			this.grid.scrollRowIntoView(item);
			target_items.push(item);

			if (!this.focusInstall(item)) {
				this.grid.onNextUpdated(() => {
					this.focusInstall(item);
				});
			}

			this.showStatus(`Install ${item.name} ...`);

			const data = item.originalData;
			data.ui_id = item.hash;
			// Batch rejections refer to id; models need a stable request ID.
			data.id ??= item.hash;


			if(batch['install_model']) {
				batch['install_model'].push(data);
			}
			else {
				batch['install_model'] = [data];
			}
		}

		this.install_context = {btn: btn, targets: target_items};

		this.batch_id = generateUUID();
		batch['batch_id'] = this.batch_id;

		let failed;
		try {
			const { data, error } = await fetchData(`/v2/manager/queue/batch`, {
				method: 'POST',
				body: JSON.stringify(batch)
			});
			if (error) throw error;
			if (!Array.isArray(data?.failed)) throw new Error('Invalid batch response.');
			failed = data.failed;
		} catch (error) {
			errorMsg = `Failed to submit installation request: ${sanitizeHTML(String(error))}`;
			this.showError(errorMsg);
			show_message("[Installation Errors]\n" + errorMsg);
			btn.classList.remove("cmm-btn-loading");
			this.element.querySelectorAll(".cmm-btn-loading").forEach(button => {
				button.classList.remove("cmm-btn-loading");
			});
			this.hideLoading();
			this.hideStop();
			this.install_context = undefined;
			return;
		}
		for (const id of failed) {
			const item = target_items.find(item => item.originalData.id === id);
			errorMsg += `[FAIL] ${item?.name ?? sanitizeHTML(String(id))}\n`;
		}
		if (errorMsg) {
			this.showError(errorMsg);
			show_message("[Installation Errors]\n" + errorMsg);
		}

		showTerminal();

		// No queued work means the server will not send batch-done.
		if (target_items.every(item => failed.includes(item.originalData.id))) {
			this.element.querySelectorAll(".cmm-btn-loading").forEach(button => {
				button.classList.remove("cmm-btn-loading");
			});
			this.hideLoading();
			this.hideStop();
			this.install_context = undefined;
			return;
		}

		this.showStop();
	}

	async onQueueStatus(event) {
		let self = ModelManager.instance;

		if(event.detail.status == 'in_progress' && event.detail.ui_target == 'model_manager') {
			const hash = event.detail.target;

			const item = self.grid.getRowItemBy("hash", hash);

			item.refresh = true;
			self.grid.setRowSelected(item, false);
			item.selectable = false;
//			self.grid.updateCell(item, "tg-column-select");
			self.grid.updateRow(item);
		}
		else if(event.detail.status == 'batch-done') {
			self.hideStop();
			self.onQueueCompleted(event.detail);
		}
	}

	async onQueueCompleted(info) {
		let result = info.model_result;

		if(result.length == 0) {
			return;
		}

		let self = ModelManager.instance;

		if(!self.install_context) {
			return;
		}

		let btn = self.install_context.btn;

		self.hideLoading();
		btn.classList.remove("cmm-btn-loading");

		let errorMsg = "";

		for(let hash in result){
			let v = result[hash];

			if(v != 'success')
				errorMsg += sanitizeHTML(String(v)) + '\n';
		}

		for(let k in self.install_context.targets) {
			let item = self.install_context.targets[k];
			self.grid.updateCell(item, "installed");
		}

		if (errorMsg) {
			self.showError(errorMsg);
			show_message("Installation Error:\n"+errorMsg);
		} else {
			self.showStatus(`Install ${result.length} models successfully`);
		}

		self.showRefresh();
		self.showMessage(`To apply the installed model, please click the 'Refresh' button.`, "red")

		infoToast('Tasks done', `[ComfyUI-Manager] All model downloading tasks in the queue have been completed.\n${info.done_count}/${info.total_count}`);
		self.install_context = undefined;
	}

	getModelList(models) {
		const typeMap = new Map();
		const baseMap = new Map();

		models.forEach((item, i) => {
			const { type, base, name, reference, installed } = item;
			item.originalData = JSON.parse(JSON.stringify(item));
			item.size = this.sizeToBytes(item.size);
			item.hash = md5(name + reference);
			item.id = i + 1;

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
		typeList.sort((a,b)=> {
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
		baseList.sort((a,b)=> {
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

		this.showStatus(`Loading external model list ...`);

		const mode = manager_instance.datasrc_combo.value;

		const res = await fetchData(`/v2/externalmodel/getlist?mode=${mode}`);
		if (res.error) {
			this.showError("Failed to get external model list.");
			this.hideLoading();
			return
		}
		
		const { models } = res.data;

		this.modelList = this.getModelList(models);
		// console.log("models", this.modelList);

		this.updateFilter();
		
		this.renderGrid();

		this.hideLoading();
		
	}

	// ===========================================================================================

	formatSize(v) {
		const base = 1000;
        const units = ['', 'K', 'M', 'G', 'T', 'P'];
        const space = '';
        const postfix = 'B';
		if (v <= 0) {
			return `0${space}${postfix}`;
		}
		for (let i = 0, l = units.length; i < l; i++) {
			const min = Math.pow(base, i);
			const max = Math.pow(base, i + 1);
			if (v > min && v <= max) {
				const unit = units[i];
				if (unit) {
					const n = v / min;
					const nl = n.toString().split('.')[0].length;
					const fl = Math.max(3 - nl, 1);
					v = n.toFixed(fl);
				}
				v = v + space + unit + postfix;
				break;
			}
		}
		return v;
	}

	// for size sort
	sizeToBytes(v) {
		if (typeof v === "number") {
			return v;
		}
		if (typeof v === "string") {
			const n = parseFloat(v);
			const unit = v.replace(/[0-9.B]+/g, "").trim().toUpperCase();
			if (unit === "K") {
				return n * 1000;
			}
			if (unit === "M") {
				return n * 1000 * 1000;
			}
			if (unit === "G") {
				return n * 1000 * 1000 * 1000;
			}
			if (unit === "T") {
				return n * 1000 * 1000 * 1000 * 1000;
			}
		}
		return v;
	}

	showSelection(msg) {
		this.element.querySelector(".cmm-manager-selection").innerHTML = msg;
	}

	showError(err) {
		this.showMessage(err, "red");
	}

	// Messages contain HTML: preserve server-escaped names and escape raw values at the caller.
	showMessage(msg, color) {
		const element = this.element.querySelector(".cmm-manager-message");
		element.style.color = color || "";
		element.innerHTML = msg ?? "";
	}

	showStatus(msg, color) {
		const element = this.element.querySelector(".cmm-manager-status");
		element.style.color = color || "";
		element.innerHTML = msg ?? "";
	}

	showLoading() {
		if (this.grid) {
			this.grid.showLoading();
			this.grid.showMask({
				opacity: 0.05
			});
		}
	}

	hideLoading() {
		if (this.grid) {
			this.grid.hideLoading();
			this.grid.hideMask();
		}
	}

	showRefresh() {
		this.element.querySelector(".cmm-manager-refresh").style.display = "block";
	}

	showStop() {
		this.element.querySelector(".cmm-manager-stop").style.display = "block";
	}

	hideStop() {
		this.element.querySelector(".cmm-manager-stop").style.display = "none";
	}

	setKeywords(keywords = "") {
		this.keywords = keywords;
		this.element.querySelector(".cmm-manager-keywords").value = keywords;
	}

	show() {
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
