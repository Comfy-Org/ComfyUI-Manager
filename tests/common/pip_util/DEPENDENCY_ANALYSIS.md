# pip_util Test Package Dependency Analysis

Real dependency analysis using `pip install --dry-run` to verify meaningful test scenarios.

## Analysis Date

Generated: 2025-10-01
Tool: `pip install --dry-run --ignore-installed`

## Test Scenarios with Real Dependencies

### Scenario 1: Dependency Version Protection (requests + urllib3)

**Purpose**: Verify pin_dependencies prevents unwanted upgrades

**Initial Environment**:
```
urllib3==1.26.15
certifi==2023.7.22
charset-normalizer==3.2.0
```

**Without pin** (`pip install requests`):
```bash
Would install:
  certifi-2025.8.3          # UPGRADED from 2023.7.22 (+2 years)
  charset-normalizer-3.4.3  # UPGRADED from 3.2.0 (minor)
  idna-3.10                 # NEW dependency
  requests-2.32.5           # NEW package
  urllib3-2.5.0             # UPGRADED from 1.26.15 (MAJOR 1.x→2.x!)
```

**With pin** (`pip install requests urllib3==1.26.15 certifi==2023.7.22 charset-normalizer==3.2.0`):
```bash
Would install:
  idna-3.10          # NEW dependency (required by requests)
  requests-2.32.5    # NEW package

# Pinned packages stay at old versions:
  urllib3==1.26.15              ✅ PROTECTED (prevented 1.x→2.x jump)
  certifi==2023.7.22            ✅ PROTECTED
  charset-normalizer==3.2.0     ✅ PROTECTED
```

**Key Finding**:
- `urllib3` 1.26.15 → 2.5.0 is a **MAJOR version jump** (breaking changes!)
- requests accepts both: `urllib3<3,>=1.21.1` (compatible with 1.x and 2.x)
- Pin successfully prevents unwanted major upgrade

---

### Scenario 2: Package with Dependency (python-dateutil + six)

**Purpose**: Verify pin_dependencies with dependency chain

**Analysis**:
```bash
$ pip install --dry-run python-dateutil

Would install:
  python-dateutil-2.9.0.post0
  six-1.17.0  # DEPENDENCY
```

**Initial Environment**:
```
six==1.16.0  # Older version
```

**Without pin** (`pip install python-dateutil`):
```bash
Would install:
  python-dateutil-2.9.0.post0
  six-1.17.0  # UPGRADED from 1.16.0
```

**With pin** (`pip install python-dateutil six==1.16.0`):
```bash
Would install:
  python-dateutil-2.9.0.post0

# Pinned package:
  six==1.16.0  ✅ PROTECTED
```

---

### Scenario 3: Package Deletion and Restore (six)

**Purpose**: Verify restore policy reinstalls deleted packages

**Initial Environment**:
```
six==1.16.0
attrs==23.1.0
packaging==23.1
```

**Action Sequence**:
1. Delete six: `pip uninstall -y six`
2. Verify deletion: `pip freeze | grep six` (empty)
3. Restore: `batch.ensure_installed()` → `pip install six==1.16.0`

**Expected Result**:
```
six==1.16.0  # ✅ RESTORED
```

---

### Scenario 4: Version Change and Restore (urllib3)

**Purpose**: Verify restore policy reverts version changes

**Initial Environment**:
```
urllib3==1.26.15
```

**Action Sequence**:
1. Upgrade: `pip install urllib3==2.5.0`
2. Verify change: `pip freeze | grep urllib3` → `urllib3==2.5.0`
3. Restore: `batch.ensure_installed()` → `pip install urllib3==1.26.15`

**Expected Result**:
```
urllib3==1.26.15  # ✅ RESTORED (downgraded from 2.5.0)
```

**Key Finding**:
- Downgrade from 2.x to 1.x requires explicit version specification
- pip allows downgrades with `pip install urllib3==1.26.15`

---

## Rejected Scenarios

### click + colorama (NO REAL DEPENDENCY)

**Analysis**:
```bash
$ pip install --dry-run click
Would install: click-8.3.0

$ pip install --dry-run click colorama==0.4.6
Would install: click-8.3.0  # colorama not installed!
```

