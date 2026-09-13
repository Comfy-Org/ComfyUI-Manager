# ComfyUI-Manager API Tests

This directory contains tests for the ComfyUI-Manager API endpoints, validating the OpenAPI specification and ensuring API functionality.

## Setup

1. Install test dependencies:

```bash
pip install -r requirements-test.txt
```

2. Ensure ComfyUI is running with ComfyUI-Manager installed:

```bash
# Start ComfyUI with the default server
python main.py
```

## Running Tests

### Run all tests

```bash
pytest -xvs
```

### Run specific test files

```bash
# Run only the spec validation tests
pytest -xvs test_spec_validation.py

# Run only the custom node API tests
pytest -xvs test_customnode_api.py
```

### Run specific test functions

```bash
# Run a specific test
pytest -xvs test_customnode_api.py::test_get_custom_node_list
```

## Test Configuration

The tests use the following default configuration:

- Server URL: `http://localhost:8188`
- Server timeout: 2 seconds
- Wait between requests: 0.5 seconds
- Maximum retries: 3

You can override these settings with environment variables:

```bash
# Use a different server URL
COMFYUI_SERVER_URL=http://localhost:8189 pytest -xvs
```

## Test Categories

The tests are organized into the following categories:

1. **Spec Validation** (`test_spec_validation.py`): Validates that the OpenAPI specification is correct and complete.
2. **Custom Node API** (`test_customnode_api.py`): Tests for custom node management endpoints.
3. **Snapshot API** (`test_snapshot_api.py`): Tests for snapshot management endpoints.
4. **Queue API** (`test_queue_api.py`): Tests for queue management endpoints.
5. **Config API** (`test_config_api.py`): Tests for configuration endpoints.
6. **Model API** (`test_model_api.py`): Tests for model management endpoints (minimal as these are being deprecated).

## Test Implementation Details

### Fixtures

- `test_config`: Provides the test configuration
- `server_url`: Returns the server URL from the configuration
- `openapi_spec`: Loads the OpenAPI specification
- `api_client`: Creates a requests Session for API calls
- `api_request`: Helper function for making consistent API requests

### Utilities

- `validation.py`: Functions for validating responses against the OpenAPI schema
- `schema_utils.py`: Utilities for extracting and manipulating schemas

## Notes

- Some tests are skipped with `@pytest.mark.skip` to avoid modifying state in automated testing
- Security-level restricted endpoints have minimal tests to avoid security issues
- Tests focus on read operations rather than write operations where possible