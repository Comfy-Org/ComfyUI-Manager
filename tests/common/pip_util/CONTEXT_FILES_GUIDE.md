# Context Files Guide for pip_util Tests

Quick reference for all context files created for extending pip_util tests.

---

## 📋 File Overview

| File | Purpose | When to Use |
|------|---------|-------------|
| **DEPENDENCY_TREE_CONTEXT.md** | Complete dependency trees with version analysis | Adding new test packages or updating scenarios |
| **DEPENDENCY_ANALYSIS.md** | Analysis methodology and findings | Understanding why packages were chosen |
| **TEST_SCENARIOS.md** | Detailed test specifications | Writing new tests or understanding existing ones |
| **analyze_dependencies.py** | Interactive dependency analyzer | Exploring new packages before adding tests |
| **requirements-test-base.txt** | Base test environment packages | Setting up or modifying test environment |

---

## 🎯 Common Tasks

### Task 1: Adding a New Test Package

**Steps**:

1. **Analyze the package**:
   ```bash
   python analyze_dependencies.py NEW_PACKAGE
   ```

2. **Check size and dependencies**:
   ```bash
   ./test_venv/bin/pip download --no-deps NEW_PACKAGE
   ls -lh NEW_PACKAGE*.whl  # Check size
   ```

3. **Verify dependency tree**:
   - Open **DEPENDENCY_TREE_CONTEXT.md**
   - Follow "Adding New Test Scenarios" section
   - Document findings in the file

4. **Update requirements** (if pre-installation needed):
   - Add to `requirements-test-base.txt`
   - Run `./setup_test_env.sh` to recreate venv

5. **Write test**:
   - Follow patterns in `test_dependency_protection.py`
   - Use `reset_test_venv` fixture
   - Add scenario to **TEST_SCENARIOS.md**

6. **Verify**:
   ```bash
   pytest test_YOUR_NEW_TEST.py -v --override-ini="addopts="
   ```

---

### Task 2: Understanding Existing Tests

**Steps**:

1. **Read test scenario**:
   - Open **TEST_SCENARIOS.md**
   - Find your scenario (1-6)
   - Review initial state, action, expected result

2. **Check dependency details**:
   - Open **DEPENDENCY_TREE_CONTEXT.md**
   - Look up package in table of contents
   - Review dependency tree and version analysis

3. **Run analysis**:
   ```bash
   python analyze_dependencies.py PACKAGE
   ```

4. **Examine test code**:
   - Open relevant test file
   - Check policy fixture
   - Review assertions

---

### Task 3: Updating for New Package Versions

**When**: PyPI releases major version updates (e.g., urllib3 3.0)

**Steps**:

1. **Check current environment**:
   ```bash
   python analyze_dependencies.py --env
   ```

2. **Analyze new versions**:
   ```bash
   ./test_venv/bin/pip index versions PACKAGE | head -20
   python analyze_dependencies.py PACKAGE
   ```

3. **Update context files**:
   - Update version numbers in **DEPENDENCY_TREE_CONTEXT.md**
   - Update "Version Analysis" section
   - Document breaking changes

4. **Test with new versions**:
   - Update `requirements-test-base.txt` (if testing new base version)
   - OR update test to verify protection from new version
   - Run tests to verify behavior

5. **Update scenarios**:
   - Update **TEST_SCENARIOS.md** with new version numbers
   - Update expected results if behavior changed

---

### Task 4: Debugging Dependency Issues

**Problem**: Test fails with unexpected dependency versions

**Steps**:

1. **Check what's installed**:
   ```bash
   ./test_venv/bin/pip freeze | grep -E "(urllib3|certifi|six|requests)"
   ```

2. **Analyze what would install**:
   ```bash
   python analyze_dependencies.py PACKAGE
   ```

3. **Compare with expected**:
   - Open **DEPENDENCY_TREE_CONTEXT.md**
   - Check "Install Scenarios" for the package
   - Compare actual vs. expected

4. **Check for PyPI changes**:
   ```bash
   ./test_venv/bin/pip index versions PACKAGE
   ```

5. **Verify test environment**:
   ```bash
   rm -rf test_venv && ./setup_test_env.sh
   pytest test_FILE.py -v --override-ini="addopts="
   ```

---

## 📚 Context File Details

### DEPENDENCY_TREE_CONTEXT.md

**Contents**:
- Current test environment snapshot
- Complete dependency trees for all test packages
- Version analysis (current vs. latest)
- Upgrade scenarios matrix
- Guidelines for adding new scenarios
- Quick reference tables

**Use when**:
- Adding new test package
- Understanding why a package was chosen
- Checking version compatibility
- Updating for new PyPI releases

**Key sections**:
- Package Dependency Trees → See what each package depends on
- Version Analysis → Understand version gaps and breaking changes
- Adding New Test Scenarios → Step-by-step guide

---

### DEPENDENCY_ANALYSIS.md

**Contents**:
- Detailed analysis of each test scenario
- Real dependency verification using `pip --dry-run`
- Version difference analysis
- Rejected scenarios (and why)
- Package size verification
- Recommendations for implementation

**Use when**:
- Understanding test design decisions
- Evaluating new package candidates
- Reviewing why certain packages were rejected
- Learning the analysis methodology

**Key sections**:
- Test Scenarios with Real Dependencies → Detailed scenarios
- Rejected Scenarios → What NOT to use (e.g., click+colorama)
- Validation Commands → How to verify analysis

---

### TEST_SCENARIOS.md

