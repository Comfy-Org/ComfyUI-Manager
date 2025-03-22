import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { $el, ComfyDialog } from "../../scripts/ui.js";
import { getBestPosition, getPositionStyle, getRect } from './popover-helper.js';


function internalCustomConfirm(message, confirmMessage, cancelMessage) {
	return new Promise((resolve) => {
		// transparent bg
		const modalOverlay = document.createElement('div');
		modalOverlay.style.position = 'fixed';
		modalOverlay.style.top = 0;
		modalOverlay.style.left = 0;
		modalOverlay.style.width = '100%';
		modalOverlay.style.height = '100%';
		modalOverlay.style.backgroundColor = 'rgba(0, 0, 0, 0.8)';
		modalOverlay.style.display = 'flex';
		modalOverlay.style.alignItems = 'center';
		modalOverlay.style.justifyContent = 'center';
		modalOverlay.style.zIndex = '1101';

		// Modal window container (dark bg)
		const modalDialog = document.createElement('div');
		modalDialog.style.backgroundColor = '#333';
		modalDialog.style.padding = '20px';
		modalDialog.style.borderRadius = '4px';
		modalDialog.style.maxWidth = '400px';
		modalDialog.style.width = '80%';
		modalDialog.style.boxShadow = '0 2px 8px rgba(0, 0, 0, 0.5)';
		modalDialog.style.color = '#fff';

		// Display message
		const modalMessage = document.createElement('p');
		modalMessage.textContent = message;
		modalMessage.style.margin = '0';
		modalMessage.style.padding = '0 0 20px';
		modalMessage.style.wordBreak = 'keep-all';

		// Button container
		const modalButtons = document.createElement('div');
		modalButtons.style.display = 'flex';
		modalButtons.style.justifyContent = 'flex-end';

		// Confirm button (green)
		const confirmButton = document.createElement('button');
		if(confirmMessage)
			confirmButton.textContent = confirmMessage;
		else
			confirmButton.textContent = 'Confirm';
		confirmButton.style.marginLeft = '10px';
		confirmButton.style.backgroundColor = '#28a745'; // green
		confirmButton.style.color = '#fff';
		confirmButton.style.border = 'none';
		confirmButton.style.padding = '6px 12px';
		confirmButton.style.borderRadius = '4px';
		confirmButton.style.cursor = 'pointer';
		confirmButton.style.fontWeight = 'bold';

		// Cancel button (red)
		const cancelButton = document.createElement('button');
		if(cancelMessage)
			cancelButton.textContent = cancelMessage;
		else
			cancelButton.textContent = 'Cancel';

		cancelButton.style.marginLeft = '10px';
		cancelButton.style.backgroundColor = '#dc3545'; // red
		cancelButton.style.color = '#fff';
		cancelButton.style.border = 'none';
		cancelButton.style.padding = '6px 12px';
		cancelButton.style.borderRadius = '4px';
		cancelButton.style.cursor = 'pointer';
		cancelButton.style.fontWeight = 'bold';

		const closeModal = () => {
			document.body.removeChild(modalOverlay);
		};

		confirmButton.addEventListener('click', () => {
			closeModal();
			resolve(true);
		});

		cancelButton.addEventListener('click', () => {
			closeModal();
			resolve(false);
		});

		modalButtons.appendChild(confirmButton);
		modalButtons.appendChild(cancelButton);
		modalDialog.appendChild(modalMessage);
		modalDialog.appendChild(modalButtons);
		modalOverlay.appendChild(modalDialog);
		document.body.appendChild(modalOverlay);
	});
}

export function show_message(msg) {
	app.ui.dialog.show(msg);
	app.ui.dialog.element.style.zIndex = 1100;
}

export async function sleep(ms) {
	return new Promise(resolve => setTimeout(resolve, ms));
}

export async function customConfirm(message) {
	try {
		let res = await
			window['app'].extensionManager.dialog
			.confirm({
				title: 'Confirm',
				message: message
			});

		return res;
	}
	catch {
		let res = await internalCustomConfirm(message);
		return res;
	}
}


export function customAlert(message) {
	try {
		window['app'].extensionManager.toast.addAlert(message);
	}
	catch {
		alert(message);
	}
}

