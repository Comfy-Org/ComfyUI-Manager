from __future__ import annotations

from dataclasses import dataclass
import os

from .git_utils import get_commit_hash


@dataclass
class InstalledNodePackage:
    """Information about an installed node package."""

    id: str
    fullpath: str
    disabled: bool
    version: str
    repo_url: str = None  # Git repository URL for nightly packages

    @property
    def is_unknown(self) -> bool:
        return self.version == "unknown"

    @property
    def is_nightly(self) -> bool:
        return self.version == "nightly"

    @property
    def is_from_cnr(self) -> bool:
        return not self.is_unknown and not self.is_nightly

    @property
    def is_enabled(self) -> bool:
        return not self.disabled

    @property
    def is_disabled(self) -> bool:
        return self.disabled

    def get_commit_hash(self) -> str:
        return get_commit_hash(self.fullpath)

    def isValid(self) -> bool:
        if self.is_from_cnr:
            return os.path.exists(os.path.join(self.fullpath, '.tracking'))

        return True

    @staticmethod
    def from_fullpath(fullpath: str, resolve_from_path) -> InstalledNodePackage:
        from . import git_utils
        
        parent_folder_name = os.path.basename(os.path.dirname(fullpath))
        module_name = os.path.basename(fullpath)

        if module_name.endswith(".disabled"):
            node_id = module_name[:-9]
            disabled = True
        elif parent_folder_name == ".disabled":
            # Nodes under custom_nodes/.disabled/* are disabled
            # Parse directory name format: packagename@version
            # Examples:
            #   comfyui_sigmoidoffsetscheduler@nightly → id: comfyui_sigmoidoffsetscheduler, version: nightly
            #   comfyui_sigmoidoffsetscheduler@1_0_2 → id: comfyui_sigmoidoffsetscheduler, version: 1.0.2
            node_id = module_name
            disabled = True
        else:
            node_id = module_name
            disabled = False

        info = resolve_from_path(fullpath)
        repo_url = None
        version_from_dirname = None

        # For disabled packages, try to extract version from directory name
        if disabled and parent_folder_name == ".disabled" and '@' in module_name:
            parts = module_name.split('@')
            if len(parts) == 2:
                node_id = parts[0]  # Use the normalized name from directory
                version_from_dirname = parts[1].replace('_', '.')  # Convert 1_0_2 → 1.0.2

        if info is None:
            version = version_from_dirname if version_from_dirname else 'unknown'
        else:
            node_id = info['id']    # robust module guessing
            # Prefer version from directory name for disabled packages (preserves 'nightly' literal)
            # Otherwise use version from package inspection (commit hash for git repos)
            if version_from_dirname:
                version = version_from_dirname
            else:
                version = info['ver']

            # Get repository URL for both nightly and CNR packages
            if version == 'nightly':
                # For nightly packages, get repo URL from git
                repo_url = git_utils.git_url(fullpath)
            elif 'url' in info and info['url']:
                # For CNR packages, get repo URL from pyproject.toml
                repo_url = info['url']

        return InstalledNodePackage(
            id=node_id, fullpath=fullpath, disabled=disabled, version=version, repo_url=repo_url
        )
