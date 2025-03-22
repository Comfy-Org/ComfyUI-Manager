/**
 * Attaches metadata to the workflow on save
 * - custom node pack version to all custom nodes used in the workflow
 *
 * Example metadata:
 * "nodes": {
 *   "1": {
 *     type: "CheckpointLoaderSimple",
 *     ...
 *     properties: {
 *       cnr_id: "comfy-core",
 *       version: "0.3.8",
 *     },
 *   },
 * }
 *
 * @typedef {Object} NodeInfo
 * @property {string} ver - Version (git hash or semantic version)
 * @property {string} cnr_id - ComfyRegistry node ID
 * @property {boolean} enabled - Whether the node is enabled
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

class WorkflowMetadataExtension {
  constructor() {
    this.name = "Comfy.CustomNodesManager.WorkflowMetadata";
    this.installedNodes = {};
    this.comfyCoreVersion = null;
  }

  /**
   * Get the installed nodes info
   * @returns {Promise<Record<string, NodeInfo>>} The mapping from node name to its info.
   * ver can either be a git commit hash or a semantic version such as "1.0.0"
   * cnr_id is the id of the node in the ComfyRegistry
   * enabled is true if the node is enabled, false if it is disabled
   */
  async getInstalledNodes() {
    const res = await api.fetchApi("/customnode/installed");
    return await res.json();
  }

  async init() {
    this.installedNodes = await this.getInstalledNodes();
    this.comfyCoreVersion = (await api.getSystemStats()).system.comfyui_version;
  }

  /**
   * Called when any node is created
   * @param {LGraphNode} node The newly created node
   */
  nodeCreated(node) {
    try {
      // nodeData doesn't exist if node is missing or node is frontend only node
      if (!node?.constructor?.nodeData?.python_module) return;

      const nodeProperties = (node.properties ??= {});
      const modules = node.constructor.nodeData.python_module.split(".");
      const moduleType = modules[0];

      if (moduleType === "custom_nodes") {
        const nodePackageName = modules[1];
        const { cnr_id, aux_id, ver } =
          this.installedNodes[nodePackageName] ??
          this.installedNodes[nodePackageName.toLowerCase()] ??
          {};

        if (cnr_id === "comfy-core") return; // don't allow hijacking comfy-core name
        if (cnr_id) nodeProperties.cnr_id = cnr_id;
        else nodeProperties.aux_id = aux_id;
        if (ver) nodeProperties.ver = ver;
      } else if (["nodes", "comfy_extras"].includes(moduleType)) {
        nodeProperties.cnr_id = "comfy-core";
        nodeProperties.ver = this.comfyCoreVersion;
      }
    } catch (e) {
      console.error(e);
    }
  }
}

app.registerExtension(new WorkflowMetadataExtension());