export function infoToast(summary, message) {
	try {
		app.extensionManager.toast.add({
			severity: 'info',
			summary: summary,
			detail: message,
			life: 3000
		})
	}
	catch {
		// do nothing
	}
}


export async function customPrompt(title, message) {
	try {
		let res = await
				window['app'].extensionManager.dialog
				.prompt({
					title: title,
					message: message
				});

		return res;
	}
	catch {
		return prompt(title, message)
	}
}


export function rebootAPI() {
	if ('electronAPI' in window) {
			window.electronAPI.restartApp();
			return true;
	}

	customConfirm("Are you sure you'd like to reboot the server?").then((isConfirmed) => {
		if (isConfirmed) {
			try {
				api.fetchApi("/manager/reboot");
			}
			catch(exception) {}
		}
	});

	return false;
}


export var manager_instance = null;

export function setManagerInstance(obj) {
	manager_instance = obj;
}

export function showToast(message, duration = 3000) {
	const toast = $el("div.comfy-toast", {textContent: message});
	document.body.appendChild(toast);
	setTimeout(() => {
		toast.classList.add("comfy-toast-fadeout");
		setTimeout(() => toast.remove(), 500);
	}, duration);
}

function isValidURL(url) {
	if(url.includes('&'))
		return false;

	const http_pattern = /^(https?|ftp):\/\/[^\s$?#]+$/;
	const ssh_pattern = /^(.+@|ssh:\/\/).+:.+$/;
	return http_pattern.test(url) || ssh_pattern.test(url);
}

export async function install_pip(packages) {
	if(packages.includes('&'))
		app.ui.dialog.show(`Invalid PIP package enumeration: '${packages}'`);

	const res = await api.fetchApi("/customnode/install/pip", {
		method: "POST",
		body: packages,
	});

	if(res.status == 403) {
		show_message('This action is not allowed with this security level configuration.');
		return;
	}

	if(res.status == 200) {
		show_message(`PIP package installation is processed.<br>To apply the pip packages, please click the <button id='cm-reboot-button3'><font size='3px'>RESTART</font></button> button in ComfyUI.`);

		const rebootButton = document.getElementById('cm-reboot-button3');
		const self = this;

		rebootButton.addEventListener("click", rebootAPI);
	}
	else {
		show_message(`Failed to install '${packages}'<BR>See terminal log.`);
	}
}

export async function install_via_git_url(url, manager_dialog) {
	if(!url) {
		return;
	}

	if(!isValidURL(url)) {
		show_message(`Invalid Git url '${url}'`);
		return;
	}

	show_message(`Wait...<BR><BR>Installing '${url}'`);

	const res = await api.fetchApi("/customnode/install/git_url", {
		method: "POST",
		body: url,
	});

	if(res.status == 403) {
		show_message('This action is not allowed with this security level configuration.');
		return;
	}

	if(res.status == 200) {
		show_message(`'${url}' is installed<BR>To apply the installed custom node, please <button id='cm-reboot-button4'><font size='3px'>RESTART</font></button> ComfyUI.`);

		const rebootButton = document.getElementById('cm-reboot-button4');
		const self = this;

		rebootButton.addEventListener("click",
			function() {
				if(rebootAPI()) {
					manager_dialog.close();
				}
			});
	}
	else {
		show_message(`Failed to install '${url}'<BR>See terminal log.`);
	}
}

export async function free_models(free_execution_cache) {
	try {
		let mode = "";
		if(free_execution_cache) {
			mode = '{"unload_models": true, "free_memory": true}';
		}
		else {
			mode = '{"unload_models": true}';
		}

		let res = await api.fetchApi(`/free`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: mode
		});

		if (res.status == 200) {
			if(free_execution_cache) {
				showToast("'Models' and 'Execution Cache' have been cleared.", 3000);
			}
			else {
				showToast("Models' have been unloaded.", 3000);
			}
		} else {
			showToast('Unloading of models failed. Installed ComfyUI may be an outdated version.', 5000);
		}
	} catch (error) {
		showToast('An error occurred while trying to unload models.', 5000);
	}
}

