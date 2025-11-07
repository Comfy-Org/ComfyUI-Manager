# Testing Guide for ComfyUI Manager

## Code Update and Testing Workflow

When you modify code that affects the API or data models, follow this **mandatory workflow** to ensure your changes are properly tested:

### 1. OpenAPI Spec Modification

If you change data being sent or received:

```bash
# Edit openapi.yaml
vim openapi.yaml

# Verify YAML syntax
python3 -c "import yaml; yaml.safe_load(open('openapi.yaml'))"
```

### 2. Regenerate Data Models

```bash
# Generate Pydantic models from OpenAPI spec
datamodel-codegen \
  --use-subclass-enum \
  --field-constraints \
  --strict-types bytes \
  --use-double-quotes \
  --input openapi.yaml \
  --output comfyui_manager/data_models/generated_models.py \
  --output-model-type pydantic_v2.BaseModel

# Verify Python syntax
python3 -m py_compile comfyui_manager/data_models/generated_models.py

# Format and lint
ruff format comfyui_manager/data_models/generated_models.py
ruff check comfyui_manager/data_models/generated_models.py --fix
```

### 3. Update Exports (if needed)

```bash
# Update __init__.py if new models were added
vim comfyui_manager/data_models/__init__.py
```

### 4. **CRITICAL**: Reinstall Package

⚠️ **You MUST reinstall the package before restarting the server!**

```bash
# Reinstall package in development mode
uv pip install .
```

**Why this is critical**: The server loads modules from `site-packages`, not from your source directory. If you don't reinstall, the server will use old models and you'll see Pydantic errors.

### 5. Restart ComfyUI Server

```bash
# Stop existing servers
ps aux | grep "main.py" | grep -v grep | awk '{print $2}' | xargs -r kill
sleep 3

# Start new server
cd tests/env
python ComfyUI/main.py \
  --enable-compress-response-body \
  --enable-manager \
  --front-end-root front \
  > /tmp/comfyui-server.log 2>&1 &

# Wait for server to be ready
sleep 10
grep -q "To see the GUI" /tmp/comfyui-server.log && echo "✓ Server ready" || echo "Waiting..."
```

### 6. Run Tests

```bash
# Run all queue task API tests
python -m pytest tests/glob/test_queue_task_api.py -v

# Run specific test
python -m pytest tests/glob/test_queue_task_api.py::test_install_package_via_queue -v

# Run with verbose output
python -m pytest tests/glob/test_queue_task_api.py -v -s
```

### 7. Check Test Results and Logs

```bash
# View server logs for errors
tail -100 /tmp/comfyui-server.log | grep -E "exception|error|failed"

# Check for specific test task
tail -100 /tmp/comfyui-server.log | grep "test_task_id"
```

## Complete Workflow Script

Here's the complete workflow in a single script:

```bash
#!/bin/bash
set -e

echo "=== Step 1: Verify OpenAPI Spec ==="
python3 -c "import yaml; yaml.safe_load(open('openapi.yaml'))"
echo "✓ YAML valid"

echo ""
echo "=== Step 2: Regenerate Data Models ==="
datamodel-codegen \
  --use-subclass-enum \
  --field-constraints \
  --strict-types bytes \
  --use-double-quotes \
  --input openapi.yaml \
  --output comfyui_manager/data_models/generated_models.py \
  --output-model-type pydantic_v2.BaseModel

python3 -m py_compile comfyui_manager/data_models/generated_models.py
ruff format comfyui_manager/data_models/generated_models.py
ruff check comfyui_manager/data_models/generated_models.py --fix
echo "✓ Models regenerated and formatted"

echo ""
echo "=== Step 3: Reinstall Package ==="
uv pip install .
echo "✓ Package reinstalled"

echo ""
echo "=== Step 4: Restart Server ==="
ps aux | grep "main.py" | grep -v grep | awk '{print $2}' | xargs -r kill
sleep 3

cd tests/env
python ComfyUI/main.py \
  --enable-compress-response-body \
  --enable-manager \
  --front-end-root front \
  > /tmp/comfyui-server.log 2>&1 &

sleep 10
grep -q "To see the GUI" /tmp/comfyui-server.log && echo "✓ Server ready" || echo "⚠ Server still starting..."
cd ../..

echo ""
echo "=== Step 5: Run Tests ==="
python -m pytest tests/glob/test_queue_task_api.py -v

echo ""
echo "=== Workflow Complete ==="
```

