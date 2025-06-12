import os
import sys

# Print current working directory
print(f"Current directory: {os.getcwd()}")

# Print module search path
print(f"System path: {sys.path}")

# Try to import
try:
    from utils.validation import load_openapi_spec
    print("Import successful!")
except ImportError as e:
    print(f"Import error: {e}")
    
    # Try direct import
    try:
        sys.path.insert(0, os.path.join(os.getcwd(), "custom_nodes/ComfyUI-Manager/tests-api"))
        from utils.validation import load_openapi_spec
        print("Direct import successful!")
    except ImportError as e:
        print(f"Direct import error: {e}")