export function md5(inputString) {
	const hc = '0123456789abcdef';
	const rh = n => {let j,s='';for(j=0;j<=3;j++) s+=hc.charAt((n>>(j*8+4))&0x0F)+hc.charAt((n>>(j*8))&0x0F);return s;}
	const ad = (x,y) => {let l=(x&0xFFFF)+(y&0xFFFF);let m=(x>>16)+(y>>16)+(l>>16);return (m<<16)|(l&0xFFFF);}
	const rl = (n,c) => (n<<c)|(n>>>(32-c));
	const cm = (q,a,b,x,s,t) => ad(rl(ad(ad(a,q),ad(x,t)),s),b);
	const ff = (a,b,c,d,x,s,t) => cm((b&c)|((~b)&d),a,b,x,s,t);
	const gg = (a,b,c,d,x,s,t) => cm((b&d)|(c&(~d)),a,b,x,s,t);
	const hh = (a,b,c,d,x,s,t) => cm(b^c^d,a,b,x,s,t);
	const ii = (a,b,c,d,x,s,t) => cm(c^(b|(~d)),a,b,x,s,t);
	const sb = x => {
	let i;const nblk=((x.length+8)>>6)+1;const blks=[];for(i=0;i<nblk*16;i++) { blks[i]=0 };
	for(i=0;i<x.length;i++) {blks[i>>2]|=x.charCodeAt(i)<<((i%4)*8);}
		blks[i>>2]|=0x80<<((i%4)*8);blks[nblk*16-2]=x.length*8;return blks;
	}
	let i,x=sb(inputString),a=1732584193,b=-271733879,c=-1732584194,d=271733878,olda,oldb,oldc,oldd;
	for(i=0;i<x.length;i+=16) {olda=a;oldb=b;oldc=c;oldd=d;
		a=ff(a,b,c,d,x[i+ 0], 7, -680876936);d=ff(d,a,b,c,x[i+ 1],12, -389564586);c=ff(c,d,a,b,x[i+ 2],17,  606105819);
		b=ff(b,c,d,a,x[i+ 3],22,-1044525330);a=ff(a,b,c,d,x[i+ 4], 7, -176418897);d=ff(d,a,b,c,x[i+ 5],12, 1200080426);
		c=ff(c,d,a,b,x[i+ 6],17,-1473231341);b=ff(b,c,d,a,x[i+ 7],22,  -45705983);a=ff(a,b,c,d,x[i+ 8], 7, 1770035416);
		d=ff(d,a,b,c,x[i+ 9],12,-1958414417);c=ff(c,d,a,b,x[i+10],17,     -42063);b=ff(b,c,d,a,x[i+11],22,-1990404162);
		a=ff(a,b,c,d,x[i+12], 7, 1804603682);d=ff(d,a,b,c,x[i+13],12,  -40341101);c=ff(c,d,a,b,x[i+14],17,-1502002290);
		b=ff(b,c,d,a,x[i+15],22, 1236535329);a=gg(a,b,c,d,x[i+ 1], 5, -165796510);d=gg(d,a,b,c,x[i+ 6], 9,-1069501632);
		c=gg(c,d,a,b,x[i+11],14,  643717713);b=gg(b,c,d,a,x[i+ 0],20, -373897302);a=gg(a,b,c,d,x[i+ 5], 5, -701558691);
		d=gg(d,a,b,c,x[i+10], 9,   38016083);c=gg(c,d,a,b,x[i+15],14, -660478335);b=gg(b,c,d,a,x[i+ 4],20, -405537848);
		a=gg(a,b,c,d,x[i+ 9], 5,  568446438);d=gg(d,a,b,c,x[i+14], 9,-1019803690);c=gg(c,d,a,b,x[i+ 3],14, -187363961);
		b=gg(b,c,d,a,x[i+ 8],20, 1163531501);a=gg(a,b,c,d,x[i+13], 5,-1444681467);d=gg(d,a,b,c,x[i+ 2], 9,  -51403784);
		c=gg(c,d,a,b,x[i+ 7],14, 1735328473);b=gg(b,c,d,a,x[i+12],20,-1926607734);a=hh(a,b,c,d,x[i+ 5], 4,    -378558);
		d=hh(d,a,b,c,x[i+ 8],11,-2022574463);c=hh(c,d,a,b,x[i+11],16, 1839030562);b=hh(b,c,d,a,x[i+14],23,  -35309556);
		a=hh(a,b,c,d,x[i+ 1], 4,-1530992060);d=hh(d,a,b,c,x[i+ 4],11, 1272893353);c=hh(c,d,a,b,x[i+ 7],16, -155497632);
		b=hh(b,c,d,a,x[i+10],23,-1094730640);a=hh(a,b,c,d,x[i+13], 4,  681279174);d=hh(d,a,b,c,x[i+ 0],11, -358537222);
		c=hh(c,d,a,b,x[i+ 3],16, -722521979);b=hh(b,c,d,a,x[i+ 6],23,   76029189);a=hh(a,b,c,d,x[i+ 9], 4, -640364487);
		d=hh(d,a,b,c,x[i+12],11, -421815835);c=hh(c,d,a,b,x[i+15],16,  530742520);b=hh(b,c,d,a,x[i+ 2],23, -995338651);
		a=ii(a,b,c,d,x[i+ 0], 6, -198630844);d=ii(d,a,b,c,x[i+ 7],10, 1126891415);c=ii(c,d,a,b,x[i+14],15,-1416354905);
		b=ii(b,c,d,a,x[i+ 5],21,  -57434055);a=ii(a,b,c,d,x[i+12], 6, 1700485571);d=ii(d,a,b,c,x[i+ 3],10,-1894986606);
		c=ii(c,d,a,b,x[i+10],15,   -1051523);b=ii(b,c,d,a,x[i+ 1],21,-2054922799);a=ii(a,b,c,d,x[i+ 8], 6, 1873313359);
		d=ii(d,a,b,c,x[i+15],10,  -30611744);c=ii(c,d,a,b,x[i+ 6],15,-1560198380);b=ii(b,c,d,a,x[i+13],21, 1309151649);
		a=ii(a,b,c,d,x[i+ 4], 6, -145523070);d=ii(d,a,b,c,x[i+11],10,-1120210379);c=ii(c,d,a,b,x[i+ 2],15,  718787259);
		b=ii(b,c,d,a,x[i+ 9],21, -343485551);a=ad(a,olda);b=ad(b,oldb);c=ad(c,oldc);d=ad(d,oldd);
	}
	return rh(a)+rh(b)+rh(c)+rh(d);
}

