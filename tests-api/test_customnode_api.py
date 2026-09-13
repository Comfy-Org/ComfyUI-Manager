"""
Tests for custom node management endpoints.
"""
import pytest
from pathlib import Path
from typing import Callable, Dict, Tuple

from utils.validation import validate_response


@pytest.mark.parametrize(
    "mode", 
    ["local", "remote"]
)
def test_get_custom_node_list(
    api_request: Callable, 
    openapi_spec: Dict, 
    mode: str
):
    """
    Test the endpoint for listing custom nodes.
    """
    # Make the API request
    path = "/customnode/getlist"
    response, json_data = api_request(
        method="get",
        path=path,
        params={"mode": mode, "skip_update": "true"},
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
    assert "channel" in json_data
    assert "node_packs" in json_data
    assert isinstance(json_data["node_packs"], dict)
    
    # If there are any node packs, verify they have the expected structure
    if json_data["node_packs"]:
        # Take the first node pack to validate
        first_node_pack = next(iter(json_data["node_packs"].values()))
        assert "title" in first_node_pack
        assert "name" in first_node_pack


def test_get_installed_nodes(
    api_request: Callable, 
    openapi_spec: Dict
):
    """
    Test the endpoint for listing installed nodes.
    """
    # Make the API request
    path = "/customnode/installed"
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
    
    # Verify the response is a dictionary of node packs
    assert isinstance(json_data, dict)


@pytest.mark.parametrize(
    "mode", 
    ["local", "nickname"]
)
def test_get_node_mappings(
    api_request: Callable, 
    openapi_spec: Dict, 
    mode: str
):
    """
    Test the endpoint for getting node-to-package mappings.
    """
    # Make the API request
    path = "/customnode/getmappings"
    response, json_data = api_request(
        method="get",
        path=path,
        params={"mode": mode},
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
    
    # Verify the response is a dictionary mapping extension IDs to node info
    assert isinstance(json_data, dict)
    
    # If there are any mappings, verify they have the expected structure
    if json_data:
        # Take the first mapping to validate
        first_mapping = next(iter(json_data.values()))
        assert isinstance(first_mapping, list)
        assert len(first_mapping) == 2
        assert isinstance(first_mapping[0], list)  # List of node classes
        assert isinstance(first_mapping[1], dict)  # Metadata


@pytest.mark.parametrize(
    "mode", 
    ["local", "remote"]
)
def test_get_node_alternatives(
    api_request: Callable, 
    openapi_spec: Dict, 
    mode: str
):
    """
    Test the endpoint for getting alternative node options.
    """
    # Make the API request
    path = "/customnode/alternatives"
    response, json_data = api_request(
        method="get",
        path=path,
        params={"mode": mode},
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
    
    # Verify the response is a dictionary
    assert isinstance(json_data, dict)


def test_fetch_updates(
    api_request: Callable
):
    """
    Test the endpoint for fetching updates.
    This might modify state, so we just check for a valid response.
    """
    # Make the API request with skip_update=true to avoid actual updates
    path = "/customnode/fetch_updates"
    response, _ = api_request(
        method="get",
        path=path,
        params={"mode": "local"},
        # Don't validate JSON since this endpoint doesn't return JSON
        expected_status=200,
        retry_on_error=False,  # Don't retry as this might have side effects
    )
    
    # Just check the status code is as expected (covered by api_request)
    assert response.status_code in [200, 201]


@pytest.mark.skip(reason="Queue endpoints are better tested with queue operations")
def test_queue_update_all(
    api_request: Callable
):
    """
    Test the endpoint for queuing updates for all nodes.
    Skipping as this would actually modify the installation.
    """
    pass


@pytest.mark.skip(reason="Security-restricted endpoint")
def test_install_node_via_git_url(
    api_request: Callable
):
    """
    Test the endpoint for installing a node via Git URL.
    Skipping as this requires high security level and would modify the installation.
    """
    pass