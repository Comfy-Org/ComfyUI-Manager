"""
Tests for snapshot management endpoints.
"""
import pytest
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from utils.validation import validate_response


def test_get_snapshot_list(
    api_request: Callable,
    openapi_spec: Dict
):
    """
    Test the endpoint for listing snapshots.
    """
    # Make the API request
    path = "/snapshot/getlist"
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
    assert "items" in json_data
    assert isinstance(json_data["items"], list)


def test_get_current_snapshot(
    api_request: Callable,
    openapi_spec: Dict
):
    """
    Test the endpoint for getting the current snapshot.
    """
    # Make the API request
    path = "/snapshot/get_current"
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
    
    # Check for basic snapshot structure
    assert "snapshot_date" in json_data
    assert "custom_nodes" in json_data


@pytest.mark.skip(reason="This test creates a snapshot which is a state-modifying operation")
def test_save_snapshot(
    api_request: Callable
):
    """
    Test the endpoint for saving a new snapshot.
    Skipped to avoid modifying state in tests.
    """
    pass


@pytest.mark.skip(reason="This test removes a snapshot which is a destructive operation")
def test_remove_snapshot(
    api_request: Callable
):
    """
    Test the endpoint for removing a snapshot.
    Skipped to avoid modifying state in tests.
    """
    pass


@pytest.mark.skip(reason="This test restores a snapshot which is a state-modifying operation")
def test_restore_snapshot(
    api_request: Callable
):
    """
    Test the endpoint for restoring a snapshot.
    Skipped to avoid modifying state in tests.
    """
    pass


class TestSnapshotWorkflow:
    """
    Test the complete snapshot workflow (create, list, get, remove).
    These tests are grouped to ensure proper sequencing but are still skipped
    to avoid modifying state in automated tests.
    """
    
    @pytest.fixture(scope="class")
    def snapshot_name(self) -> str:
        """
        Generate a unique snapshot name for testing.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"test_snapshot_{timestamp}"
    
    @pytest.mark.skip(reason="State-modifying test")
    def test_create_snapshot(
        self,
        api_request: Callable,
        snapshot_name: str
    ):
        """
        Test creating a snapshot.
        """
        # Make the API request to save a snapshot
        response, _ = api_request(
            method="get",
            path="/snapshot/save",
            expected_status=200,
        )
        
        # Verify a snapshot was created (would need to check the snapshot list)
        response2, json_data = api_request(
            method="get",
            path="/snapshot/getlist",
            expected_status=200,
        )
        
        # The most recently created snapshot should be first in the list
        assert json_data["items"]
        
        # Store the snapshot name for later tests
        self.actual_snapshot_name = json_data["items"][0]
        
    @pytest.mark.skip(reason="State-modifying test")
    def test_get_snapshot_details(
        self,
        api_request: Callable,
        openapi_spec: Dict
    ):
        """
        Test getting details of the created snapshot.
        """
        # This would check the current snapshot, not a specific one
        # since there's no direct API to get a specific snapshot
        response, json_data = api_request(
            method="get",
            path="/snapshot/get_current",
            expected_status=200,
        )
        
        # Validate the snapshot data
        assert json_data is not None
        validate_response(
            response_data=json_data,
            path="/snapshot/get_current",
            method="get",
            spec=openapi_spec,
        )
    
    @pytest.mark.skip(reason="State-modifying test")
    def test_remove_test_snapshot(
        self,
        api_request: Callable
    ):
        """
        Test removing the test snapshot.
        """
        # Make the API request to remove the snapshot
        response, _ = api_request(
            method="get",
            path="/snapshot/remove",
            params={"target": self.actual_snapshot_name},
            expected_status=200,
        )
        
        # Verify the snapshot was removed
        response2, json_data = api_request(
            method="get",
            path="/snapshot/getlist",
            expected_status=200,
        )
        
        # The snapshot should no longer be in the list
        assert self.actual_snapshot_name not in json_data["items"]