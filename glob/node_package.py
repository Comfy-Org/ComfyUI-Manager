from __future__ import annotations

from dataclasses import dataclass
import os

from git_utils import get_commit_hash


IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def is_link(path: str) -> bool:
    """
    A junction is told by the reparse tag that os.lstat reads on every Python; os.path.isjunction is new in 3.12.
    """
    try:
        return os.path.islink(path) or getattr(os.lstat(path), 'st_reparse_tag', 0) == IO_REPARSE_TAG_MOUNT_POINT
    except OSError:
        return False


@dataclass(frozen=True)
class InvalidInstallation:
    fullpath: str
    unknown_key: str
    project_name: str | None
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

    def is_exempt_from_installation_check(self) -> bool:
        name = os.path.basename(self.fullpath)
        return ('comfyui-manager' in self.id.lower() or is_link(self.fullpath)
                or name.startswith('.') or name in ('__MACOSX', '__pycache__'))

    def isValid(self) -> bool:
        if self.is_exempt_from_installation_check():
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
