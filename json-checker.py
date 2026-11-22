#!/usr/bin/env python3
"""JSON Entry Validator

Validates JSON entries based on content structure.

Validation rules based on JSON content:
- {"custom_nodes": [...]}: Validates required fields (author, title, reference, files, install_type, description)
- {"models": [...]}: Validates JSON syntax only (no required fields)
- Other JSON structures: Validates JSON syntax only

Git repository URL validation (for custom_nodes):
1. URLs must NOT end with .git
2. URLs must follow format: https://github.com/{author}/{reponame}
3. .py and .js files are exempt from this check

Supported formats:
- Array format: [{...}, {...}]
- Object format: {"custom_nodes": [...]} or {"models": [...]}
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


# Required fields for each entry type
REQUIRED_FIELDS_CUSTOM_NODE = ['author', 'title', 'reference', 'files', 'install_type', 'description']
REQUIRED_FIELDS_MODEL = []  # model-list.json doesn't require field validation

# Pattern for valid GitHub repository URL (without .git suffix)
GITHUB_REPO_PATTERN = re.compile(r'^https://github\.com/[^/]+/[^/]+$')


def get_entry_context(entry: Dict) -> str:
    """Get identifying information from entry for error messages

    Args:
        entry: JSON entry

    Returns:
        String with author and reference info
    """
    parts = []
    if 'author' in entry:
        parts.append(f"author={entry['author']}")
    if 'reference' in entry:
        parts.append(f"ref={entry['reference']}")
    if 'title' in entry:
        parts.append(f"title={entry['title']}")

    if parts:
        return " | ".join(parts)
    else:
        # No identifying info - show actual entry content (truncated)
        import json
        entry_str = json.dumps(entry, ensure_ascii=False)
        if len(entry_str) > 100:
            entry_str = entry_str[:100] + "..."
        return f"content={entry_str}"


def validate_required_fields(entry: Dict, entry_index: int, required_fields: List[str]) -> List[str]:
    """Validate that all required fields are present

    Args:
        entry: JSON entry to validate
        entry_index: Index of entry in array (for error reporting)
        required_fields: List of required field names

    Returns:
        List of error descriptions (without entry prefix/context)
    """
    errors = []

    for field in required_fields:
        if field not in entry:
            errors.append(f"Missing required field '{field}'")
        elif entry[field] is None:
            errors.append(f"Field '{field}' is null")
        elif isinstance(entry[field], str) and not entry[field].strip():
            errors.append(f"Field '{field}' is empty")
        elif field == 'files' and not entry[field]:  # Empty array
            errors.append("Field 'files' is empty array")

    return errors


def validate_git_repo_urls(entry: Dict, entry_index: int) -> List[str]:
    """Validate git repository URLs in 'files' array

    Requirements:
    - Git repo URLs must NOT end with .git
    - Must follow format: https://github.com/{author}/{reponame}
    - .py and .js files are exempt

    Args:
        entry: JSON entry to validate
        entry_index: Index of entry in array (for error reporting)

    Returns:
        List of error descriptions (without entry prefix/context)
    """
    errors = []

    if 'files' not in entry or not isinstance(entry['files'], list):
        return errors

    for file_url in entry['files']:
        if not isinstance(file_url, str):
            continue

        # Skip .py and .js files - they're exempt from git repo validation
        if file_url.endswith('.py') or file_url.endswith('.js'):
            continue

        # Check if it's a GitHub URL (likely a git repo)
        if 'github.com' in file_url:
            # Error if URL ends with .git
            if file_url.endswith('.git'):
                errors.append(f"Git repo URL must NOT end with .git: {file_url}")
                continue

            # Validate format: https://github.com/{author}/{reponame}
            if not GITHUB_REPO_PATTERN.match(file_url):
                errors.append(f"Invalid git repo URL format (expected https://github.com/author/reponame): {file_url}")

    return errors


def validate_entry(entry: Dict, entry_index: int, required_fields: List[str]) -> List[str]:
    """Validate a single JSON entry

    Args:
        entry: JSON entry to validate
        entry_index: Index of entry in array (for error reporting)
        required_fields: List of required field names

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Check required fields
    errors.extend(validate_required_fields(entry, entry_index, required_fields))

    # Check git repository URLs
    errors.extend(validate_git_repo_urls(entry, entry_index))

    return errors


