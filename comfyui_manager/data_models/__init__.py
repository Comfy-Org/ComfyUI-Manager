"""
Data models for ComfyUI Manager.

This package contains Pydantic models used throughout the ComfyUI Manager
for data validation, serialization, and type safety.

All models are auto-generated from the OpenAPI specification to ensure
consistency between the API and implementation.
"""

from .generated_models import (
    # Core Task Queue Models
    QueueTaskItem,
    TaskHistoryItem,
    TaskStateMessage,
    TaskExecutionStatus,
    
    # WebSocket Message Models
    MessageTaskDone,
    MessageTaskStarted,
    MessageTaskFailed,
    MessageUpdate,
    ManagerMessageName,
    
    # State Management Models
    BatchExecutionRecord,
    ComfyUISystemState,
    BatchOperation,
    InstalledNodeInfo,
    InstalledModelInfo,
    ComfyUIVersionInfo,
    
    # Other models
    Kind,
    StatusStr,
    ManagerPackInfo,
    ManagerPackInstalled,
    SelectedVersion,
    ManagerChannel,
    ManagerDatabaseSource,
    ManagerPackState,
    ManagerPackInstallType,
    ManagerPack,
    InstallPackParams,
    UpdatePackParams,
    UpdateAllPacksParams,
    UpdateComfyUIParams,
    FixPackParams,
    UninstallPackParams,
    DisablePackParams,
    EnablePackParams,
    QueueStatus,
    ManagerMappings,
    ModelMetadata,
    NodePackageMetadata,
    SnapshotItem,
    Error,
    InstalledPacksResponse,
    HistoryResponse,
    HistoryListResponse,
    InstallType,
    OperationType,
    Result,
)

__all__ = [
    # Core Task Queue Models
    "QueueTaskItem",
    "TaskHistoryItem",
    "TaskStateMessage",
    "TaskExecutionStatus",
    
    # WebSocket Message Models
    "MessageTaskDone",
    "MessageTaskStarted",
    "MessageTaskFailed",
    "MessageUpdate",
    "ManagerMessageName",
    
    # State Management Models
    "BatchExecutionRecord",
    "ComfyUISystemState",
    "BatchOperation",
    "InstalledNodeInfo",
    "InstalledModelInfo",
    "ComfyUIVersionInfo",
    
    # Other models
    "Kind",
    "StatusStr",
    "ManagerPackInfo",
    "ManagerPackInstalled",
    "SelectedVersion",
    "ManagerChannel",
    "ManagerDatabaseSource",
    "ManagerPackState",
    "ManagerPackInstallType",
    "ManagerPack",
    "InstallPackParams",
    "UpdatePackParams",
    "UpdateAllPacksParams",
    "UpdateComfyUIParams",
    "FixPackParams",
    "UninstallPackParams",
    "DisablePackParams",
    "EnablePackParams",
    "QueueStatus",
    "ManagerMappings",
    "ModelMetadata",
    "NodePackageMetadata",
    "SnapshotItem",
    "Error",
    "InstalledPacksResponse",
    "HistoryResponse",
    "HistoryListResponse",
    "InstallType",
    "OperationType",
    "Result",
]