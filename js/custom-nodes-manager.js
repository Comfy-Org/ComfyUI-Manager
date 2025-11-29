import { app } from "../../scripts/app.js";
import { ComfyDialog, $el } from "../../scripts/ui.js";
import { api } from "../../scripts/api.js";

import {
	manager_instance, rebootAPI, install_via_git_url,
	fetchData, md5, icons, show_message, customConfirm, customAlert, customPrompt,
	sanitizeHTML, infoToast, showTerminal, setNeedRestart,
	storeColumnWidth, restoreColumnWidth, getTimeAgo, copyText, loadCss,
	showPopover, hidePopover
} from  "./common.js";

// https://cenfun.github.io/turbogrid/api.html
import TG from "./turbogrid.esm.js";

loadCss("./custom-nodes-manager.css");

const gridId = "node";

const pageHtml = `
<div class="cn-manager-header">
	<label>Filter
		<select class="cn-manager-filter"></select>
	</label>
	<input class="cn-manager-keywords" type="search" placeholder="Search" />
	<div class="cn-manager-status"></div>
	<div class="cn-flex-auto"></div>
	<div class="cn-manager-channel"></div>
</div>
<div class="cn-manager-grid"></div>
<div class="cn-manager-selection"></div>
<div class="cn-manager-message"></div>
<div class="cn-manager-footer">
	<button class="cn-manager-back">
		<svg class="arrow-icon" width="14" height="14" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
			<path d="M2 8H18M2 8L8 2M2 8L8 14" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
		</svg>
		Back
	</button>
	<button class="cn-manager-restart">Restart</button>
	<button class="cn-manager-stop">Stop</button>
	<div class="cn-flex-auto"></div>
	<button class="cn-manager-used-in-workflow">Used In Workflow</button>
	<button class="cn-manager-check-update">Check Update</button>
	<button class="cn-manager-check-missing">Check Missing</button>
	<button class="cn-manager-install-url">Install via Git URL</button>
</div>
`;

const ShowMode = {
	NORMAL: "Normal",
	UPDATE: "Update",
	MISSING: "Missing",
	FAVORITES: "Favorites",
	ALTERNATIVES: "Alternatives",
	IN_WORKFLOW: "In Workflow",
};

export class CustomNodesManager {
	static instance = null;
	static ShowMode = ShowMode;

	constructor(app, manager_dialog) {
		this.app = app;
		this.manager_dialog = manager_dialog;
		this.id = "cn-manager";

		app.registerExtension({
			name: "Comfy.CustomNodesManager",
			afterConfigureGraph: (missingNodeTypes) => {
				const item = this.getFilterItem(ShowMode.MISSING);
				if (item) {
					item.hasData = false;
					item.hashMap = null;
				}
			}
		});

		this.filter = '';
		this.keywords = '';
		this.restartMap = {};

		this.init();

        api.addEventListener("cm-queue-status", this.onQueueStatus);
		api.getNodeDefs().then(objs => {
			this.nodeMap = objs;
		})
	}

	init() {
		this.element = $el("div", {
			parent: document.body,
			className: "comfy-modal cn-manager"
		});
		this.element.innerHTML = pageHtml;
		this.element.setAttribute("tabindex", 0);
		this.element.focus();

		this.initFilter();
		this.bindEvents();
		this.initGrid();
	}

