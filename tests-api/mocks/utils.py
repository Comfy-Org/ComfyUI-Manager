"""
Mock utils module for testing purposes
"""

def merge_json_recursive(a, b):
    """
    Mock implementation of merge_json_recursive
    """
    if isinstance(a, dict) and isinstance(b, dict):
        result = a.copy()
        for key, value in b.items():
            if key in result and isinstance(result[key], (dict, list)) and isinstance(value, (dict, list)):
                result[key] = merge_json_recursive(result[key], value)
            else:
                result[key] = value
        return result
    elif isinstance(a, list) and isinstance(b, list):
        return a + b
    else:
        return b