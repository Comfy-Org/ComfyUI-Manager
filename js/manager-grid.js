import { Grid } from "./turbogrid.esm.js";

// Keep Manager's search hardening outside the vendored TurboGrid bundle.
export default class ManagerGrid extends Grid {
	highlightKeywordsFilter(rowItem, columns, value) {
		const { textKey, textGenerator, highlightKey } = this.options.highlightKeywords;
		for (const column of columns) {
			rowItem[`${highlightKey}${column}`] = null;
		}
		const keywords = value ? String(value).trim().toLowerCase().split(/\s+/).filter(Boolean) : [];
		if (!keywords.length) return true;

		let matched = false;
		for (const column of columns) {
			const value = typeof textGenerator === "function" ? textGenerator(rowItem, column) : rowItem[column];
			if (value === null || value === undefined) continue;
			let text = String(value).trim();
			if (!text) continue;
			const key = `${textKey}${column}`;
			if (rowItem[key] === null || rowItem[key] === undefined) {
				// A detached element's innerHTML can still run image handlers.
				rowItem[key] = new DOMParser().parseFromString(text, "text/html").body.textContent;
			}
			text = rowItem[key].toLowerCase();
			let offset = 0;
			const found = keywords.every(keyword => {
				const index = text.indexOf(keyword, offset);
				if (index === -1) return false;
				offset = index + keyword.length;
				return true;
			});
			if (found) {
				rowItem[`${highlightKey}${column}`] = true;
				this.highlightKeywords = keywords;
				matched = true;
			}
		}
		return matched;
	}

	highlightTextNodes(nodes, keywords) {
		if (!keywords.length) return;
		let keywordIndex = 0;
		for (const node of nodes) {
			const text = node.textContent;
			const lower = text.toLowerCase();
			const wrapper = document.createElement("span");
			let offset = 0;
			while (offset < text.length) {
				const keyword = keywords[keywordIndex];
				const index = lower.indexOf(keyword, offset);
				if (index === -1) break;
				wrapper.append(text.slice(offset, index));
				const mark = document.createElement("mark");
				mark.textContent = text.slice(index, index + keyword.length);
				wrapper.append(mark);
				offset = index + keyword.length;
				keywordIndex = (keywordIndex + 1) % keywords.length;
			}
			if (wrapper.childNodes.length) {
				// Decoded cell text stays in text nodes, including inside <mark>.
				wrapper.append(text.slice(offset));
				node.replaceWith(wrapper);
			}
		}
	}
}