export async function fetchData(route, options) {
	let err;
	const res = await api.fetchApi(route, options).catch(e => {
		err = e;
	});

	if (!res) {
		return {
			status: 400,
			error: new Error("Unknown Error")
		}
	}

	const { status, statusText } = res;
	if (err) {
		return {
			status,
			error: err
		}
	}

	if (status !== 200) {
		return {
			status,
			error: new Error(statusText || "Unknown Error")
		}
	}

	const data = await res.json();
	if (!data) {
		return {
			status,
			error: new Error(`Failed to load data: ${route}`)
		}
	}
	return {
		status,
		data
	}
}

// https://cenfun.github.io/open-icons/
export const icons = {
	search: '<svg viewBox="0 0 24 24" width="100%" height="100%" pointer-events="none" xmlns="http://www.w3.org/2000/svg"><path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m21 21-4.486-4.494M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0"/></svg>',
	conflicts: '<svg viewBox="0 0 400 400" width="100%" height="100%" pointer-events="none" xmlns="http://www.w3.org/2000/svg"><path fill="currentColor" d="m397.2 350.4.2-.2-180-320-.2.2C213.8 24.2 207.4 20 200 20s-13.8 4.2-17.2 10.4l-.2-.2-180 320 .2.2c-1.6 2.8-2.8 6-2.8 9.6 0 11 9 20 20 20h360c11 0 20-9 20-20 0-3.6-1.2-6.8-2.8-9.6M220 340h-40v-40h40zm0-60h-40V120h40z"/></svg>',
	passed: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 426.667 426.667"><path fill="#6AC259" d="M213.333,0C95.518,0,0,95.514,0,213.333s95.518,213.333,213.333,213.333c117.828,0,213.333-95.514,213.333-213.333S331.157,0,213.333,0z M174.199,322.918l-93.935-93.931l31.309-31.309l62.626,62.622l140.894-140.898l31.309,31.309L174.199,322.918z"/></svg>',
	download: '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" aria-hidden="true" width="100%" height="100%" viewBox="0 0 32 32"><path fill="currentColor" d="M26 24v4H6v-4H4v4a2 2 0 0 0 2 2h20a2 2 0 0 0 2-2v-4zm0-10l-1.41-1.41L17 20.17V2h-2v18.17l-7.59-7.58L6 14l10 10l10-10z"></path></svg>',
	close: '<svg xmlns="http://www.w3.org/2000/svg" pointer-events="none" width="100%" height="100%" viewBox="0 0 16 16"><g fill="currentColor"><path fill-rule="evenodd" clip-rule="evenodd" d="m7.116 8-4.558 4.558.884.884L8 8.884l4.558 4.558.884-.884L8.884 8l4.558-4.558-.884-.884L8 7.116 3.442 2.558l-.884.884L7.116 8z"/></g></svg>',
	arrowRight: '<svg xmlns="http://www.w3.org/2000/svg" pointer-events="none" width="100%" height="100%" viewBox="0 0 20 20"><path fill="currentColor" fill-rule="evenodd" d="m2.542 2.154 7.254 7.26c.136.14.204.302.204.483a.73.73 0 0 1-.204.5l-7.575 7.398c-.383.317-.724.317-1.022 0-.299-.317-.299-.643 0-.98l7.08-6.918-6.754-6.763c-.237-.343-.215-.654.066-.935.281-.28.598-.295.951-.045Zm9 0 7.254 7.26c.136.14.204.302.204.483a.73.73 0 0 1-.204.5l-7.575 7.398c-.383.317-.724.317-1.022 0-.299-.317-.299-.643 0-.98l7.08-6.918-6.754-6.763c-.237-.343-.215-.654.066-.935.281-.28.598-.295.951-.045Z"/></svg>'
}

