"""
Tests for model management endpoints.
These features are scheduled for deprecation, so tests are minimal.
"""
import pytest
from typing import Callable, Dict

from utils.validation import validate_response


@pytest.mark.parametrize(
    "mode", 
    ["local", "remote"]
)
def test_get_external_model_list(
    api_request: Callable,
    openapi_spec: Dict,
    mode: str
):
    """
    Test the endpoint for listing external models.
    """
    # Make the API request
    path = "/externalmodel/getlist"
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
    
    # Verify the response contains the expected fields
    assert "models" in json_data
    assert isinstance(json_data["models"], list)
    
    # If there are any models, verify they have the expected structure
    if json_data["models"]:
        first_model = json_data["models"][0]
        assert "name" in first_model
        assert "type" in first_model
        assert "url" in first_model
        assert "filename" in first_model
        assert "installed" in first_model


@pytest.mark.skip(reason="State-modifying operation that requires auth")
def test_install_model():
    """
    Test queuing a model installation.
    Skipped to avoid modifying state and requires authentication.
    This feature is also scheduled for deprecation.
    """
    pass