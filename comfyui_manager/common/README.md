# ComfyUI-Manager: Core Backend (glob)

This directory contains the Python backend modules that power ComfyUI-Manager, handling the core functionality of node management, downloading, security, and server operations.

## Core Modules

- **manager_downloader.py**: Handles downloading operations for models, extensions, and other resources.
- **manager_util.py**: Provides utility functions used throughout the system.

## Specialized Modules

- **cm_global.py**: Maintains global variables and state management across the system.
- **cnr_utils.py**: Helper utilities for interacting with the custom node registry (CNR).
- **git_utils.py**: Git-specific utilities for repository operations.
- **node_package.py**: Handles the packaging and installation of node extensions.
- **security_check.py**: Implements the multi-level security system for installation safety.
