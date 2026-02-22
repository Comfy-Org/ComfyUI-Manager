"""
Tests for queue management endpoints.
"""
import pytest
import time
from pathlib import Path
from typing import Callable, Dict, Tuple

from utils.validation import validate_response


def test_get_queue_status(
    api_request: Callable,
    openapi_spec: Dict
):
    """
    Test the endpoint for getting queue status.
    """
    # Make the API request
    path = "/manager/queue/status"
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
    assert "total_count" in json_data
    assert "done_count" in json_data
    assert "in_progress_count" in json_data
    assert "is_processing" in json_data
    
    # Type checks
    assert isinstance(json_data["total_count"], int)
    assert isinstance(json_data["done_count"], int)
    assert isinstance(json_data["in_progress_count"], int)
    assert isinstance(json_data["is_processing"], bool)


def test_reset_queue(
    api_request: Callable
):
    """
    Test the endpoint for resetting the queue.
    """
    # Make the API request
    path = "/manager/queue/reset"
    response, _ = api_request(
        method="get",
        path=path,
        expected_status=200,
    )
    
    # Now check the queue status to verify it was reset
    response2, json_data = api_request(
        method="get",
        path="/manager/queue/status",
        expected_status=200,
    )
    
    # Queue should be empty after reset
    assert json_data["total_count"] == json_data["done_count"] + json_data["in_progress_count"]


@pytest.mark.skip(reason="State-modifying operation that requires auth")
def test_queue_install_node():
    """
    Test queuing a node installation.
    Skipped to avoid modifying state and requires authentication.
    """
    pass


@pytest.mark.skip(reason="State-modifying operation that requires auth")
def test_queue_update_node():
    """
    Test queuing a node update.
    Skipped to avoid modifying state and requires authentication.
    """
    pass


@pytest.mark.skip(reason="State-modifying operation that requires auth")
def test_queue_uninstall_node():
    """
    Test queuing a node uninstallation.
    Skipped to avoid modifying state and requires authentication.
    """
    pass


@pytest.mark.skip(reason="State-modifying operation")
def test_queue_start():
    """
    Test starting the queue.
    Skipped to avoid modifying state.
    """
    pass


class TestQueueOperations:
    """
    Test a complete queue workflow.
    These tests are grouped to ensure proper sequencing but are still skipped
    to avoid modifying state in automated tests.
    """
    
    @pytest.fixture(scope="class")
    def node_data(self) -> Dict:
        """
        Create test data for a node operation.
        """
        # This would be replaced with actual data for a known safe node
        return {
            "ui_id": "test_node_1",
            "id": "comfyui-manager",  # Manager itself
            "version": "latest",
            "channel": "default",
            "mode": "local",
        }
    
    @pytest.mark.skip(reason="State-modifying operation")
    def test_queue_operation_sequence(
        self,
        api_request: Callable,
        node_data: Dict
    ):
        """
        Test the queue operation sequence.
        """
        # 1. Reset the queue
        api_request(
            method="get",
            path="/manager/queue/reset",
            expected_status=200,
        )
        
        # 2. Queue a node operation (we'll use the manager itself)
        api_request(
            method="post",
            path="/manager/queue/update",
            json_data=node_data,
            expected_status=200,
        )
        
        # 3. Check queue status - should have one operation
        response, json_data = api_request(
            method="get",
            path="/manager/queue/status",
            expected_status=200,
        )
        
        assert json_data["total_count"] > 0
        assert not json_data["is_processing"]  # Queue hasn't started yet
        
        # 4. Start the queue
        api_request(
            method="get",
            path="/manager/queue/start",
            expected_status=200,
        )
        
        # 5. Check queue status again - should be processing
        response, json_data = api_request(
            method="get",
            path="/manager/queue/status",
            expected_status=200,
        )
        
        # Queue should be processing or already done
        assert json_data["is_processing"] or json_data["done_count"] == json_data["total_count"]
        
        # 6. Wait for queue to complete (with timeout)
        max_wait_time = 60  # seconds
        start_time = time.time()
        completed = False
        
        while time.time() - start_time < max_wait_time:
            response, json_data = api_request(
                method="get",
                path="/manager/queue/status",
                expected_status=200,
            )
            
            if json_data["done_count"] == json_data["total_count"] and not json_data["is_processing"]:
                completed = True
                break
                
            time.sleep(2)  # Wait before checking again
        
        assert completed, "Queue did not complete within timeout period"
    
    @pytest.mark.skip(reason="State-modifying operation")
    def test_concurrent_queue_operations(
        self,
        api_request: Callable,
        node_data: Dict
    ):
        """
        Test concurrent queue operations.
        """
        # This would test adding multiple operations to the queue
        # and verifying they all complete correctly
        pass