	showVersionSelectorDialog(versions, onSelect) {
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
			selected: index === 0
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

	initFilter() {
		const $filter  = this.element.querySelector(".cn-manager-filter");
		const filterList = [{
			label: "All",
			value: "",
			hasData: true
		}, {
			label: "Installed",
			value: "installed",
			hasData: true
		}, {
			label: "Enabled",
			value: "enabled",
			hasData: true
		}, {
			label: "Disabled",
			value: "disabled",
			hasData: true
		}, {
			label: "Import Failed",
			value: "import-fail",
			hasData: true
		}, {
			label: "Not Installed",
			value: "not-installed",
			hasData: true
		}, {
			label: "ComfyRegistry",
			value: "cnr",
			hasData: true
		}, {
			label: "Non-ComfyRegistry",
			value: "unknown",
			hasData: true
		}, {
			label: "Update",
			value: ShowMode.UPDATE,
			hasData: false
		}, {
			label: "In Workflow",
			value: ShowMode.IN_WORKFLOW,
			hasData: false
		}, {
			label: "Missing",
			value: ShowMode.MISSING,
			hasData: false
		}, {
			label: "Favorites",
			value: ShowMode.FAVORITES,
			hasData: false
		}, {
			label: "Alternatives of A1111",
			value: ShowMode.ALTERNATIVES,
			hasData: false
		}];
		this.filterList = filterList;
		$filter.innerHTML = filterList.map(item => {
			return `<option value="${item.value}">${item.label}</option>`
		}).join("");
	}

	getFilterItem(filter) {
		return this.filterList.find(it => it.value === filter)
	}

	getActionButtons(action, rowItem, is_selected_button) {
		const buttons = {
			"enable": {
				label: "Enable",
				mode: "enable"
			},
			"disable": {
				label: "Disable",
				mode: "disable"
			},

			"update": {
				label: "Update",
				mode: "update"
			},
			"try-update": {
				label: "Try update",
				mode: "update"
			},

			"try-fix": {
				label: "Try fix",
				mode: "fix"
			},

			"reinstall": {
				label: "Reinstall",
				mode: "reinstall"
			},

			"install": {
				label: "Install",
				mode: "install"
			},

			"try-install": {
				label: "Try install",
				mode: "install"
			},

			"uninstall": {
				label: "Uninstall",
				mode: "uninstall"
			},

			"switch": {
				label: "Switch Ver",
				mode: "switch"
			}
		}

		const installGroups = {
			"disabled": ["enable", "switch", "uninstall"],
			"updatable": ["update", "switch", "disable", "uninstall"],
			"import-fail": ["try-fix", "switch", "disable", "uninstall"],
			"enabled": ["try-update", "switch", "disable", "uninstall"],
			"not-installed": ["install"],
			'unknown': ["try-install"],
			"invalid-installation": ["reinstall"],
		}

		if (!installGroups.updatable) {
			installGroups.enabled = installGroups.enabled.filter(it => it !== "try-update");
		}

		if (rowItem?.title === "ComfyUI-Manager") {
			installGroups.enabled = installGroups.enabled.filter(it => it !== "disable" && it !== "uninstall" && it !== "switch");
		}

		let list = installGroups[action];

		if(is_selected_button || rowItem?.version === "unknown") {
			list = list.filter(it => it !== "switch");
		}

		if (!list) {
			return "";
		}

		return list.map(id => {
			const bt = buttons[id];
			return `<button class="cn-btn-${id}" group="${action}" mode="${bt.mode}">${bt.label}</button>`;
		}).join("");
	}

	getButton(target) {
		if(!target) {
			return;
		}
		const mode = target.getAttribute("mode");
		if (!mode) {
			return;
		}
		const group = target.getAttribute("group");
		if (!group) {
			return;
		}
		return {
			group,
			mode,
			target,
			label: target.innerText
		}
	}

	bindEvents() {
		const eventsMap = {
			".cn-manager-filter": {
				change: (e) => {

					if (this.grid) {
						this.grid.selectAll(false);
					}

					const value = e.target.value
					this.filter = value;
					const item = this.getFilterItem(value);
					if (item && (!item.hasData)) {
						this.loadData(value);
						return;
					}
					this.updateGrid();
				}
			},

			".cn-manager-keywords": {
				input: (e) => {
					const keywords = `${e.target.value}`.trim();
					if (keywords !== this.keywords) {
						this.keywords = keywords;
						this.updateGrid();
					}
				},
				focus: (e) => e.target.select()
			},

			".cn-manager-selection": {
				click: (e) => {
					const btn = this.getButton(e.target);
					if (btn) {
						const nodes = this.selectedMap[btn.group];
						if (nodes) {
							this.installNodes(nodes, btn);
						}
					}
				}
			},

			".cn-manager-back": {
				click: (e) => {
					this.flyover.hide(true);
					this.removeHighlight();
					hidePopover();
				    this.close()
				    manager_instance.show();
				}
			},

			".cn-manager-restart": {
				click: () => {
					this.close();
					this.manager_dialog.close();
					rebootAPI();
				}
			},

			".cn-manager-stop": {
				click: () => {
					api.fetchApi('/manager/queue/reset');
					infoToast('Cancel', 'Remaining tasks will stop after completing the current task.');
				}
			},

			".cn-manager-used-in-workflow": {
				click: (e) => {
					e.target.classList.add("cn-btn-loading");
					this.setFilter(ShowMode.IN_WORKFLOW);
					this.loadData(ShowMode.IN_WORKFLOW);
				}
			},

			".cn-manager-check-update": {
				click: (e) => {
					e.target.classList.add("cn-btn-loading");
					this.setFilter(ShowMode.UPDATE);
					this.loadData(ShowMode.UPDATE);
				}
			},

			".cn-manager-check-missing": {
				click: (e) => {
					e.target.classList.add("cn-btn-loading");
					this.setFilter(ShowMode.MISSING);
					this.loadData(ShowMode.MISSING);
				}
			},

			".cn-manager-install-url": {
				click: async (e) => {
					const url = await customPrompt("Please enter the URL of the Git repository to install", "");
					if (url !== null) {
						install_via_git_url(url, this.manager_dialog);
					}
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
		const container = this.element.querySelector(".cn-manager-grid");
		const grid = new TG.Grid(container);
		this.grid = grid;

		this.flyover = this.createFlyover(container);
		
		let prevViewRowsLength = -1;
		grid.bind('onUpdated', (e, d) => {
			const viewRows = grid.viewRows;
            prevViewRowsLength = viewRows.length;
            this.showStatus(`${prevViewRowsLength.toLocaleString()} custom nodes`);
		});

		grid.bind('onSelectChanged', (e, changes) => {
			this.renderSelected();
		});

		grid.bind("onColumnWidthChanged", (e, columnItem) => {
			storeColumnWidth(gridId, columnItem)
		});

		grid.bind('onClick', (e, d) => {

			this.addHighlight(d.rowItem);

			if (d.columnItem.id === "nodes") {
				this.showNodes(d);
				return;
			}

			const btn = this.getButton(d.e.target);
			if (btn) {
				const item = this.grid.getRowItemBy("hash", d.rowItem.hash);

				const { target, label, mode} = btn;
				if((mode === "install" || mode === "switch" || mode == "enable") && item.originalData.version != 'unknown') {
					// install after select version via dialog if item is cnr node
					this.installNodeWithVersion(d.rowItem, btn, mode == 'enable');
				} else {
					this.installNodes([d.rowItem.hash], btn, d.rowItem.title);
				}
				return;
			}

		});

		// iteration events
		this.element.addEventListener("click", (e) => {
			if (container === e.target || container.contains(e.target)) {
                return;
            }
			this.removeHighlight();
		});
		// proxy keyboard events
		this.element.addEventListener("keydown", (e) => {
			if (e.target === this.element) {
				grid.containerKeyDownHandler(e);
			}
		}, true);


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
				const autoHeightColumns = ['title', 'action', 'description', "alternatives"];
				return autoHeightColumns.includes(columnItem.id)
			},

			// updateGrid handler for filter and keywords
			rowFilter: (rowItem) => {

				const searchableColumns = ["title", "author", "description"];
				if (this.hasAlternatives()) {
					searchableColumns.push("alternatives");
				}

				let shouldShown = grid.highlightKeywordsFilter(rowItem, searchableColumns, this.keywords);

				if (shouldShown) {
					if(this.filter && rowItem.filterTypes) {
						shouldShown = rowItem.filterTypes.includes(this.filter);
					}
				}

				return shouldShown;
			}
		});

	}

	hasAlternatives() {
		return this.filter === ShowMode.ALTERNATIVES
	}

	async handleImportFail(rowItem) {
		var info;
		if(rowItem.version == 'unknown'){
			info = {
				'url': rowItem.originalData.files[0]
			};
		}
		else{
			info = {
				'cnr_id': rowItem.originalData.id
			};
		}

		const response = await api.fetchApi(`/customnode/import_fail_info`, {
									method: 'POST',
									headers: { 'Content-Type': 'application/json' },
									body: JSON.stringify(info)
								});

		let res = await response.json();

		let title = `<FONT COLOR=GREEN><B>Error message occurred while importing the '${rowItem.title}' module.</B></FONT><BR><HR><BR>`

		if(res.code == 400)
		{
			show_message(title+'The information is not available.')
		}
		else {
			show_message(title+sanitizeHTML(res['msg']).replace(/ /g, '&nbsp;').replace(/\n/g, '<BR>'));
		}
	}

	renderGrid() {

		// update theme
		const globalStyle = window.getComputedStyle(document.body);
		this.colorVars = {
			bgColor: globalStyle.getPropertyValue('--comfy-menu-bg'),
			borderColor: globalStyle.getPropertyValue('--border-color')
		}

		const colorPalette = this.app.ui.settings.settingsValues['Comfy.ColorPalette'];
		this.colorPalette = colorPalette;
		Array.from(this.element.classList).forEach(cn => {
			if (cn.startsWith("cn-manager-")) {
				this.element.classList.remove(cn);
			}
		});
		this.element.classList.add(`cn-manager-${colorPalette}`);

		const options = {
			theme: colorPalette === "light" ? "" : "dark"
		};


		let self = this;
		const columns = [{
			id: 'id',
			name: 'ID',
			width: 50,
			align: 'center'
		}, {
			id: 'title',
			name: 'Title',
			width: 200,
			minWidth: 100,
			maxWidth: 500,
			classMap: 'cn-pack-name',
			formatter: (title, rowItem, columnItem) => {
				const container = document.createElement('div');

				if (rowItem.action === 'invalid-installation') {
					const invalidTag = document.createElement('span');
					invalidTag.style.color = 'red';
					invalidTag.innerHTML = '<b>(INVALID)</b>';
					container.appendChild(invalidTag);
				} else if (rowItem.action === 'import-fail') {
					const button = document.createElement('button');
					button.className = 'cn-btn-import-failed';
					button.innerText = 'IMPORT FAILED ↗';
					button.onclick = () => self.handleImportFail(rowItem);
					container.appendChild(button);
					container.appendChild(document.createElement('br'));
				}

				const link = document.createElement('a');
				if(rowItem.originalData.repository)
					link.href = rowItem.originalData.repository;
				else
					link.href = rowItem.reference;
				link.target = '_blank';
				link.innerHTML = `<b>${title}</b>`;
				link.title = rowItem.originalData.id;
				container.appendChild(link);

				return container;
			}
		}, {
			id: 'version',
			name: 'Version',
			width: 100,
			minWidth: 80,
			maxWidth: 300,
			classMap: 'cn-pack-version',
			formatter: (version, rowItem, columnItem) => {
				if(!version) {
					return;
				}
				if(rowItem.cnr_latest && version != rowItem.cnr_latest) {
					if(version == 'nightly') {
						return `<div>${version}</div><div>[${rowItem.cnr_latest}]</div>`;
					}
					return `<div>${version}</div><div>[↑${rowItem.cnr_latest}]</div>`;
				}
				return version;
			}
		}, {
			id: 'action',
			name: 'Action',
			width: 130,
			minWidth: 110,
			maxWidth: 200,
			sortable: false,
			align: 'center',
			formatter: (action, rowItem, columnItem) => {
				if (rowItem.restart) {
					return `<font color="red">Restart Required</span>`;
				}
				const buttons = this.getActionButtons(action, rowItem);
				return `<div class="cn-install-buttons">${buttons}</div>`;
			}
		}, {
			id: "nodes",
			name: "Nodes",
			width: 100,
			formatter: (v, rowItem, columnItem) => {
				if (!rowItem.nodes) {
					return '';
				}
				const list = [`<div class="cn-pack-nodes">`];
				list.push(`<div>${rowItem.nodes} node${(rowItem.nodes>1?'s':'')}</div>`);
				if (rowItem.conflicts) {
					list.push(`<div class="cn-pack-conflicts">${rowItem.conflicts} conflict${(rowItem.conflicts>1?'s':'')}</div>`);
				}
				list.push('</div>');
				return list.join("");
			}
		}, {
			id: "alternatives",
			name: "Alternatives",
			width: 400,
			maxWidth: 5000,
			invisible: !this.hasAlternatives(),
			classMap: 'cn-pack-desc'
		}, {
			id: 'description',
			name: 'Description',
			width: 400,
			maxWidth: 5000,
			classMap: 'cn-pack-desc'
		}, {
			id: 'author',
			name: 'Author',
			width: 120,
			classMap: "cn-pack-author", 
			formatter: (author, rowItem, columnItem) => {
				if (rowItem.trust) {
					return `<span tooltip="This author has been active for more than six months in GitHub">✅ ${author}</span>`;
				}
				return author;
			}
		}, {
			id: 'stars',
			name: '★',
			align: 'center',
			classMap: "cn-pack-stars",
			formatter: (stars) => {
				if (stars < 0) {
					return 'N/A';
				}
				if (typeof stars === 'number') {
					return stars.toLocaleString();
				}
				return stars;
			}
		}, {
			id: 'last_update',
			name: 'Last Update',
			align: 'center',
			type: 'date',
			width: 100,
			classMap: "cn-pack-last-update",
			formatter: (last_update) => {
				if (last_update < 0) {
					return 'N/A';
				}
				const ago = getTimeAgo(last_update);
				const short = `${last_update}`.split(' ')[0];
				return `<span tooltip="${ago}">${short}</span>`;
			}
		}];

		restoreColumnWidth(gridId, columns);

		const rows_values = Object.values(this.custom_nodes);
		rows_values.sort((a, b) => {
			if (a.version == 'unknown' && b.version != 'unknown') return 1;
			if (a.version != 'unknown' && b.version == 'unknown') return -1;

			if (a.stars !== b.stars) {
				return b.stars - a.stars;
			}

			if (a.last_update !== b.last_update) {
				return new Date(b.last_update) - new Date(a.last_update);
			}

			return 0;
		});

		rows_values.forEach((it, i) => {
			it.id = i + 1;
		});

		this.grid.setData({
			options: options,
			rows: rows_values,
			columns: columns
		});

		this.grid.render();
	}

	updateGrid() {
		if (this.grid) {
			this.grid.update();
			if (this.hasAlternatives()) {
				this.grid.showColumn("alternatives");
			} else {
				this.grid.hideColumn("alternatives");
			}
		}
	}

	addHighlight(rowItem) {
		this.removeHighlight();
		if (this.grid && rowItem) {
			this.grid.setRowState(rowItem, 'highlight', true);
			this.highlightRow = rowItem;
		}
	}
	
	removeHighlight() {
		if (this.grid && this.highlightRow) {
			this.grid.setRowState(this.highlightRow, 'highlight', false);
			this.highlightRow = null;
		}
	}

	// ===========================================================================================

	getWidgetType(type, inputName) {
		if (type === 'COMBO') {
		  	return 'COMBO'
		}
		const widgets = app.widgets;
		if (`${type}:${inputName}` in widgets) {
		  	return `${type}:${inputName}`
		}
		if (type in widgets) {
		  	return type
		}
	}
	
	createNodePreview(nodeItem) {
		// console.log(nodeItem);
		const list = [`<div class="cn-preview-header">
			<div class="cn-preview-dot"></div>
			<div class="cn-preview-name">${nodeItem.name}</div>
			<div class="cn-pack-badge">Preview</div>
		</div>`];

		// Node slot I/O
		const inputList = [];
		nodeItem.input_order.required?.map(name => {
			inputList.push({
				name
			});
		})
		nodeItem.input_order.optional?.map(name => {
			inputList.push({
				name,
				optional: true
			});
		});

		const slotInputList = [];
		const widgetInputList = [];
		const inputMap = Object.assign({}, nodeItem.input.optional, nodeItem.input.required);
		inputList.forEach(it => {
			const inputName = it.name;
			const _inputData = inputMap[inputName];
			let type = _inputData[0];
			let options = _inputData[1] || {};
			if (Array.isArray(type)) {
				options.default = type[0];
				type = 'COMBO';
			}
			it.type = type;
			it.options = options;

			// convert force/default inputs
			if (options.forceInput || options.defaultInput) {
				slotInputList.push(it);
				return;
			}

			const widgetType = this.getWidgetType(type, inputName);
			if (widgetType) {
				it.default = options.default;
				widgetInputList.push(it);
			} else {
				slotInputList.push(it);
			}
		});

		const outputList = nodeItem.output.map((type, i) => {
			return {
				type,
				name: nodeItem.output_name[i],
				list: nodeItem.output_is_list[i]
			}
		});

		// dark
		const colorMap = {
			"CLIP": "#FFD500",
			"CLIP_VISION": "#A8DADC",
			"CLIP_VISION_OUTPUT": "#ad7452",
			"CONDITIONING": "#FFA931",
			"CONTROL_NET": "#6EE7B7",
			"IMAGE": "#64B5F6",
			"LATENT": "#FF9CF9",
			"MASK": "#81C784",
			"MODEL": "#B39DDB",
			"STYLE_MODEL": "#C2FFAE",
			"VAE": "#FF6E6E",
			"NOISE": "#B0B0B0",
			"GUIDER": "#66FFFF",
			"SAMPLER": "#ECB4B4",
			"SIGMAS": "#CDFFCD",
			"TAESD": "#DCC274"
		}

		const inputHtml = slotInputList.map(it => {
			const color = colorMap[it.type] || "gray";
			const optional = it.optional ? " cn-preview-optional" : ""
			return `<div class="cn-preview-input">
				<div class="cn-preview-dot${optional}" style="background-color:${color}"></div>
				${it.name}
			</div>`;
		}).join("");

		const outputHtml = outputList.map(it => {
			const color = colorMap[it.type] || "gray";
			const grid = it.list ? " cn-preview-grid" : "";
			return `<div class="cn-preview-output">
				${it.name}
				<div class="cn-preview-dot${grid}" style="background-color:${color}"></div>
			</div>`;
		}).join("");

		list.push(`<div class="cn-preview-io">
			<div class="cn-preview-column">${inputHtml}</div>
			<div class="cn-preview-column">${outputHtml}</div>
		</div>`);

		// Node widget inputs
		if (widgetInputList.length) {
			list.push(`<div class="cn-preview-list">`);

			// console.log(widgetInputList);
			widgetInputList.forEach(it => {

				let value = it.default;
				if (typeof value === "object" && value && Object.prototype.hasOwnProperty.call(value, "content")) {
					value = value.content;
				}
				if (typeof value === "undefined" || value === null) {
					value = "";
				} else {
					value = `${value}`;
				}
	
				if (
					(it.type === "STRING" && (value || it.options.multiline))
					|| it.type === "MARKDOWN"
				) {
					if (value) {
						value = value.replace(/\r?\n/g, "<br>")
					}
					list.push(`<div class="cn-preview-string">${value || it.name}</div>`);
					return;
				}

				list.push(`<div class="cn-preview-switch">
					<div>${it.name}</div>
					<div class="cn-preview-value">${value}</div>	
				</div>`);
			});
			list.push(`</div>`);
		}

		if (nodeItem.description) {
			list.push(`<div class="cn-preview-description">${nodeItem.description}</div>`)
		}

		return list.join("");
	}
	
	showNodePreview(target) {
		const nodeName = target.innerText;
		const nodeItem = this.nodeMap[nodeName];
		if (!nodeItem) {
			this.hideNodePreview();
			return;
		}
		const html = this.createNodePreview(nodeItem);
		showPopover(target, html, "cn-preview cn-preview-"+this.colorPalette, {
			positions: ['left'],
			bgColor: this.colorVars.bgColor,
			borderColor: this.colorVars.borderColor
		})
	}

	hideNodePreview() {
		hidePopover();
	}

	createFlyover(container) {
		const $flyover = document.createElement("div");
		$flyover.className = "cn-flyover";
		$flyover.innerHTML = `<div class="cn-flyover-header">
			<div class="cn-flyover-close">${icons.arrowRight}</div>
			<div class="cn-flyover-title"></div>
			<div class="cn-flyover-close">${icons.close}</div>
			</div>
			<div class="cn-flyover-body"></div>`
		container.appendChild($flyover);

		const $flyoverTitle = $flyover.querySelector(".cn-flyover-title");
		const $flyoverBody = $flyover.querySelector(".cn-flyover-body");
		
		let width = '50%';
		let visible = false;

		let timeHide;
		const closeHandler = (e) => {
            if ($flyover === e.target || $flyover.contains(e.target)) {
                return;
            }
			clearTimeout(timeHide);
			timeHide = setTimeout(() => {
				flyover.hide();
			}, 100);
		}

		const hoverHandler = (e) => {
			if(e.type === "mouseenter") {
				if(e.target.classList.contains("cn-nodes-name")) {
					this.showNodePreview(e.target);
				}
				return;
			}
			this.hideNodePreview();
		}

		const displayHandler = () => {
			if (visible) {
				$flyover.classList.remove("cn-slide-in-right");
			} else {
				$flyover.classList.remove("cn-slide-out-right");
				$flyover.style.width = '0px';
				$flyover.style.display = "none";
			}
		}

		const flyover = {
			show: (titleHtml, bodyHtml) => {
				clearTimeout(timeHide);
				this.element.removeEventListener("click", closeHandler);
				$flyoverTitle.innerHTML = titleHtml;
				$flyoverBody.innerHTML = bodyHtml;
				$flyover.style.display = "block";
				$flyover.style.width = width;
				if(!visible) {
					$flyover.classList.add("cn-slide-in-right");
				}
				visible = true;
				setTimeout(() => {
					this.element.addEventListener("click", closeHandler);
				}, 100);
			},
			hide: (now) => {
				visible = false;
				this.element.removeEventListener("click", closeHandler);
				if(now) {
					displayHandler();
					return;
				}
				$flyover.classList.add("cn-slide-out-right");
			}
		}

		$flyover.addEventListener("animationend", (e) => {
			displayHandler();
		});

		$flyover.addEventListener("mouseenter", hoverHandler, true);
		$flyover.addEventListener("mouseleave", hoverHandler, true);

		$flyover.addEventListener("click", (e) => {

			if(e.target.classList.contains("cn-nodes-name")) {
				const nodeName = e.target.innerText;
				const nodeItem = this.nodeMap[nodeName];
				if (!nodeItem) {
					copyText(nodeName).then((res) => {
						if (res) {
							e.target.setAttribute("action", "Copied");
							e.target.classList.add("action");
							setTimeout(() => {
								e.target.classList.remove("action");
								e.target.removeAttribute("action");
							}, 1000);
						}
					});
					return;
				}

				const [x, y, w, h] = app.canvas.ds.visible_area;
				const dpi = Math.max(window.devicePixelRatio ?? 1, 1);
				const node = window.LiteGraph?.createNode(
					nodeItem.name,
					nodeItem.display_name,
					{
						pos: [x + (w-300) / dpi / 2, y]
					}
				);
				if (node) {
					app.graph.add(node);
					e.target.setAttribute("action", "Added to Workflow");
					e.target.classList.add("action");
					setTimeout(() => {
						e.target.classList.remove("action");
						e.target.removeAttribute("action");
					}, 1000);
				}
				
				return;
			}
			if(e.target.classList.contains("cn-nodes-pack")) {
				const hash = e.target.getAttribute("hash");
				const rowItem = this.grid.getRowItemBy("hash", hash);
				//console.log(rowItem);
				this.grid.scrollToRow(rowItem);
				this.addHighlight(rowItem);
				return;
			}
			if(e.target.classList.contains("cn-flyover-close")) {
				flyover.hide();
				return;
			}
		});

		return flyover;
	}

	showNodes(d) {
		const nodesList = d.rowItem.nodesList;
		if (!nodesList) {
			return;
		}

		const rowItem = d.rowItem;
		const isNotInstalled = rowItem.action == "not-installed";

		let titleHtml = `<div class="cn-nodes-pack" hash="${rowItem.hash}">${rowItem.title}</div>`;
		if (isNotInstalled) {
			titleHtml += '<div class="cn-pack-badge">Not Installed</div>'
		}

		const list = [];
		list.push(`<div class="cn-nodes-list">`);
	
		nodesList.forEach((it, i) => {
			let rowClass = 'cn-nodes-row'
			if (it.conflicts) {
				rowClass += ' cn-nodes-conflict';
			}

			list.push(`<div class="${rowClass}">`);
			list.push(`<div class="cn-nodes-sn">${i+1}</div>`);
			list.push(`<div class="cn-nodes-name">${it.name}</div>`);

			if (it.conflicts) {
				list.push(`<div class="cn-conflicts-list"><div class="cn-nodes-conflict cn-icon">${icons.conflicts}</div><b>Conflict with</b>${it.conflicts.map(c => {
					return `<div class="cn-nodes-pack" hash="${c.hash}">${c.title}</div>`;
				}).join("<b>,</b>")}</div>`);
			}
			list.push(`</div>`);
		});

		list.push("</div>");
		const bodyHtml = list.join("");

		this.flyover.show(titleHtml, bodyHtml);
	}

	async loadNodes(node_packs) {
		const mode = manager_instance.datasrc_combo.value;
		this.showStatus(`Loading node mappings (${mode}) ...`);
		const res = await fetchData(`/customnode/getmappings?mode=${mode}`);
		if (res.error) {
			console.log(res.error);
			return;
		}
	
		const data = res.data;

		const findNode = (k, title) => {
			let item = node_packs[k];
			if (item) {
				return item;
			}
			
			// git url
			if (k.includes("/")) {
				const gitName = k.split("/").pop();
				item = node_packs[gitName];
				if (item) {
					return item;
				}
			}
			
			return node_packs[title];
		}

		const conflictsMap = {};

		// add nodes data
		Object.keys(data).forEach(k => {
			const [nodes, metadata] = data[k];
			if (nodes?.length) {
				const title = metadata?.title_aux;
				const nodeItem = findNode(k, title);
				if (nodeItem) {

					// deduped
					const eList = Array.from(new Set(nodes));

					nodeItem.nodes = eList.length;
					const nodesMap = {};
					eList.forEach(extName => {
						nodesMap[extName] = {
							name: extName
						};
						let cList = conflictsMap[extName];
						if(!cList) {
							cList = [];
							conflictsMap[extName] = cList;
						}
						cList.push(nodeItem.key);
					});
					nodeItem.nodesMap = nodesMap;
				} else {
					// should be removed
					// console.log("not found", k, title, nodes)
				}
			}
		});

		// calculate conflicts data
		Object.keys(conflictsMap).forEach(extName => {
			const cList = conflictsMap[extName];
			if(cList.length <= 1) {
				return;
			}
			cList.forEach(key => {
				const nodeItem = node_packs[key];
				const extItem = nodeItem.nodesMap[extName];
				if(!extItem.conflicts) {
					extItem.conflicts = []
				}
				const conflictsList = cList.filter(k => k !== key);
				conflictsList.forEach(k => {
					const nItem = node_packs[k];
					extItem.conflicts.push({
						key: k,
						title: nItem.title, 
						hash: nItem.hash
					})

				})
			})
		})

		Object.values(node_packs).forEach(nodeItem => {
			if (nodeItem.nodesMap) {
				nodeItem.nodesList = Object.values(nodeItem.nodesMap);
				nodeItem.conflicts = nodeItem.nodesList.filter(it => it.conflicts).length;
			}
		})
	
	}

	// ===========================================================================================

	renderSelected() {
		const selectedList = this.grid.getSelectedRows();
		if (!selectedList.length) {
			this.showSelection("");
			return;
		}

		const selectedMap = {};
		selectedList.forEach(item => {
			let type = item.action;
			if (item.restart) {
				type = "Restart Required";
			}
			if (selectedMap[type]) {
				selectedMap[type].push(item.hash);
			} else {
				selectedMap[type] = [item.hash];
			}
		});

		this.selectedMap = selectedMap;

		const list = [];
		Object.keys(selectedMap).forEach(v => {
			const filterItem = this.getFilterItem(v);
			list.push(`<div class="cn-selected-buttons">
				<span>Selected <b>${selectedMap[v].length}</b> ${filterItem ? filterItem.label : v}</span>
				${this.grid.hasMask ? "" : this.getActionButtons(v, null, true)}
			</div>`);
		});

		this.showSelection(list.join(""));
	}

	focusInstall(item, mode) {
		const cellNode = this.grid.getCellNode(item, "action");
		if (cellNode) {
			const cellBtn = cellNode.querySelector(`button[mode="${mode}"]`);
			if (cellBtn) {
				cellBtn.classList.add("cn-btn-loading");
				return true
			}
		}
	}

	async installNodeWithVersion(rowItem, btn, is_enable) {
		let hash = rowItem.hash;
		let title = rowItem.title;

		const item = this.grid.getRowItemBy("hash", hash);

		let node_id = item.originalData.id;

		this.showLoading();
		let res;
		if(is_enable) {
			res = await api.fetchApi(`/customnode/disabled_versions/${node_id}`, { cache: "no-store" });
		}
		else {
			res = await api.fetchApi(`/customnode/versions/${node_id}`, { cache: "no-store" });
		}
		this.hideLoading();

		if(res.status == 200) {
			let obj = await res.json();

			let versions = [];
			let default_version;
			let version_cnt = 0;

			if(!is_enable) {

				if(rowItem.cnr_latest != rowItem.originalData.active_version && obj.length > 0) {
					versions.push('latest');
				}

				if(rowItem.originalData.active_version != 'nightly') {
					versions.push('nightly');
					default_version = 'nightly';
					version_cnt++;
				}
			}

			for(let v of obj) {
				if(rowItem.originalData.active_version != v.version) {
					default_version = v.version;
					versions.push(v.version);
					version_cnt++;
				}
			}

            this.showVersionSelectorDialog(versions, (selected_version) => {
                this.installNodes([hash], btn, title, selected_version);
            });
		}
		else {
			show_message('Failed to fetch versions from ComfyRegistry.');
		}
	}

	async installNodes(list, btn, title, selected_version) {
		let stats = await api.fetchApi('/manager/queue/status');
		stats = await stats.json();
		if(stats.is_processing) {
			customAlert(`[ComfyUI-Manager] There are already tasks in progress. Please try again after it is completed. (${stats.done_count}/${stats.total_count})`);
			return;
		}

		const { target, label, mode} = btn;

		if(mode === "uninstall") {
			title = title || `${list.length} custom nodes`;

			const confirmed = await customConfirm(`Are you sure uninstall ${title}?`);
			if (!confirmed) {
				return;
			}
		}

		if(mode === "reinstall") {
			title = title || `${list.length} custom nodes`;

			const confirmed = await customConfirm(`Are you sure reinstall ${title}?`);
			if (!confirmed) {
				return;
			}
		}

		target.classList.add("cn-btn-loading");
		this.showError("");

		let needRestart = false;
		let errorMsg = "";

		await api.fetchApi('/manager/queue/reset');

		let target_items = [];

		for (const hash of list) {
			const item = this.grid.getRowItemBy("hash", hash);
			target_items.push(item);

			if (!item) {
				errorMsg = `Not found custom node: ${hash}`;
				break;
			}

			this.grid.scrollRowIntoView(item);

			if (!this.focusInstall(item, mode)) {
				this.grid.onNextUpdated(() => {
					this.focusInstall(item, mode);
				});
			}

			this.showStatus(`${label} ${item.title} ...`);

			const data = item.originalData;
			data.selected_version = selected_version;
			data.channel = this.channel;
			data.mode = this.mode;
			data.ui_id = hash;

			let install_mode = mode;
			if(mode == 'switch') {
				install_mode = 'install';
			}

			// don't post install if install_mode == 'enable'
			data.skip_post_install = install_mode == 'enable';
			let api_mode = install_mode;
			if(install_mode == 'enable') {
				api_mode = 'install';
			}

			if(install_mode == 'reinstall') {
				api_mode = 'reinstall';
			}

			const res = await api.fetchApi(`/manager/queue/${api_mode}`, {
				method: 'POST',
				body: JSON.stringify(data)
			});

			if (res.status != 200) {
				errorMsg = `'${item.title}': `;

				if(res.status == 403) {
					errorMsg += `This action is not allowed with this security level configuration.\n`;
				} else if(res.status == 404) {
					errorMsg += `With the current security level configuration, only custom nodes from the <B>"default channel"</B> can be installed.\n`;
				} else {
					errorMsg += await res.text() + '\n';
				}

				break;
			}
		}

		this.install_context = {btn: btn, targets: target_items};

		if(errorMsg) {
			this.showError(errorMsg);
			show_message("[Installation Errors]\n"+errorMsg);

			// reset
			for(let k in target_items) {
				const item = target_items[k];
				this.grid.updateCell(item, "action");
			}
		}
		else {
			await api.fetchApi('/manager/queue/start');
			this.showStop();
			showTerminal();
		}
	}

	async onQueueStatus(event) {
		let self = CustomNodesManager.instance;
		if(event.detail.status == 'in_progress' && event.detail.ui_target == 'nodepack_manager') {
			const hash = event.detail.target;

			const item = self.grid.getRowItemBy("hash", hash);

			item.restart = true;
			self.restartMap[item.hash] = true;
			self.grid.updateCell(item, "action");
			self.grid.setRowSelected(item, false);
		}
		else if(event.detail.status == 'done') {
			self.hideStop();
			self.onQueueCompleted(event.detail);
		}
	}

	async onQueueCompleted(info) {
		let result = info.nodepack_result;

		if(result.length == 0) {
			return;
		}

		let self = CustomNodesManager.instance;

		if(!self.install_context) {
			return;
		}

		const { target, label, mode } = self.install_context.btn;
		target.classList.remove("cn-btn-loading");

		let errorMsg = "";

		for(let hash in result){
			let v = result[hash];

			if(v != 'success' && v != 'skip')
				errorMsg += v+'\n';
		}

		for(let k in self.install_context.targets) {
			let item = self.install_context.targets[k];
			self.grid.updateCell(item, "action");
		}

		if (errorMsg) {
			self.showError(errorMsg);
			show_message("Installation Error:\n"+errorMsg);
		} else {
			self.showStatus(`${label} ${result.length} custom node(s) successfully`);
		}

		self.showRestart();
		self.showMessage(`To apply the installed/updated/disabled/enabled custom node, please restart ComfyUI. And refresh browser.`, "red");

		infoToast(`[ComfyUI-Manager] All node pack tasks in the queue have been completed.\n${info.done_count}/${info.total_count}`);
		self.install_context = undefined;
	}

	// ===========================================================================================

	getNodesInWorkflow() {
		let usedGroupNodes = new Set();
		let allUsedNodes = {};
		const visitedGraphs = new Set();

		const visitGraph = (graph) => {
			if (!graph || visitedGraphs.has(graph)) return;
			visitedGraphs.add(graph);

			const nodes = graph._nodes || graph.nodes || [];
			for(let k in nodes) {
				let node = nodes[k];
				if (!node) continue;

				// If it's a SubgraphNode, recurse into its graph and continue searching
				if (node.isSubgraphNode?.() && node.subgraph) {
					visitGraph(node.subgraph);
				}

				if (!node.type) continue;

				// Group nodes / components
				if(typeof node.type === 'string' && node.type.startsWith('workflow>')) {
					usedGroupNodes.add(node.type.slice(9));
					continue;
				}

				allUsedNodes[node.type] = node;
			}
		};

		visitGraph(app.graph);

		for(let k of usedGroupNodes) {
			let subnodes = app.graph.extra.groupNodes[k]?.nodes;

			if(subnodes) {
				for(let k2 in subnodes) {
					let node = subnodes[k2];
					allUsedNodes[node.type] = node;
				}
			}
		}

		return allUsedNodes;
	}

	async getMissingNodes() {
		let unresolved_missing_nodes = new Set();
		let hashMap = {};
		let allUsedNodes = this.getNodesInWorkflow();
		
		const registered_nodes = new Set();
		for (let i in LiteGraph.registered_node_types) {
			registered_nodes.add(LiteGraph.registered_node_types[i].type);
		}

		let unresolved_aux_ids = {};
		let outdated_comfyui = false;
		let unresolved_cnr_list = [];

		for(let k in allUsedNodes) {
			let node = allUsedNodes[k];

			if(!registered_nodes.has(node.type)) {
				// missing node
				if(node.properties.cnr_id) {
					if(node.properties.cnr_id == 'comfy-core') {
						outdated_comfyui = true;
					}

					let item = this.custom_nodes[node.properties.cnr_id];
					if(item) {
						hashMap[item.hash] = true;
					}
					else {
						console.log(`CM: cannot find '${node.properties.cnr_id}' from cnr list.`);
						unresolved_aux_ids[node.properties.cnr_id] = node.type;
						unresolved_cnr_list.push(node.properties.cnr_id);
					}
				}
				else if(node.properties.aux_id) {
					unresolved_aux_ids[node.properties.aux_id] = node.type;
				}
				else {
					unresolved_missing_nodes.add(node.type);
				}
			}
		}


		if(unresolved_cnr_list.length > 0) {
			let error_msg = "Failed to find the following ComfyRegistry list.\nThe cache may be outdated, or the nodes may have been removed from ComfyRegistry.<HR>";
			for(let i in unresolved_cnr_list) {
				error_msg += '<li>'+unresolved_cnr_list[i]+'</li>';
			}

			show_message(error_msg);
		}

		if(outdated_comfyui) {
			customAlert('ComfyUI is outdated, so some built-in nodes cannot be used.');
		}

		if(Object.keys(unresolved_aux_ids).length > 0) {
			// building aux_id to nodepack map
			let aux_id_to_pack = {};
			for(let k in this.custom_nodes) {
				let nodepack = this.custom_nodes[k];
				let aux_id;
				if(nodepack.repository?.startsWith('https://github.com')) {
					aux_id = nodepack.repository.split('/').slice(-2).join('/');
					aux_id_to_pack[aux_id] = nodepack;
				}
				else if(nodepack.repository) {
					aux_id = nodepack.repository.split('/').slice(-1);
					aux_id_to_pack[aux_id] = nodepack;
				}
			}

			// resolving aux_id
			for(let k in unresolved_aux_ids) {
				let nodepack = aux_id_to_pack[k];
				if(nodepack) {
					hashMap[nodepack.hash] = true;
				}
				else {
					unresolved_missing_nodes.add(unresolved_aux_ids[k]);
				}
			}
		}

		if(unresolved_missing_nodes.size > 0) {
			await this.getMissingNodesLegacy(hashMap, unresolved_missing_nodes);
		}

		return hashMap;
	}

	async getMissingNodesLegacy(hashMap, missing_nodes) {
		const mode = manager_instance.datasrc_combo.value;
		this.showStatus(`Loading missing nodes (${mode}) ...`);
		const res = await fetchData(`/customnode/getmappings?mode=${mode}`);
		if (res.error) {
			this.showError(`Failed to get custom node mappings: ${res.error}`);
			return;
		}

		const mappings = res.data;

		// build regex->url map
		const regex_to_pack = [];
		for(let k in this.custom_nodes) {
			let node = this.custom_nodes[k];

			if(node.nodename_pattern) {
				regex_to_pack.push({
					regex: new RegExp(node.nodename_pattern),
					url: node.files[0]
				});
			}
		}

		// build name->url map
		const name_to_packs = {};
		for (const url in mappings) {
			const names = mappings[url];

			for(const name in names[0]) {
				let v = name_to_packs[names[0][name]];
				if(v == undefined) {
					v = [];
					name_to_packs[names[0][name]] = v;
				}
				v.push(url);
			}
		}

		let unresolved_missing_nodes = new Set();
		for (let node_type of missing_nodes) {
			const packs = name_to_packs[node_type.trim()];
			if(packs)
				packs.forEach(url => {
					unresolved_missing_nodes.add(url);
				});
			else {
				for(let j in regex_to_pack) {
					if(regex_to_pack[j].regex.test(node_type)) {
						unresolved_missing_nodes.add(regex_to_pack[j].url);
					}
				}
			}
		}

		for(let k in this.custom_nodes) {
			let item = this.custom_nodes[k];

			if(unresolved_missing_nodes.has(item.id)) {
				hashMap[item.hash] = true;
			}
			else if (item.files?.some(file => unresolved_missing_nodes.has(file))) {
				hashMap[item.hash] = true;
			}
		}

		return hashMap;
	}

	async getFavorites() {
		const hashMap = {};
		for(let k in this.custom_nodes) {
			let item = this.custom_nodes[k];
			if(item.is_favorite)
			    hashMap[item.hash] = true;
		}

		return hashMap;
	}

	async getNodepackInWorkflow() {
		let allUsedNodes = this.getNodesInWorkflow();

		// building aux_id to nodepack map
		let aux_id_to_pack = {};
		for(let k in this.custom_nodes) {
			let nodepack = this.custom_nodes[k];
			let aux_id;
			if(nodepack.repository?.startsWith('https://github.com')) {
				aux_id = nodepack.repository.split('/').slice(-2).join('/');
				aux_id_to_pack[aux_id] = nodepack;
			}
			else if(nodepack.repository) {
				aux_id = nodepack.repository.split('/').slice(-1);
				aux_id_to_pack[aux_id] = nodepack;
			}
		}

		const hashMap = {};
		for(let k in allUsedNodes) {
			var item;
			if(allUsedNodes[k].properties.cnr_id) {
				item = this.custom_nodes[allUsedNodes[k].properties.cnr_id];
			}
			else if(allUsedNodes[k].properties.aux_id) {
				item = aux_id_to_pack[allUsedNodes[k].properties.aux_id];
			}

			if(item)
			    hashMap[item.hash] = true;
		}

		return hashMap;
	}

	async getAlternatives() {
		const mode = manager_instance.datasrc_combo.value;
		this.showStatus(`Loading alternatives (${mode}) ...`);
		const res = await fetchData(`/customnode/alternatives?mode=${mode}`);
		if (res.error) {
			this.showError(`Failed to get alternatives: ${res.error}`);
			return [];
		}

		const hashMap = {};
		const items = res.data;

		for(let i in items) {
			let item = items[i];
			let custom_node = this.custom_nodes[i];

			if (!custom_node) {
				console.log(`Not found custom node: ${item.id}`);
				continue;
			}

			const tags = `${item.tags}`.split(",").map(tag => {
				return `<div>${tag.trim()}</div>`;
			}).join("");

			hashMap[custom_node.hash] = {
				alternatives: `<div class="cn-tag-list">${tags}</div> ${item.description}`
			}

		}
	
		return hashMap;
	}

	async loadData(show_mode = ShowMode.NORMAL) {
		const isElectron = 'electronAPI' in window;

		this.show_mode = show_mode;
		console.log("Show mode:", show_mode);

		this.showLoading();

		const mode = manager_instance.datasrc_combo.value;
		this.showStatus(`Loading custom nodes (${mode}) ...`);

		const skip_update = this.show_mode === ShowMode.UPDATE ? "" : "&skip_update=true";

		if(this.show_mode === ShowMode.UPDATE) {
			infoToast('Fetching updated information. This may take some time if many custom nodes are installed.');
		}

		const res = await fetchData(`/customnode/getlist?mode=${mode}${skip_update}`);
		if (res.error) {
			this.showError("Failed to get custom node list.");
			this.hideLoading();
			return;
		}
		
		const { channel, node_packs } = res.data;

		if(isElectron) {
			delete node_packs['comfyui-manager'];
		}

		this.channel = channel;
		this.mode = mode;
		this.custom_nodes = node_packs;

		if(this.channel !== 'default') {
			this.element.querySelector(".cn-manager-channel").innerHTML = `Channel: ${this.channel} (Incomplete list)`;
		}

		for (const k in node_packs) {
			let item = node_packs[k];
			item.originalData = JSON.parse(JSON.stringify(item));
			if(item.originalData.id == undefined) {
				item.originalData.id = k;
			}
			item.key = k;
			item.hash = md5(k);
		}

		await this.loadNodes(node_packs);

		const filterItem = this.getFilterItem(this.show_mode);
		if(filterItem) {
			let hashMap;
			if(this.show_mode == ShowMode.UPDATE) {
				hashMap = {};
				for (const k in node_packs) {
					let it = node_packs[k];
					if (it['update-state'] === "true") {
						hashMap[it.hash] = true;
					}
				}
			} else if(this.show_mode == ShowMode.MISSING) {
				hashMap = await this.getMissingNodes();
			} else if(this.show_mode == ShowMode.ALTERNATIVES) {
				hashMap = await this.getAlternatives();
			} else if(this.show_mode == ShowMode.FAVORITES) {
				hashMap = await this.getFavorites();
			} else if(this.show_mode == ShowMode.IN_WORKFLOW) {
				hashMap = await this.getNodepackInWorkflow();
			}
			filterItem.hashMap = hashMap;

			if(this.show_mode != ShowMode.IN_WORKFLOW) {
				filterItem.hasData = true;
			}
		}

		for(let k in node_packs) {
			let nodeItem = node_packs[k];

			if (this.restartMap[nodeItem.hash]) {
				nodeItem.restart = true;
			}

			if(nodeItem['update-state'] == "true") {
				nodeItem.action = 'updatable';
			}
			else if(nodeItem['import-fail']) {
				nodeItem.action = 'import-fail';
			}
			else {
				nodeItem.action = nodeItem.state;
			}

            if(nodeItem['invalid-installation']) {
                nodeItem.action = 'invalid-installation';
            }

			const filterTypes = new Set();
			this.filterList.forEach(filterItem => {
				const { value, hashMap } = filterItem;
				if (hashMap) {
					const hashData = hashMap[nodeItem.hash]
					if (hashData) {
						filterTypes.add(value);
						if (value === ShowMode.UPDATE) {
							nodeItem['update-state'] = "true";
						}
						if (value === ShowMode.MISSING) {
							nodeItem['missing-node'] = "true";
						}
						if (typeof hashData === "object") {
							Object.assign(nodeItem, hashData);
						}
					}
				} else {
					if (nodeItem.state === value) {
						filterTypes.add(value);
					}

					switch(nodeItem.state) {
						case "enabled":
							filterTypes.add("enabled");
						case "disabled":
							filterTypes.add("installed");
							break;
						case "not-installed":
							filterTypes.add("not-installed");
							break;
					}

					if(nodeItem.version != 'unknown') {
						filterTypes.add("cnr");
					}
					else {
						filterTypes.add("unknown");
					}

					if(nodeItem['update-state'] == 'true') {
						filterTypes.add("updatable");
					}

					if(nodeItem['import-fail']) {
						filterTypes.add("import-fail");
					}

					if(nodeItem['invalid-installation']) {
						filterTypes.add("invalid-installation");
					}
				}
			});

			nodeItem.filterTypes = Array.from(filterTypes);
		}

		this.renderGrid();

		this.hideLoading();
		
	}

	// ===========================================================================================

	showSelection(msg) {
		this.element.querySelector(".cn-manager-selection").innerHTML = msg;
	}

	showError(err) {
		this.showMessage(err, "red");
	}

	showMessage(msg, color) {
		if (color) {
			msg = `<font color="${color}">${msg}</font>`;
		}
		this.element.querySelector(".cn-manager-message").innerHTML = msg;
	}

	showStatus(msg, color) {
		if (color) {
			msg = `<font color="${color}">${msg}</font>`;
		}
		this.element.querySelector(".cn-manager-status").innerHTML = msg;
	}

	showLoading() {
		this.setDisabled(true);
		if (this.grid) {
			this.grid.showLoading();
			this.grid.showMask({
				opacity: 0.05
			});
		}
	}

	hideLoading() {
		this.setDisabled(false);
		if (this.grid) {
			this.grid.hideLoading();
			this.grid.hideMask();
		}
	}

	setDisabled(disabled) {
		const $close = this.element.querySelector(".cn-manager-close");
		const $restart = this.element.querySelector(".cn-manager-restart");
		const $stop = this.element.querySelector(".cn-manager-stop");

		const list = [
			".cn-manager-header input",
			".cn-manager-header select",
			".cn-manager-footer button",
			".cn-manager-selection button"
		].map(s => {
			return Array.from(this.element.querySelectorAll(s));
		})
		.flat()
		.filter(it => {
			return it !== $close && it !== $restart && it !== $stop;
		});
		
		list.forEach($elem => {
			if (disabled) {
				$elem.setAttribute("disabled", "disabled");
			} else {
				$elem.removeAttribute("disabled");
			}
		});

		Array.from(this.element.querySelectorAll(".cn-btn-loading")).forEach($elem => {
			$elem.classList.remove("cn-btn-loading");
		});

	}

	showRestart() {
		this.element.querySelector(".cn-manager-restart").style.display = "block";
		setNeedRestart(true);
	}

	showStop() {
		this.element.querySelector(".cn-manager-stop").style.display = "block";
	}

	hideStop() {
		this.element.querySelector(".cn-manager-stop").style.display = "none";
	}

	setFilter(filterValue) {
		let filter = "";
		const filterItem = this.getFilterItem(filterValue);
		if(filterItem) {
			filter = filterItem.value;
		}
		this.filter = filter;
		this.element.querySelector(".cn-manager-filter").value = filter;
	}

	setKeywords(keywords = "") {
		this.keywords = keywords;
		this.element.querySelector(".cn-manager-keywords").value = keywords;
	}

	show(show_mode) {
		this.element.style.display = "flex";
		this.element.focus();
		this.setFilter(show_mode);
		this.setKeywords("");
		this.showSelection("");
		this.showMessage("");
		this.loadData(show_mode);
	}

	close() {
		this.element.style.display = "none";
	}

	get isVisible() {
		return this.element?.style?.display !== "none";
	}
}