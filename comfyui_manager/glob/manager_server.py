"""
ComfyUI Manager Server

Main server implementation providing REST API endpoints for ComfyUI Manager functionality.
Handles task queue management, custom node operations, model installation, and system configuration.
"""

import asyncio
import concurrent
import copy
import heapq
import json
import logging
import os
import platform
import re
import shutil
import subprocess  # don't remove this
import sys
import threading
import traceback
import urllib.request
import uuid
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

import folder_paths
import latent_preview
import nodes
from aiohttp import web
from comfy.cli_args import args
from pydantic import ValidationError

from comfyui_manager.glob.utils import (
    formatting_utils,
    model_utils,
    security_utils,
    node_pack_utils,
    environment_utils,
)


from server import PromptServer

from . import manager_core as core
from ..common import manager_util
from ..common import cm_global
from ..common import manager_downloader
from ..common import context


from ..data_models import (
    QueueTaskItem,
    TaskHistoryItem,
    TaskStateMessage,
    TaskExecutionStatus,
    MessageTaskDone,
    MessageTaskStarted,
    MessageUpdate,
    ManagerMessageName,
    BatchExecutionRecord,
    ComfyUISystemState,
    BatchOperation,
    InstalledNodeInfo,
    ComfyUIVersionInfo,
    InstallPackParams,
    UpdatePackParams,
    UpdateAllPacksParams,
    UpdateComfyUIParams,
    FixPackParams,
    UninstallPackParams,
    DisablePackParams,
    EnablePackParams,
    ModelMetadata,
)

from .constants import (
    model_dir_name_map,
    SECURITY_MESSAGE_MIDDLE_OR_BELOW,
)

if not manager_util.is_manager_pip_package():
    network_mode_description = "offline"
else:
    network_mode_description = core.get_config()["network_mode"]
logging.info("[ComfyUI-Manager] network_mode: " + network_mode_description)


MAXIMUM_HISTORY_SIZE = 10000
routes = PromptServer.instance.routes


def is_loopback(address):
    import ipaddress

    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


is_local_mode = is_loopback(args.listen)


def validate_required_params(request: web.Request, required_params: List[str]) -> Optional[web.Response]:
    """Validate that all required query parameters are present.
    
    Args:
        request: The aiohttp request object
        required_params: List of required parameter names
        
    Returns:
        web.Response with 400 status if validation fails, None if validation passes
    """
    missing_params = []
    for param in required_params:
        if param not in request.rel_url.query:
            missing_params.append(param)
    
    if missing_params:
        missing_str = ", ".join(missing_params)
        return web.Response(
            status=400, 
            text=f"Missing required parameter(s): {missing_str}"
        )
    return None


def error_response(status: int, message: str, error_type: Optional[str] = None) -> web.Response:
    """Create a standardized error response.
    
    Args:
        status: HTTP status code
        message: Error message
        error_type: Optional error type/category
        
    Returns:
        web.Response with JSON error body
    """
    error_data = {"error": message}
    if error_type:
        error_data["error_type"] = error_type
        
    return web.json_response(error_data, status=status)


class ManagerFuncsInComfyUI(core.ManagerFuncs):
    def get_current_preview_method(self):
        if args.preview_method == latent_preview.LatentPreviewMethod.Auto:
            return "auto"
        elif args.preview_method == latent_preview.LatentPreviewMethod.Latent2RGB:
            return "latent2rgb"
        elif args.preview_method == latent_preview.LatentPreviewMethod.TAESD:
            return "taesd"
        else:
            return "none"

    def run_script(self, cmd, cwd="."):
        if len(cmd) > 0 and cmd[0].startswith("#"):
            logging.error(f"[ComfyUI-Manager] Unexpected behavior: `{cmd}`")
            return 0

        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=core.get_script_env(),
        )

        stdout_thread = threading.Thread(
            target=formatting_utils.handle_stream, args=(process.stdout, "")
        )
        stderr_thread = threading.Thread(
            target=formatting_utils.handle_stream, args=(process.stderr, "[!]")
        )

        stdout_thread.start()
        stderr_thread.start()

        stdout_thread.join()
        stderr_thread.join()

        return process.wait()


core.manager_funcs = ManagerFuncsInComfyUI()

from comfyui_manager.common.manager_downloader import (
    download_url,
    download_url_with_agent,
)