**Finding**: click has **NO direct dependency** on colorama
- colorama is **optional** and platform-specific (Windows only)
- Not a good test case for dependency protection

**Recommendation**: Use python-dateutil + six instead

---

## Package Size Verification

```bash
Package                Size    Version    Purpose
-------------------------------------------------------
urllib3               ~140KB  1.26.15    Protected dependency
certifi               ~158KB  2023.7.22  SSL certificates
charset-normalizer    ~46KB   3.2.0      Charset detection
idna                  ~69KB   3.10       NEW dep from requests
requests              ~100KB  2.32.5     Main package to install
six                   ~11KB   1.16.0     Restore test
python-dateutil       ~280KB  2.9.0      Depends on six
attrs                 ~61KB   23.1.0     Bystander
packaging             ~48KB   23.1       Bystander
-------------------------------------------------------
Total                 ~913KB  (< 1MB)    ✅ All lightweight
```

---

## Dependency Graph

```
requests 2.32.5
├── charset_normalizer<4,>=2  (have: 3.2.0)
├── idna<4,>=2.5              (need: 3.10)  ← NEW
├── urllib3<3,>=1.21.1        (have: 1.26.15, latest: 2.5.0)
└── certifi>=2017.4.17        (have: 2023.7.22, latest: 2025.8.3)

python-dateutil 2.9.0
└── six>=1.5                  (have: 1.16.0, latest: 1.17.0)
```

---

## Version Compatibility Matrix

| Package | Old Version | Latest | Spec | Compatible? |
|---------|------------|--------|------|-------------|
| urllib3 | 1.26.15 | 2.5.0 | <3,>=1.21.1 | ✅ Both work |
| certifi | 2023.7.22 | 2025.8.3 | >=2017.4.17 | ✅ Both work |
| charset-normalizer | 3.2.0 | 3.4.3 | <4,>=2 | ✅ Both work |
| six | 1.16.0 | 1.17.0 | >=1.5 | ✅ Both work |
| idna | (none) | 3.10 | <4,>=2.5 | ⚠️ Must install |

---

## Test Data Justification

### Why urllib3 1.26.15?
1. **Real world scenario**: Many projects pin urllib3<2 to avoid breaking changes
2. **Meaningful test**: 1.26.15 → 2.5.0 is a major version jump (API changes)
3. **Compatibility**: requests accepts both 1.x and 2.x (good for testing)

### Why certifi 2023.7.22?
1. **Real world scenario**: Older environment with outdated SSL certificates
2. **Meaningful test**: 2-year version gap (2023 → 2025)
3. **Safety**: Still compatible with requests

### Why six 1.16.0?
1. **Lightweight**: Only 11KB
2. **Real dependency**: python-dateutil actually depends on it
3. **Stable**: six is mature and rarely changes

---

## Recommendations for Test Implementation

### ✅ Keep These Scenarios:
1. **requests + urllib3 pin** - Real major version protection
2. **python-dateutil + six** - Real dependency chain
3. **six deletion/restore** - Real package management
4. **urllib3 version change** - Real downgrade scenario

### ❌ Remove These Scenarios:
1. **click + colorama** - No real dependency (colorama is optional/Windows-only)

### 📝 Update Required Files:
1. `requirements-test-base.txt` - Add idna (new dependency from requests)
2. `TEST_SCENARIOS.md` - Update with real dependency analysis
3. `test_dependency_protection.py` - Remove click-colorama test
4. `pip_util.design.en.md` - Update examples with verified dependencies

---

## Validation Commands

Run these to verify analysis:

```bash
# Check current environment
./test_venv/bin/pip freeze

# Simulate requests installation without pin
./test_venv/bin/pip install --dry-run requests

# Simulate requests installation with pin
./test_venv/bin/pip install --dry-run requests urllib3==1.26.15 certifi==2023.7.22 charset-normalizer==3.2.0

# Check python-dateutil dependencies
./test_venv/bin/pip install --dry-run python-dateutil

# Verify urllib3 version availability
./test_venv/bin/pip index versions urllib3 | head -20
```
