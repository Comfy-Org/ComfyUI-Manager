"""
Tests for configuration endpoints.
"""
import pytest
from typing import Callable, Dict, List, Tuple

from utils.validation import validate_response


def test_get_preview_method(
    api_request: Callable
):
    """
    Test getting the current preview method.
    """
    # Make the API request
    path = "/manager/preview_method"
    response, _ = api_request(
        method="get",
        path=path,
        expected_status=200,
    )
    
    # Verify the response is one of the valid preview methods
    assert response.text in ["auto", "latent2rgb", "taesd", "none"]


def test_get_db_mode(
    api_request: Callable
):
    """
    Test getting the current database mode.
    """
    # Make the API request
    path = "/manager/db_mode"
    response, _ = api_request(
        method="get",
        path=path,
        expected_status=200,
    )
    
    # Verify the response is one of the valid database modes
    assert response.text in ["channel", "local", "remote"]


def test_get_component_policy(
    api_request: Callable
):
    """
    Test getting the current component policy.
    """
    # Make the API request
    path = "/manager/policy/component"
    response, _ = api_request(
        method="get",
        path=path,
        expected_status=200,
    )
    
    # Component policy could be any string
    assert response.text is not None


def test_get_update_policy(
    api_request: Callable
):
    """
    Test getting the current update policy.
    """
    # Make the API request
    path = "/manager/policy/update"
    response, _ = api_request(
        method="get",
        path=path,
        expected_status=200,
    )
    
    # Verify the response is one of the valid update policies
    assert response.text in ["stable", "nightly", "nightly-comfyui"]


def test_get_channel_url_list(
    api_request: Callable,
    openapi_spec: Dict
):
    """
    Test getting the channel URL list.
    """
    # Make the API request
    path = "/manager/channel_url_list"
    response, json_data = api_request(
        method="get",
        path=path,
        expected_status=200,
    )
    
    # Validate response structure against the schema
    assert json_data is not None
    validate_response(
        response_data=json_data,
        path=path,
        method="get",
        spec=openapi_spec,
    )
    
    # Verify the response contains the expected fields
    assert "selected" in json_data
    assert "list" in json_data
    assert isinstance(json_data["list"], list)
    
    # Each channel should have a name and URL
    if json_data["list"]:
        first_channel = json_data["list"][0]
        assert "name" in first_channel
        assert "url" in first_channel


def test_get_manager_version(
    api_request: Callable
):
    """
    Test getting the manager version.
    """
    # Make the API request
    path = "/manager/version"
    response, _ = api_request(
        method="get",
        path=path,
        expected_status=200,
    )
    
    # Verify the response is a version string
    assert response.text.startswith("V")  # Version strings start with V


def test_get_manager_notice(
    api_request: Callable
):
    """
    Test getting the manager notice.
    """
    # Make the API request
    path = "/manager/notice"
    response, _ = api_request(
        method="get",
        path=path,
        expected_status=200,
    )
    
    # Verify the response is HTML content
    assert response.headers.get("Content-Type", "").startswith("text/html") or "ComfyUI" in response.text


@pytest.mark.skip(reason="State-modifying operations")
class TestConfigChanges:
    """
    Tests for changing configuration settings.
    These are skipped to avoid modifying state in automated tests.
    """
    
    @pytest.fixture(scope="class", autouse=True)
    def save_original_config(self, api_request: Callable):
        """
        Save the original configuration to restore after tests.
        """
        # Save original values
        response, _ = api_request(
            method="get",
            path="/manager/preview_method",
            expected_status=200,
        )
        self.original_preview_method = response.text
        
        response, _ = api_request(
            method="get",
            path="/manager/db_mode",
            expected_status=200,
        )
        self.original_db_mode = response.text
        
        response, _ = api_request(
            method="get",
            path="/manager/policy/update",
            expected_status=200,
        )
        self.original_update_policy = response.text
        
        yield
        
        # Restore original values
        api_request(
            method="get",
            path="/manager/preview_method",
            params={"value": self.original_preview_method},
            expected_status=200,
        )
        
        api_request(
            method="get",
            path="/manager/db_mode",
            params={"value": self.original_db_mode},
            expected_status=200,
        )
        
        api_request(
            method="get",
            path="/manager/policy/update",
            params={"value": self.original_update_policy},
            expected_status=200,
        )
    
    def test_set_preview_method(self, api_request: Callable):
        """
        Test setting the preview method.
        """
        # Set to a different value (taesd)
        api_request(
            method="get",
            path="/manager/preview_method",
            params={"value": "taesd"},
            expected_status=200,
        )
        
        # Verify it was changed
        response, _ = api_request(
            method="get",
            path="/manager/preview_method",
            expected_status=200,
        )
        assert response.text == "taesd"
    
    def test_set_db_mode(self, api_request: Callable):
        """
        Test setting the database mode.
        """
        # Set to local mode
        api_request(
            method="get",
            path="/manager/db_mode",
            params={"value": "local"},
            expected_status=200,
        )
        
        # Verify it was changed
        response, _ = api_request(
            method="get",
            path="/manager/db_mode",
            expected_status=200,
        )
        assert response.text == "local"
    
    def test_set_update_policy(self, api_request: Callable):
        """
        Test setting the update policy.
        """
        # Set to stable
        api_request(
            method="get",
            path="/manager/policy/update",
            params={"value": "stable"},
            expected_status=200,
        )
        
        # Verify it was changed
        response, _ = api_request(
            method="get",
            path="/manager/policy/update",
            expected_status=200,
        )
        assert response.text == "stable"