class TaskQueue:
    instance = None

    def __init__(self):
        TaskQueue.instance = self
        self.mutex = threading.RLock()
        self.not_empty = threading.Condition(self.mutex)
        self.current_index = 0
        self.pending_tasks = []
        self.running_tasks = {}
        self.history_tasks = {}
        self.task_counter = 0
        self.batch_id = None
        self.batch_start_time = None
        self.batch_state_before = None
        self._worker_task = None

    def is_processing(self) -> bool:
        """Check if the queue is currently processing tasks"""
        return (
            self._worker_task is not None 
            and self._worker_task.is_alive()
        )
    
    def start_worker(self) -> bool:
        """Start the task worker if not already running. Returns True if started, False if already running."""
        if self._worker_task is not None and self._worker_task.is_alive():
            return False  # Already running
        
        self._worker_task = threading.Thread(target=lambda: asyncio.run(task_worker()))
        self._worker_task.start()
        return True

    def get_current_state(self) -> TaskStateMessage:
        return TaskStateMessage(
            history=self.get_history(),
            running_queue=self.get_current_queue()[0],
            pending_queue=self.get_current_queue()[1],
            installed_packs=core.get_installed_node_packs(),
        )

    @staticmethod
    def send_queue_state_update(
        msg: str, update: MessageUpdate, client_id: Optional[str] = None
    ) -> None:
        """Send queue state update to clients.

        Args:
            msg: Message type/event name
            update: Update data to send
            client_id: Optional client ID. If None, broadcasts to all clients.
                      If provided, sends only to that specific client.
        """
        PromptServer.instance.send_sync(msg, update.model_dump(mode='json'), client_id)

    def put(self, item) -> None:
        """Add a task to the queue. Item can be a dict or QueueTaskItem model."""
        with self.mutex:
            # Start a new batch if this is the first task after queue was empty
            if (
                self.batch_id is None
                and len(self.pending_tasks) == 0
                and len(self.running_tasks) == 0
            ):
                self._start_new_batch()

            # Convert to Pydantic model if it's a dict
            if isinstance(item, dict):
                item = QueueTaskItem(**item)

            heapq.heappush(self.pending_tasks, item)
            self.not_empty.notify()

    def _start_new_batch(self) -> None:
        """Start a new batch session for tracking operations."""
        self.batch_id = (
            f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        )
        self.batch_start_time = datetime.now().isoformat()
        self.batch_state_before = self._capture_system_state()
        logging.debug("[ComfyUI-Manager] Started new batch: %s", self.batch_id)

    def get(
        self, timeout: Optional[float] = None
    ) -> tuple[Optional[QueueTaskItem], int]:
        with self.not_empty:
            while len(self.pending_tasks) == 0:
                self.not_empty.wait(timeout=timeout)
                if timeout is not None and len(self.pending_tasks) == 0:
                    return None
            item = heapq.heappop(self.pending_tasks)
            task_index = self.task_counter
            self.running_tasks[task_index] = copy.deepcopy(item)
            self.task_counter += 1
            TaskQueue.send_queue_state_update(
                ManagerMessageName.cm_task_started.value,
                MessageTaskStarted(
                    ui_id=item.ui_id,
                    kind=item.kind,
                    timestamp=datetime.now(),
                    state=self.get_current_state(),
                ),
                client_id=item.client_id,  # Send task started only to the client that requested it
            )
            return item, task_index

    async def task_done(
        self,
        item: QueueTaskItem,
        task_index: int,
        result_msg: str,
        status: Optional[TaskExecutionStatus] = None,
    ) -> None:
        """Mark task as completed and add to history"""

        with self.mutex:
            timestamp = datetime.now().isoformat()

            # Remove task from running_tasks using the task_index
            self.running_tasks.pop(task_index, None)

            # Manage history size
            if len(self.history_tasks) > MAXIMUM_HISTORY_SIZE:
                self.history_tasks.pop(next(iter(self.history_tasks)))


            # Update history
            self.history_tasks[item.ui_id] = TaskHistoryItem(
                ui_id=item.ui_id,
                client_id=item.client_id,
                timestamp=datetime.fromisoformat(timestamp),
                result=result_msg,
                kind=item.kind,
                status=status,
            )

        # Force cache refresh for successful pack-modifying operations
        pack_modifying_tasks = {"install", "uninstall", "enable", "disable"}
        if (item.kind in pack_modifying_tasks and 
            status and status.status_str == "success"):
            try:
                # Force unified_manager to refresh its installed packages cache
                await core.unified_manager.reload("cache", dont_wait=True, update_cnr_map=False)
            except Exception as e:
                logging.warning(f"[ComfyUI-Manager] Failed to refresh cache after {item.kind}: {e}")

        # Send WebSocket message indicating task is complete
        TaskQueue.send_queue_state_update(
            ManagerMessageName.cm_task_completed.value,
            MessageTaskDone(
                ui_id=item.ui_id,
                result=result_msg,
                kind=item.kind,
                status=status,
                timestamp=datetime.fromisoformat(timestamp),
                state=self.get_current_state(),
            ),
            client_id=item.client_id,  # Send completion only to the client that requested it
        )

    def get_current_queue(self) -> tuple[list[QueueTaskItem], list[QueueTaskItem]]:
        """Get current running and remaining tasks"""
        with self.mutex:
            running = list(self.running_tasks.values())
            remaining = copy.copy(self.pending_tasks)
            return running, remaining

    def get_tasks_remaining(self) -> int:
        """Get number of tasks remaining"""
        with self.mutex:
            return len(self.pending_tasks) + len(self.running_tasks)

    def wipe_queue(self) -> None:
        """Clear all task queue"""
        with self.mutex:
            self.pending_tasks = []

    def abort(self) -> None:
        """Abort current operations"""
        with self.mutex:
            self.pending_tasks = []
            self.running_tasks = {}

    def delete_history_item(self, ui_id: str) -> None:
        """Delete specific task from history"""
        with self.mutex:
            self.history_tasks.pop(ui_id, None)

    def get_history(
        self,
        ui_id: Optional[str] = None,
        max_items: Optional[int] = None,
        offset: int = -1,
    ) -> dict[str, TaskHistoryItem]:
        """Get task history. If ui_id (task id) is passsed, only return that task's history item entry."""
        with self.mutex:
            if ui_id is None:
                out = {}
                i = 0
                if offset < 0 and max_items is not None:
                    offset = len(self.history_tasks) - max_items
                for k in self.history_tasks:
                    if i >= offset:
                        out[k] = self.history_tasks[k]
                        if max_items is not None and len(out) >= max_items:
                            break
                    i += 1
                return out
            elif ui_id in self.history_tasks:
                return self.history_tasks[ui_id]
            else:
                return {}

    def done_count(self) -> int:
        """Get the number of completed tasks in history.

        Returns:
            int: Number of tasks that have been completed and are stored in history.
                 Returns 0 if history_tasks is None (defensive programming).
        """
        return len(self.history_tasks) if self.history_tasks is not None else 0

    def total_count(self) -> int:
        """Get the total number of tasks currently in the system (pending + running).

        Returns:
            int: Combined count of pending and running tasks.
                 Returns 0 if either collection is None (defensive programming).
        """
        return (
            len(self.pending_tasks) + len(self.running_tasks)
            if self.pending_tasks is not None and self.running_tasks is not None
            else 0
        )

    def finalize(self) -> None:
        """Finalize a completed task batch by saving execution history to disk.

        This method is intended to be called when the queue transitions from having
        tasks to being completely empty (no pending or running tasks). It will create
        a comprehensive snapshot of the ComfyUI state and all operations performed.
        """
        if self.batch_id is not None:
            batch_path = os.path.join(
                context.manager_batch_history_path, self.batch_id + ".json"
            )

            try:
                end_time = datetime.now().isoformat()
                state_after = self._capture_system_state()
                operations = self._extract_batch_operations()

                batch_record = BatchExecutionRecord(
                    batch_id=self.batch_id,
                    start_time=self.batch_start_time,
                    end_time=end_time,
                    state_before=self.batch_state_before,
                    state_after=state_after,
                    operations=operations,
                    total_operations=len(operations),
                    successful_operations=len(
                        [op for op in operations if op.result == "success"]
                    ),
                    failed_operations=len(
                        [op for op in operations if op.result == "failed"]
                    ),
                    skipped_operations=len(
                        [op for op in operations if op.result == "skipped"]
                    ),
                )

                # Save to disk
                with open(batch_path, "w", encoding="utf-8") as json_file:
                    json.dump(
                        batch_record.model_dump(), json_file, indent=4, default=str
                    )

                logging.debug(f"[ComfyUI-Manager] Batch history saved: {batch_path}")

                # Reset batch tracking
                self.batch_id = None
                self.batch_start_time = None
                self.batch_state_before = None

            except Exception as e:
                logging.error(f"[ComfyUI-Manager] Failed to save batch history: {e}")

    def _capture_system_state(self) -> ComfyUISystemState:
        """Capture current ComfyUI system state for batch record."""
        return ComfyUISystemState(
            snapshot_time=datetime.now().isoformat(),
            comfyui_version=self._get_comfyui_version_info(),
            python_version=platform.python_version(),
            platform_info=f"{platform.system()} {platform.release()} ({platform.machine()})",
            installed_nodes=self._get_installed_nodes(),
        )

    def _get_comfyui_version_info(self) -> ComfyUIVersionInfo:
        """Get ComfyUI version information."""
        try:
            version_info = core.get_comfyui_versions()
            current_version = version_info[1] if len(version_info) > 1 else "unknown"
            return ComfyUIVersionInfo(version=current_version)
        except Exception:
            return ComfyUIVersionInfo(version="unknown")

    def _get_installed_nodes(self) -> dict[str, InstalledNodeInfo]:
        """Get information about installed node packages."""
        installed_nodes = {}

        try:
            node_packs = core.get_installed_node_packs()
            for pack_name, pack_info in node_packs.items():
                installed_nodes[pack_name] = InstalledNodeInfo(
                    name=pack_name,
                    version=pack_info.get("ver", "unknown"),
                    install_method="unknown",
                    enabled=pack_info.get("enabled", True),
                )
        except Exception as e:
            logging.warning(f"[ComfyUI-Manager] Failed to get installed nodes: {e}")

        return installed_nodes

    def _extract_batch_operations(self) -> list[BatchOperation]:
        """Extract operations from completed task history for this batch."""
        operations = []

        try:
            for ui_id, task in self.history_tasks.items():
                result_status = "success"
                if task.status:
                    status_str = task.status.get("status_str", "success")
                    if status_str == "error":
                        result_status = "failed"
                    elif status_str == "skip":
                        result_status = "skipped"

                operation = BatchOperation(
                    operation_id=ui_id,
                    operation_type=task.kind,
                    target=f"task_{ui_id}",
                    result=result_status,
                    start_time=task.timestamp,
                    client_id=task.client_id,
                )
                operations.append(operation)
        except Exception as e:
            logging.warning(
                f"[ComfyUI-Manager] Failed to extract batch operations: {e}"
            )

        return operations


