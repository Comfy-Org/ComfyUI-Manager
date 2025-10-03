#!/usr/bin/env python3
"""
Dependency Tree Analyzer for pip_util Tests

Usage:
    python analyze_dependencies.py [package]
    python analyze_dependencies.py --all
    python analyze_dependencies.py --update-context

Examples:
    python analyze_dependencies.py requests
    python analyze_dependencies.py python-dateutil
    python analyze_dependencies.py --all
"""

import subprocess
import sys
from typing import Dict, List, Tuple, Optional
from pathlib import Path


PIP = "./test_venv/bin/pip"


def check_venv():
    """Check if test venv exists"""
    if not Path(PIP).exists():
        print("❌ Test venv not found!")
        print("   Run: ./setup_test_env.sh")
        sys.exit(1)


def get_installed_packages() -> Dict[str, str]:
    """Get currently installed packages"""
    result = subprocess.run(
        [PIP, "freeze"],
        capture_output=True,
        text=True,
        check=True
    )

    packages = {}
    for line in result.stdout.strip().split('\n'):
        if '==' in line:
            pkg, ver = line.split('==', 1)
            packages[pkg] = ver

    return packages


def analyze_package_dry_run(
    package: str,
    constraints: Optional[List[str]] = None
) -> Tuple[List[Tuple[str, str]], Dict[str, str]]:
    """
    Analyze what would be installed with --dry-run

    Returns:
        - List of (package_name, version) tuples in install order
        - Dict of current_version → new_version for upgrades
    """
    cmd = [PIP, "install", "--dry-run", "--ignore-installed", package]
    if constraints:
        cmd.extend(constraints)

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Parse "Would install" line
    would_install = []
    for line in result.stdout.split('\n'):
        if 'Would install' in line:
            packages_str = line.split('Would install')[1].strip()
            for pkg_str in packages_str.split():
                parts = pkg_str.split('-', 1)
                if len(parts) == 2:
                    would_install.append((parts[0], parts[1]))

    # Check against current installed
    installed = get_installed_packages()
    changes = {}
    for pkg, new_ver in would_install:
        if pkg in installed:
            old_ver = installed[pkg]
            if old_ver != new_ver:
                changes[pkg] = (old_ver, new_ver)

    return would_install, changes


def get_available_versions(package: str, limit: int = 10) -> Tuple[str, List[str]]:
    """
    Get available versions from PyPI

    Returns:
        - Latest version
        - List of available versions (limited)
    """
    result = subprocess.run(
        [PIP, "index", "versions", package],
        capture_output=True,
        text=True
    )

    latest = None
    versions = []

    for line in result.stdout.split('\n'):
        if 'LATEST:' in line:
            latest = line.split('LATEST:')[1].strip()
        elif 'Available versions:' in line:
            versions_str = line.split('Available versions:')[1].strip()
            versions = [v.strip() for v in versions_str.split(',')[:limit]]

    return latest, versions


def print_package_analysis(package: str, with_pin: bool = False):
    """Print detailed analysis for a package"""
    print(f"\n{'='*80}")
    print(f"Package: {package}")
    print(f"{'='*80}")

    installed = get_installed_packages()

    # Get latest version
    latest, available = get_available_versions(package)
    if latest:
        print(f"\n📦 Latest version: {latest}")
        print(f"📋 Available versions: {', '.join(available[:5])}")

    # Scenario 1: Without constraints
    print(f"\n🔍 Scenario A: Install without constraints")
    print(f"   Command: pip install {package}")

    would_install, changes = analyze_package_dry_run(package)

    if would_install:
        print(f"\n   Would install {len(would_install)} packages:")
        for pkg, ver in would_install:
            if pkg in changes:
                old_ver, new_ver = changes[pkg]
                print(f"     • {pkg:25} {old_ver:15} → {new_ver:15} ⚠️ UPGRADE")
            elif pkg in installed:
                print(f"     • {pkg:25} {ver:15} (already installed)")
            else:
                print(f"     • {pkg:25} {ver:15} ✨ NEW")

    # Scenario 2: With pin constraints (if dependencies exist)
    dependencies = [pkg for pkg, _ in would_install if pkg != package]
    if dependencies and with_pin:
        print(f"\n🔍 Scenario B: Install with pin constraints")

        # Create pin constraints for all current dependencies
        constraints = []
        for dep in dependencies:
            if dep in installed:
                constraints.append(f"{dep}=={installed[dep]}")

        if constraints:
            print(f"   Command: pip install {package} {' '.join(constraints)}")

            would_install_pinned, changes_pinned = analyze_package_dry_run(
                package, constraints
            )

            print(f"\n   Would install {len(would_install_pinned)} packages:")
            for pkg, ver in would_install_pinned:
                if pkg in constraints:
                    print(f"     • {pkg:25} {ver:15} 📌 PINNED")
                elif pkg in installed:
                    print(f"     • {pkg:25} {ver:15} (no change)")
                else:
                    print(f"     • {pkg:25} {ver:15} ✨ NEW")

            # Show what was prevented
            prevented = set(changes.keys()) - set(changes_pinned.keys())
            if prevented:
                print(f"\n   ✅ Pin prevented {len(prevented)} upgrade(s):")
                for pkg in prevented:
                    old_ver, new_ver = changes[pkg]
                    print(f"     • {pkg:25} {old_ver:15} ❌→ {new_ver}")


def analyze_all_test_packages():
    """Analyze all packages used in tests"""
    print("="*80)
    print("ANALYZING ALL TEST PACKAGES")
    print("="*80)

    test_packages = [
        ("requests", True),
        ("python-dateutil", True),
    ]

    for package, with_pin in test_packages:
        print_package_analysis(package, with_pin)

    print(f"\n{'='*80}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*80}")


def print_current_environment():
    """Print current test environment"""
    print("="*80)
    print("CURRENT TEST ENVIRONMENT")
    print("="*80)

    installed = get_installed_packages()

    print(f"\nTotal packages: {len(installed)}\n")

    # Group by category
    test_packages = ["urllib3", "certifi", "charset-normalizer", "six", "attrs", "packaging"]
    framework = ["pytest", "iniconfig", "pluggy", "Pygments"]

    print("Test packages:")
    for pkg in test_packages:
        if pkg in installed:
            print(f"  {pkg:25} {installed[pkg]}")

    print("\nTest framework:")
    for pkg in framework:
        if pkg in installed:
            print(f"  {pkg:25} {installed[pkg]}")

    other = set(installed.keys()) - set(test_packages) - set(framework)
    if other:
        print("\nOther packages:")
        for pkg in sorted(other):
            print(f"  {pkg:25} {installed[pkg]}")


def main():
    """Main entry point"""
    check_venv()

    if len(sys.argv) == 1:
        print("Usage: python analyze_dependencies.py [package|--all|--env]")
        print("\nExamples:")
        print("  python analyze_dependencies.py requests")
        print("  python analyze_dependencies.py --all")
        print("  python analyze_dependencies.py --env")
        sys.exit(0)

    command = sys.argv[1]

    if command == "--all":
        analyze_all_test_packages()
    elif command == "--env":
        print_current_environment()
    elif command.startswith("--"):
        print(f"Unknown option: {command}")
        sys.exit(1)
    else:
        # Analyze specific package
        print_package_analysis(command, with_pin=True)


if __name__ == "__main__":
    main()