**Contents**:
- Complete specifications for scenarios 1-6
- Exact package versions and states
- Policy configurations (JSON)
- Expected pip commands
- Expected final states
- Key points for each scenario

**Use when**:
- Writing new tests
- Understanding test expectations
- Debugging test failures
- Documenting new scenarios

**Key sections**:
- Each scenario section → Complete specification
- Summary tables → Quick reference
- Policy types summary → Available policy options

---

### analyze_dependencies.py

**Features**:
- Interactive package analysis
- Dry-run simulation
- Version comparison
- Pin impact analysis

**Use when**:
- Exploring new packages
- Verifying current environment
- Checking upgrade impacts
- Quick dependency checks

**Commands**:
```bash
# Analyze specific package
python analyze_dependencies.py requests

# Analyze all test packages
python analyze_dependencies.py --all

# Show current environment
python analyze_dependencies.py --env
```

---

### requirements-test-base.txt

**Contents**:
- Base packages for test environment
- Version specifications
- Comments explaining each package's purpose

**Use when**:
- Setting up test environment
- Adding pre-installed packages
- Modifying base versions
- Recreating clean environment

**Format**:
```txt
# Scenario X: Purpose
package==version  # Comment explaining role
```

---

## 🔄 Workflow Examples

### Example 1: Adding flask Test

```bash
# 1. Analyze flask
python analyze_dependencies.py flask

# Output shows:
#   Would install: Flask, Jinja2, MarkupSafe, Werkzeug, blinker, click, itsdangerous

# 2. Check sizes
./test_venv/bin/pip download --no-deps flask jinja2 werkzeug
ls -lh *.whl

# 3. Document in DEPENDENCY_TREE_CONTEXT.md
# Add section:
### 3. flask → Dependencies
**Package**: `flask==3.1.2`
**Size**: ~100KB
...

# 4. Write test
# Create test_flask_dependencies.py

# 5. Test
pytest test_flask_dependencies.py -v --override-ini="addopts="
```

---

### Example 2: Investigating Test Failure

```bash
# Test failed: "urllib3 version mismatch"

# 1. Check installed
./test_venv/bin/pip freeze | grep urllib3
# Output: urllib3==2.5.0  (expected: 1.26.15)

# 2. Analyze what happened
python analyze_dependencies.py requests

# 3. Check context
# Open DEPENDENCY_TREE_CONTEXT.md
# Section: "urllib3: Major Version Jump"
# Confirms: 1.26.15 → 2.5.0 is expected without pin

# 4. Verify test has pin
# Check test_dependency_protection.py for pin_policy fixture

# 5. Reset environment
rm -rf test_venv && ./setup_test_env.sh

# 6. Re-run test
pytest test_dependency_protection.py -v --override-ini="addopts="
```

---

## 🎓 Best Practices

### When Adding New Tests

✅ **DO**:
- Use `analyze_dependencies.py` first
- Document in **DEPENDENCY_TREE_CONTEXT.md**
- Add scenario to **TEST_SCENARIOS.md**
- Verify with real pip operations
- Keep packages lightweight (<500KB total)

❌ **DON'T**:
- Add packages without verifying dependencies
- Use packages with optional dependencies only
- Add heavy packages (>1MB)
- Skip documentation
- Mock subprocess for integration tests

---

### When Updating Context

✅ **DO**:
- Re-run `analyze_dependencies.py --all`
- Update version numbers throughout
- Document breaking changes
- Test after updates
- Note update date

❌ **DON'T**:
- Update only one file
- Skip verification
- Forget to update TEST_SCENARIOS.md
- Leave outdated version numbers

---

## 🆘 Quick Troubleshooting

| Problem | Check | Solution |
|---------|-------|----------|
| Test fails with version mismatch | `pip freeze` | Recreate venv with `./setup_test_env.sh` |
| Package not found | `pip index versions PKG` | Check if package exists on PyPI |
| Unexpected dependencies | `analyze_dependencies.py PKG` | Review dependency tree in context file |
| Wrong test data | **TEST_SCENARIOS.md** | Verify against documented scenario |
| Unclear why package chosen | **DEPENDENCY_ANALYSIS.md** | Read "Rejected Scenarios" section |

---

## 📞 Need Help?

1. **Check context files first**: Most answers are documented
2. **Run analyze_dependencies.py**: Verify current state
3. **Review test scenarios**: Understand expected behavior
4. **Examine dependency trees**: Understand relationships
5. **Check DEPENDENCY_ANALYSIS.md**: Learn the "why" behind decisions

---

## 📝 Maintenance Checklist

**Every 6 months or when major versions release**:

- [ ] Run `python analyze_dependencies.py --all`
- [ ] Check for new major versions: `pip index versions urllib3 certifi six`
- [ ] Update **DEPENDENCY_TREE_CONTEXT.md** version numbers
- [ ] Update **TEST_SCENARIOS.md** expected versions
- [ ] Test all scenarios: `pytest -v --override-ini="addopts="`
- [ ] Document any breaking changes
- [ ] Update this guide if workflow changed

---

## 🔗 File Relationships

```
requirements-test-base.txt
    ↓ (defines)
Current Test Environment
    ↓ (analyzed by)
analyze_dependencies.py
    ↓ (documents)
DEPENDENCY_TREE_CONTEXT.md
    ↓ (informs)
TEST_SCENARIOS.md
    ↓ (implemented in)
test_*.py files
```

---

**Last Updated**: 2025-10-01
**Python Version**: 3.12.3
**pip Version**: 25.2
