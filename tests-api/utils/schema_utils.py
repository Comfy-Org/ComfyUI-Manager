"""
Schema utilities for extracting and manipulating OpenAPI schemas.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from .validation import load_openapi_spec


def get_all_paths(spec: Dict[str, Any]) -> List[str]:
    """
    Get all paths defined in the OpenAPI specification.
    
    Args:
        spec: The OpenAPI specification
        
    Returns:
        List of all paths
    """
    return list(spec.get("paths", {}).keys())


def get_grouped_paths(spec: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Group paths by their top-level segment.
    
    Args:
        spec: The OpenAPI specification
        
    Returns:
        Dictionary mapping top-level segments to lists of paths
    """
    result = {}
    
    for path in get_all_paths(spec):
        segments = path.strip("/").split("/")
        if not segments:
            continue
            
        top_segment = segments[0]
        if top_segment not in result:
            result[top_segment] = []
            
        result[top_segment].append(path)
        
    return result


def get_methods_for_path(spec: Dict[str, Any], path: str) -> List[str]:
    """
    Get all HTTP methods defined for a path.
    
    Args:
        spec: The OpenAPI specification
        path: The API path
        
    Returns:
        List of HTTP methods (lowercase)
    """
    if path not in spec.get("paths", {}):
        return []
        
    return [
        method.lower() 
        for method in spec["paths"][path].keys() 
        if method.lower() in {"get", "post", "put", "delete", "patch", "options", "head"}
    ]


def find_paths_with_security(
    spec: Dict[str, Any], 
    security_scheme: Optional[str] = None
) -> List[Tuple[str, str]]:
    """
    Find all paths that require security.
    
    Args:
        spec: The OpenAPI specification
        security_scheme: Optional specific security scheme to filter by
        
    Returns:
        List of (path, method) tuples that require security
    """
    result = []
    
    for path, path_item in spec.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "delete", "patch", "options", "head"}:
                continue
                
            if "security" in operation:
                if security_scheme is None:
                    result.append((path, method.lower()))
                else:
                    # Check if this security scheme is required
                    for security_req in operation["security"]:
                        if security_scheme in security_req:
                            result.append((path, method.lower()))
                            break
                            
    return result


def get_content_types_for_response(
    spec: Dict[str, Any], 
    path: str, 
    method: str, 
    status_code: str = "200"
) -> List[str]:
    """
    Get content types defined for a response.
    
    Args:
        spec: The OpenAPI specification
        path: The API path
        method: The HTTP method
        status_code: The HTTP status code
        
    Returns:
        List of content types
    """
    method = method.lower()
    
    if path not in spec["paths"]:
        return []
    
    if method not in spec["paths"][path]:
        return []
    
    if "responses" not in spec["paths"][path][method]:
        return []
    
    if status_code not in spec["paths"][path][method]["responses"]:
        return []
    
    response_def = spec["paths"][path][method]["responses"][status_code]
    
    if "content" not in response_def:
        return []
    
    return list(response_def["content"].keys())


def get_required_parameters(
    spec: Dict[str, Any], 
    path: str, 
    method: str
) -> List[Dict[str, Any]]:
    """
    Get all required parameters for a path/method.
    
    Args:
        spec: The OpenAPI specification
        path: The API path
        method: The HTTP method
        
    Returns:
        List of parameter objects that are required
    """
    method = method.lower()
    
    if path not in spec["paths"]:
        return []
    
    if method not in spec["paths"][path]:
        return []
    
    if "parameters" not in spec["paths"][path][method]:
        return []
    
    return [
        param for param in spec["paths"][path][method]["parameters"]
        if param.get("required", False)
    ]