task_queue = TaskQueue()

# Preview method initialization
if args.preview_method == latent_preview.LatentPreviewMethod.NoPreviews:
    environment_utils.set_preview_method(core.get_config()['preview_method'])
else:
    logging.warning("[ComfyUI-Manager] Since --preview-method is set, ComfyUI-Manager's preview method feature will be ignored.")


# Note: Model path utilities moved to model_utils.py to avoid duplication


async def task_worker():
    await core.unified_manager.reload("cache")

    async def do_install(params: InstallPackParams) -> str:
        node_id = params.id
        node_version = params.selected_version
        channel = params.channel
        mode = params.mode
        skip_post_install = params.skip_post_install

        try:
            node_spec = core.unified_manager.resolve_node_spec(
                f"{node_id}@{node_version}"
            )
            if node_spec is None:
                logging.error(
                    f"Cannot resolve install target: '{node_id}@{node_version}'"
                )
                return f"Cannot resolve install target: '{node_id}@{node_version}'"

            node_name, version_spec, is_specified = node_spec
            res = await core.unified_manager.install_by_id(
                node_name,
                version_spec,
                channel,
                mode,
                return_postinstall=skip_post_install,
            )  # discard post install if skip_post_install mode

            if res.action not in [
                "skip",
                "enable",
                "install-git",
                "install-cnr",
                "switch-cnr",
            ]:
                logging.error(f"[ComfyUI-Manager] Installation failed:\n{res.msg}")
                return res.msg

            elif not res.result:
                logging.error(f"[ComfyUI-Manager] Installation failed:\n{res.msg}")
                return res.msg

            return "success"
        except Exception:
            traceback.print_exc()
            return "Installation failed"

    async def do_enable(params: EnablePackParams) -> str:
        cnr_id = params.cnr_id
        core.unified_manager.unified_enable(cnr_id)
        return "success"

    async def do_update(params: UpdatePackParams) -> str:
        node_name = params.node_name
        node_ver = params.node_ver

        try:
            res = core.unified_manager.unified_update(node_name, node_ver)

            if res.ver == "unknown":
                url = core.unified_manager.unknown_active_nodes[node_name][0]
                try:
                    title = os.path.basename(url)
                except Exception:
                    title = node_name
            else:
                url = core.unified_manager.cnr_map[node_name].get("repository")
                title = core.unified_manager.cnr_map[node_name]["name"]

            manager_util.clear_pip_cache()

            if url is not None:
                base_res = {"url": url, "title": title}
            else:
                base_res = {"title": title}

            if res.result:
                if res.action == "skip":
                    base_res["msg"] = "skip"
                    return base_res
                else:
                    base_res["msg"] = "success"
                    return base_res

            base_res["msg"] = f"An error occurred while updating '{node_name}'."
            logging.error(
                f"\nERROR: An error occurred while updating '{node_name}'. (res.result={res.result}, res.action={res.action})"
            )
            return base_res
        except Exception:
            traceback.print_exc()

        return {"msg": f"An error occurred while updating '{node_name}'."}

    async def do_update_comfyui(params: UpdateComfyUIParams) -> str:
        try:
            repo_path = os.path.dirname(folder_paths.__file__)
            
            # Check if this is a version switch operation
            if params.target_version:
                # Switch to specific version
                logging.info(f"Switching ComfyUI to version: {params.target_version}")
                core.switch_comfyui(params.target_version)
                return f"success-switched-{params.target_version}"
            else:
                # Regular update operation
                is_stable = params.is_stable if params.is_stable is not None else True
                latest_tag = None
                if is_stable:
                    res, latest_tag = core.update_to_stable_comfyui(repo_path)
                else:
                    res = core.update_path(repo_path)

                if res == "fail":
                    logging.error("ComfyUI update failed")
                    return "fail"
                elif res == "updated":
                    if is_stable:
                        logging.info("ComfyUI is updated to latest stable version.")
                        return "success-stable-" + latest_tag
                    else:
                        logging.info("ComfyUI is updated to latest nightly version.")
                        return "success-nightly"
                else:  # skipped
                    logging.info("ComfyUI is up-to-date.")
                    return "skip"

        except Exception:
            traceback.print_exc()

        return "An error occurred while updating 'comfyui'."

    async def do_fix(params: FixPackParams) -> str:
        node_name = params.node_name
        node_ver = params.node_ver

        try:
            res = core.unified_manager.unified_fix(node_name, node_ver)

            if res.result:
                return "success"
            else:
                logging.error(res.msg)

            logging.error(
                f"\nERROR: An error occurred while fixing '{node_name}@{node_ver}'."
            )
        except Exception:
            traceback.print_exc()

        return f"An error occurred while fixing '{node_name}@{node_ver}'."

    async def do_uninstall(params: UninstallPackParams) -> str:
        node_name = params.node_name
        is_unknown = params.is_unknown

        try:
            res = core.unified_manager.unified_uninstall(node_name, is_unknown)

            if res.result:
                return "success"

            logging.error(
                f"\nERROR: An error occurred while uninstalling '{node_name}'."
            )
        except Exception:
            traceback.print_exc()

        return f"An error occurred while uninstalling '{node_name}'."

    async def do_disable(params: DisablePackParams) -> str:
        node_name = params.node_name
        try:
            res = core.unified_manager.unified_disable(
                node_name, params.is_unknown
            )

            if res:
                return "success"

        except Exception:
            traceback.print_exc()

        return f"Failed to disable: '{node_name}'"

    async def do_install_model(params: ModelMetadata) -> str:
        json_data = params.model_dump()

        model_path = model_utils.get_model_path(json_data)
        model_url = json_data.get("url")

        res = False

        try:
            if model_path is not None:
                logging.info(
                    f"Install model '{json_data['name']}' from '{model_url}' into '{model_path}'"
                )

                if json_data["filename"] == "<huggingface>":
                    if os.path.exists(
                        os.path.join(model_path, os.path.dirname(json_data["url"]))
                    ):
                        logging.error(
                            f"[ComfyUI-Manager] the model path already exists: {model_path}"
                        )
                        return f"The model path already exists: {model_path}"

                    logging.info(
                        f"[ComfyUI-Manager] Downloading '{model_url}' into '{model_path}'"
                    )
                    manager_downloader.download_repo_in_bytes(
                        repo_id=model_url, local_dir=model_path
                    )

                    return "success"

                elif not core.get_config()["model_download_by_agent"] and (
                    model_url.startswith("https://github.com")
                    or model_url.startswith("https://huggingface.co")
                    or model_url.startswith("https://heibox.uni-heidelberg.de")
                ):
                    model_dir = model_utils.get_model_dir(json_data, True)
                    download_url(model_url, model_dir, filename=json_data["filename"])
                    if model_path.endswith(".zip"):
                        res = core.unzip(model_path)
                    else:
                        res = True

                    if res:
                        return "success"
                else:
                    res = download_url_with_agent(model_url, model_path)
                    if res and model_path.endswith(".zip"):
                        res = core.unzip(model_path)
            else:
                logging.error(
                    f"[ComfyUI-Manager] Model installation error: invalid model type - {json_data['type']}"
                )

            if res:
                return "success"

        except Exception as e:
            logging.error(f"[ComfyUI-Manager] ERROR: {e}", file=sys.stderr)

        return f"Model installation error: {model_url}"


    async def do_update_all(params: UpdateAllPacksParams):
        # For update-all tasks, we need client info from the original task
        # This should not be called anymore since update_all now creates individual tasks
        return "error: update_all should create individual tasks, not use task worker"

    while True:
        timeout = 4096
        task = task_queue.get(timeout)
        if task is None:
            # Check if queue is truly empty (no pending or running tasks)
            if task_queue.total_count() == 0 and len(task_queue.running_tasks) == 0:
                logging.debug("\n[ComfyUI-Manager] All tasks are completed.")

                # Trigger batch history serialization if there are completed tasks
                if task_queue.done_count() > 0:
                    logging.debug("[ComfyUI-Manager] Finalizing batch history...")
                    task_queue.finalize()
                    logging.debug("[ComfyUI-Manager] Batch history saved.")

                logging.info("\nAfter restarting ComfyUI, please refresh the browser.")

                res = {"status": "all-done"}

                # Broadcast general status updates to all clients
                PromptServer.instance.send_sync("cm-queue-status", res)

            return

        item, task_index = task
        kind = item.kind

        logging.debug(f"Processing task: {kind} with item: {item} at index: {task_index}")

        try:
            if kind == "install":
                msg = await do_install(item.params)
            elif kind == "enable":
                msg = await do_enable(item.params)
            elif kind == "install-model":
                msg = await do_install_model(item.params)
            elif kind == "update":
                msg = await do_update(item.params)
            elif kind == "update-main":
                msg = await do_update(item.params)
            elif kind == "update-comfyui":
                msg = await do_update_comfyui(item.params)
            elif kind == "fix":
                msg = await do_fix(item.params)
            elif kind == "uninstall":
                msg = await do_uninstall(item.params)
            elif kind == "disable":
                msg = await do_disable(item.params)
            else:
                msg = "Unexpected kind: " + kind
        except Exception:
            msg = f"Exception: {(kind, item)}"
            await task_queue.task_done(
                item, task_index, msg, TaskExecutionStatus(status_str="error", completed=True, messages=[msg])
            )
            return

        # Determine status and message for task completion
        if isinstance(msg, dict) and "msg" in msg:
            result_msg = msg["msg"]
        else:
            result_msg = msg

        # Determine status
        if result_msg == "success":
            status = TaskExecutionStatus(status_str="success", completed=True, messages=[])
        elif result_msg == "skip":
            status = TaskExecutionStatus(status_str="skip", completed=True, messages=[])
        else:
            status = TaskExecutionStatus(status_str="error", completed=True, messages=[result_msg])

        await task_queue.task_done(item, task_index, result_msg, status)


