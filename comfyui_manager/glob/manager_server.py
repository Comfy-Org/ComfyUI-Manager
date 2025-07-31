"""
ComfyUI Manager Server

Main server implementation providing REST API endpoints for ComfyUI Manager functionality.
Handles task queue management, custom node operations, model installation, and system configuration.
"""

import asyncio
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
from datetime import datetime, timedelta
from typing import Any, Optional

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
    ImportFailInfoBulkRequest,
    ImportFailInfoBulkResponse,
    BatchOperation,
    InstalledNodeInfo,
    ComfyUIVersionInfo,
    InstallPackParams,
    UpdatePackParams,
    UpdateComfyUIParams,
    FixPackParams,
    UninstallPackParams,
    DisablePackParams,
    EnablePackParams,
    ModelMetadata,
    OperationType,
    OperationResult,
    ManagerDatabaseSource,
    SecurityLevel,
    UpdateAllQueryParams,
    UpdateComfyUIQueryParams,
    ComfyUISwitchVersionQueryParams,
)

from .constants import (
    model_dir_name_map,
    SECURITY_MESSAGE_MIDDLE,
    SECURITY_MESSAGE_MIDDLE_P,
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


def error_response(
    status: int, message: str, error_type: Optional[str] = None
) -> web.Response:
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
        self._cleanup_performed = False

    def is_processing(self) -> bool:
        """Check if the queue is currently processing tasks"""
        return self._worker_task is not None and self._worker_task.is_alive()

    def start_worker(self) -> bool:
        """Start the task worker if not already running. Returns True if started, False if already running."""
        if self._worker_task is not None and self._worker_task.is_alive():
            logging.debug("[ComfyUI-Manager] Worker already running, skipping start")
            return False

        logging.debug("[ComfyUI-Manager] Starting task worker thread")
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
        PromptServer.instance.send_sync(msg, update.model_dump(mode="json"), client_id)

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

            # Use current_index as priority (earlier tasks have lower numbers)
            priority = self.current_index
            self.current_index += 1

            # Push tuple: (priority, task_counter, item)
            # task_counter ensures stable sort for items with same priority
            heapq.heappush(self.pending_tasks, (priority, self.task_counter, item))
            logging.debug(
                "[ComfyUI-Manager] Task added to queue: kind=%s, ui_id=%s, client_id=%s, pending_count=%d",
                item.kind,
                item.ui_id,
                item.client_id,
                len(self.pending_tasks),
            )
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
                    logging.debug("[ComfyUI-Manager] Task queue get timed out")
                    return None
            # Pop tuple and extract the item
            priority, counter, item = heapq.heappop(self.pending_tasks)
            task_index = self.task_counter
            self.running_tasks[task_index] = copy.deepcopy(item)
            self.task_counter += 1
            logging.debug(
                "[ComfyUI-Manager] Task retrieved from queue: kind=%s, ui_id=%s, task_index=%d, running_count=%d, pending_count=%d",
                item.kind,
                item.ui_id,
                task_index,
                len(self.running_tasks),
                len(self.pending_tasks),
            )
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
            now = datetime.now()
            timestamp = now.isoformat()

            # Remove task from running_tasks using the task_index
            self.running_tasks.pop(task_index, None)
            logging.debug(
                "[ComfyUI-Manager] Task completed: kind=%s, ui_id=%s, task_index=%d, status=%s, running_count=%d",
                item.kind,
                item.ui_id,
                task_index,
                status.status_str if status else "unknown",
                len(self.running_tasks),
            )

            # Manage history size
            if len(self.history_tasks) > MAXIMUM_HISTORY_SIZE:
                self.history_tasks.pop(next(iter(self.history_tasks)))

            # Update history
            self.history_tasks[item.ui_id] = TaskHistoryItem(
                ui_id=item.ui_id,
                client_id=item.client_id,
                timestamp=now,
                result=result_msg,
                kind=item.kind,
                status=status,
                batch_id=self.batch_id,
                end_time=now,
            )

        # Force cache refresh for successful pack-modifying operations
        pack_modifying_tasks = {
            OperationType.install.value,
            OperationType.uninstall.value,
            OperationType.enable.value,
            OperationType.disable.value,
        }
        if (
            item.kind in pack_modifying_tasks
            and status
            and status.status_str == OperationResult.success.value
        ):
            try:
                logging.debug(
                    "[ComfyUI-Manager] Refreshing cache after successful %s operation",
                    item.kind,
                )
                # Force unified_manager to refresh its installed packages cache
                await core.unified_manager.reload(
                    ManagerDatabaseSource.cache.value,
                    dont_wait=True,
                    update_cnr_map=False,
                )
            except Exception as e:
                logging.warning(
                    f"[ComfyUI-Manager] Failed to refresh cache after {item.kind}: {e}"
                )

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
            # Extract items from tuples, maintaining heap order
            remaining = [item for priority, counter, item in sorted(self.pending_tasks)]
            return running, remaining

    def get_tasks_remaining(self) -> int:
        """Get number of tasks remaining"""
        with self.mutex:
            return len(self.pending_tasks) + len(self.running_tasks)

    def wipe_queue(self) -> None:
        """Clear all task queue"""
        with self.mutex:
            pending_count = len(self.pending_tasks)
            self.pending_tasks = []
            logging.debug(
                "[ComfyUI-Manager] Queue wiped: cleared %d pending tasks", pending_count
            )

    def abort(self) -> None:
        """Abort current operations"""
        with self.mutex:
            pending_count = len(self.pending_tasks)
            running_count = len(self.running_tasks)
            self.pending_tasks = []
            self.running_tasks = {}
            logging.debug(
                "[ComfyUI-Manager] Queue aborted: cleared %d pending and %d running tasks",
                pending_count,
                running_count,
            )

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
            logging.debug(
                "[ComfyUI-Manager] Finalizing batch: batch_id=%s, history_count=%d",
                self.batch_id,
                len(self.history_tasks),
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
                        [
                            op
                            for op in operations
                            if op.result == OperationResult.success.value
                        ]
                    ),
                    failed_operations=len(
                        [
                            op
                            for op in operations
                            if op.result == OperationResult.failed.value
                        ]
                    ),
                    skipped_operations=len(
                        [
                            op
                            for op in operations
                            if op.result == OperationResult.skipped.value
                        ]
                    ),
                )

                # Save to disk
                with open(batch_path, "w", encoding="utf-8") as json_file:
                    json.dump(
                        batch_record.model_dump(), json_file, indent=4, default=str
                    )

                logging.debug(
                    "[ComfyUI-Manager] Batch history saved: batch_id=%s, path=%s, total_ops=%d, successful=%d, failed=%d, skipped=%d",
                    self.batch_id,
                    batch_path,
                    batch_record.total_operations,
                    batch_record.successful_operations,
                    batch_record.failed_operations,
                    batch_record.skipped_operations,
                )

                # Reset batch tracking
                self.batch_id = None
                self.batch_start_time = None
                self.batch_state_before = None

                # Cleanup old batch files once per session
                if not self._cleanup_performed:
                    self._cleanup_old_batches()
                    self._cleanup_performed = True

            except Exception as e:
                logging.error(f"[ComfyUI-Manager] Failed to save batch history: {e}")

    def _capture_system_state(self) -> ComfyUISystemState:
        """Capture current ComfyUI system state for batch record."""
        logging.debug("[ComfyUI-Manager] Capturing system state for batch record")
        return ComfyUISystemState(
            snapshot_time=datetime.now().isoformat(),
            comfyui_version=self._get_comfyui_version_info(),
            frontend_version=self._get_frontend_version(),
            python_version=platform.python_version(),
            platform_info=f"{platform.system()} {platform.release()} ({platform.machine()})",
            installed_nodes=self._get_installed_nodes(),
            comfyui_root_path=self._get_comfyui_root_path(),
            model_paths=self._get_model_paths(),
            manager_version=self._get_manager_version(),
            security_level=self._get_security_level(),
            network_mode=self._get_network_mode(),
            cli_args=self._get_cli_args(),
            custom_nodes_count=self._get_custom_nodes_count(),
            failed_imports=self._get_failed_imports(),
            pip_packages=self._get_pip_packages(),
            manager_config=core.get_config(),
            embedded_python=os.path.split(os.path.split(sys.executable)[0])[1] == "python_embeded",
        )

    def _get_comfyui_version_info(self) -> ComfyUIVersionInfo:
        """Get ComfyUI version information."""
        try:
            version_info = core.get_comfyui_versions()
            current_version = version_info[1] if len(version_info) > 1 else "unknown"
            return ComfyUIVersionInfo(version=current_version)
        except Exception:
            return ComfyUIVersionInfo(version="unknown")

    def _get_frontend_version(self) -> Optional[str]:
        """Get ComfyUI frontend version."""
        try:
            # Check if front-end-root is specified (overrides version)
            if hasattr(args, "front_end_root") and args.front_end_root:
                return f"custom-root: {args.front_end_root}"

            # Check if front-end-version is specified
            if hasattr(args, "front_end_version") and args.front_end_version:
                if "@" in args.front_end_version:
                    return args.front_end_version.split("@")[1]
                else:
                    return args.front_end_version

            # Otherwise, check for installed package
            pip_packages = self._get_pip_packages()
            for package_name in ["comfyui-frontend", "comfyui_frontend"]:
                if package_name in pip_packages:
                    return pip_packages[package_name]

            return None
        except Exception:
            return None

    def _get_installed_nodes(self) -> dict[str, InstalledNodeInfo]:
        """Get information about installed node packages."""
        installed_nodes = {}

        try:
            node_packs = core.get_installed_node_packs()
            for pack_name, pack_info in node_packs.items():
                # Determine install method and repository URL
                install_method = "git" if pack_info.get("aux_id") else "cnr"
                repository_url = None

                if pack_info.get("aux_id"):
                    # It's a git-based node, construct GitHub URL
                    repository_url = f"https://github.com/{pack_info['aux_id']}"

                installed_nodes[pack_name] = InstalledNodeInfo(
                    name=pack_name,
                    version=pack_info.get("ver", "unknown"),
                    install_method=install_method,
                    repository_url=repository_url,
                    enabled=pack_info.get("enabled", True),
                )
        except Exception as e:
            logging.warning(f"[ComfyUI-Manager] Failed to get installed nodes: {e}")

        return installed_nodes

    def _get_comfyui_root_path(self) -> str:
        """Get ComfyUI root installation directory."""
        try:
            return os.path.dirname(folder_paths.__file__)
        except Exception:
            return None

    def _get_model_paths(self) -> dict[str, list[str]]:
        """Get model paths for different model types."""
        try:
            model_paths = {}
            for model_type in model_dir_name_map.keys():
                try:
                    paths = folder_paths.get_folder_paths(model_type)
                    if paths:
                        model_paths[model_type] = paths
                except Exception:
                    continue
            return model_paths
        except Exception:
            return {}

    def _get_manager_version(self) -> str:
        """Get ComfyUI Manager version."""
        try:
            version_code = getattr(core, "version_code", [4, 0])
            return f"V{version_code[0]}.{version_code[1]}"
        except Exception:
            return None

    def _get_security_level(self) -> SecurityLevel:
        """Get current security level."""
        try:
            config = core.get_config()
            level_str = config.get("security_level", "normal")
            # Map the string to SecurityLevel enum
            level_mapping = {
                "strong": SecurityLevel.strong,
                "normal": SecurityLevel.normal,
                "normal-": SecurityLevel.normal_,
                "weak": SecurityLevel.weak,
            }
            return level_mapping.get(level_str, SecurityLevel.normal)
        except Exception:
            return None

    def _get_network_mode(self) -> str:
        """Get current network mode."""
        try:
            config = core.get_config()
            return config.get("network_mode", "online")
        except Exception:
            return None

    def _get_cli_args(self) -> dict[str, Any]:
        """Get selected CLI arguments."""
        try:
            cli_args = {}
            if hasattr(args, "listen"):
                cli_args["listen"] = args.listen
            if hasattr(args, "port"):
                cli_args["port"] = args.port
            if hasattr(args, "preview_method"):
                cli_args["preview_method"] = str(args.preview_method)
            if hasattr(args, "enable_manager_legacy_ui"):
                cli_args["enable_manager_legacy_ui"] = args.enable_manager_legacy_ui
            if hasattr(args, "front_end_version"):
                cli_args["front_end_version"] = args.front_end_version
            if hasattr(args, "front_end_root"):
                cli_args["front_end_root"] = args.front_end_root
            return cli_args
        except Exception:
            return {}

    def _get_custom_nodes_count(self) -> int:
        """Get total number of custom node packages."""
        try:
            node_packs = core.get_installed_node_packs()
            return len(node_packs)
        except Exception:
            return 0

    def _get_failed_imports(self) -> list[str]:
        """Get list of custom nodes that failed to import."""
        try:
            # Check if the import_failed_extensions set is available
            if hasattr(sys, "__comfyui_manager_import_failed_extensions"):
                failed_set = getattr(sys, "__comfyui_manager_import_failed_extensions")
                return list(failed_set) if failed_set else []
            return []
        except Exception:
            return []

    def _get_pip_packages(self) -> dict[str, str]:
        """Get installed pip packages."""
        try:
            return core.get_installed_pip_packages()
        except Exception:
            return {}

    def _extract_batch_operations(self) -> list[BatchOperation]:
        """Extract operations from completed task history for this batch."""
        operations = []

        try:
            for ui_id, task in self.history_tasks.items():
                # Only include operations from the current batch
                if task.batch_id != self.batch_id:
                    continue

                result_status = OperationResult.success
                if task.status:
                    status_str = (
                        task.status.status_str
                        if hasattr(task.status, "status_str")
                        else task.status.get(
                            "status_str", OperationResult.success.value
                        )
                    )
                    if status_str == OperationResult.error.value:
                        result_status = OperationResult.failed
                    elif status_str == OperationResult.skip.value:
                        result_status = OperationResult.skipped

                operation = BatchOperation(
                    operation_id=ui_id,
                    operation_type=task.kind,
                    target=f"task_{ui_id}",
                    result=result_status.value,
                    start_time=task.timestamp,
                    end_time=task.end_time,
                    client_id=task.client_id,
                )
                operations.append(operation)
        except Exception as e:
            logging.warning(
                f"[ComfyUI-Manager] Failed to extract batch operations: {e}"
            )

        return operations

    def _cleanup_old_batches(self) -> None:
        """Clean up batch history files older than 90 days.

        This is a best-effort cleanup that silently ignores any errors
        to avoid disrupting normal operations.
        """
        try:
            cutoff = datetime.now() - timedelta(days=16)
            cutoff_timestamp = cutoff.timestamp()

            pattern = os.path.join(context.manager_batch_history_path, "batch_*.json")
            removed_count = 0

            import glob

            for file_path in glob.glob(pattern):
                try:
                    if os.path.getmtime(file_path) < cutoff_timestamp:
                        os.remove(file_path)
                        removed_count += 1
                except Exception:
                    pass

            if removed_count > 0:
                logging.debug(
                    "[ComfyUI-Manager] Cleaned up %d old batch history files",
                    removed_count,
                )

        except Exception:
            # Silently ignore all errors - this is non-critical functionality
            pass


