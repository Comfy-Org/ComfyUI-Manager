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
    
    # Import Fail Info Models
    ImportFailInfoBulkRequest,
    ImportFailInfoBulkResponse,
    ImportFailInfoItem,
    ImportFailInfoItem1,
    
    # Other models
    OperationType,
    OperationResult,
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
    UpdateAllQueryParams,
    UpdateComfyUIQueryParams,
    ComfyUISwitchVersionQueryParams,
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
    SecurityLevel,
    RiskLevel,
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
    
    # Import Fail Info Models
    "ImportFailInfoBulkRequest",
    "ImportFailInfoBulkResponse",
    "ImportFailInfoItem",
    "ImportFailInfoItem1",
    
    # Other models
    "OperationType",
    "OperationResult",
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
    "UpdateAllQueryParams",
    "UpdateComfyUIQueryParams",
    "ComfyUISwitchVersionQueryParams",
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
    "SecurityLevel",
    "RiskLevel",
]