@routes.post("/v2/manager/queue/task")
async def queue_task(request) -> web.Response:
    """Add a new task to the processing queue.

    Accepts task data via JSON POST and adds it to the TaskQueue for processing.
    The task worker will automatically pick up and process queued tasks.

    Args:
        request: aiohttp request containing JSON task data

    Returns:
        web.Response: HTTP 200 on successful queueing, HTTP 400 on validation error
    """
    try:
        json_data = await request.json()
        # Validate input using Pydantic model
        task_item = QueueTaskItem.model_validate(json_data)
        TaskQueue.instance.put(task_item)
        # maybe start worker
        return web.Response(status=200)
    except ValidationError as e:
        logging.error(f"[ComfyUI-Manager] Invalid task data: {e}")
        return web.Response(status=400, text=f"Invalid task data: {e}")
    except Exception as e:
        logging.error(f"[ComfyUI-Manager] Error processing task: {e}")
        return web.Response(status=500, text="Internal server error")


@routes.get("/v2/manager/queue/history_list")
async def get_history_list(request) -> web.Response:
    """Get list of available batch history files.

    Returns a list of batch history IDs sorted by modification time (newest first).
    These IDs can be used with the history endpoint to retrieve detailed batch information.

    Returns:
        web.Response: JSON response with 'ids' array of history file IDs
    """
    history_path = context.manager_batch_history_path

    try:
        files = [
            os.path.join(history_path, f)
            for f in os.listdir(history_path)
            if os.path.isfile(os.path.join(history_path, f))
        ]
        files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        history_ids = [os.path.basename(f)[:-5] for f in files]

        return web.json_response(
            {"ids": list(history_ids)}, content_type="application/json"
        )
    except Exception as e:
        logging.error(f"[ComfyUI-Manager] /v2/manager/queue/history_list - {e}")
        return web.Response(status=400)


