# ComfyUI Manager Test Suite

This directory contains all tests for the ComfyUI Manager project, organized by module structure.

## Directory Structure

```
tests/
├── setup_test_env.sh         # Setup isolated test environment
├── requirements.txt          # Test dependencies
├── pytest.ini               # Global pytest configuration
├── .gitignore              # Ignore test artifacts
│
└── common/                 # Tests for comfyui_manager/common/
    └── pip_util/          # Tests for pip_util.py
        ├── README.md      # pip_util test documentation
        ├── conftest.py    # pip_util test fixtures
        ├── pytest.ini     # pip_util-specific pytest config
        └── test_*.py      # Actual test files (to be created)
```

## Quick Start

### 1. Setup Test Environment (One Time)

```bash
cd tests
./setup_test_env.sh
```

This creates an isolated virtual environment with all test dependencies.

### 2. Run Tests

```bash
# Activate test environment
source test_venv/bin/activate

# Run all tests from root
cd tests
pytest

# Run specific module tests
cd tests/common/pip_util
pytest

# Deactivate when done
deactivate
```

## Test Organization

Tests mirror the source code structure:

| Source Code | Test Location |
|-------------|---------------|
| `comfyui_manager/common/pip_util.py` | `tests/common/pip_util/test_*.py` |
| `comfyui_manager/common/other.py` | `tests/common/other/test_*.py` |
| `comfyui_manager/module/file.py` | `tests/module/file/test_*.py` |

## Writing Tests

1. Create test directory matching source structure
2. Add `conftest.py` for module-specific fixtures
3. Add `pytest.ini` for module-specific configuration (optional)
4. Create `test_*.py` files with actual tests
5. Document in module-specific README

## Test Categories

Use pytest markers to categorize tests:

```python
@pytest.mark.unit
def test_simple_function():
    pass

@pytest.mark.integration
def test_complex_workflow():
    pass

@pytest.mark.e2e
def test_full_system():
    pass
```

Run by category:
```bash
pytest -m unit           # Only unit tests
pytest -m integration    # Only integration tests
pytest -m e2e           # Only end-to-end tests
```

## Coverage Reports

Coverage reports are generated per module:

```bash
cd tests/common/pip_util
pytest  # Generates htmlcov_pip_util/ and coverage_pip_util.xml
```

## Environment Isolation

**Why use venv?**
- ✅ Prevents test dependencies from corrupting main environment
- ✅ Allows safe package installation/uninstallation during tests
- ✅ Consistent test results across machines
- ✅ Easy to recreate clean environment

## Available Test Modules

- **[common/pip_util](common/pip_util/)** - Policy-based pip package management system tests
  - Unit tests for policy loading, parsing, condition evaluation
  - Integration tests for policy application (60% of tests)
  - End-to-end workflow tests

## Adding New Test Modules

1. Create directory structure: `tests/module_path/component_name/`
2. Add `conftest.py` with fixtures
3. Add `pytest.ini` if needed (optional)
4. Add `README.md` documenting the tests
5. Create `test_*.py` files

Example:
```bash
mkdir -p tests/data_models/config
cd tests/data_models/config
touch conftest.py README.md test_config_loader.py
```

## CI/CD Integration

Tests are designed to run in CI/CD pipelines:

```yaml
# Example GitHub Actions
- name: Setup test environment
  run: |
    cd tests
    ./setup_test_env.sh

- name: Run tests
  run: |
    source tests/test_venv/bin/activate
    pytest tests/
```

## Troubleshooting

### Import errors
```bash
# Make sure venv is activated
source test_venv/bin/activate

# Verify Python path
python -c "import sys; print(sys.path)"
```

### Tests not discovered
```bash
# Check pytest configuration
pytest --collect-only

# Verify test file naming (must start with test_)
ls test_*.py
```

### Clean rebuild
```bash
# Remove and recreate test environment
rm -rf test_venv/
./setup_test_env.sh
```

## Resources

- **pytest Documentation**: https://docs.pytest.org/
- **Coverage.py**: https://coverage.readthedocs.io/
- **Module-specific READMEs**: Check each test module directory
