from __future__ import annotations

from dataclasses import dataclass
import os

from .git_utils import get_commit_hash


# the reparse tag of a directory junction on Windows (IO_REPARSE_TAG_MOUNT_POINT)
JUNCTION_REPARSE_TAG = 0xA0000003


def is_link(path: str) -> bool:
    """
    A symbolic link, or a directory junction on Windows. A junction is told by the reparse tag that os.lstat reads on
    every Python; os.path.isjunction is new in 3.12.
    """
    try:
        return os.path.islink(path) or getattr(os.lstat(path), 'st_reparse_tag', 0) == JUNCTION_REPARSE_TAG
    except OSError:
        return False


@dataclass(frozen=True)
class InvalidInstallation:
    """What a reload knows of an invalid installation (see InstalledNodePackage.isValid). Which nodepack it is
    depends on the registry list, so UnifiedManager.invalid_pack_id answers that when it is asked."""

    fullpath: str
    folder: str                 # its name without a .disabled suffix, as the unknown nodes key it
    project_name: str | None    # [project].name of its pyproject.toml
    enabled: bool


@dataclass
class InstalledNodePackage:
    """Information about an installed node package."""

    id: str
    fullpath: str
    disabled: bool
    version: str

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
        """False for an invalid installation: a folder with neither .git nor .tracking, so that the Manager can
        neither update it nor tell its version."""
        name = os.path.basename(self.fullpath)
        # Not an installation of a nodepack: the Manager's own folder, a link the user placed on purpose, a hidden
        # folder (.git, .ipynb_checkpoints, the holding place of a reinstall), what Python or an unzip tool leaves.
        if ('comfyui-manager' in self.id.lower() or is_link(self.fullpath)
                or name.startswith('.') or name in ('__MACOSX', '__pycache__')):
            return True

        return os.path.exists(os.path.join(self.fullpath, '.git')) or os.path.exists(os.path.join(self.fullpath, '.tracking'))

    @staticmethod
    def from_fullpath(fullpath: str, resolve_from_path) -> InstalledNodePackage:
        parent_folder_name = os.path.basename(os.path.dirname(fullpath))
        module_name = os.path.basename(fullpath)

        if module_name.endswith(".disabled"):
            node_id = module_name[:-9]
            disabled = True
        elif parent_folder_name == ".disabled":
            # Nodes under custom_nodes/.disabled/* are disabled
            node_id = module_name
            disabled = True
        else:
            node_id = module_name
            disabled = False

        info = resolve_from_path(fullpath)
        if info is None:
            version = 'unknown'
        else:
            node_id = info['id']    # robust module guessing
            version = info['ver']

        return InstalledNodePackage(
            id=node_id, fullpath=fullpath, disabled=disabled, version=version
        )