@routes.get("/v2/manager/queue/history")
async def get_history(request):
    """Get task history with optional client filtering.

    Query parameters:
        id: Batch history ID (for file-based history)
        client_id: Optional client ID to filter current session history
        ui_id: Optional specific task ID to get single task history
        max_items: Maximum number of items to return
        offset: Offset for pagination

    Returns:
        JSON with filtered history data
    """
    try:
        # Handle file-based batch history
        if "id" in request.rel_url.query:
            json_name = request.rel_url.query["id"] + ".json"
            batch_path = os.path.join(context.manager_batch_history_path, json_name)

            with open(batch_path, "r", encoding="utf-8") as file:
                json_str = file.read()
                json_obj = json.loads(json_str)
                return web.json_response(json_obj, content_type="application/json")

        # Handle current session history with optional filtering
        client_id = request.rel_url.query.get("client_id")
        ui_id = request.rel_url.query.get("ui_id")
        max_items = request.rel_url.query.get("max_items")
        offset = request.rel_url.query.get("offset", -1)

        if max_items:
            max_items = int(max_items)
        if offset:
            offset = int(offset)

        # Get history from TaskQueue
        if ui_id:
            history = task_queue.get_history(ui_id=ui_id)
        else:
            history = task_queue.get_history(max_items=max_items, offset=offset)

        # Filter by client_id if provided
        if client_id and isinstance(history, dict):
            filtered_history = {
                task_id: task_data
                for task_id, task_data in history.items()
                if hasattr(task_data, "client_id") and task_data.client_id == client_id
            }
            history = filtered_history

        return web.json_response({"history": history}, content_type="application/json")

    except Exception as e:
        logging.error(f"[ComfyUI-Manager] /v2/manager/queue/history - {e}")

    return web.Response(status=400)


@routes.get("/v2/customnode/getmappings")
async def fetch_customnode_mappings(request):
    """
    provide unified (node -> node pack) mapping list
    """
    mode = request.rel_url.query["mode"]

    nickname_mode = False
    if mode == "nickname":
        mode = "local"
        nickname_mode = True

    json_obj = await core.get_data_by_mode(mode, "extension-node-map.json")
    json_obj = core.map_to_unified_keys(json_obj)

    if nickname_mode:
        json_obj = node_pack_utils.nickname_filter(json_obj)

    all_nodes = set()
    patterns = []
    for k, x in json_obj.items():
        all_nodes.update(set(x[0]))

        if "nodename_pattern" in x[1]:
            patterns.append((x[1]["nodename_pattern"], x[0]))

    missing_nodes = set(nodes.NODE_CLASS_MAPPINGS.keys()) - all_nodes

    for x in missing_nodes:
        for pat, item in patterns:
            if re.match(pat, x):
                item.append(x)

    return web.json_response(json_obj, content_type="application/json")


@routes.get("/v2/customnode/fetch_updates")
async def fetch_updates(request):
    """
    DEPRECATED: This endpoint is no longer supported.
    
    Repository fetching has been removed from the API.
    Updates should be performed through the queue system using update operations.
    """
    return web.json_response(
        {
            "error": "This endpoint has been deprecated",
            "message": "Repository fetching is no longer supported. Please use the update operations through the queue system.",
            "deprecated": True
        },
        status=410  # 410 Gone
    )


@routes.get("/v2/manager/queue/update_all")
async def update_all(request: web.Request) -> web.Response:
    # Validate required query parameters
    validation_error = validate_required_params(request, ["client_id", "ui_id"])
    if validation_error:
        return validation_error
    
    json_data = dict(request.rel_url.query)
    return await _update_all(json_data)


