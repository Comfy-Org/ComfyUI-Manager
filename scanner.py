import ast
import re
import os
import json
from git import Repo
import concurrent
import datetime
import concurrent.futures
import requests
import warnings
import argparse

builtin_nodes = set()

import sys

from urllib.parse import urlparse
from github import Github, Auth
from pathlib import Path
from typing import Set, Dict, Optional

# Scanner version for cache invalidation
SCANNER_VERSION = "2.0.12"  # Add dict comprehension + export list detection

# Cache for extract_nodes and extract_nodes_enhanced results
_extract_nodes_cache: Dict[str, Set[str]] = {}
_extract_nodes_enhanced_cache: Dict[str, Set[str]] = {}
_file_mtime_cache: Dict[Path, float] = {}


def _get_repo_root(file_path: Path) -> Optional[Path]:
    """Find the repository root directory containing .git"""
    current = file_path if file_path.is_dir() else file_path.parent
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def _get_repo_hash(repo_path: Path) -> str:
    """Get git commit hash or fallback identifier"""
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return ""

    try:
        # Read HEAD to get current commit
        head_file = git_dir / "HEAD"
        if head_file.exists():
            head_content = head_file.read_text().strip()
            if head_content.startswith("ref:"):
                # HEAD points to a ref
                ref_path = git_dir / head_content[5:].strip()
                if ref_path.exists():
                    commit_hash = ref_path.read_text().strip()
                    return commit_hash[:16]  # First 16 chars
            else:
                # Detached HEAD
                return head_content[:16]
    except:
        pass

    return ""


def _load_per_repo_cache(repo_path: Path) -> Optional[tuple]:
    """Load nodes and metadata from per-repo cache

    Returns:
        tuple: (nodes_set, metadata_dict) or None if cache invalid
    """
    cache_file = repo_path / ".git" / "nodecache.json"

    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)

        # Verify scanner version
        if cache_data.get('scanner_version') != SCANNER_VERSION:
            return None

        # Verify git hash
        current_hash = _get_repo_hash(repo_path)
        if cache_data.get('git_hash') != current_hash:
            return None

        # Return nodes and metadata
        nodes = cache_data.get('nodes', [])
        metadata = cache_data.get('metadata', {})
        return (set(nodes) if nodes else set(), metadata)

    except:
        return None


def _save_per_repo_cache(repo_path: Path, all_nodes: Set[str], metadata: dict = None):
    """Save nodes and metadata to per-repo cache"""
    cache_file = repo_path / ".git" / "nodecache.json"

    if not cache_file.parent.exists():
        return

    git_hash = _get_repo_hash(repo_path)
    cache_data = {
        "scanner_version": SCANNER_VERSION,
        "git_hash": git_hash,
        "scanned_at": datetime.datetime.now().isoformat(),
        "nodes": sorted(list(all_nodes)),
        "metadata": metadata if metadata else {}
    }

    try:
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
    except:
        pass  # Silently fail - cache is optional


