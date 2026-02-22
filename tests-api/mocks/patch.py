"""
Patch module to mock imports for testing
"""
import sys
import importlib.util
import os
from pathlib import Path

# Import mock modules
from mocks.prompt_server import PromptServer
from mocks.custom_node_manager import CustomNodeManager

# Current directory 
current_dir = Path(__file__).parent.parent  # tests-api directory

# Define mocks
class MockModule:
    """Base class for mock modules"""
    pass

# Create server mock module with PromptServer
server_mock = MockModule()
server_mock.PromptServer = PromptServer
prompt_server_instance = PromptServer()
server_mock.PromptServer.instance = prompt_server_instance
server_mock.PromptServer.inst = prompt_server_instance

# Create app mock module with custom_node_manager submodule
app_mock = MockModule()
app_custom_node_manager = MockModule()
app_custom_node_manager.CustomNodeManager = CustomNodeManager
app_custom_node_manager.CustomNodeManager.instance = CustomNodeManager()

# Create utils mock module with json_util submodule
utils_mock = MockModule()
utils_json_util = MockModule()

# Create utils.validation and utils.schema_utils submodules
utils_validation = MockModule()
utils_schema_utils = MockModule()

# Import actual modules (make sure path is set up correctly)
sys.path.insert(0, str(current_dir))

try:
    # Import the validation module
    from utils.validation import load_openapi_spec
    utils_validation.load_openapi_spec = load_openapi_spec
    
    # Import all schema_utils functions
    from utils.schema_utils import (
        get_all_paths, 
        get_grouped_paths,
        get_methods_for_path,
        find_paths_with_security,
        get_content_types_for_response,
        get_required_parameters
    )
    
    utils_schema_utils.get_all_paths = get_all_paths
    utils_schema_utils.get_grouped_paths = get_grouped_paths
    utils_schema_utils.get_methods_for_path = get_methods_for_path
    utils_schema_utils.find_paths_with_security = find_paths_with_security
    utils_schema_utils.get_content_types_for_response = get_content_types_for_response
    utils_schema_utils.get_required_parameters = get_required_parameters
    
except ImportError as e:
    print(f"Error importing test utilities: {e}")
    # Define dummy functions if imports fail
    def dummy_load_openapi_spec():
        """Dummy function for testing"""
        return {"paths": {}}
    utils_validation.load_openapi_spec = dummy_load_openapi_spec
    
    def dummy_get_all_paths(spec):
        return list(spec.get("paths", {}).keys())
    utils_schema_utils.get_all_paths = dummy_get_all_paths
    
    def dummy_get_grouped_paths(spec):
        return {}
    utils_schema_utils.get_grouped_paths = dummy_get_grouped_paths
    
    def dummy_get_methods_for_path(spec, path):
        return []
    utils_schema_utils.get_methods_for_path = dummy_get_methods_for_path
    
    def dummy_find_paths_with_security(spec, security_scheme=None):
        return []
    utils_schema_utils.find_paths_with_security = dummy_find_paths_with_security
    
    def dummy_get_content_types_for_response(spec, path, method, status_code="200"):
        return []
    utils_schema_utils.get_content_types_for_response = dummy_get_content_types_for_response
    
    def dummy_get_required_parameters(spec, path, method):
        return []
    utils_schema_utils.get_required_parameters = dummy_get_required_parameters

# Add merge_json_recursive from our mock utils
from mocks.utils import merge_json_recursive
utils_json_util.merge_json_recursive = merge_json_recursive

# Apply the mocks to sys.modules
def apply_mocks():
    """Apply all mocks to sys.modules"""
    sys.modules['server'] = server_mock
    sys.modules['app'] = app_mock
    sys.modules['app.custom_node_manager'] = app_custom_node_manager
    sys.modules['utils'] = utils_mock
    sys.modules['utils.json_util'] = utils_json_util
    sys.modules['utils.validation'] = utils_validation
    sys.modules['utils.schema_utils'] = utils_schema_utils
    
    # Make sure our actual utils module is importable
    if current_dir not in sys.path:
        sys.path.insert(0, str(current_dir))