task_queue = TaskQueue()

# Preview method initialization
if args.preview_method == latent_preview.LatentPreviewMethod.NoPreviews:
    environment_utils.set_preview_method(core.get_config()["preview_method"])
else:
    logging.warning(
        "[ComfyUI-Manager] Since --preview-method is set, ComfyUI-Manager's preview method feature will be ignored."
    )


async def task_worker():
    logging.debug("[ComfyUI-Manager] Task worker started")
    await core.unified_manager.reload(ManagerDatabaseSource.cache.value)

    async def do_install(params: InstallPackParams) -> str:
        if not security_utils.is_allowed_security_level('middle+'):
            logging.error(SECURITY_MESSAGE_MIDDLE_P)
            return OperationResult.failed.value

        node_id = params.id
        node_version = params.selected_version
        channel = params.channel
        mode = params.mode
        skip_post_install = params.skip_post_install

        logging.debug(
            "[ComfyUI-Manager] Installing node: id=%s, version=%s, channel=%s, mode=%s",
            node_id,
            node_version,
            channel,
            mode,
        )

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

            return OperationResult.success.value
        except Exception:
            traceback.print_exc()
            return "Installation failed"

    async def do_enable(params: EnablePackParams) -> str:
        cnr_id = params.cnr_id
        logging.debug("[ComfyUI-Manager] Enabling node: cnr_id=%s", cnr_id)
        core.unified_manager.unified_enable(cnr_id)
        return OperationResult.success.value

    async def do_update(params: UpdatePackParams) -> dict[str, str]:
        node_name = params.node_name
        node_ver = params.node_ver

        logging.debug(
            "[ComfyUI-Manager] Updating node: name=%s, version=%s", node_name, node_ver
        )

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
                    base_res["msg"] = OperationResult.skip.value
                    return base_res
                else:
                    base_res["msg"] = OperationResult.success.value
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
                logging.debug(
                    "[ComfyUI-Manager] Updating ComfyUI: is_stable=%s, repo_path=%s",
                    is_stable,
                    repo_path,
                )
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
                    return OperationResult.skip.value

        except Exception:
            traceback.print_exc()

        return "An error occurred while updating 'comfyui'."

    async def do_fix(params: FixPackParams) -> str:
        if not security_utils.is_allowed_security_level('middle'):
            logging.error(SECURITY_MESSAGE_MIDDLE)
            return OperationResult.failed.value

        node_name = params.node_name
        node_ver = params.node_ver

        try:
            res = core.unified_manager.unified_fix(node_name, node_ver)

            if res.result:
                return OperationResult.success.value
            else:
                logging.error(res.msg)

            logging.error(
                f"\nERROR: An error occurred while fixing '{node_name}@{node_ver}'."
            )
        except Exception:
            traceback.print_exc()

        return f"An error occurred while fixing '{node_name}@{node_ver}'."

    async def do_uninstall(params: UninstallPackParams) -> str:
        if not security_utils.is_allowed_security_level('middle'):
            logging.error(SECURITY_MESSAGE_MIDDLE)
            return OperationResult.failed.value

        node_name = params.node_name
        is_unknown = params.is_unknown

        logging.debug(
            "[ComfyUI-Manager] Uninstalling node: name=%s, is_unknown=%s",
            node_name,
            is_unknown,
        )

        try:
            res = core.unified_manager.unified_uninstall(node_name, is_unknown)

            if res.result:
                return OperationResult.success.value

            logging.error(
                f"\nERROR: An error occurred while uninstalling '{node_name}'."
            )
        except Exception:
            traceback.print_exc()

        return f"An error occurred while uninstalling '{node_name}'."

    async def do_disable(params: DisablePackParams) -> str:
        node_name = params.node_name

        logging.debug(
            "[ComfyUI-Manager] Disabling node: name=%s, is_unknown=%s",
            node_name,
            params.is_unknown,
        )

        try:
            res = core.unified_manager.unified_disable(node_name, params.is_unknown)

            if res:
                return OperationResult.success.value

        except Exception:
            traceback.print_exc()

        return f"Failed to disable: '{node_name}'"

    async def do_install_model(params: ModelMetadata) -> str:
        if not security_utils.is_allowed_security_level('middle+'):
            logging.error(SECURITY_MESSAGE_MIDDLE_P)
            return OperationResult.failed.value

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

                    return OperationResult.success.value

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
                        return OperationResult.success.value
                else:
                    res = download_url_with_agent(model_url, model_path)
                    if res and model_path.endswith(".zip"):
                        res = core.unzip(model_path)
            else:
                logging.error(
                    f"[ComfyUI-Manager] Model installation error: invalid model type - {json_data['type']}"
                )

            if res:
                return OperationResult.success.value

        except Exception as e:
            logging.error(f"[ComfyUI-Manager] ERROR: {e}")

        return f"Model installation error: {model_url}"

    while True:
        timeout = 4.0
        task = task_queue.get(timeout)
        if task is None:
            is_empty_queue = (
                task_queue.total_count() == 0 and len(task_queue.running_tasks) == 0
            )
            if is_empty_queue:
                logging.debug("[ComfyUI-Manager] Queue empty - all tasks completed")

                did_complete_tasks = task_queue.done_count() > 0
                if did_complete_tasks:
                    logging.debug(
                        "[ComfyUI-Manager] Finalizing batch history with %d completed tasks",
                        task_queue.done_count(),
                    )
                    task_queue.finalize()
                    logging.debug("[ComfyUI-Manager] Batch finalization complete")

                logging.info("\nAfter restarting ComfyUI, please refresh the browser.")

                res = {"status": "all-done"}

                # Broadcast general status updates to all clients
                logging.debug("[ComfyUI-Manager] Broadcasting queue all-done status")
                PromptServer.instance.send_sync("cm-queue-status", res)

                logging.debug("[ComfyUI-Manager] Task worker exiting")
                return

        item, task_index = task
        kind = item.kind

        logging.debug(
            "[ComfyUI-Manager] Processing task: kind=%s, ui_id=%s, client_id=%s, task_index=%d",
            kind,
            item.ui_id,
            item.client_id,
            task_index,
        )

        try:
            if kind == OperationType.install.value:
                msg = await do_install(item.params)
            elif kind == OperationType.enable.value:
                msg = await do_enable(item.params)
            elif kind == OperationType.install_model.value:
                msg = await do_install_model(item.params)
            elif kind == OperationType.update.value:
                msg = await do_update(item.params)
            elif kind == "update-main":
                msg = await do_update(item.params)
            elif kind == OperationType.update_comfyui.value:
                msg = await do_update_comfyui(item.params)
            elif kind == OperationType.fix.value:
                msg = await do_fix(item.params)
            elif kind == OperationType.uninstall.value:
                msg = await do_uninstall(item.params)
            elif kind == OperationType.disable.value:
                msg = await do_disable(item.params)
            else:
                msg = "Unexpected kind: " + kind
        except Exception:
            msg = f"Exception: {(kind, item)}"
            logging.error(
                "[ComfyUI-Manager] Task execution exception: kind=%s, ui_id=%s, error=%s",
                kind,
                item.ui_id,
                traceback.format_exc(),
            )
            await task_queue.task_done(
                item,
                task_index,
                msg,
                TaskExecutionStatus(
                    status_str=OperationResult.error, completed=True, messages=[msg]
                ),
            )
            return

        # Determine status and message for task completion
        if isinstance(msg, dict) and "msg" in msg:
            result_msg = msg["msg"]
        else:
            result_msg = msg

        # Determine status
        if result_msg == OperationResult.success.value:
            status = TaskExecutionStatus(
                status_str=OperationResult.success, completed=True, messages=[]
            )
        elif result_msg == OperationResult.skip.value:
            status = TaskExecutionStatus(
                status_str=OperationResult.skip, completed=True, messages=[]
            )
        else:
            status = TaskExecutionStatus(
                status_str=OperationResult.error, completed=True, messages=[result_msg]
            )

        logging.debug(
            "[ComfyUI-Manager] Task execution completed: kind=%s, ui_id=%s, status=%s, result=%s",
            kind,
            item.ui_id,
            status.status_str,
            result_msg,
        )
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
        logging.debug(
            "[ComfyUI-Manager] Queueing task via API: kind=%s, ui_id=%s, client_id=%s",
            task_item.kind,
            task_item.ui_id,
            task_item.client_id,
        )
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
            logging.debug(
                "[ComfyUI-Manager] Fetching batch history: id=%s",
                request.rel_url.query["id"],
            )

            with open(batch_path, "r", encoding="utf-8") as file:
                json_str = file.read()
                json_obj = json.loads(json_str)
                return web.json_response(json_obj, content_type="application/json")

        # Handle current session history with optional filtering
        client_id = request.rel_url.query.get("client_id")
        ui_id = request.rel_url.query.get("ui_id")
        max_items = request.rel_url.query.get("max_items")
        offset = request.rel_url.query.get("offset", -1)

        logging.debug(
            "[ComfyUI-Manager] Fetching history: client_id=%s, ui_id=%s, max_items=%s",
            client_id,
            ui_id,
            max_items,
        )

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
            "deprecated": True,
        },
        status=410,  # 410 Gone
    )


