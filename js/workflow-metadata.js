/**
 * Attaches metadata to the workflow on save
 * - custom node pack version to all custom nodes used in the workflow
 *
 * Example metadata:
 "extra": {
    "node_versions": {
      "comfy-core": "v0.3.8-4-g0b2eb7f",
      "comfyui-easy-use": "1.2.5"
    }
  },
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
   * @returns {Promise<Record<string, {ver: string, cnr_id: string, enabled: boolean}>>} The mapping from node name to its info.
   * ver can either be a git commit hash or a semantic version such as "1.0.0"
   * cnr_id is the id of the node in the ComfyRegistry
   * enabled is true if the node is enabled, false if it is disabled
   */
  async getInstalledNodes() {
    const res = await api.fetchApi("/customnode/installed");
    return await res.json();
  }

  /**
   * Get the node versions for the given graph
   * @param {LGraph} graph The graph to get the node versions for
   * @returns {Promise<Record<string, string>>} The mapping from node name to version
   */
  getGraphNodeVersions(graph) {
    const nodeVersions = {};
    for (const node of graph.nodes) {
      const nodeData = node.constructor.nodeData;
      // Frontend only nodes don't have nodeData
      if (!nodeData) {
        continue;
      }
      const modules = nodeData.python_module.split(".");

      if (modules[0] === "custom_nodes") {
        const nodePackageName = modules[1];
        const nodeInfo =
          this.installedNodes[nodePackageName] ??
          this.installedNodes[nodePackageName.toLowerCase()];
        if (nodeInfo) {
          nodeVersions[nodePackageName] = nodeInfo.ver;
        }
      } else if (["nodes", "comfy_extras"].includes(modules[0])) {
        nodeVersions["comfy-core"] = this.comfyCoreVersion;
      } else {
        console.warn(`Unknown node source: ${nodeData.python_module}`);
      }
    }
    return nodeVersions;
  }

  async init() {
    const extension = this;
    this.installedNodes = await this.getInstalledNodes();
    this.comfyCoreVersion = (await api.getSystemStats()).system.comfyui_version;

    // Attach metadata when app.graphToPrompt is called.
    const originalSerialize = LGraph.prototype.serialize;
    LGraph.prototype.serialize = function () {
      const workflow = originalSerialize.apply(this, arguments);

      // Add metadata to the workflow
      if (!workflow.extra) {
        workflow.extra = {};
      }
      const graph = this;
      try {
        workflow.extra["node_versions"] = extension.getGraphNodeVersions(graph);
      } catch (e) {
        console.error(e);
      }

      return workflow;
    };
  }
}

app.registerExtension(new WorkflowMetadataExtension());