export function sanitizeHTML(str) {
	return str
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#039;");
}

export function showTerminal() {
	try {
		const panel = app.extensionManager.bottomPanel;
		const isTerminalVisible = panel.bottomPanelVisible && panel.activeBottomPanelTab.id === 'logs-terminal';
		if (!isTerminalVisible)
			panel.toggleBottomPanelTab('logs-terminal');
	}
	catch(exception) {
		// do nothing
	}
}

let need_restart = false;

export function setNeedRestart(value) {
	need_restart = value;
}

async function onReconnected(event) {
	if(need_restart) {
		setNeedRestart(false);

		const confirmed = await customConfirm("To apply the changes to the node pack's installation status, you need to refresh the browser. Would you like to refresh?");
		if (!confirmed) {
			return;
		}

		window.location.reload(true);
	}
}

api.addEventListener('reconnected', onReconnected);

const storeId = "comfyui-manager-grid";
let timeId;
export function storeColumnWidth(gridId, columnItem) {
	clearTimeout(timeId);
	timeId = setTimeout(() => {
		let data = {};
		const dataStr = localStorage.getItem(storeId);
		if (dataStr) {
			try {
				data = JSON.parse(dataStr);
			} catch (e) {}
		}

		if (!data[gridId]) {
			data[gridId] =  {};
		}

		data[gridId][columnItem.id] = columnItem.width;

		localStorage.setItem(storeId, JSON.stringify(data));

	}, 200)
}

export function restoreColumnWidth(gridId, columns) {
	const dataStr = localStorage.getItem(storeId);
	if (!dataStr) {
		return;
	}
	let data;
	try {
		data = JSON.parse(dataStr);
	} catch (e) {}
	if(!data) {
		return;
	}
	const widthMap = data[gridId];
	if (!widthMap) {
		return;
	}

	columns.forEach(columnItem => {
		const w = widthMap[columnItem.id];
		if (w) {
			columnItem.width = w;
		}
	});

}

export function getTimeAgo(dateStr) {
	const date = new Date(dateStr);

	if (!date || !(date instanceof Date) || isNaN(date.getTime())) {
		return "";
	}

	const units = [
		{ max: 2760000, value: 60000, name: 'minute', past: 'a minute ago', future: 'in a minute' },
		{ max: 72000000, value: 3600000, name: 'hour', past: 'an hour ago', future: 'in an hour' },
		{ max: 518400000, value: 86400000, name: 'day', past: 'yesterday', future: 'tomorrow' },
		{ max: 2419200000, value: 604800000, name: 'week', past: 'last week', future: 'in a week' },
		{ max: 28512000000, value: 2592000000, name: 'month', past: 'last month', future: 'in a month' }
	];
    const diff = Date.now() - date.getTime();
    // less than a minute
    if (Math.abs(diff) < 60000)
        return 'just now';
    for (let i = 0; i < units.length; i++) {
        if (Math.abs(diff) < units[i].max) {
            return format(diff, units[i].value, units[i].name, units[i].past, units[i].future, diff < 0);
        }
    }
    function format(diff, divisor, unit, past, future, isInTheFuture) {
		const val = Math.round(Math.abs(diff) / divisor);
		if (isInTheFuture)
			return val <= 1 ? future : 'in ' + val + ' ' + unit + 's';
		return val <= 1 ? past : val + ' ' + unit + 's ago';
	}
    return format(diff, 31536000000, 'year', 'last year', 'in a year', diff < 0);
};