async def _update_all(json_data: Dict[str, Any]) -> web.Response:
    if not security_utils.is_allowed_security_level("middle"):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    # Extract client info
    base_ui_id = json_data["ui_id"]
    client_id = json_data["client_id"]
    mode = json_data.get("mode", "remote")

    if mode == "local":
        channel = "local"
    else:
        channel = core.get_config()["channel_url"]

    await core.unified_manager.reload(mode)
    await core.unified_manager.get_custom_nodes(channel, mode)

    for k, v in core.unified_manager.active_nodes.items():
        if k == "comfyui-manager":
            # skip updating comfyui-manager if desktop version
            if os.environ.get("__COMFYUI_DESKTOP_VERSION__"):
                continue

        update_task = QueueTaskItem(
            kind="update", 
            ui_id=f"{base_ui_id}_{k}",  # Use client's base ui_id + node name
            client_id=client_id,
            params=UpdatePackParams(node_name=k, node_ver=v[0])
        )
        task_queue.put(update_task)

    for k, v in core.unified_manager.unknown_active_nodes.items():
        if k == "comfyui-manager":
            # skip updating comfyui-manager if desktop version
            if os.environ.get("__COMFYUI_DESKTOP_VERSION__"):
                continue

        update_task = QueueTaskItem(
            kind="update", 
            ui_id=f"{base_ui_id}_{k}",  # Use client's base ui_id + node name
            client_id=client_id,
            params=UpdatePackParams(node_name=k, node_ver="unknown")
        )
        task_queue.put(update_task)

    return web.Response(status=200)


@routes.get("/v2/manager/is_legacy_manager_ui")
async def is_legacy_manager_ui(request):
    return web.json_response(
        {"is_legacy_manager_ui": args.enable_manager_legacy_ui},
        content_type="application/json",
        status=200,
    )


# freeze imported version
startup_time_installed_node_packs = core.get_installed_node_packs()


@routes.get("/v2/customnode/installed")
async def installed_list(request):
    mode = request.query.get("mode", "default")

    if mode == "imported":
        res = startup_time_installed_node_packs
    else:
        res = core.get_installed_node_packs()

    return web.json_response(res, content_type="application/json")


def check_model_installed(json_obj):
    def is_exists(model_dir_name, filename, url):
        if filename == "<huggingface>":
            filename = os.path.basename(url)

        dirs = folder_paths.get_folder_paths(model_dir_name)

        for x in dirs:
            if os.path.exists(os.path.join(x, filename)):
                return True

        return False

    model_dir_names = [
        "checkpoints",
        "loras",
        "vae",
        "text_encoders",
        "diffusion_models",
        "clip_vision",
        "embeddings",
        "diffusers",
        "vae_approx",
        "controlnet",
        "gligen",
        "upscale_models",
        "hypernetworks",
        "photomaker",
        "classifiers",
    ]

    total_models_files = set()
    for x in model_dir_names:
        for y in folder_paths.get_filename_list(x):
            total_models_files.add(y)

    def process_model_phase(item):
        if (
            "diffusion" not in item["filename"]
            and "pytorch" not in item["filename"]
            and "model" not in item["filename"]
        ):
            # non-general name case
            if item["filename"] in total_models_files:
                item["installed"] = "True"
                return

        if item["save_path"] == "default":
            model_dir_name = model_dir_name_map.get(item["type"].lower())
            if model_dir_name is not None:
                item["installed"] = str(
                    is_exists(model_dir_name, item["filename"], item["url"])
                )
            else:
                item["installed"] = "False"
        else:
            model_dir_name = item["save_path"].split("/")[0]
            if model_dir_name in folder_paths.folder_names_and_paths:
                if is_exists(model_dir_name, item["filename"], item["url"]):
                    item["installed"] = "True"

            if "installed" not in item:
                if item["filename"] == "<huggingface>":
                    filename = os.path.basename(item["url"])
                else:
                    filename = item["filename"]

                fullpath = os.path.join(
                    folder_paths.models_dir, item["save_path"], filename
                )

                item["installed"] = "True" if os.path.exists(fullpath) else "False"

    with concurrent.futures.ThreadPoolExecutor(8) as executor:
        for item in json_obj["models"]:
            executor.submit(process_model_phase, item)


@routes.get("/v2/snapshot/getlist")
async def get_snapshot_list(request):
    items = [
        f[:-5] for f in os.listdir(context.manager_snapshot_path) if f.endswith(".json")
    ]
    items.sort(reverse=True)
    return web.json_response({"items": items}, content_type="application/json")


@routes.get("/v2/snapshot/remove")
async def remove_snapshot(request):
    if not security_utils.is_allowed_security_level("middle"):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    try:
        target = request.rel_url.query["target"]

        path = os.path.join(context.manager_snapshot_path, f"{target}.json")
        if os.path.exists(path):
            os.remove(path)

        return web.Response(status=200)
    except Exception:
        return web.Response(status=400)


@routes.get("/v2/snapshot/restore")
async def restore_snapshot(request):
    if not security_utils.is_allowed_security_level("middle"):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    try:
        target = request.rel_url.query["target"]

        path = os.path.join(context.manager_snapshot_path, f"{target}.json")
        if os.path.exists(path):
            if not os.path.exists(context.manager_startup_script_path):
                os.makedirs(context.manager_startup_script_path)

            target_path = os.path.join(
                context.manager_startup_script_path, "restore-snapshot.json"
            )
            shutil.copy(path, target_path)

            logging.info(f"Snapshot restore scheduled: `{target}`")
            return web.Response(status=200)

        logging.error(f"Snapshot file not found: `{path}`")
        return web.Response(status=400)
    except Exception:
        return web.Response(status=400)


@routes.get("/v2/snapshot/get_current")
async def get_current_snapshot_api(request):
    try:
        return web.json_response(
            await core.get_current_snapshot(), content_type="application/json"
        )
    except Exception:
        return web.Response(status=400)


@routes.get("/v2/snapshot/save")
async def save_snapshot(request):
    try:
        await core.save_snapshot_with_postfix("snapshot")
        return web.Response(status=200)
    except Exception:
        return web.Response(status=400)


def unzip_install(files):
    temp_filename = "manager-temp.zip"
    for url in files:
        if url.endswith("/"):
            url = url[:-1]
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
            }

            req = urllib.request.Request(url, headers=headers)
            response = urllib.request.urlopen(req)
            data = response.read()

            with open(temp_filename, "wb") as f:
                f.write(data)

            with zipfile.ZipFile(temp_filename, "r") as zip_ref:
                zip_ref.extractall(core.get_default_custom_nodes_path())

            os.remove(temp_filename)
        except Exception as e:
            logging.error(f"Install(unzip) error: {url} / {e}", file=sys.stderr)
            return False

    logging.info("Installation was successful.")
    return True