@routes.get("/v2/manager/queue/update_all")
async def update_all(request: web.Request) -> web.Response:
    try:
        # Validate query parameters using Pydantic model
        query_params = UpdateAllQueryParams.model_validate(dict(request.rel_url.query))
        return await _update_all(query_params)
    except ValidationError as e:
        return web.json_response(
            {"error": "Validation error", "details": e.errors()}, status=400
        )


async def _update_all(params: UpdateAllQueryParams) -> web.Response:
    if not security_utils.is_allowed_security_level("middle+"):
        logging.error(SECURITY_MESSAGE_MIDDLE_P)
        return web.Response(status=403)

    # Extract client info from validated params
    base_ui_id = params.ui_id
    client_id = params.client_id
    mode = params.mode.value if params.mode else ManagerDatabaseSource.remote.value

    logging.debug(
        "[ComfyUI-Manager] Update all requested: client_id=%s, base_ui_id=%s, mode=%s",
        client_id,
        base_ui_id,
        mode,
    )

    if mode == ManagerDatabaseSource.local.value:
        channel = "local"
    else:
        channel = core.get_config()["channel_url"]

    await core.unified_manager.reload(mode)
    await core.unified_manager.get_custom_nodes(channel, mode)

    update_count = 0
    for k, v in core.unified_manager.active_nodes.items():
        if k == "comfyui-manager":
            # skip updating comfyui-manager if desktop version
            if os.environ.get("__COMFYUI_DESKTOP_VERSION__"):
                continue

        update_task = QueueTaskItem(
            kind=OperationType.update.value,
            ui_id=f"{base_ui_id}_{k}",  # Use client's base ui_id + node name
            client_id=client_id,
            params=UpdatePackParams(node_name=k, node_ver=v[0]),
        )
        task_queue.put(update_task)
        update_count += 1

    for k, v in core.unified_manager.unknown_active_nodes.items():
        if k == "comfyui-manager":
            # skip updating comfyui-manager if desktop version
            if os.environ.get("__COMFYUI_DESKTOP_VERSION__"):
                continue

        update_task = QueueTaskItem(
            kind=OperationType.update.value,
            ui_id=f"{base_ui_id}_{k}",  # Use client's base ui_id + node name
            client_id=client_id,
            params=UpdatePackParams(node_name=k, node_ver="unknown"),
        )
        task_queue.put(update_task)
        update_count += 1

    logging.debug(
        "[ComfyUI-Manager] Update all queued %d tasks for client_id=%s",
        update_count,
        client_id,
    )
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
        logging.error(SECURITY_MESSAGE_MIDDLE)
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
    if not security_utils.is_allowed_security_level("middle+"):
        logging.error(SECURITY_MESSAGE_MIDDLE_P)
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
            logging.error(f"Install(unzip) error: {url} / {e}")
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


