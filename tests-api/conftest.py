"""
PyTest configuration and fixtures for API tests.
"""
import os
import sys
import json
import pytest
import requests
import tempfile
import time
import yaml
from pathlib import Path
from typing import Dict, Generator, Optional, Tuple

# Import test utilities
import sys
import os
from pathlib import Path

# Get the absolute path to the current file (conftest.py)
current_file = Path(os.path.abspath(__file__))

# Get the directory containing the current file (the tests-api directory)
tests_api_dir = current_file.parent

# Add the tests-api directory to the Python path
if str(tests_api_dir) not in sys.path:
    sys.path.insert(0, str(tests_api_dir))

# Apply mocks for ComfyUI imports
from mocks.patch import apply_mocks
apply_mocks()

# Now we can import from utils.validation
from utils.validation import load_openapi_spec


# Default test configuration
DEFAULT_TEST_CONFIG = {
    "server_url": "http://localhost:8188",
    "server_timeout": 2,  # seconds
    "wait_between_requests": 0.5,  # seconds
    "max_retries": 3,
}


@pytest.fixture(scope="session")
def test_config() -> Dict:
    """
    Load test configuration from environment variables or use defaults.
    """
    config = DEFAULT_TEST_CONFIG.copy()
    
    # Override from environment variables if present
    if "COMFYUI_SERVER_URL" in os.environ:
        config["server_url"] = os.environ["COMFYUI_SERVER_URL"]
    
    return config


@pytest.fixture(scope="session")
def server_url(test_config: Dict) -> str:
    """
    Get the server URL from the test configuration.
    """
    return test_config["server_url"]


@pytest.fixture(scope="session")
def openapi_spec() -> Dict:
    """
    Load the OpenAPI specification.
    """
    return load_openapi_spec()


@pytest.fixture(scope="session")
def api_client(server_url: str, test_config: Dict) -> requests.Session:
    """
    Create a requests Session for API calls.
    """
    session = requests.Session()
    
    # Check if the server is running
    try:
        response = session.get(f"{server_url}/", timeout=test_config["server_timeout"])
        response.raise_for_status()
    except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
        pytest.skip("ComfyUI server is not running or not accessible")
    
    return session


@pytest.fixture(scope="function")
def temp_dir() -> Generator[Path, None, None]:
    """
    Create a temporary directory for test files.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


class SecurityLevelContext:
    """
    Context manager for setting and restoring security levels.
    """
    def __init__(self, api_client: requests.Session, server_url: str, security_level: str):
        self.api_client = api_client
        self.server_url = server_url
        self.security_level = security_level
        self.original_level = None
    
    async def __aenter__(self):
        # Get the current security level (not directly exposed in API, would require more setup)
        # For now, we'll just set the new level
        
        # Set the new security level
        # Note: In a real implementation, we would need a way to set this
        # This is a placeholder - the actual implementation would depend on how
        # security levels are managed in ComfyUI-Manager
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Restore the original security level if needed
        pass


@pytest.fixture
def security_level_context(api_client: requests.Session, server_url: str):
    """
    Create a context manager for setting security levels.
    """
    return lambda level: SecurityLevelContext(api_client, server_url, level)


def make_api_url(server_url: str, path: str) -> str:
    """
    Construct a full API URL from the server URL and path.
    """
    # Ensure the path starts with a slash
    if not path.startswith("/"):
        path = f"/{path}"
    
    # Remove trailing slash from server_url if present
    if server_url.endswith("/"):
        server_url = server_url[:-1]
    
    return f"{server_url}{path}"


@pytest.fixture
def api_request(api_client: requests.Session, server_url: str, test_config: Dict):
    """
    Helper function for making API requests with consistent behavior.
    """
    def _request(
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        expected_status: int = 200,
        retry_on_error: bool = True,
    ) -> Tuple[requests.Response, Optional[Dict]]:
        """
        Make an API request with automatic validation.
        
        Args:
            method: HTTP method
            path: API path
            params: Query parameters
            json_data: JSON request body
            headers: HTTP headers
            expected_status: Expected HTTP status code
            retry_on_error: Whether to retry on connection errors
            
        Returns:
            Tuple of (Response object, JSON response data or None)
        """
        method = method.lower()
        url = make_api_url(server_url, path)
        
        if headers is None:
            headers = {}
        
        # Add common headers
        headers.setdefault("Accept", "application/json")
        
        # Sleep between requests to avoid overwhelming the server
        time.sleep(test_config["wait_between_requests"])
        
        retries = test_config["max_retries"] if retry_on_error else 0
        last_exception = None
        
        for attempt in range(retries + 1):
            try:
                if method == "get":
                    response = api_client.get(url, params=params, headers=headers)
                elif method == "post":
                    response = api_client.post(url, params=params, json=json_data, headers=headers)
                elif method == "put":
                    response = api_client.put(url, params=params, json=json_data, headers=headers)
                elif method == "delete":
                    response = api_client.delete(url, params=params, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                # Check status code
                assert response.status_code == expected_status, (
                    f"Expected status code {expected_status}, got {response.status_code}"
                )
                
                # Parse JSON response if possible
                json_response = None
                if response.headers.get("Content-Type", "").startswith("application/json"):
                    try:
                        json_response = response.json()
                    except json.JSONDecodeError:
                        if expected_status == 200:
                            raise ValueError("Response was not valid JSON")
                
                return response, json_response
                
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exception = e
                if attempt < retries:
                    # Wait before retrying
                    time.sleep(1)
                    continue
                break
        
        if last_exception:
            raise last_exception
        
        raise RuntimeError("Failed to make API request")
    
    return _request