@routes.post("/v2/customnode/import_fail_info")
async def import_fail_info(request):
    try:
        json_data = await request.json()

        # Basic validation - ensure we have either cnr_id or url
        if not isinstance(json_data, dict):
            return web.Response(status=400, text="Request body must be a JSON object")

        if "cnr_id" not in json_data and "url" not in json_data:
            return web.Response(
                status=400, text="Either 'cnr_id' or 'url' field is required"
            )

        if "cnr_id" in json_data:
            if not isinstance(json_data["cnr_id"], str):
                return web.Response(status=400, text="'cnr_id' must be a string")
            module_name = core.unified_manager.get_module_name(json_data["cnr_id"])
        else:
            if not isinstance(json_data["url"], str):
                return web.Response(status=400, text="'url' must be a string")
            module_name = core.unified_manager.get_module_name(json_data["url"])

        if module_name is not None:
            info = cm_global.error_dict.get(module_name)
            if info is not None:
                return web.json_response(info)

        return web.Response(status=400)
    except Exception as e:
        logging.error(f"[ComfyUI-Manager] Error processing import fail info: {e}")
        return web.Response(status=500, text="Internal server error")



@routes.get("/v2/manager/queue/reset")
async def reset_queue(request):
    task_queue.wipe_queue()
    return web.Response(status=200)




@routes.get("/v2/manager/queue/status")
async def queue_count(request):
    """Get current queue status with optional client filtering.

    Query parameters:
        client_id: Optional client ID to filter tasks

    Returns:
        JSON with queue counts and processing status
    """
    client_id = request.query.get("client_id")

    if client_id:
        # Filter tasks by client_id
        running_client_tasks = [
            task
            for task in task_queue.running_tasks.values()
            if task.client_id == client_id
        ]
        pending_client_tasks = [
            task
            for task in task_queue.pending_tasks
            if task.client_id == client_id
        ]
        history_client_tasks = {
            ui_id: task
            for ui_id, task in task_queue.history_tasks.items()
            if hasattr(task, "client_id") and task.client_id == client_id
        }

        return web.json_response(
            {
                "client_id": client_id,
                "total_count": len(pending_client_tasks) + len(running_client_tasks),
                "done_count": len(history_client_tasks),
                "in_progress_count": len(running_client_tasks),
                "pending_count": len(pending_client_tasks),
                "is_processing": len(running_client_tasks) > 0,
            }
        )
    else:
        # Return overall status
        return web.json_response(
            {
                "total_count": task_queue.total_count(),
                "done_count": task_queue.done_count(),
                "in_progress_count": len(task_queue.running_tasks),
                "pending_count": len(task_queue.pending_tasks),
                "is_processing": task_queue.is_processing(),
            }
        )




@routes.get("/v2/manager/queue/start")
async def queue_start(request):
    # finalize_temp_queue_batch()
    started = task_queue.start_worker()
    
    if started:
        return web.Response(status=200)  # Started successfully
    else:
        return web.Response(status=201)  # Already in-progress


@routes.get("/v2/manager/queue/update_comfyui")
async def update_comfyui(request):
    """Queue a ComfyUI update based on the configured update policy."""
    # Validate required query parameters
    validation_error = validate_required_params(request, ["client_id", "ui_id"])
    if validation_error:
        return validation_error
    
    is_stable = core.get_config()["update_policy"] != "nightly-comfyui"
    client_id = request.rel_url.query["client_id"]
    ui_id = request.rel_url.query["ui_id"]
    
    # Create update-comfyui task
    task = QueueTaskItem(
        ui_id=ui_id,
        client_id=client_id,
        kind="update-comfyui",
        params=UpdateComfyUIParams(is_stable=is_stable)
    )
    
    task_queue.put(task)
    return web.Response(status=200)


@routes.get("/v2/comfyui_manager/comfyui_versions")
async def comfyui_versions(request):
    try:
        res, current, latest = core.get_comfyui_versions()
        return web.json_response(
            {"versions": res, "current": current},
            status=200,
            content_type="application/json",
        )
    except Exception as e:
        logging.error(f"ComfyUI update fail: {e}", file=sys.stderr)

    return web.Response(status=400)


@routes.get("/v2/comfyui_manager/comfyui_switch_version")
async def comfyui_switch_version(request):
    try:
        # Validate required query parameters
        validation_error = validate_required_params(request, ["ver", "client_id", "ui_id"])
        if validation_error:
            return validation_error
            
        target_version = request.rel_url.query["ver"]
        client_id = request.rel_url.query["client_id"]
        ui_id = request.rel_url.query["ui_id"]
        
        # Create update-comfyui task with target version
        task = QueueTaskItem(
            ui_id=ui_id,
            client_id=client_id,
            kind="update-comfyui",
            params=UpdateComfyUIParams(target_version=target_version)
        )
        
        task_queue.put(task)
        return web.Response(status=200)
    except Exception as e:
        logging.error(f"ComfyUI version switch fail: {e}", file=sys.stderr)
        return web.Response(status=400)


async def check_whitelist_for_model(item):
    json_obj = await core.get_data_by_mode("cache", "model-list.json")

    for x in json_obj.get("models", []):
        if (
            x["save_path"] == item["save_path"]
            and x["base"] == item["base"]
            and x["filename"] == item["filename"]
        ):
            return True

    json_obj = await core.get_data_by_mode("local", "model-list.json")

    for x in json_obj.get("models", []):
        if (
            x["save_path"] == item["save_path"]
            and x["base"] == item["base"]
            and x["filename"] == item["filename"]
        ):
            return True

    return False


@routes.post("/v2/manager/queue/install_model")
async def install_model(request):
    try:
        json_data = await request.json()
        
        # Validate required fields
        if 'client_id' not in json_data:
            return web.Response(status=400, text="Missing required field: client_id")
        if 'ui_id' not in json_data:
            return web.Response(status=400, text="Missing required field: ui_id")
            
        # Validate model metadata
        model_data = ModelMetadata.model_validate(json_data)
        
        # Create install-model task with client-provided IDs
        task = QueueTaskItem(
            ui_id=json_data['ui_id'],
            client_id=json_data['client_id'],
            kind="install-model",
            params=model_data
        )
        
        task_queue.put(task)
        return web.Response(status=200)
    except ValidationError as e:
        logging.error(f"[ComfyUI-Manager] Invalid model data: {e}")
        return web.Response(status=400, text=f"Invalid model data: {e}")
    except Exception as e:
        logging.error(f"[ComfyUI-Manager] Error processing model install: {e}")
        return web.Response(status=500, text="Internal server error")


