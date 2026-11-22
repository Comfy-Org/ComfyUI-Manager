# ComfyUI-Manager: Node Database (node_db)

This directory contains the JSON database files that power ComfyUI-Manager's legacy node registry system. While the manager is gradually transitioning to the online Custom Node Registry (CNR), these local JSON files continue to provide important metadata about custom nodes, models, and their integrations.

## Directory Structure

The node_db directory is organized into several subdirectories, each serving a specific purpose:

- **dev/**: Development channel files with latest additions and experimental nodes
- **legacy/**: Historical/legacy nodes that may require special handling
- **new/**: New nodes that have passed initial verification but are still being evaluated
- **forked/**: Forks of existing nodes with modifications
- **tutorial/**: Example and tutorial nodes designed for learning purposes

## Core Database Files

Each subdirectory contains a standard set of JSON files:

- **custom-node-list.json**: Primary database of custom nodes with metadata
- **extension-node-map.json**: Maps between extensions and individual nodes they provide
- **model-list.json**: Catalog of models that can be downloaded through the manager
- **alter-list.json**: Alternative implementations of nodes for compatibility or functionality
- **github-stats.json**: GitHub repository statistics for node popularity metrics

## Database Schema

### custom-node-list.json
```json
{
  "custom_nodes": [
    {
      "title": "Node display name",
      "name": "Repository name",
      "reference": "Original repository if forked",
      "files": ["GitHub URL or other source location"],
      "install_type": "git",
      "description": "Description of the node's functionality",
      "pip": ["optional pip dependencies"],
      "js": ["optional JavaScript files"],
      "tags": ["categorization tags"]
    }
  ]
}
```

### extension-node-map.json
```json
{
  "extension-id": [
    ["list", "of", "node", "classes"],
    {
      "author": "Author name",
      "description": "Extension description",
      "nodename_pattern": "Optional regex pattern for node name matching"
    }
  ]
}
```

## Transition to Custom Node Registry (CNR)

This local database system is being progressively replaced by the online Custom Node Registry (CNR), which provides:
- Real-time updates without manual JSON maintenance
- Improved versioning support
- Better security validation
- Enhanced metadata

The Manager supports both systems simultaneously during the transition period.

## Implementation Details

- The database follows a channel-based architecture for different sources
- Multiple database modes are supported: Channel, Local, and Remote
- The system supports differential updates to minimize bandwidth usage
- Security levels are enforced for different node installations based on source

## Usage in the Application

The Manager's backend uses these database files to:

1. Provide browsable lists of available nodes and models
2. Resolve dependencies for installation
3. Track updates and new versions
4. Map node classes to their source repositories
5. Assess risk levels for installation security

## Maintenance Scripts

Each subdirectory contains a `scan.sh` script that assists with:
- Scanning repositories for new nodes
- Updating metadata
- Validating database integrity
- Generating proper JSON structures

This database system enables a flexible, secure, and comprehensive management system for the ComfyUI ecosystem while the transition to CNR continues.