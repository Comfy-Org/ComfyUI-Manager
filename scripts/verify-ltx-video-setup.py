#!/usr/bin/env python3
"""
ComfyUI + LTX-Video Setup Verification Script

This script verifies that ComfyUI and LTX-Video are correctly installed.
Run this after installation to validate the setup before generating videos.

Usage:
    python verify-ltx-video-setup.py
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

# Color codes for output
class Colors:
    SUCCESS = '\033[92m'   # Green
    WARNING = '\033[93m'   # Yellow
    ERROR = '\033[91m'     # Red
    INFO = '\033[94m'      # Blue
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_success(msg: str):
    print(f"{Colors.SUCCESS}✓ {msg}{Colors.RESET}")

def print_warning(msg: str):
    print(f"{Colors.WARNING}⚠ {msg}{Colors.RESET}")

def print_error(msg: str):
    print(f"{Colors.ERROR}✗ {msg}{Colors.RESET}")

def print_info(msg: str):
    print(f"{Colors.INFO}ℹ {msg}{Colors.RESET}")

def print_header(msg: str):
    print(f"\n{Colors.BOLD}{msg}{Colors.RESET}")

def find_comfyui_root() -> Path:
    """Find the ComfyUI installation directory."""
    current = Path.cwd()
    
    # Check if we're already in ComfyUI directory
    if (current / "main.py").exists() and (current / "custom_nodes").exists():
        return current
    
    # Check parent directory
    if (current.parent / "ComfyUI").exists():
        return current.parent / "ComfyUI"
    
    # Check common paths
    home = Path.home()
    common_paths = [
        home / "ComfyUI",
        home / "ComfyUI-LTX",
        Path("/home/comfyui"),
        Path("/opt/comfyui"),
    ]
    
    for path in common_paths:
        if (path / "main.py").exists():
            return path
    
    return None

def check_python_version() -> bool:
    """Verify Python version is 3.9+."""
    print_header("Checking Python Version")
    
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    
    if version.major >= 3 and version.minor >= 9:
        print_success(f"Python {version_str} (required: 3.9+)")
        return True
    else:
        print_error(f"Python {version_str} (required: 3.9+)")
        return False

def check_dependencies() -> bool:
    """Check if critical Python packages are installed."""
    print_header("Checking Python Dependencies")
    
    required_packages = {
        "torch": "PyTorch",
        "torchvision": "torchvision",
        "PIL": "Pillow",
        "cv2": "OpenCV",
        "git": "GitPython",
        "requests": "requests",
    }
    
    all_ok = True
    for import_name, package_name in required_packages.items():
        try:
            __import__(import_name)
            print_success(f"{package_name}")
        except ImportError:
            print_error(f"{package_name} - NOT INSTALLED")
            all_ok = False
    
    return all_ok

def check_comfyui_installation(comfyui_root: Path) -> bool:
    """Verify ComfyUI is properly installed."""
    print_header("Checking ComfyUI Installation")
    
    checks = {
        "main.py": comfyui_root / "main.py",
        "requirements.txt": comfyui_root / "requirements.txt",
        "custom_nodes/": comfyui_root / "custom_nodes",
        "models/": comfyui_root / "models",
    }
    
    all_ok = True
    for name, path in checks.items():
        if path.exists():
            print_success(f"{name} found at {path}")
        else:
            print_error(f"{name} not found - expected at {path}")
            all_ok = False
    
    return all_ok

def check_manager_installation(comfyui_root: Path) -> bool:
    """Verify ComfyUI-Manager is installed."""
    print_header("Checking ComfyUI-Manager")
    
    manager_path = comfyui_root / "custom_nodes" / "comfyui-manager"
    
    if manager_path.exists():
        print_success(f"ComfyUI-Manager found at {manager_path}")
        
        # Check key files
        key_files = ["__init__.py", "requirements.txt"]
        all_ok = True
        for file in key_files:
            if (manager_path / file).exists():
                print_success(f"  - {file}")
            else:
                print_warning(f"  - {file} (missing)")
                all_ok = False
        
        return all_ok
    else:
        print_error(f"ComfyUI-Manager not found at {manager_path}")
        return False

def check_model_directories(comfyui_root: Path) -> bool:
    """Check if model directories exist and their status."""
    print_header("Checking Model Directories")
    
    models_root = comfyui_root / "models"
    model_subdirs = [
        "checkpoints",
        "diffusion_models",
        "text_encoders",
        "vae",
        "loras",
        "embeddings",
    ]
    
    all_ok = True
    for subdir in model_subdirs:
        path = models_root / subdir
        if path.exists():
            file_count = len(list(path.glob("*.*")))
            if file_count > 0:
                print_success(f"{subdir}/ ({file_count} files)")
            else:
                print_warning(f"{subdir}/ (empty)")
        else:
            print_warning(f"{subdir}/ (doesn't exist)")
    
    return True

def check_ltx_video_models(comfyui_root: Path) -> bool:
    """Check for LTX-Video specific model files."""
    print_header("Checking LTX-Video Models")
    
    models_root = comfyui_root / "models"
    ltx_patterns = {
        "checkpoints": ["*ltx*.safetensors", "*ltx*.ckpt", "*ltxv*.pt"],
        "diffusion_models": ["*ltx*.pt", "*diffusion*.pt"],
        "text_encoders": ["*t5*.pt", "*text*.pt"],
        "vae": ["*vae*.pt", "*ltx*.pt"],
    }
    
    found_any = False
    for subdir, patterns in ltx_patterns.items():
        path = models_root / subdir
        if not path.exists():
            continue
        
        for pattern in patterns:
            matches = list(path.glob(pattern))
            if matches:
                for match in matches:
                    print_success(f"Found {match.name} in {subdir}/")
                    found_any = True
    
    if not found_any:
        print_warning("No LTX-Video models found. Download from: https://huggingface.co/Lightricks")
    
    return found_any

def check_gpu_availability() -> bool:
    """Check if CUDA-enabled GPU is available."""
    print_header("Checking GPU/CUDA Support")
    
    try:
        import torch
        
        cuda_available = torch.cuda.is_available()
        if cuda_available:
            device_count = torch.cuda.device_count()
            current_device = torch.cuda.current_device()
            device_name = torch.cuda.get_device_name(current_device)
            capability = torch.cuda.get_device_capability(current_device)
            vram = torch.cuda.get_device_properties(current_device).total_memory / 1e9
            
            print_success(f"CUDA is available")
            print_success(f"GPU Device: {device_name}")
            print_success(f"CUDA Capability: {capability[0]}.{capability[1]}")
            print_success(f"Total VRAM: {vram:.1f} GB")
            
            if vram >= 8:
                print_success("VRAM sufficient for LTX-Video")
            elif vram >= 6:
                print_warning("VRAM may be tight for LTX-Video (6-8GB)")
            else:
                print_error("VRAM insufficient for LTX-Video (< 6GB)")
            
            return True
        else:
            print_warning("CUDA not available - GPU acceleration disabled")
            print_info("CPU mode will be very slow for video generation")
            return False
    
    except Exception as e:
        print_error(f"Error checking GPU: {e}")
        return False

def check_comfy_custom_nodes(comfyui_root: Path) -> bool:
    """List installed custom nodes."""
    print_header("Installed Custom Nodes")
    
    custom_nodes_dir = comfyui_root / "custom_nodes"
    if not custom_nodes_dir.exists():
        return False
    
    nodes = []
    for item in custom_nodes_dir.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            nodes.append(item.name)
    
    if nodes:
        for node in sorted(nodes):
            print_success(f"{node}")
        
        # Check for LTX-Video related nodes
        ltx_nodes = [n for n in nodes if "ltx" in n.lower() or "video" in n.lower()]
        if ltx_nodes:
            print_info(f"LTX-Video nodes found: {', '.join(ltx_nodes)}")
        else:
            print_warning("No LTX-Video related nodes found")
    else:
        print_warning("No custom nodes installed")
    
    return True

def test_comfyui_import() -> bool:
    """Test if ComfyUI can be imported."""
    print_header("Testing ComfyUI Import")
    
    comfyui_root = find_comfyui_root()
    if not comfyui_root:
        print_error("ComfyUI root not found")
        return False
    
    # Add ComfyUI to path
    sys.path.insert(0, str(comfyui_root))
    
    try:
        # Try importing basic ComfyUI modules
        import nodes
        print_success("ComfyUI nodes module imports successfully")
        return True
    except ImportError as e:
        print_warning(f"ComfyUI import warning: {e}")
        return False
    except Exception as e:
        print_error(f"ComfyUI import error: {e}")
        return False

def generate_report(comfyui_root: Path) -> Dict:
    """Generate a verification report."""
    report = {
        "comfyui_path": str(comfyui_root),
        "checks": {},
    }
    
    # Perform all checks
    checks = [
        ("Python Version", check_python_version()),
        ("Dependencies", check_dependencies()),
        ("ComfyUI Installation", check_comfyui_installation(comfyui_root)),
        ("ComfyUI-Manager", check_manager_installation(comfyui_root)),
        ("Model Directories", check_model_directories(comfyui_root)),
        ("LTX-Video Models", check_ltx_video_models(comfyui_root)),
        ("GPU/CUDA Support", check_gpu_availability()),
        ("ComfyUI Import", test_comfyui_import()),
        ("Custom Nodes", check_comfy_custom_nodes(comfyui_root)),
    ]
    
    for name, result in checks:
        report["checks"][name] = result
    
    return report

def print_summary(report: Dict):
    """Print a summary of the verification."""
    print_header("Verification Summary")
    
    passed = sum(1 for v in report["checks"].values() if v)
    total = len(report["checks"])
    
    print_info(f"Passed: {passed}/{total}")
    print_info(f"ComfyUI Path: {report['comfyui_path']}")
    
    print()
    print_header("Next Steps")
    
    if report["checks"].get("LTX-Video Models", False):
        print_success("LTX-Video models detected!")
        print_info("You can now:")
        print_info("  1. Start ComfyUI with: ./run_gpu.sh or run_gpu.bat")
        print_info("  2. Load an LTX-Video workflow")
        print_info("  3. Generate your first video")
    else:
        print_warning("LTX-Video models not found")
        print_info("To complete setup:")
        print_info("  1. Download LTXV 2B from: https://huggingface.co/Lightricks")
        print_info("  2. Place files in: models/{checkpoints,diffusion_models,text_encoders,vae}/")
        print_info("  3. Run this script again to verify")
    
    print()
    if report["checks"].get("GPU/CUDA Support", False):
        print_success("GPU acceleration is available - video generation will be fast")
    else:
        print_warning("GPU acceleration not available - video generation will be slow")
    
    print()

def main():
    """Main entry point."""
    print_header("ComfyUI + LTX-Video Setup Verification")
    
    # Find ComfyUI installation
    comfyui_root = find_comfyui_root()
    if not comfyui_root:
        print_error("ComfyUI installation not found")
        print_info("Please run this script from the ComfyUI directory or parent directory")
        sys.exit(1)
    
    print_success(f"Found ComfyUI at: {comfyui_root}")
    print()
    
    # Generate verification report
    report = generate_report(comfyui_root)
    
    # Print summary
    print_summary(report)
    
    # Determine exit code
    if all(report["checks"].values()):
        print_success("Setup verification PASSED - Ready to generate videos!")
        return 0
    else:
        print_warning("Setup verification completed with warnings - See above for details")
        return 1

if __name__ == "__main__":
    sys.exit(main())