export const loadCss = (cssFile) => {
	const cssPath = import.meta.resolve(cssFile);
	//console.log(cssPath);
	const $link = document.createElement("link");
	$link.setAttribute("rel", 'stylesheet');
	$link.setAttribute("href", cssPath);
	document.head.appendChild($link);
};

export const copyText = (text) => {
	return new Promise((resolve) => {
		let err;
		try {
			navigator.clipboard.writeText(text);
		} catch (e) {
			err = e;
		}
		if (err) {
			resolve(false);
		} else {
			resolve(true);
		}
	});
};

function renderPopover($elem, target, options = {}) {
	// async microtask
	queueMicrotask(() => {
		
		const containerRect = getRect(window);
		const targetRect = getRect(target);
		const elemRect = getRect($elem);

		const positionInfo = getBestPosition(
			containerRect,
			targetRect,
			elemRect,
			options.positions
		);
		const style = getPositionStyle(positionInfo, {
			bgColor: options.bgColor,
			borderColor: options.borderColor,
			borderRadius: options.borderRadius
		});

		$elem.style.top = positionInfo.top + "px";
		$elem.style.left = positionInfo.left + "px";
		$elem.style.background = style.background;
	
	});
}

let $popover;
export function hidePopover() {
	if ($popover) {
		$popover.remove();
		$popover = null;
	}
}
export function showPopover(target, text, className, options) {
	hidePopover();
	$popover = document.createElement("div");
	$popover.className = ['cn-popover', className].filter(it => it).join(" ");
	document.body.appendChild($popover);
	$popover.innerHTML = text;
	$popover.style.display = "block";
	renderPopover($popover, target, {
		borderRadius: 10,
		... options
	});
}

let $tooltip;
export function hideTooltip(target) {
	if ($tooltip) {
		$tooltip.style.display = "none";
		$tooltip.innerHTML = "";
		$tooltip.style.top = "0px";
		$tooltip.style.left = "0px";
	}
}
export function showTooltip(target, text, className = 'cn-tooltip', styleMap = {}) {
	if (!$tooltip) {
		$tooltip = document.createElement("div");
		$tooltip.className = className;
		$tooltip.style.cssText = `
			pointer-events: none;
			position: fixed;
			z-index: 10001;
			padding: 20px;
			color: #1e1e1e;
			max-width: 350px;
			filter: drop-shadow(1px 5px 5px rgb(0 0 0 / 30%));
			${Object.keys(styleMap).map(k=>k+":"+styleMap[k]+";").join("")}
		`;
		document.body.appendChild($tooltip);
	}

	$tooltip.innerHTML = text;
	$tooltip.style.display = "block";
	renderPopover($tooltip, target, {
		positions: ['top', 'bottom', 'right', 'center'],
		bgColor: "#ffffff",
		borderColor: "#cccccc",
		borderRadius: 5
	});
}

function initTooltip () {
	const mouseenterHandler = (e) => {
        const target = e.target;
        const text = target.getAttribute('tooltip');
        if (text) {
            showTooltip(target, text);
        }
    };
	const mouseleaveHandler = (e) => {
        const target = e.target;
        const text = target.getAttribute('tooltip');
        if (text) {
            hideTooltip(target);
        }
    };
	document.body.removeEventListener('mouseenter', mouseenterHandler, true);
	document.body.removeEventListener('mouseleave', mouseleaveHandler, true);
	document.body.addEventListener('mouseenter', mouseenterHandler, true);
    document.body.addEventListener('mouseleave', mouseleaveHandler, true);
}

initTooltip();