## Common Issues

### Issue 1: Pydantic Validation Errors

**Symptom**: `AttributeError: 'UpdateComfyUIParams' object has no attribute 'id'`

**Cause**: Server is using old data models from site-packages

**Solution**:
```bash
uv pip install .  # Reinstall package
# Then restart server
```

### Issue 2: Server Using Old Code

**Symptom**: Changes don't take effect even after editing files

**Cause**: Server needs to be restarted to load new code

**Solution**:
```bash
ps aux | grep "main.py" | grep -v grep | awk '{print $2}' | xargs -r kill
# Then start server again
```

### Issue 3: Union Type Discrimination

**Symptom**: Wrong params type selected in Union

**Cause**: Pydantic matches Union types in order; types with all optional fields match everything

**Solution**: Place specific types first, types with all optional fields last:
```python
# Good
params: Union[
    InstallPackParams,      # Has required fields
    UpdatePackParams,       # Has required fields
    UpdateComfyUIParams,    # All optional - place last
    UpdateAllPacksParams,   # All optional - place last
]

# Bad
params: Union[
    UpdateComfyUIParams,    # All optional - matches everything!
    InstallPackParams,      # Never reached
]
```

## Testing Checklist

Before committing code changes:

- [ ] OpenAPI spec validated (`yaml.safe_load`)
- [ ] Data models regenerated
- [ ] Generated models verified (syntax check)
- [ ] Code formatted and linted
- [ ] Package reinstalled (`uv pip install .`)
- [ ] Server restarted with new code
- [ ] All tests passing
- [ ] Server logs checked for errors
- [ ] Manual testing of changed functionality

## Adding New Tests

When you add new tests or significantly modify existing ones, follow these steps to maintain optimal test performance.

### 1. Write Your Test

Create or modify test files in `tests/glob/`:

```python
# tests/glob/test_my_new_feature.py
import pytest
from tests.glob.conftest import *

def test_my_new_feature(session, base_url):
    """Test description."""
    # Your test implementation
    response = session.get(f"{base_url}/my/endpoint")
    assert response.status_code == 200
```

### 2. Run Tests to Verify

```bash
# Quick verification with automated script
./tests/run_automated_tests.sh

# Or manually
cd /mnt/teratera/git/comfyui-manager
source ~/venv/bin/activate
uv pip install .
./tests/run_parallel_tests.sh
```

### 3. Check Load Balancing

After tests complete, check the load balance variance in the report:

```bash
# Look for "Load Balancing Analysis" section in:
cat .claude/livecontext/automated_test_*.md | grep -A 20 "Load Balance"
```

**Thresholds**:
- ✅ **Excellent**: Variance < 1.2x (no action needed)
- ⚠️ **Good**: Variance 1.2x - 2.0x (consider updating)
- ❌ **Poor**: Variance > 2.0x (update required)

### 4. Update Test Durations (If Needed)

**When to update**:
- Added 3+ new tests
- Significantly modified test execution time
- Load balance variance increased above 2.0x
- Tests redistributed unevenly

**How to update**:

```bash
# Run the duration update script (takes ~15-20 minutes)
./tests/update_test_durations.sh

# This will:
# 1. Run all tests sequentially
# 2. Measure each test's execution time
# 3. Generate .test_durations file
# 4. Enable pytest-split to optimize distribution
```

**Commit the results**:

```bash
git add .test_durations
git commit -m "chore: update test duration data for optimal load balancing"
```

### 5. Verify Optimization

Run tests again to verify improved load balancing:

```bash
./tests/run_automated_tests.sh
# Check new variance in report - should be < 1.2x
```

### Example: Adding 5 New Tests

```bash
# 1. Write tests
vim tests/glob/test_new_api_feature.py

# 2. Run and check results
./tests/run_automated_tests.sh
# Output shows: "Load Balance: 2.3x variance (poor)"

# 3. Update durations
./tests/update_test_durations.sh
# Wait ~15-20 minutes

# 4. Commit duration data
git add .test_durations
git commit -m "chore: update test durations after adding 5 new API tests"

# 5. Verify improvement
./tests/run_automated_tests.sh
# Output shows: "Load Balance: 1.08x variance (excellent)"
```