@routes.post("/v2/customnode/import_fail_info_bulk")
async def import_fail_info_bulk(request):
    try:
        json_data = await request.json()
        
        # Validate input using Pydantic model
        request_data = ImportFailInfoBulkRequest.model_validate(json_data)
        
        # Ensure we have either cnr_ids or urls
        if not request_data.cnr_ids and not request_data.urls:
            return web.Response(
                status=400, text="Either 'cnr_ids' or 'urls' field is required"
            )

        await core.unified_manager.reload('cache')
        await core.unified_manager.get_custom_nodes('default', 'cache')

        results = {}

        if request_data.cnr_ids:
            for cnr_id in request_data.cnr_ids:
                module_name = core.unified_manager.get_module_name(cnr_id)
                if module_name is not None:
                    info = cm_global.error_dict.get(module_name)
                    if info is not None:
                        results[cnr_id] = info
                    else:
                        results[cnr_id] = None
                else:
                    results[cnr_id] = None

        if request_data.urls:
            for url in request_data.urls:
                module_name = core.unified_manager.get_module_name(url)
                if module_name is not None:
                    info = cm_global.error_dict.get(module_name)
                    if info is not None:
                        results[url] = info
                    else:
                        results[url] = None
                else:
                    results[url] = None

        # Create response using Pydantic model
        response_data = ImportFailInfoBulkResponse(root=results)
        return web.json_response(response_data.root)
    except ValidationError as e:
        logging.error(f"[ComfyUI-Manager] Invalid request data: {e}")
        return web.Response(status=400, text=f"Invalid request data: {e}")
    except Exception as e:
        logging.error(f"[ComfyUI-Manager] Error processing bulk import fail info: {e}")
        return web.Response(status=500, text="Internal server error")