@routes.get("/v2/manager/db_mode")
async def db_mode(request):
    if "value" in request.rel_url.query:
        environment_utils.set_db_mode(request.rel_url.query["value"])
        core.write_config()
    else:
        return web.Response(text=core.get_config()["db_mode"], status=200)

    return web.Response(status=200)


@routes.get("/v2/manager/policy/update")
async def update_policy(request):
    if "value" in request.rel_url.query:
        environment_utils.set_update_policy(request.rel_url.query["value"])
        core.write_config()
    else:
        return web.Response(text=core.get_config()["update_policy"], status=200)

    return web.Response(status=200)


@routes.get("/v2/manager/channel_url_list")
async def channel_url_list(request):
    channels = core.get_channel_dict()
    if "value" in request.rel_url.query:
        channel_url = channels.get(request.rel_url.query["value"])
        if channel_url is not None:
            core.get_config()["channel_url"] = channel_url
            core.write_config()
    else:
        selected = "custom"
        selected_url = core.get_config()["channel_url"]

        for name, url in channels.items():
            if url == selected_url:
                selected = name
                break

        res = {"selected": selected, "list": core.get_channel_list()}
        return web.json_response(res, status=200)

    return web.Response(status=200)


@routes.get("/v2/manager/reboot")
def restart(self):
    if not security_utils.is_allowed_security_level("middle"):
        logging.error(SECURITY_MESSAGE_MIDDLE_OR_BELOW)
        return web.Response(status=403)

    try:
        sys.stdout.close_log()
    except Exception:
        pass

    if "__COMFY_CLI_SESSION__" in os.environ:
        with open(os.path.join(os.environ["__COMFY_CLI_SESSION__"] + ".reboot"), "w"):
            pass

        print(
            "\nRestarting...\n\n"
        )  # This printing should not be logging - that will be ugly
        exit(0)

    print(
        "\nRestarting... [Legacy Mode]\n\n"
    )  # This printing should not be logging - that will be ugly

    sys_argv = sys.argv.copy()
    if "--windows-standalone-build" in sys_argv:
        sys_argv.remove("--windows-standalone-build")

    if sys_argv[0].endswith("__main__.py"):  # this is a python module
        module_name = os.path.basename(os.path.dirname(sys_argv[0]))
        cmds = [sys.executable, "-m", module_name] + sys_argv[1:]
    elif sys.platform.startswith("win32"):
        cmds = ['"' + sys.executable + '"', '"' + sys_argv[0] + '"'] + sys_argv[1:]
    else:
        cmds = [sys.executable] + sys_argv

    print(f"Command: {cmds}", flush=True)

    return os.execv(sys.executable, cmds)


@routes.get("/v2/manager/version")
async def get_version(request):
    return web.Response(text=core.version_str, status=200)


async def _confirm_try_install(sender, custom_node_url, msg):
    json_obj = await core.get_data_by_mode("default", "custom-node-list.json")

    sender = manager_util.sanitize_tag(sender)
    msg = manager_util.sanitize_tag(msg)
    target = core.lookup_customnode_by_url(json_obj, custom_node_url)

    if target is not None:
        PromptServer.instance.send_sync(
            "cm-api-try-install-customnode",
            {"sender": sender, "target": target, "msg": msg},
        )
    else:
        logging.error(
            f"[ComfyUI Manager API] Failed to try install - Unknown custom node url '{custom_node_url}'"
        )


def confirm_try_install(sender, custom_node_url, msg):
    asyncio.run(_confirm_try_install(sender, custom_node_url, msg))


cm_global.register_api("cm.try-install-custom-node", confirm_try_install)


async def default_cache_update():
    core.refresh_channel_dict()
    channel_url = core.get_config()["channel_url"]

    async def get_cache(filename):
        try:
            if core.get_config()["default_cache_as_channel_url"]:
                uri = f"{channel_url}/{filename}"
            else:
                uri = f"{core.DEFAULT_CHANNEL}/{filename}"

            cache_uri = str(manager_util.simple_hash(uri)) + "_" + filename
            cache_uri = os.path.join(manager_util.cache_dir, cache_uri)

            json_obj = await manager_util.get_data(uri, True)

            with manager_util.cache_lock:
                with open(cache_uri, "w", encoding="utf-8") as file:
                    json.dump(json_obj, file, indent=4, sort_keys=True)
                    logging.debug(f"[ComfyUI-Manager] default cache updated: {uri}")
        except Exception as e:
            logging.error(
                f"[ComfyUI-Manager] Failed to perform initial fetching '{filename}': {e}"
            )
            traceback.print_exc()

    if (
        core.get_config()["network_mode"] != "offline"
        and not manager_util.is_manager_pip_package()
    ):
        a = get_cache("custom-node-list.json")
        b = get_cache("extension-node-map.json")
        c = get_cache("model-list.json")
        d = get_cache("alter-list.json")
        e = get_cache("github-stats.json")

        await asyncio.gather(a, b, c, d, e)

        if core.get_config()["network_mode"] == "private":
            logging.info(
                "[ComfyUI-Manager] The private comfyregistry is not yet supported in `network_mode=private`."
            )
        else:
            # load at least once
            await core.unified_manager.reload("remote", dont_wait=False)
            await core.unified_manager.get_custom_nodes(channel_url, "remote")
    else:
        await core.unified_manager.reload(
            "remote", dont_wait=False, update_cnr_map=False
        )

    logging.info("[ComfyUI-Manager] All startup tasks have been completed.")


threading.Thread(target=lambda: asyncio.run(default_cache_update())).start()

if not os.path.exists(context.manager_config_path):
    core.get_config()
    core.write_config()


cm_global.register_extension(
    "ComfyUI-Manager",
    {
        "version": core.version,
        "name": "ComfyUI Manager",
        "nodes": {},
        "description": "This extension provides the ability to manage custom nodes in ComfyUI.",
    },
)