### Load Balancing Optimization Timeline

| Tests Added | Action | Reason |
|-------------|--------|--------|
| 1-2 tests | No update needed | Minimal impact on distribution |
| 3-5 tests | Consider updating | May cause slight imbalance |
| 6+ tests | **Update required** | Significant distribution changes |
| Major refactor | **Update required** | Test times may have changed |

### Current Status (2025-11-06)

```
Total Tests: 54
Execution Time: ~140-160s (2.3-2.7 minutes)
Load Balance: 1.2x variance (excellent)
Speedup: 9x+ vs sequential
Parallel Efficiency: >90%
Pass Rate: 100%
```

**Recent Updates**:
- **P1 Implementation Complete**: Added 5 new complex scenario tests
  - Phase 3.1: Disable CNR when Nightly disabled
  - Phase 5.1: Install CNR when Nightly enabled (automatic version switch)
  - Phase 5.2: Install Nightly when CNR enabled (automatic version switch)
  - Phase 5.3: Install new version when both disabled
  - Phase 6: Uninstall removes all versions

**Recent Fixes** (2025-11-06):
- Fixed `test_case_sensitivity_full_workflow` - migrated to queue API
- Fixed `test_enable_package` - added pre-test cleanup
- Increased timeouts for parallel execution reliability
- Enhanced fixture cleanup with filesystem sync delays

**No duration update needed** - test distribution remains optimal after fixes.

## Test Documentation

For details about specific test failures and known issues, see:
- [README.md](./README.md) - Test suite overview and known issues
- [../README.md](../README.md) - Main testing guide with Quick Start

## API Usage Patterns

### Correct Queue API Usage

**Install Package**:
```python
# Queue install task
response = api_client.queue_task(
    kind="install",
    ui_id="unique_test_id",
    params={
        "id": "ComfyUI_PackageName",  # Original case
        "version": "1.0.2",
        "selected_version": "latest"
    }
)
assert response.status_code == 200

# Start queue
response = api_client.start_queue()
assert response.status_code in [200, 201]

# Wait for completion
time.sleep(10)
```

**Switch to Nightly**:
```python
# Queue install with version=nightly
response = api_client.queue_task(
    kind="install",
    ui_id="unique_test_id",
    params={
        "id": "ComfyUI_PackageName",
        "version": "nightly",
        "selected_version": "nightly"
    }
)
```

**Uninstall Package**:
```python
response = api_client.queue_task(
    kind="uninstall",
    ui_id="unique_test_id",
    params={
        "node_name": "ComfyUI_PackageName"  # Can use lowercase
    }
)
```

**Enable/Disable Package**:
```python
# Enable
response = api_client.queue_task(
    kind="enable",
    ui_id="unique_test_id",
    params={
        "cnr_id": "comfyui_packagename"  # Lowercase
    }
)

# Disable
response = api_client.queue_task(
    kind="disable",
    ui_id="unique_test_id",
    params={
        "node_name": "ComfyUI_PackageName"
    }
)
```

### Common Pitfalls

❌ **Don't use non-existent endpoints**:
```python
# WRONG - This endpoint doesn't exist!
url = f"{server_url}/customnode/install"
requests.post(url, json={"id": "PackageName"})
```

✅ **Always use the queue API**:
```python
# CORRECT
api_client.queue_task(kind="install", ...)
api_client.start_queue()
```

❌ **Don't use short timeouts in parallel tests**:
```python
time.sleep(5)  # Too short for parallel execution
```

✅ **Use adequate timeouts**:
```python
time.sleep(20-30)  # Better for parallel execution
```

### Test Fixture Best Practices

**Always cleanup before AND after tests**:
```python
@pytest.fixture
def my_fixture(custom_nodes_path):
    def _cleanup():
        # Remove test artifacts
        if package_path.exists():
            shutil.rmtree(package_path)
        time.sleep(0.5)  # Filesystem sync

    # Cleanup BEFORE test
    _cleanup()

    # Setup test state
    # ...

    yield

    # Cleanup AFTER test
    _cleanup()
```

## Additional Resources

- [data_models/README.md](../../comfyui_manager/data_models/README.md) - Data model generation guide
- [update_test_durations.sh](../update_test_durations.sh) - Duration update script
- [../TESTING_PROMPT.md](../TESTING_PROMPT.md) - Claude Code automation guide