@routes.get("/v2/manager/queue/reset")
async def reset_queue(request):
    logging.debug("[ComfyUI-Manager] Queue reset requested")
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
            item
            for priority, counter, item in task_queue.pending_tasks
            if item.client_id == client_id
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
    logging.debug("[ComfyUI-Manager] Queue start requested")
    started = task_queue.start_worker()

    if started:
        logging.debug("[ComfyUI-Manager] Queue worker started successfully")
        return web.Response(status=200)  # Started successfully
    else:
        logging.debug("[ComfyUI-Manager] Queue worker already in progress")
        return web.Response(status=201)  # Already in-progress


@routes.get("/v2/manager/queue/update_comfyui")
async def update_comfyui(request):
    """Queue a ComfyUI update based on the configured update policy."""
    try:
        # Validate query parameters using Pydantic model
        query_params = UpdateComfyUIQueryParams.model_validate(
            dict(request.rel_url.query)
        )

        # Check if stable parameter was provided, otherwise use config
        if query_params.stable is None:
            is_stable = core.get_config()["update_policy"] != "nightly-comfyui"
        else:
            is_stable = query_params.stable

        client_id = query_params.client_id
        ui_id = query_params.ui_id
    except ValidationError as e:
        return web.json_response(
            {"error": "Validation error", "details": e.errors()}, status=400
        )

    # Create update-comfyui task
    task = QueueTaskItem(
        ui_id=ui_id,
        client_id=client_id,
        kind=OperationType.update_comfyui.value,
        params=UpdateComfyUIParams(is_stable=is_stable),
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
        logging.error(f"ComfyUI update fail: {e}")

    return web.Response(status=400)


@routes.get("/v2/comfyui_manager/comfyui_switch_version")
async def comfyui_switch_version(request):
    try:
        # Validate query parameters using Pydantic model
        query_params = ComfyUISwitchVersionQueryParams.model_validate(
            dict(request.rel_url.query)
        )

        target_version = query_params.ver
        client_id = query_params.client_id
        ui_id = query_params.ui_id

        # Create update-comfyui task with target version
        task = QueueTaskItem(
            ui_id=ui_id,
            client_id=client_id,
            kind=OperationType.update_comfyui.value,
            params=UpdateComfyUIParams(target_version=target_version),
        )

        task_queue.put(task)
        return web.Response(status=200)
    except ValidationError as e:
        return web.json_response(
            {"error": "Validation error", "details": e.errors()}, status=400
        )
    except Exception as e:
        logging.error(f"ComfyUI version switch fail: {e}")
        return web.Response(status=400)


@routes.post("/v2/manager/queue/install_model")
async def install_model(request):
    try:
        json_data = await request.json()

        # Validate required fields
        if "client_id" not in json_data:
            return web.Response(status=400, text="Missing required field: client_id")
        if "ui_id" not in json_data:
            return web.Response(status=400, text="Missing required field: ui_id")

        # Validate model metadata
        model_data = ModelMetadata.model_validate(json_data)

        # Create install-model task with client-provided IDs
        task = QueueTaskItem(
            ui_id=json_data["ui_id"],
            client_id=json_data["client_id"],
            kind=OperationType.install_model.value,
            params=model_data,
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
        logging.error(SECURITY_MESSAGE_MIDDLE)
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
            await core.unified_manager.reload(
                ManagerDatabaseSource.remote.value, dont_wait=False
            )
            await core.unified_manager.get_custom_nodes(
                channel_url, ManagerDatabaseSource.remote.value
            )
    else:
        await core.unified_manager.reload(
            ManagerDatabaseSource.remote.value, dont_wait=False, update_cnr_map=False
        )

    logging.info("[ComfyUI-Manager] All startup tasks have been completed.")


threading.Thread(target=lambda: asyncio.run(default_cache_update())).start()

if not os.path.exists(context.manager_config_path):
    core.get_config()
    core.write_config()

