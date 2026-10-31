"""
Validation utilities for API tests.
"""
import json
import jsonschema
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, Union


def load_openapi_spec(spec_path: Union[str, Path] = None) -> Dict[str, Any]:
    """
    Load the OpenAPI specification document.
    
    Args:
        spec_path: Path to the OpenAPI specification file
        
    Returns:
        The OpenAPI specification as a dictionary
    """
    if spec_path is None:
        # Default to the root openapi.yaml file
        spec_path = Path(__file__).parents[2] / "openapi.yaml"
    
    with open(spec_path, "r") as f:
        if str(spec_path).endswith(".yaml") or str(spec_path).endswith(".yml"):
            return yaml.safe_load(f)
        else:
            return json.load(f)


def get_schema_for_path(
    spec: Dict[str, Any], 
    path: str, 
    method: str, 
    status_code: str = "200",
    content_type: str = "application/json"
) -> Optional[Dict[str, Any]]:
    """
    Extract the response schema for a specific path, method, and status code.
    
    Args:
        spec: The OpenAPI specification
        path: The API path (e.g., "/customnode/getlist")
        method: The HTTP method (e.g., "get", "post")
        status_code: The HTTP status code (default: "200")
        content_type: The response content type (default: "application/json")
        
    Returns:
        The schema for the specified path and method, or None if not found
    """
    method = method.lower()
    
    if path not in spec["paths"]:
        return None
    
    if method not in spec["paths"][path]:
        return None
    
    if "responses" not in spec["paths"][path][method]:
        return None
    
    if status_code not in spec["paths"][path][method]["responses"]:
        return None
    
    response_def = spec["paths"][path][method]["responses"][status_code]
    
    if "content" not in response_def:
        return None
    
    if content_type not in response_def["content"]:
        return None
    
    if "schema" not in response_def["content"][content_type]:
        return None
    
    return response_def["content"][content_type]["schema"]


def validate_response_schema(
    response_data: Any, 
    schema: Dict[str, Any],
    spec: Dict[str, Any] = None
) -> bool:
    """
    Validate a response against a schema from the OpenAPI specification.
    
    Args:
        response_data: The response data to validate
        schema: The schema to validate against
        spec: The complete OpenAPI specification (for resolving references)
        
    Returns:
        True if validation succeeds, raises an exception otherwise
    """
    if spec is None:
        spec = load_openapi_spec()
    
    # Create a resolver for references within the schema
    resolver = jsonschema.RefResolver.from_schema(spec)
    
    # Validate the response against the schema
    jsonschema.validate(
        instance=response_data,
        schema=schema,
        resolver=resolver
    )
    
    return True


def validate_response(
    response_data: Any,
    path: str,
    method: str,
    status_code: str = "200",
    content_type: str = "application/json",
    spec: Dict[str, Any] = None
) -> bool:
    """
    Validate a response against the schema defined in the OpenAPI specification.
    
    Args:
        response_data: The response data to validate
        path: The API path
        method: The HTTP method
        status_code: The HTTP status code (default: "200")
        content_type: The response content type (default: "application/json")
        spec: The OpenAPI specification (loaded from default location if None)
        
    Returns:
        True if validation succeeds, raises an exception otherwise
    """
    if spec is None:
        spec = load_openapi_spec()
    
    schema = get_schema_for_path(
        spec=spec,
        path=path,
        method=method,
        status_code=status_code,
        content_type=content_type
    )
    
    if schema is None:
        raise ValueError(
            f"No schema found for {method.upper()} {path} "
            f"with status {status_code} and content type {content_type}"
        )
    
    return validate_response_schema(
        response_data=response_data,
        schema=schema,
        spec=spec
    )