"""
Tests for validating the OpenAPI specification.
"""
import json
import pytest
import yaml
from typing import Dict, Any, List, Tuple
from pathlib import Path
from openapi_spec_validator import validate_spec
from utils.validation import load_openapi_spec
from utils.schema_utils import (
    get_all_paths, 
    get_methods_for_path, 
    find_paths_with_security, 
    get_required_parameters
)


def test_spec_is_valid():
    """
    Test that the OpenAPI specification is valid according to the spec validator.
    """
    spec = load_openapi_spec()
    validate_spec(spec)


def test_spec_has_info():
    """
    Test that the OpenAPI specification has basic info.
    """
    spec = load_openapi_spec()
    
    assert "info" in spec
    assert "title" in spec["info"]
    assert "version" in spec["info"]
    assert spec["info"]["title"] == "ComfyUI-Manager API"


def test_spec_has_paths():
    """
    Test that the OpenAPI specification has paths defined.
    """
    spec = load_openapi_spec()
    
    assert "paths" in spec
    assert len(spec["paths"]) > 0


def test_paths_have_responses():
    """
    Test that all paths have responses defined.
    """
    spec = load_openapi_spec()
    
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "delete", "patch", "options", "head"}:
                continue
                
            assert "responses" in operation, f"Path {path} method {method} has no responses"
            assert len(operation["responses"]) > 0, f"Path {path} method {method} has empty responses"


def test_responses_have_schemas():
    """
    Test that responses with application/json content type have schemas.
    """
    spec = load_openapi_spec()
    
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "delete", "patch", "options", "head"}:
                continue
                
            for status, response in operation["responses"].items():
                if "content" not in response:
                    continue
                    
                if "application/json" in response["content"]:
                    assert "schema" in response["content"]["application/json"], (
                        f"Path {path} method {method} status {status} "
                        f"application/json content has no schema"
                    )


def test_required_parameters_have_schemas():
    """
    Test that all required parameters have schemas.
    """
    spec = load_openapi_spec()
    
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "delete", "patch", "options", "head"}:
                continue
                
            if "parameters" not in operation:
                continue
                
            for param in operation["parameters"]:
                if param.get("required", False):
                    assert "schema" in param, (
                        f"Path {path} method {method} required parameter {param.get('name')} has no schema"
                    )


def test_security_schemes_defined():
    """
    Test that security schemes are properly defined.
    """
    spec = load_openapi_spec()
    
    # Get paths requiring security
    secure_paths = find_paths_with_security(spec)
    
    if secure_paths:
        assert "components" in spec, "Spec has secure paths but no components"
        assert "securitySchemes" in spec["components"], "Spec has secure paths but no securitySchemes"
        
        # Check each security reference is defined
        for path, method in secure_paths:
            operation = spec["paths"][path][method]
            for security_req in operation["security"]:
                for scheme_name in security_req:
                    assert scheme_name in spec["components"]["securitySchemes"], (
                        f"Security scheme {scheme_name} used by {method.upper()} {path} "
                        f"is not defined in components.securitySchemes"
                    )


def test_common_endpoint_groups_present():
    """
    Test that the spec includes the main endpoint groups.
    """
    spec = load_openapi_spec()
    paths = get_all_paths(spec)
    
    # Define the expected endpoint prefixes
    expected_prefixes = [
        "/customnode/",
        "/externalmodel/",
        "/manager/",
        "/snapshot/",
        "/comfyui_manager/",
    ]
    
    # Check that at least one path exists for each expected prefix
    for prefix in expected_prefixes:
        matching_paths = [p for p in paths if p.startswith(prefix)]
        assert matching_paths, f"No endpoints found with prefix {prefix}"