# Dependency Tree Context for pip_util Tests

**Generated**: 2025-10-01
**Tool**: `pip install --dry-run --ignore-installed`
**Python**: 3.12.3
**pip**: 25.2

This document provides detailed dependency tree information for all test packages, verified against real PyPI data. Use this as a reference when extending tests.

---

## Table of Contents

1. [Current Test Environment](#current-test-environment)
2. [Package Dependency Trees](#package-dependency-trees)
3. [Version Analysis](#version-analysis)
4. [Upgrade Scenarios](#upgrade-scenarios)
5. [Adding New Test Scenarios](#adding-new-test-scenarios)

---

## Current Test Environment

**Base packages installed in test_venv** (from `requirements-test-base.txt`):

```
urllib3==1.26.15           # Protected from 2.x upgrade
certifi==2023.7.22         # Protected from 2025.x upgrade
charset-normalizer==3.2.0  # Protected from 3.4.x upgrade
six==1.16.0                # For deletion/restore tests
attrs==23.1.0              # Bystander package
packaging==23.1            # Bystander package
pytest==8.4.2              # Test framework
```

**Total environment size**: ~913KB (all packages < 1MB)

---

## Package Dependency Trees

### 1. requests → Dependencies

**Package**: `requests==2.32.5`
**Size**: ~100KB
**Purpose**: Main test package for dependency protection

#### Dependency Tree

```
requests==2.32.5
├── charset-normalizer<4,>=2
│   └── 3.2.0 (OLD) → 3.4.3 (LATEST)
├── idna<4,>=2.5
│   └── (NOT INSTALLED) → 3.10 (LATEST)
├── urllib3<3,>=1.21.1
│   └── 1.26.15 (OLD) → 2.5.0 (LATEST) ⚠️ MAJOR VERSION JUMP
└── certifi>=2017.4.17
    └── 2023.7.22 (OLD) → 2025.8.3 (LATEST)
```

#### Install Scenarios

**Scenario A: Without constraints (fresh install)**
```bash
$ pip install --dry-run --ignore-installed requests

Would install:
  certifi-2025.8.3           # Latest version
  charset-normalizer-3.4.3   # Latest version
  idna-3.10                  # New dependency
  requests-2.32.5            # Target package
  urllib3-2.5.0              # Latest version (2.x!)
```

**Scenario B: With pin constraints**
```bash
$ pip install --dry-run requests \
    urllib3==1.26.15 \
    certifi==2023.7.22 \
    charset-normalizer==3.2.0

Would install:
  certifi-2023.7.22          # Pinned to OLD version
  charset-normalizer-3.2.0   # Pinned to OLD version
  idna-3.10                  # New dependency (not pinned)
  requests-2.32.5            # Target package
  urllib3-1.26.15            # Pinned to OLD version
```

**Impact Analysis**:
- ✅ Pin successfully prevents urllib3 1.x → 2.x major upgrade
- ✅ Pin prevents certifi 2023 → 2025 upgrade (2 years)
- ✅ Pin prevents charset-normalizer minor upgrade
- ⚠️ idna is NEW and NOT pinned (acceptable - new dependency)

---

### 2. python-dateutil → Dependencies

**Package**: `python-dateutil==2.9.0.post0`
**Size**: ~280KB
**Purpose**: Real dependency chain test (depends on six)

#### Dependency Tree

```
python-dateutil==2.9.0.post0
└── six>=1.5
    └── 1.16.0 (OLD) → 1.17.0 (LATEST)
```

#### Install Scenarios

**Scenario A: Without constraints**
```bash
$ pip install --dry-run --ignore-installed python-dateutil

Would install:
  python-dateutil-2.9.0.post0  # Target package
  six-1.17.0                   # Latest version
```

**Scenario B: With pin constraints**
```bash
$ pip install --dry-run python-dateutil six==1.16.0

Would install:
  python-dateutil-2.9.0.post0  # Target package
  six-1.16.0                   # Pinned to OLD version
```

**Impact Analysis**:
- ✅ Pin successfully prevents six 1.16.0 → 1.17.0 upgrade
- ✅ Real dependency relationship (verified via PyPI)

---

### 3. Other Test Packages (No Dependencies)

These packages have no dependencies or only have dependencies already in the test environment:

```
attrs==23.1.0         # No dependencies
packaging==23.1       # No dependencies (standalone)
six==1.16.0           # No dependencies (pure Python)
```

---

## Version Analysis

### urllib3: Major Version Jump (1.x → 2.x)

**Current**: 1.26.15 (2023)
**Latest**: 2.5.0 (2025)
**Breaking Changes**: YES - urllib3 2.0 removed deprecated APIs

**Available versions**:
```
2.x series: 2.5.0, 2.4.0, 2.3.0, 2.2.3, 2.2.2, 2.2.1, 2.2.0, 2.1.0, 2.0.7, ...
1.26.x:     1.26.20, 1.26.19, 1.26.18, 1.26.17, 1.26.16, 1.26.15, ...
1.25.x:     1.25.11, 1.25.10, 1.25.9, ...
```

**Why test with 1.26.15?**
- ✅ Real-world scenario: Many projects pin `urllib3<2` to avoid breaking changes
- ✅ Meaningful test: 1.x → 2.x is a major API change
- ✅ Compatibility: requests accepts both 1.x and 2.x (`urllib3<3,>=1.21.1`)

**Breaking changes in urllib3 2.0**:
- Removed `urllib3.contrib.pyopenssl`
- Removed `urllib3.contrib.securetransport`
- Changed import paths for some modules
- Updated connection pooling behavior

---

### certifi: Long-Term Version Gap (2023 → 2025)

**Current**: 2023.7.22 (July 2023)
**Latest**: 2025.8.3 (August 2025)
**Gap**: ~2 years of SSL certificate updates

**Available versions**:
```
2025: 2025.8.3, 2025.7.14, 2025.7.9, 2025.6.15, 2025.4.26, ...
2024: 2024.12.25, 2024.11.28, 2024.10.29, 2024.9.19, ...
2023: 2023.11.17, 2023.7.22, 2023.5.7, ...
```

**Why test with 2023.7.22?**
- ✅ Real-world scenario: Older environments with outdated SSL certificates
- ✅ Meaningful test: 2-year gap shows protection of older versions
- ✅ Safety: Still compatible with requests (`certifi>=2017.4.17`)

---

### charset-normalizer: Minor Version Updates

**Current**: 3.2.0 (2023)
**Latest**: 3.4.3 (2025)
**Breaking Changes**: NO - only minor/patch updates

**Available versions**:
```
3.4.x: 3.4.3, 3.4.2, 3.4.1, 3.4.0
3.3.x: 3.3.2, 3.3.1, 3.3.0
3.2.x: 3.2.0
```

**Why test with 3.2.0?**
- ✅ Demonstrates protection of minor version updates
- ✅ Compatible with requests (`charset-normalizer<4,>=2`)

---

### six: Stable Version Update

**Current**: 1.16.0 (2021)
**Latest**: 1.17.0 (2024)
**Breaking Changes**: NO - six is very stable

**Available versions**:
```
1.17.0, 1.16.0, 1.15.0, 1.14.0, 1.13.0, 1.12.0, ...
```

**Why test with 1.16.0?**
- ✅ Real dependency of python-dateutil
- ✅ Small size (11KB) - lightweight for tests
- ✅ Demonstrates protection of stable packages

---

### idna: New Dependency

**Not pre-installed** - Added by requests

**Version**: 3.10
**Size**: ~69KB
**Dependency spec**: `idna<4,>=2.5` (from requests)

**Why NOT pre-installed?**
- ✅ Tests that new dependencies are correctly added
- ✅ Tests that pins only affect specified packages
- ✅ Real-world scenario: new dependency introduced by package update

---

## Upgrade Scenarios

### Scenario Matrix

| Package | Initial | Without Pin | With Pin | Change Type |
|---------|---------|-------------|----------|-------------|
| **urllib3** | 1.26.15 | 2.5.0 ❌ | 1.26.15 ✅ | Major (breaking) |
| **certifi** | 2023.7.22 | 2025.8.3 ❌ | 2023.7.22 ✅ | 2-year gap |
| **charset-normalizer** | 3.2.0 | 3.4.3 ❌ | 3.2.0 ✅ | Minor update |
| **six** | 1.16.0 | 1.17.0 ❌ | 1.16.0 ✅ | Stable update |
| **idna** | (none) | 3.10 ✅ | 3.10 ✅ | New dependency |
| **requests** | (none) | 2.32.5 ✅ | 2.32.5 ✅ | Target package |
| **python-dateutil** | (none) | 2.9.0 ✅ | 2.9.0 ✅ | Target package |

---

## Adding New Test Scenarios

### Step 1: Identify Candidate Package

Use `pip install --dry-run` to analyze dependencies:

```bash
# Analyze package dependencies
./test_venv/bin/pip install --dry-run --ignore-installed PACKAGE

# Check what changes with current environment
./test_venv/bin/pip install --dry-run PACKAGE

# List available versions
./test_venv/bin/pip index versions PACKAGE
```

### Step 2: Verify Real Dependencies

**Good candidates**:
- ✅ Has 2+ dependencies
- ✅ Dependencies have version upgrades available
- ✅ Total size < 500KB (all packages combined)
- ✅ Real-world use case (popular package)

**Examples**:
```bash
# flask → click, werkzeug, jinja2 (good: multiple dependencies)
$ pip install --dry-run --ignore-installed flask
Would install: Flask-3.1.2 Jinja2-3.1.6 MarkupSafe-3.0.3 Werkzeug-3.1.3 blinker-1.9.0 click-8.3.0 itsdangerous-2.2.0

# pytest-cov → pytest, coverage (good: popular testing tool)
$ pip install --dry-run --ignore-installed pytest-cov
Would install: coverage-7.10.7 pytest-8.4.2 pytest-cov-7.0.0
```

**Bad candidates**:
- ❌ click → colorama (no real dependency - colorama is optional/Windows-only)
- ❌ pandas → numpy (too large - numpy is 50MB+)
- ❌ torch → ... (too large - 800MB+)

### Step 3: Document Dependencies

Add to this file:

```markdown
### Package: PACKAGE_NAME → Dependencies

**Package**: `PACKAGE==VERSION`
**Size**: ~XXXKB
**Purpose**: Brief description

#### Dependency Tree
(Use tree format)

#### Install Scenarios
(Show with/without pin)

#### Impact Analysis
(What does pin protect?)
```

### Step 4: Update Test Files

1. Add package to `requirements-test-base.txt` (if pre-installation needed)
2. Create policy fixture in test file
3. Write test function using `reset_test_venv` fixture
4. Update `TEST_SCENARIOS.md` with detailed scenario

---

## Maintenance Notes

### Updating This Document

Re-run analysis when:
- ✅ PyPI releases major version updates (e.g., urllib3 3.0)
- ✅ Adding new test packages
- ✅ Test environment base packages change
- ✅ Every 6 months (to catch version drift)

### Verification Commands

```bash
# Regenerate dependency tree
./test_venv/bin/pip install --dry-run --ignore-installed requests
./test_venv/bin/pip install --dry-run --ignore-installed python-dateutil

# Check current environment
./test_venv/bin/pip freeze

# Verify test packages still available on PyPI
./test_venv/bin/pip index versions urllib3
./test_venv/bin/pip index versions certifi
./test_venv/bin/pip index versions six
```

---

## Quick Reference: Package Specs

From actual package metadata:

```python
# requests dependencies (from requests==2.32.5)
install_requires = [
    "charset_normalizer<4,>=2",
    "idna<4,>=2.5",
    "urllib3<3,>=1.21.1",
    "certifi>=2017.4.17"
]

# python-dateutil dependencies (from python-dateutil==2.9.0)
install_requires = [
    "six>=1.5"
]

# six dependencies
install_requires = []  # No dependencies

# attrs dependencies
install_requires = []  # No dependencies

# packaging dependencies
install_requires = []  # No dependencies
```

---

## Version Compatibility Table

| Package | Minimum | Maximum | Current Test | Latest | Notes |
|---------|---------|---------|--------------|--------|-------|
| urllib3 | 1.21.1 | <3.0 | 1.26.15 | 2.5.0 | Major version jump possible |
| certifi | 2017.4.17 | (none) | 2023.7.22 | 2025.8.3 | Always backward compatible |
| charset-normalizer | 2.0 | <4.0 | 3.2.0 | 3.4.3 | Within major version |
| six | 1.5 | (none) | 1.16.0 | 1.17.0 | Very stable |
| idna | 2.5 | <4.0 | (new) | 3.10 | Added by requests |

---

## See Also

- **DEPENDENCY_ANALYSIS.md** - Detailed analysis methodology
- **TEST_SCENARIOS.md** - Complete test scenario specifications
- **requirements-test-base.txt** - Base environment packages
- **README.md** - Test suite overview and usage
