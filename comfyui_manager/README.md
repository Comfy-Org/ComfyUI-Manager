# ComfyUI-Manager: Core Backend (glob)

This directory contains the Python backend modules that power ComfyUI-Manager, handling the core functionality of node management, downloading, security, and server operations.

## Directory Structure
- **glob/** - code for new cacheless ComfyUI-Manager
- **legacy/** - code for legacy ComfyUI-Manager

## Core Modules
- **manager_core.py**: The central implementation of management functions, handling configuration, installation, updates, and node management.
- **manager_server.py**: Implements server functionality and API endpoints for the web interface to interact with the backend.

## Specialized Modules

- **share_3rdparty.py**: Manages integration with third-party sharing platforms.

## Architecture

The backend follows a modular design pattern with clear separation of concerns:

1. **Core Layer**: Manager modules provide the primary API and business logic
2. **Utility Layer**: Helper modules provide specialized functionality
3. **Integration Layer**: Modules that connect to external systems

## Security Model

The system implements a comprehensive security framework with multiple levels:

- **Block**: Highest security - blocks most remote operations
- **High**: Allows only specific trusted operations
- **Middle**: Standard security for most users
- **Normal-**: More permissive for advanced users
- **Weak**: Lowest security for development environments

## Implementation Details

- The backend is designed to work seamlessly with ComfyUI
- Asynchronous task queuing is implemented for background operations
- The system supports multiple installation modes
- Error handling and risk assessment are integrated throughout the codebase

## API Integration

The backend exposes a REST API via `manager_server.py` that enables:
- Custom node management (install, update, disable, remove)
- Model downloading and organization
- System configuration
- Snapshot management
- Workflow component handling