def download_url(url, dest_folder, filename=None):
    # Ensure the destination folder exists
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    # Extract filename from URL if not provided
    if filename is None:
        filename = os.path.basename(url)

    # Full path to save the file
    dest_path = os.path.join(dest_folder, filename)

    # Download the file
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(dest_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    file.write(chunk)
    else:
        raise Exception(f"Failed to download file from {url}")


def parse_arguments():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='ComfyUI Manager Node Scanner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Standard mode
  python3 scanner.py
  python3 scanner.py --skip-update
  python3 scanner.py --skip-all --force-rescan

  # Scan-only mode
  python3 scanner.py --scan-only temp-urls-clean.list
  python3 scanner.py --scan-only urls.list --temp-dir /custom/temp
  python3 scanner.py --scan-only urls.list --skip-update --force-rescan
        '''
    )

    parser.add_argument('--scan-only', type=str, metavar='URL_LIST_FILE',
                       help='Scan-only mode: provide URL list file (one URL per line)')
    parser.add_argument('--temp-dir', type=str, metavar='DIR',
                       help='Temporary directory for cloned repositories')
    parser.add_argument('--skip-update', action='store_true',
                       help='Skip git clone/pull operations')
    parser.add_argument('--skip-stat-update', action='store_true',
                       help='Skip GitHub stats collection')
    parser.add_argument('--skip-all', action='store_true',
                       help='Skip all update operations')
    parser.add_argument('--force-rescan', action='store_true',
                       help='Force rescan all nodes (ignore cache)')

    # Backward compatibility: positional argument for temp_dir
    parser.add_argument('temp_dir_positional', nargs='?', metavar='TEMP_DIR',
                       help='(Legacy) Temporary directory path')

    args = parser.parse_args()
    return args


# Module-level variables (will be set in main if running as script)
args = None
scan_only_mode = False
url_list_file = None
temp_dir = None
skip_update = False
skip_stat_update = True
g = None


parse_cnt = 0


def extract_nodes(code_text):
    global parse_cnt

    # Check cache first
    cache_key = hash(code_text)
    if cache_key in _extract_nodes_cache:
        return _extract_nodes_cache[cache_key].copy()

    try:
        if parse_cnt % 100 == 0:
            print(".", end="", flush=True)
        parse_cnt += 1

        code_text = re.sub(r'\\[^"\']', '', code_text)
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning)
            warnings.filterwarnings('ignore', category=DeprecationWarning)
            parsed_code = ast.parse(code_text)

        # Support both ast.Assign and ast.AnnAssign (for type-annotated assignments)
        assignments = (node for node in parsed_code.body if isinstance(node, (ast.Assign, ast.AnnAssign)))

        for assignment in assignments:
            # Handle ast.AnnAssign (e.g., NODE_CLASS_MAPPINGS: Type = {...})
            if isinstance(assignment, ast.AnnAssign):
                if isinstance(assignment.target, ast.Name) and assignment.target.id in ['NODE_CONFIG', 'NODE_CLASS_MAPPINGS']:
                    node_class_mappings = assignment.value
                    break
            # Handle ast.Assign (e.g., NODE_CLASS_MAPPINGS = {...})
            elif isinstance(assignment.targets[0], ast.Name) and assignment.targets[0].id in ['NODE_CONFIG', 'NODE_CLASS_MAPPINGS']:
                node_class_mappings = assignment.value
                break
        else:
            node_class_mappings = None

        if node_class_mappings:
            s = set()

            for key in node_class_mappings.keys:
                    if key is not None and isinstance(key.value, str):
                        s.add(key.value.strip())

            # Cache the result
            _extract_nodes_cache[cache_key] = s
            return s
        else:
            # Cache empty result
            _extract_nodes_cache[cache_key] = set()
            return set()
    except:
        # Cache empty result on error
        _extract_nodes_cache[cache_key] = set()
        return set()

def extract_nodes_from_repo(repo_path: Path, verbose: bool = False, force_rescan: bool = False) -> tuple:
    """
    Extract all nodes and metadata from a repository with per-repo caching.

    Automatically caches results in .git/nodecache.json.
    Cache is invalidated when:
    - Git commit hash changes
    - Scanner version changes
    - force_rescan flag is True

    Args:
        repo_path: Path to repository root
        verbose: If True, print UI-only extension detection messages
        force_rescan: If True, ignore cache and force fresh scan

    Returns:
        tuple: (nodes_set, metadata_dict)
    """
    # Ensure path is absolute
    repo_path = repo_path.resolve()

    # Check per-repo cache first (unless force_rescan is True)
    if not force_rescan:
        cached_result = _load_per_repo_cache(repo_path)
        if cached_result is not None:
            return cached_result

    # Cache miss - scan all .py files
    all_nodes = set()
    all_metadata = {}
    py_files = list(repo_path.rglob("*.py"))

    # Filter out __pycache__, .git, and other hidden directories
    filtered_files = []
    for f in py_files:
        try:
            rel_path = f.relative_to(repo_path)
            # Skip __pycache__, .git, and any directory starting with .
            if '__pycache__' not in str(rel_path) and not any(part.startswith('.') for part in rel_path.parts):
                filtered_files.append(f)
        except:
            continue
    py_files = filtered_files

    for py_file in py_files:
        try:
            # Read file with proper encoding
            with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                code = f.read()

            if code:
                # Extract nodes using SAME logic as scan_in_file
                # V1 nodes (enhanced with fallback patterns)
                nodes = extract_nodes_enhanced(code, py_file, visited=set(), verbose=verbose)
                all_nodes.update(nodes)

                # V3 nodes detection
                v3_nodes = extract_v3_nodes(code)
                all_nodes.update(v3_nodes)

                # Dict parsing - exclude commented NODE_CLASS_MAPPINGS lines
                pattern = r"_CLASS_MAPPINGS\s*(?::\s*\w+\s*)?=\s*(?:\\\s*)?{([^}]*)}"
                regex = re.compile(pattern, re.MULTILINE | re.DOTALL)

                for match_obj in regex.finditer(code):
                    # Get the line where NODE_CLASS_MAPPINGS is defined
                    match_start = match_obj.start()
                    line_start = code.rfind('\n', 0, match_start) + 1
                    line_end = code.find('\n', match_start)
                    if line_end == -1:
                        line_end = len(code)
                    line = code[line_start:line_end]

                    # Skip if line starts with # (commented)
                    if re.match(r'^\s*#', line):
                        continue

                    match = match_obj.group(1)

                    # Filter out commented lines from dict content
                    match_lines = match.split('\n')
                    match_filtered = '\n'.join(
                        line for line in match_lines
                        if not re.match(r'^\s*#', line)
                    )

                    # Extract key-value pairs with double quotes
                    key_value_pairs = re.findall(r"\"([^\"]*)\"\s*:\s*([^,\n]*)", match_filtered)
                    for key, value in key_value_pairs:
                        all_nodes.add(key.strip())

                    # Extract key-value pairs with single quotes
                    key_value_pairs = re.findall(r"'([^']*)'\s*:\s*([^,\n]*)", match_filtered)
                    for key, value in key_value_pairs:
                        all_nodes.add(key.strip())

                # Handle .update() pattern (AFTER comment removal)
                code_cleaned = re.sub(r'^#.*?$', '', code, flags=re.MULTILINE)

                update_pattern = r"_CLASS_MAPPINGS\.update\s*\(\s*{([^}]*)}\s*\)"
                update_match = re.search(update_pattern, code_cleaned, re.DOTALL)
                if update_match:
                    update_dict_text = update_match.group(1)
                    # Extract key-value pairs (double quotes)
                    update_pairs = re.findall(r'"([^"]*)"\s*:\s*([^,\n]*)', update_dict_text)
                    for key, value in update_pairs:
                        all_nodes.add(key.strip())
                    # Extract key-value pairs (single quotes)
                    update_pairs_single = re.findall(r"'([^']*)'\s*:\s*([^,\n]*)", update_dict_text)
                    for key, value in update_pairs_single:
                        all_nodes.add(key.strip())

                # Additional regex patterns (AFTER comment removal)
                patterns = [
                    r'^[^=]*_CLASS_MAPPINGS\["(.*?)"\]',
                    r'^[^=]*_CLASS_MAPPINGS\[\'(.*?)\'\]',
                    r'@register_node\("(.+)",\s*\".+"\)',
                    r'"(\w+)"\s*:\s*{"class":\s*\w+\s*'
                ]

                for pattern in patterns:
                    keys = re.findall(pattern, code_cleaned)
                    all_nodes.update(key.strip() for key in keys)

                # Extract metadata from this file
                metadata = extract_metadata_only(str(py_file))
                all_metadata.update(metadata)
        except Exception:
            # Silently skip files that can't be read
            continue

    # Save to per-repo cache
    _save_per_repo_cache(repo_path, all_nodes, all_metadata)

    return (all_nodes, all_metadata)


def _verify_class_exists(node_name: str, code_text: str, file_path: Optional[Path] = None) -> tuple[bool, Optional[str], Optional[int]]:
    """
    Verify that a node class exists and has ComfyUI node structure.

    Returns: (exists: bool, file_path: str, line_number: int)

    A valid ComfyUI node must have:
    - Class definition (not commented)
    - At least one of: INPUT_TYPES, RETURN_TYPES, FUNCTION method/attribute
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning)
            tree = ast.parse(code_text)
    except:
        return (False, None, None)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if node.name == node_name or node.name.replace('_', '') == node_name.replace('_', ''):
                # Found class definition - check if it has ComfyUI interface
                has_input_types = False
                has_return_types = False
                has_function = False

                for item in node.body:
                    # Check for INPUT_TYPES method
                    if isinstance(item, ast.FunctionDef) and item.name == 'INPUT_TYPES':
                        has_input_types = True
                    # Check for RETURN_TYPES attribute
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                if target.id == 'RETURN_TYPES':
                                    has_return_types = True
                                elif target.id == 'FUNCTION':
                                    has_function = True
                    # Check for FUNCTION method
                    elif isinstance(item, ast.FunctionDef):
                        has_function = True

                # Valid if has any ComfyUI signature
                if has_input_types or has_return_types or has_function:
                    file_str = str(file_path) if file_path else None
                    return (True, file_str, node.lineno)

    return (False, None, None)


def _extract_display_name_mappings(code_text: str) -> Set[str]:
    """
    Extract node names from NODE_DISPLAY_NAME_MAPPINGS.

    Pattern:
        NODE_DISPLAY_NAME_MAPPINGS = {
            "node_key": "Display Name",
            ...
        }

    Returns:
        Set of node keys from NODE_DISPLAY_NAME_MAPPINGS
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning)
            tree = ast.parse(code_text)
    except:
        return set()

    nodes = set()

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'NODE_DISPLAY_NAME_MAPPINGS':
                    if isinstance(node.value, ast.Dict):
                        for key in node.value.keys:
                            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                nodes.add(key.value.strip())

    return nodes


def extract_nodes_enhanced(
    code_text: str,
    file_path: Optional[Path] = None,
    visited: Optional[Set[Path]] = None,
    verbose: bool = False
) -> Set[str]:
    """
    Enhanced node extraction with multi-layer detection system.

    Scanner 2.0.11 - Comprehensive detection strategy:
    - Phase 1: NODE_CLASS_MAPPINGS dict literal
    - Phase 2: Class.NAME attribute access (e.g., FreeChat.NAME)
    - Phase 3: Item assignment (NODE_CLASS_MAPPINGS["key"] = value)
    - Phase 4: Class existence verification (detects active classes even if registration commented)
    - Phase 5: NODE_DISPLAY_NAME_MAPPINGS cross-reference
    - Phase 6: Empty dict detection (UI-only extensions, logging only)

    Fixed Bugs:
    - Scanner 2.0.9: Fallback cascade prevented Phase 3 execution
    - Scanner 2.0.10: Missed active classes with commented registrations (15 false negatives)

    Args:
        code_text: Python source code
        file_path: Path to file (for logging and caching)
        visited: Visited paths (for circular import prevention)
        verbose: If True, print UI-only extension detection messages

    Returns:
        Set of node names (union of all detected patterns)
    """
    # Check file-based cache if file_path provided
    if file_path is not None:
        try:
            file_path_obj = Path(file_path) if not isinstance(file_path, Path) else file_path
            if file_path_obj.exists():
                current_mtime = file_path_obj.stat().st_mtime

                # Check if we have cached result with matching mtime and scanner version
                if file_path_obj in _file_mtime_cache:
                    cached_mtime = _file_mtime_cache[file_path_obj]
                    cache_key = (str(file_path_obj), cached_mtime, SCANNER_VERSION)

                    if current_mtime == cached_mtime and cache_key in _extract_nodes_enhanced_cache:
                        return _extract_nodes_enhanced_cache[cache_key].copy()
        except:
            pass  # Ignore cache errors, proceed with normal execution

    # Suppress warnings from AST parsing
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=SyntaxWarning)
        warnings.filterwarnings('ignore', category=DeprecationWarning)

        # Phase 1: Original extract_nodes() - dict literal
        phase1_nodes = extract_nodes(code_text)

    # Phase 2: Class.NAME pattern
    if visited is None:
        visited = set()
    phase2_nodes = _fallback_classname_resolver(code_text, file_path)

    # Phase 3: Item assignment pattern
    phase3_nodes = _fallback_item_assignment(code_text)

    # Phase 4: NODE_DISPLAY_NAME_MAPPINGS cross-reference (NEW in 2.0.11)
    # This catches nodes that are in display names but not in NODE_CLASS_MAPPINGS
    phase4_nodes = _extract_display_name_mappings(code_text)

    # Phase 5: Class existence verification ONLY for display name candidates (NEW in 2.0.11)
    # This phase is CONSERVATIVE - only verify classes that appear in display names
    # This catches the specific Scanner 2.0.10 bug pattern:
    #   - NODE_CLASS_MAPPINGS registration is commented
    #   - NODE_DISPLAY_NAME_MAPPINGS still has the entry
    #   - Class implementation exists
    # Example: Bjornulf_ollamaLoader in Bjornulf_custom_nodes
    phase5_nodes = set()
    for node_name in phase4_nodes:
        # Only check classes that appear in display names but not in registrations
        if node_name not in (phase1_nodes | phase2_nodes | phase3_nodes):
            exists, _, _ = _verify_class_exists(node_name, code_text, file_path)
            if exists:
                phase5_nodes.add(node_name)

    # Phase 6: Dict comprehension pattern (NEW in 2.0.12)
    # Detects: NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in to_export}
    # Example: TobiasGlaubach/ComfyUI-TG_PyCode
    phase6_nodes = _fallback_dict_comprehension(code_text, file_path)

    # Phase 7: Import-based class names for dict comprehension (NEW in 2.0.12)
    # Detects imported classes that are added to export lists
    phase7_nodes = _fallback_import_class_names(code_text, file_path)

    # Union all results (FIX: Scanner 2.0.9 bug + Scanner 2.0.10 bug + Scanner 2.0.12 dict comp)
    # 2.0.9: Used early return which missed Phase 3 nodes
    # 2.0.10: Only checked registrations, missed classes referenced in display names
    # 2.0.12: Added dict comprehension and import-based class detection
    all_nodes = phase1_nodes | phase2_nodes | phase3_nodes | phase4_nodes | phase5_nodes | phase6_nodes | phase7_nodes

    # Phase 8: Empty dict detector (logging only, doesn't add nodes)
    if not all_nodes:
        _fallback_empty_dict_detector(code_text, file_path, verbose)

    # Cache the result
    if file_path is not None:
        try:
            file_path_obj = Path(file_path) if not isinstance(file_path, Path) else file_path
            if file_path_obj.exists():
                current_mtime = file_path_obj.stat().st_mtime
                cache_key = (str(file_path_obj), current_mtime, SCANNER_VERSION)
                _extract_nodes_enhanced_cache[cache_key] = all_nodes
                _file_mtime_cache[file_path_obj] = current_mtime
        except:
            pass

    return all_nodes


def _fallback_classname_resolver(code_text: str, file_path: Optional[Path]) -> Set[str]:
    """
    Detect Class.NAME pattern in NODE_CLASS_MAPPINGS.

    Pattern:
        NODE_CLASS_MAPPINGS = {
            FreeChat.NAME: FreeChat,
            PaidChat.NAME: PaidChat
        }
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning)
            parsed = ast.parse(code_text)
    except:
        return set()
    
    nodes = set()
    
    for node in parsed.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'NODE_CLASS_MAPPINGS':
                    if isinstance(node.value, ast.Dict):
                        for key in node.value.keys:
                            # Detect Class.NAME pattern
                            if isinstance(key, ast.Attribute):
                                if isinstance(key.value, ast.Name):
                                    # Use class name as node name
                                    nodes.add(key.value.id)
                            # Also handle literal strings
                            elif isinstance(key, ast.Constant) and isinstance(key.value, str):
                                nodes.add(key.value.strip())
    
    return nodes


def _fallback_item_assignment(code_text: str) -> Set[str]:
    """
    Detect item assignment pattern.

    Pattern:
        NODE_CLASS_MAPPINGS = {}
        NODE_CLASS_MAPPINGS["MyNode"] = MyNode
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning)
            parsed = ast.parse(code_text)
    except:
        return set()

    nodes = set()

    for node in ast.walk(parsed):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    if (isinstance(target.value, ast.Name) and
                        target.value.id in ['NODE_CLASS_MAPPINGS', 'NODE_CONFIG']):
                        # Extract key
                        if isinstance(target.slice, ast.Constant):
                            if isinstance(target.slice.value, str):
                                nodes.add(target.slice.value)

    return nodes


def _fallback_dict_comprehension(code_text: str, file_path: Optional[Path] = None) -> Set[str]:
    """
    Detect dict comprehension pattern with __name__ attribute access.

    Pattern:
        NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in to_export}
        NODE_CLASS_MAPPINGS = {c.__name__: c for c in [ClassA, ClassB]}

    This function detects dict comprehension assignments to NODE_CLASS_MAPPINGS
    and extracts class names from the iterable (list literal or variable reference).

    Returns:
        Set of class names extracted from the dict comprehension
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning)
            parsed = ast.parse(code_text)
    except:
        return set()

    nodes = set()
    export_lists = {}  # Track list variables and their contents

    # First pass: collect list assignments (to_export = [...], exports = [...])
    for node in ast.walk(parsed):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    # Check for list literal
                    if isinstance(node.value, ast.List):
                        class_names = set()
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Name):
                                class_names.add(elt.id)
                        export_lists[var_name] = class_names

        # Handle augmented assignment: to_export += [...]
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add):
                var_name = node.target.id
                if isinstance(node.value, ast.List):
                    class_names = set()
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Name):
                            class_names.add(elt.id)
                    if var_name in export_lists:
                        export_lists[var_name].update(class_names)
                    else:
                        export_lists[var_name] = class_names

    # Second pass: find NODE_CLASS_MAPPINGS dict comprehension
    for node in ast.walk(parsed):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ['NODE_CLASS_MAPPINGS', 'NODE_CONFIG']:
                    # Check for dict comprehension
                    if isinstance(node.value, ast.DictComp):
                        dictcomp = node.value

                        # Check if key is cls.__name__ pattern
                        key = dictcomp.key
                        if isinstance(key, ast.Attribute) and key.attr == '__name__':
                            # Get the iterable from the first generator
                            for generator in dictcomp.generators:
                                iter_node = generator.iter

                                # Case 1: Inline list [ClassA, ClassB, ...]
                                if isinstance(iter_node, ast.List):
                                    for elt in iter_node.elts:
                                        if isinstance(elt, ast.Name):
                                            nodes.add(elt.id)

                                # Case 2: Variable reference (to_export, exports, etc.)
                                elif isinstance(iter_node, ast.Name):
                                    var_name = iter_node.id
                                    if var_name in export_lists:
                                        nodes.update(export_lists[var_name])

    return nodes


def _fallback_import_class_names(code_text: str, file_path: Optional[Path] = None) -> Set[str]:
    """
    Extract class names from imports that are added to export lists.

    Pattern:
        from .module import ClassA, ClassB
        to_export = [ClassA, ClassB]
        NODE_CLASS_MAPPINGS = {cls.__name__: cls for cls in to_export}

    This is a complementary fallback that works with _fallback_dict_comprehension
    to resolve import-based node registrations.

    Returns:
        Set of imported class names that appear in export-like contexts
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning)
            parsed = ast.parse(code_text)
    except:
        return set()

    # Collect imported names
    imported_names = set()
    for node in ast.walk(parsed):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                imported_names.add(name)

    # Check if these names appear in list assignments that feed into NODE_CLASS_MAPPINGS
    export_candidates = set()
    has_dict_comp_mapping = False

    for node in ast.walk(parsed):
        # Check for dict comprehension NODE_CLASS_MAPPINGS
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'NODE_CLASS_MAPPINGS':
                    if isinstance(node.value, ast.DictComp):
                        has_dict_comp_mapping = True

        # Collect list contents
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.List):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Name) and elt.id in imported_names:
                        export_candidates.add(elt.id)

        # Handle augmented assignment
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.value, ast.List):
                for elt in node.value.elts:
                    if isinstance(elt, ast.Name) and elt.id in imported_names:
                        export_candidates.add(elt.id)

    # Only return if there's a dict comprehension mapping
    if has_dict_comp_mapping:
        return export_candidates

    return set()


def _extract_repo_name(file_path: Path) -> str:
    """
    Extract repository name from file path.

    Path structure: /home/rho/.tmp/analysis/temp/{author}_{reponame}/{path/to/file.py}
    Returns: {author}_{reponame} or filename if extraction fails
    """
    try:
        parts = file_path.parts
        # Find 'temp' directory in path
        if 'temp' in parts:
            temp_idx = parts.index('temp')
            if temp_idx + 1 < len(parts):
                # Next part after 'temp' is the repo directory
                return parts[temp_idx + 1]
    except (ValueError, IndexError):
        pass

    # Fallback to filename if extraction fails
    return file_path.name if hasattr(file_path, 'name') else str(file_path)


def _fallback_empty_dict_detector(code_text: str, file_path: Optional[Path], verbose: bool = False) -> None:
    """
    Detect empty NODE_CLASS_MAPPINGS (UI-only extensions).
    Logs for documentation purposes only (when verbose=True).

    Args:
        code_text: Python source code to analyze
        file_path: Path to the file being analyzed
        verbose: If True, print detection messages
    """
    empty_patterns = [
        'NODE_CLASS_MAPPINGS = {}',
        'NODE_CLASS_MAPPINGS={}',
    ]

    code_normalized = code_text.replace(' ', '').replace('\n', '')

    for pattern in empty_patterns:
        pattern_normalized = pattern.replace(' ', '')
        if pattern_normalized in code_normalized:
            if file_path and verbose:
                repo_name = _extract_repo_name(file_path)
                print(f"Info: UI-only extension (empty NODE_CLASS_MAPPINGS): {repo_name}")
            return

def has_comfy_node_base(class_node):
    """Check if class inherits from io.ComfyNode or ComfyNode"""
    for base in class_node.bases:
        # Case 1: ComfyNode
        if isinstance(base, ast.Name) and base.id == 'ComfyNode':
            return True
        # Case 2: io.ComfyNode
        elif isinstance(base, ast.Attribute):
            if base.attr == 'ComfyNode':
                return True
    return False


def extract_keyword_value(call_node, keyword):
    """
    Extract string value of keyword argument
    Schema(node_id="MyNode") -> "MyNode"
    """
    for kw in call_node.keywords:
        if kw.arg == keyword:
            # ast.Constant (Python 3.8+)
            if isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    return kw.value.value
            # ast.Str (Python 3.7-) - suppress deprecation warning
            else:
                with warnings.catch_warnings():
                    warnings.filterwarnings('ignore', category=DeprecationWarning)
                    if hasattr(ast, 'Str') and isinstance(kw.value, ast.Str):
                        return kw.value.s
    return None


def is_schema_call(call_node):
    """Check if ast.Call is io.Schema() or Schema()"""
    func = call_node.func
    if isinstance(func, ast.Name) and func.id == 'Schema':
        return True
    elif isinstance(func, ast.Attribute) and func.attr == 'Schema':
        return True
    return False


def extract_node_id_from_schema(class_node):
    """
    Extract node_id from define_schema() method
    """
    for item in class_node.body:
        if isinstance(item, ast.FunctionDef) and item.name == 'define_schema':
            # Walk through function body
            for stmt in ast.walk(item):
                if isinstance(stmt, ast.Call):
                    # Check if it's Schema() call
                    if is_schema_call(stmt):
                        node_id = extract_keyword_value(stmt, 'node_id')
                        if node_id:
                            return node_id
    return None


def extract_v3_nodes(code_text):
    """
    Extract V3 node IDs using AST parsing
    Returns: set of node_id strings
    """
    global parse_cnt

    try:
        if parse_cnt % 100 == 0:
            print(".", end="", flush=True)
        parse_cnt += 1

        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=SyntaxWarning)
            warnings.filterwarnings('ignore', category=DeprecationWarning)
            tree = ast.parse(code_text)
    except (SyntaxError, UnicodeDecodeError):
        return set()

    nodes = set()

    # Find io.ComfyNode subclasses
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if inherits from ComfyNode
            if has_comfy_node_base(node):
                node_id = extract_node_id_from_schema(node)
                if node_id:
                    nodes.add(node_id)

    return nodes


# scan
def extract_metadata_only(filename):
    """Extract only metadata (@author, @title, etc) without node scanning"""
    try:
        with open(filename, encoding='utf-8', errors='ignore') as file:
            code = file.read()

        metadata = {}
        lines = code.strip().split('\n')
        for line in lines:
            if line.startswith('@'):
                if line.startswith("@author:") or line.startswith("@title:") or line.startswith("@nickname:") or line.startswith("@description:"):
                    key, value = line[1:].strip().split(':', 1)
                    metadata[key.strip()] = value.strip()

        return metadata
    except:
        return {}


def scan_in_file(filename, is_builtin=False):
    global builtin_nodes

    with open(filename, encoding='utf-8', errors='ignore') as file:
        code = file.read()

    # Support type annotations (e.g., NODE_CLASS_MAPPINGS: Type = {...}) and line continuations (\)
    pattern = r"_CLASS_MAPPINGS\s*(?::\s*\w+\s*)?=\s*(?:\\\s*)?{([^}]*)}"
    regex = re.compile(pattern, re.MULTILINE | re.DOTALL)

    nodes = set()
    class_dict = {}

    # V1 nodes detection (enhanced with fallback patterns)
    nodes |= extract_nodes_enhanced(code, file_path=Path(filename), visited=set())

    # V3 nodes detection
    nodes |= extract_v3_nodes(code)
    code = re.sub(r'^#.*?$', '', code, flags=re.MULTILINE)

    def extract_keys(pattern, code):
        keys = re.findall(pattern, code)
        return {key.strip() for key in keys}

    def update_nodes(nodes, new_keys):
        nodes |= new_keys

    patterns = [
        r'^[^=]*_CLASS_MAPPINGS\["(.*?)"\]',
        r'^[^=]*_CLASS_MAPPINGS\[\'(.*?)\'\]',
        r'@register_node\("(.+)",\s*\".+"\)',
        r'"(\w+)"\s*:\s*{"class":\s*\w+\s*'
    ]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(extract_keys, pattern, code): pattern for pattern in patterns}
        for future in concurrent.futures.as_completed(futures):
            update_nodes(nodes, future.result())

    matches = regex.findall(code)
    for match in matches:
        dict_text = match

        key_value_pairs = re.findall(r"\"([^\"]*)\"\s*:\s*([^,\n]*)", dict_text)
        for key, value in key_value_pairs:
            class_dict[key.strip()] = value.strip()

        key_value_pairs = re.findall(r"'([^']*)'\s*:\s*([^,\n]*)", dict_text)
        for key, value in key_value_pairs:
            class_dict[key.strip()] = value.strip()

        for key, value in class_dict.items():
            nodes.add(key.strip())

        update_pattern = r"_CLASS_MAPPINGS.update\s*\({([^}]*)}\)"
        update_match = re.search(update_pattern, code)
        if update_match:
            update_dict_text = update_match.group(1)
            update_key_value_pairs = re.findall(r"\"([^\"]*)\"\s*:\s*([^,\n]*)", update_dict_text)
            for key, value in update_key_value_pairs:
                class_dict[key.strip()] = value.strip()
                nodes.add(key.strip())

    metadata = {}
    lines = code.strip().split('\n')
    for line in lines:
        if line.startswith('@'):
            if line.startswith("@author:") or line.startswith("@title:") or line.startswith("@nickname:") or line.startswith("@description:"):
                key, value = line[1:].strip().split(':', 1)
                metadata[key.strip()] = value.strip()

    if is_builtin:
        builtin_nodes += set(nodes)
    else:
        for x in builtin_nodes:
            if x in nodes:
                nodes.remove(x)

    return nodes, metadata


def get_py_file_paths(dirname):
    file_paths = []
    
    for root, dirs, files in os.walk(dirname):
        if ".git" in root or "__pycache__" in root:
            continue

        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                file_paths.append(file_path)
    
    return file_paths


def get_nodes(target_dir):
    py_files = []
    directories = []
    
    for item in os.listdir(target_dir):
        if ".git" in item or "__pycache__" in item:
            continue

        path = os.path.abspath(os.path.join(target_dir, item))
        
        if os.path.isfile(path) and item.endswith(".py"):
            py_files.append(path)
        elif os.path.isdir(path):
            directories.append(path)
    
    return py_files, directories


def get_urls_from_list_file(list_file):
    """
    Read URLs from list file for scan-only mode

    Args:
        list_file (str): Path to URL list file (one URL per line)

    Returns:
        list of tuples: [(url, "", None, None), ...]
        Format: (url, title, preemptions, nodename_pattern)
        - title: Empty string
        - preemptions: None
        - nodename_pattern: None

    File format:
        https://github.com/owner/repo1
        https://github.com/owner/repo2
        # Comments starting with # are ignored

    Raises:
        FileNotFoundError: If list_file does not exist
    """
    if not os.path.exists(list_file):
        raise FileNotFoundError(f"URL list file not found: {list_file}")

    urls = []
    with open(list_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            # Validate URL format (basic check)
            if not (line.startswith('http://') or line.startswith('https://')):
                print(f"WARNING: Line {line_num} is not a valid URL: {line}")
                continue

            # Add URL with empty metadata
            # (url, title, preemptions, nodename_pattern)
            urls.append((line, "", None, None))

    print(f"Loaded {len(urls)} URLs from {list_file}")
    return urls


def get_git_urls_from_json(json_file):
    with open(json_file, encoding='utf-8') as file:
        data = json.load(file)

        custom_nodes = data.get('custom_nodes', [])
        git_clone_files = []
        for node in custom_nodes:
            if node.get('install_type') == 'git-clone':
                files = node.get('files', [])
                if files:
                    git_clone_files.append((files[0], node.get('title'), node.get('preemptions'), node.get('nodename_pattern')))

    git_clone_files.append(("https://github.com/comfyanonymous/ComfyUI", "ComfyUI", None, None))

    return git_clone_files


def get_py_urls_from_json(json_file):
    with open(json_file, encoding='utf-8') as file:
        data = json.load(file)

        custom_nodes = data.get('custom_nodes', [])
        py_files = []
        for node in custom_nodes:
            if node.get('install_type') == 'copy':
                files = node.get('files', [])
                if files:
                    py_files.append((files[0], node.get('title'), node.get('preemptions'), node.get('nodename_pattern')))

    return py_files


def clone_or_pull_git_repository(git_url):
    repo_name = git_url.split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
        
    repo_dir = os.path.join(temp_dir, repo_name)

    if os.path.exists(repo_dir):
        try:
            repo = Repo(repo_dir)
            origin = repo.remote(name="origin")
            origin.pull()
            repo.git.submodule('update', '--init', '--recursive')
            print(f"Pulling {repo_name}...")
        except Exception as e:
            print(f"Failed to pull '{repo_name}': {e}")
    else:
        try:
            Repo.clone_from(git_url, repo_dir, recursive=True)
            print(f"Cloning {repo_name}...")
        except Exception as e:
            print(f"Failed to clone '{repo_name}': {e}")


def update_custom_nodes(scan_only_mode=False, url_list_file=None):
    """
    Update custom nodes by cloning/pulling repositories

    Args:
        scan_only_mode (bool): If True, use URL list file instead of custom-node-list.json
        url_list_file (str): Path to URL list file (required if scan_only_mode=True)

    Returns:
        dict: node_info mapping {repo_name: (url, title, preemptions, node_pattern)}
    """
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    node_info = {}

    # Select URL source based on mode
    if scan_only_mode:
        if not url_list_file:
            raise ValueError("url_list_file is required in scan-only mode")

        git_url_titles_preemptions = get_urls_from_list_file(url_list_file)
        print("\n[Scan-Only Mode]")
        print(f"  - URL source: {url_list_file}")
        print("  - GitHub stats: DISABLED")
        print(f"  - Git clone/pull: {'ENABLED' if not skip_update else 'DISABLED'}")
        print("  - Metadata: EMPTY")
    else:
        if not os.path.exists('custom-node-list.json'):
            raise FileNotFoundError("custom-node-list.json not found")

        git_url_titles_preemptions = get_git_urls_from_json('custom-node-list.json')
        print("\n[Standard Mode]")
        print("  - URL source: custom-node-list.json")
        print(f"  - GitHub stats: {'ENABLED' if not skip_stat_update else 'DISABLED'}")
        print(f"  - Git clone/pull: {'ENABLED' if not skip_update else 'DISABLED'}")
        print("  - Metadata: FULL")

    def process_git_url_title(url, title, preemptions, node_pattern):
        name = os.path.basename(url)
        if name.endswith(".git"):
            name = name[:-4]
        
        node_info[name] = (url, title, preemptions, node_pattern)
        if not skip_update:
            clone_or_pull_git_repository(url)

    def process_git_stats(git_url_titles_preemptions):
        GITHUB_STATS_CACHE_FILENAME = 'github-stats-cache.json'
        GITHUB_STATS_FILENAME = 'github-stats.json'

        github_stats = {}
        try:
            with open(GITHUB_STATS_CACHE_FILENAME, 'r', encoding='utf-8') as file:
                github_stats = json.load(file)
        except FileNotFoundError:
            pass

        def is_rate_limit_exceeded():
            return g.rate_limiting[0] <= 20

        if is_rate_limit_exceeded():
            print(f"GitHub API Rate Limit Exceeded: remained - {(g.rate_limiting_resettime - datetime.datetime.now().timestamp())/60:.2f} min")
        else:
            def renew_stat(url):
                if is_rate_limit_exceeded():
                    return

                if 'github.com' not in url:
                    return None

                print('.', end="")
                sys.stdout.flush()
                try:
                    # Parsing the URL
                    parsed_url = urlparse(url)
                    domain = parsed_url.netloc
                    path = parsed_url.path
                    path_parts = path.strip("/").split("/")
                    if len(path_parts) >= 2 and domain == "github.com":
                        owner_repo = "/".join(path_parts[-2:])
                        repo = g.get_repo(owner_repo)
                        owner = repo.owner
                        now = datetime.datetime.now(datetime.timezone.utc)
                        author_time_diff = now - owner.created_at
                        
                        last_update = repo.pushed_at.strftime("%Y-%m-%d %H:%M:%S") if repo.pushed_at else 'N/A'
                        item = {
                            "stars": repo.stargazers_count,
                            "last_update": last_update,
                            "cached_time": now.timestamp(),
                            "author_account_age_days": author_time_diff.days,
                        }
                        return url, item
                    else:
                        print(f"\nInvalid URL format for GitHub repository: {url}\n")
                except Exception as e:
                    print(f"\nERROR on {url}\n{e}")

                return None

            # resolve unresolved urls
            with concurrent.futures.ThreadPoolExecutor(11) as executor:
                futures = []
                for url, title, preemptions, node_pattern in git_url_titles_preemptions:
                    if url not in github_stats:
                        futures.append(executor.submit(renew_stat, url))

                for future in concurrent.futures.as_completed(futures):
                    url_item = future.result()
                    if url_item is not None:
                        url, item = url_item
                        github_stats[url] = item

            # renew outdated cache
            outdated_urls = []
            for k, v in github_stats.items():
                elapsed = (datetime.datetime.now().timestamp() - v['cached_time'])
                if elapsed > 60*60*12:  # 12 hours
                    outdated_urls.append(k)

            with concurrent.futures.ThreadPoolExecutor(11) as executor:
                for url in outdated_urls:
                    futures.append(executor.submit(renew_stat, url))

                for future in concurrent.futures.as_completed(futures):
                    url_item = future.result()
                    if url_item is not None:
                        url, item = url_item
                        github_stats[url] = item
                        
            with open('github-stats-cache.json', 'w', encoding='utf-8') as file:
                json.dump(github_stats, file, ensure_ascii=False, indent=4)

        with open(GITHUB_STATS_FILENAME, 'w', encoding='utf-8') as file:
            for v in github_stats.values():
                if "cached_time" in v:
                    del v["cached_time"]

            github_stats = dict(sorted(github_stats.items()))

            json.dump(github_stats, file, ensure_ascii=False, indent=4)

        print(f"Successfully written to {GITHUB_STATS_FILENAME}.")

    if not skip_stat_update:
        process_git_stats(git_url_titles_preemptions)

    # Git clone/pull for all repositories
    with concurrent.futures.ThreadPoolExecutor(11) as executor:
        for url, title, preemptions, node_pattern in git_url_titles_preemptions:
            executor.submit(process_git_url_title, url, title, preemptions, node_pattern)

    # .py file download (skip in scan-only mode - only process git repos)
    if not scan_only_mode:
        py_url_titles_and_pattern = get_py_urls_from_json('custom-node-list.json')

        def download_and_store_info(url_title_preemptions_and_pattern):
            url, title, preemptions, node_pattern = url_title_preemptions_and_pattern
            name = os.path.basename(url)
            if name.endswith(".py"):
                node_info[name] = (url, title, preemptions, node_pattern)

            try:
                download_url(url, temp_dir)
            except:
                print(f"[ERROR] Cannot download '{url}'")

        with concurrent.futures.ThreadPoolExecutor(10) as executor:
            executor.map(download_and_store_info, py_url_titles_and_pattern)

    return node_info


def gen_json(node_info, scan_only_mode=False, force_rescan=False):
    """
    Generate extension-node-map.json from scanned node information

    Args:
        node_info (dict): Repository metadata mapping
        scan_only_mode (bool): If True, exclude metadata from output
        force_rescan (bool): If True, ignore cache and force rescan all nodes
    """
    # scan from .py file
    node_files, node_dirs = get_nodes(temp_dir)

    comfyui_path = os.path.abspath(os.path.join(temp_dir, "ComfyUI"))
    # Only reorder if ComfyUI exists in the list
    if comfyui_path in node_dirs:
        node_dirs.remove(comfyui_path)
        node_dirs = [comfyui_path] + node_dirs

    data = {}
    for dirname in node_dirs:
        py_files = get_py_file_paths(dirname)
        metadata = {}

        # Use per-repo cache for node AND metadata extraction
        try:
            nodes, metadata = extract_nodes_from_repo(Path(dirname), verbose=False, force_rescan=force_rescan)
        except:
            # Fallback to file-by-file scanning if extract_nodes_from_repo fails
            nodes = set()
            for py in py_files:
                nodes_in_file, metadata_in_file = scan_in_file(py, dirname == "ComfyUI")
                nodes.update(nodes_in_file)
                metadata.update(metadata_in_file)

        dirname = os.path.basename(dirname)

        if 'Jovimetrix' in dirname:
            pass

        if len(nodes) > 0 or (dirname in node_info and node_info[dirname][3] is not None):
            nodes = list(nodes)
            nodes.sort()

            if dirname in node_info:
                git_url, title, preemptions, node_pattern = node_info[dirname]

                # Conditionally add metadata based on mode
                if not scan_only_mode:
                    # Standard mode: include all metadata
                    metadata['title_aux'] = title

                    if preemptions is not None:
                        metadata['preemptions'] = preemptions

                    if node_pattern is not None:
                        metadata['nodename_pattern'] = node_pattern
                # Scan-only mode: metadata remains empty

                data[git_url] = (nodes, metadata)
            else:
                # Scan-only mode: Repository not in node_info (expected behavior)
                # Construct URL from dirname (author_repo format)
                if '_' in dirname:
                    parts = dirname.split('_', 1)
                    git_url = f"https://github.com/{parts[0]}/{parts[1]}"
                    data[git_url] = (nodes, metadata)
                else:
                    print(f"WARN: {dirname} is removed from custom-node-list.json")

    for file in node_files:
        nodes, metadata = scan_in_file(file)

        if len(nodes) > 0 or (dirname in node_info and node_info[dirname][3] is not None):
            nodes = list(nodes)
            nodes.sort()

            file = os.path.basename(file)

            if file in node_info:
                url, title, preemptions, node_pattern = node_info[file]

                # Conditionally add metadata based on mode
                if not scan_only_mode:
                    metadata['title_aux'] = title

                    if preemptions is not None:
                        metadata['preemptions'] = preemptions

                    if node_pattern is not None:
                        metadata['nodename_pattern'] = node_pattern

                data[url] = (nodes, metadata)
            else:
                print(f"Missing info: {file}")

    # scan from node_list.json file
    extensions = [name for name in os.listdir(temp_dir) if os.path.isdir(os.path.join(temp_dir, name))]

    for extension in extensions:
        node_list_json_path = os.path.join(temp_dir, extension, 'node_list.json')
        if os.path.exists(node_list_json_path):
            # Skip if extension not in node_info (scan-only mode with limited URLs)
            if extension not in node_info:
                continue

            git_url, title, preemptions, node_pattern = node_info[extension]

            with open(node_list_json_path, 'r', encoding='utf-8') as f:
                try:
                    node_list_json = json.load(f)
                except Exception as e:
                    print(f"\nERROR: Invalid json format '{node_list_json_path}'")
                    print("------------------------------------------------------")
                    print(e)
                    print("------------------------------------------------------")
                    node_list_json = {}

            metadata_in_url = {}
            if git_url not in data:
                nodes = set()
            else:
                nodes_in_url, metadata_in_url = data[git_url]
                nodes = set(nodes_in_url)

            try:
                for x, desc in node_list_json.items():
                    nodes.add(x.strip())
            except Exception as e:
                print(f"\nERROR: Invalid json format '{node_list_json_path}'")
                print("------------------------------------------------------")
                print(e)
                print("------------------------------------------------------")
                node_list_json = {}

            # Conditionally add metadata based on mode
            if not scan_only_mode:
                metadata_in_url['title_aux'] = title

                if preemptions is not None:
                    metadata_in_url['preemptions'] = preemptions

                if node_pattern is not None:
                    metadata_in_url['nodename_pattern'] = node_pattern

            nodes = list(nodes)
            nodes.sort()
            data[git_url] = (nodes, metadata_in_url)

    json_path = "extension-node-map.json"
    with open(json_path, "w", encoding='utf-8') as file:
        json.dump(data, file, indent=4, sort_keys=True)


if __name__ == "__main__":
    # Parse arguments
    args = parse_arguments()

    # Determine mode
    scan_only_mode = args.scan_only is not None
    url_list_file = args.scan_only if scan_only_mode else None

    # Determine temp_dir
    if args.temp_dir:
        temp_dir = args.temp_dir
    elif args.temp_dir_positional:
        temp_dir = args.temp_dir_positional
    else:
        temp_dir = os.path.join(os.getcwd(), ".tmp")

    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    # Determine skip flags
    skip_update = args.skip_update or args.skip_all
    skip_stat_update = args.skip_stat_update or args.skip_all or scan_only_mode

    if not skip_stat_update:
        auth = Auth.Token(os.environ.get('GITHUB_TOKEN'))
        g = Github(auth=auth)
    else:
        g = None

    print("### ComfyUI Manager Node Scanner ###")

    if scan_only_mode:
        print(f"\n# [Scan-Only Mode] Processing URL list: {url_list_file}\n")
    else:
        print("\n# [Standard Mode] Updating extensions\n")

    # Update/clone repositories and collect node info
    updated_node_info = update_custom_nodes(scan_only_mode, url_list_file)

    print("\n# Generating 'extension-node-map.json'...\n")

    # Generate extension-node-map.json
    force_rescan = args.force_rescan if hasattr(args, 'force_rescan') else False
    if force_rescan:
        print("⚠️  Force rescan enabled - ignoring all cached results\n")
    gen_json(updated_node_info, scan_only_mode, force_rescan)

    print("\n✅ DONE.\n")

    if scan_only_mode:
        print("Output: extension-node-map.json (node mappings only)")
    else:
        print("Output: extension-node-map.json (full metadata)")