def validate_json_file(file_path: str) -> Tuple[bool, List[str]]:
    """Validate JSON file containing entries

    Args:
        file_path: Path to JSON file

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []

    # Check file exists
    path = Path(file_path)
    if not path.exists():
        return False, [f"File not found: {file_path}"]

    # Load JSON
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]
    except Exception as e:
        return False, [f"Error reading file: {e}"]

    # Determine required fields based on JSON content
    required_fields = []

    # Validate structure - support both array and object formats
    entries_to_validate = []

    if isinstance(data, list):
        # Direct array format: [{...}, {...}]
        entries_to_validate = data
    elif isinstance(data, dict):
        # Object format: {"custom_nodes": [...]} or {"models": [...]}
        # Determine validation based on keys
        if 'custom_nodes' in data and isinstance(data['custom_nodes'], list):
            required_fields = REQUIRED_FIELDS_CUSTOM_NODE
            entries_to_validate = data['custom_nodes']
        elif 'models' in data and isinstance(data['models'], list):
            required_fields = REQUIRED_FIELDS_MODEL
            entries_to_validate = data['models']
        else:
            # Other JSON structures (extension-node-map.json, etc.) - just validate JSON syntax
            return True, []
    else:
        return False, ["JSON root must be either an array or an object containing arrays"]

    # Validate each entry
    for idx, entry in enumerate(entries_to_validate, start=1):
        if not isinstance(entry, dict):
            # Show actual value for type errors
            entry_str = json.dumps(entry, ensure_ascii=False) if not isinstance(entry, str) else repr(entry)
            if len(entry_str) > 150:
                entry_str = entry_str[:150] + "..."
            errors.append(f"\n❌ Entry #{idx}: Must be an object, got {type(entry).__name__}")
            errors.append(f"   Actual value: {entry_str}")
            continue

        entry_errors = validate_entry(entry, idx, required_fields)
        if entry_errors:
            # Group errors by entry with context
            context = get_entry_context(entry)
            errors.append(f"\n❌ Entry #{idx} ({context}):")
            for error in entry_errors:
                errors.append(f"   - {error}")

    is_valid = len(errors) == 0
    return is_valid, errors


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python json-checker.py <json-file>")
        print("\nValidates JSON entries based on content:")
        print("  - {\"custom_nodes\": [...]}: Validates required fields (author, title, reference, files, install_type, description)")
        print("  - {\"models\": [...]}: Validates JSON syntax only (no required fields)")
        print("  - Other JSON structures: Validates JSON syntax only")
        print("\nGit repo URL validation (for custom_nodes):")
        print("  - URLs must NOT end with .git")
        print("  - URLs must follow: https://github.com/{author}/{reponame}")
        sys.exit(1)

    file_path = sys.argv[1]

    is_valid, errors = validate_json_file(file_path)

    if is_valid:
        print(f"✅ {file_path}: Validation passed")
        sys.exit(0)
    else:
        print(f"Validating: {file_path}")
        print("=" * 60)
        print("❌ Validation failed!\n")
        print("Errors:")
        # Count actual errors (lines starting with "   -")
        error_count = sum(1 for e in errors if e.strip().startswith('-'))
        for error in errors:
            # Don't add ❌ prefix to grouped entries (they already have it)
            if error.strip().startswith('❌'):
                print(error)
            else:
                print(error)
        print(f"\nTotal errors: {error_count}")
        sys.exit(1)


if __name__ == '__main__':
    main()
