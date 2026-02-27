# Test Cases: Unified Dependency Resolver

See [TEST-environment-setup.md](TEST-environment-setup.md) for environment setup.

## Enabling the Resolver

Add the following to `config.ini` (in the Manager data directory):

```ini
[default]
use_unified_resolver = true
```

> Config path: `$COMFY_ROOT/user/__manager/config.ini`
> Also printed at startup: `** ComfyUI-Manager config path: <path>/config.ini`

**Log visibility note**: `[UnifiedDepResolver]` messages are emitted via Python's `logging` module (INFO and WARNING levels), not `print()`. Ensure the logging level is set to INFO or lower. ComfyUI defaults typically show these, but if messages are missing, check that the root logger or the `ComfyUI-Manager` logger is not set above INFO.

## API Reference (for Runtime Tests)

Node pack installation at runtime uses the task queue API:

```
POST http://localhost:8199/v2/manager/queue/task
Content-Type: application/json
```

> **Port**: E2E tests use port 8199 to avoid conflicts with running ComfyUI instances. Replace with your actual port if different.

**Payload** (`QueueTaskItem`):

| Field | Type | Description |
|-------|------|-------------|
| `ui_id` | string | Unique task identifier (any string) |
| `client_id` | string | Client identifier (any string) |
| `kind` | `OperationType` enum | `"install"`, `"uninstall"`, `"update"`, `"update-comfyui"`, `"fix"`, `"disable"`, `"enable"`, `"install-model"` |
| `params` | object | Operation-specific parameters (see below) |

**Install params** (`InstallPackParams`):

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | CNR node pack ID (e.g., `"comfyui-impact-pack"`) or `"author/repo"` |
| `version` | string | Required by model. Set to same value as `selected_version`. |
| `selected_version` | string | **Controls install target**: `"latest"`, `"nightly"`, or specific semver |
| `mode` | string | `"remote"`, `"local"`, or `"cache"` |
| `channel` | string | `"default"`, `"recent"`, `"legacy"`, etc. |

> **Note**: `cm_cli` imports from `legacy/manager_core.py` and does **not** participate in unified resolver. CLI-based installs always use per-node pip. See [Out of Scope](#out-of-scope-deferred).

---

## Out of Scope (Deferred)

The following are intentionally **not tested** in this version:

- **cm_global integration**: `pip_blacklist`, `pip_overrides`, `pip_downgrade_blacklist` are passed as empty defaults to the resolver. Integration with cm_global is deferred to a future commit. Do not file defects for blacklist/override/downgrade behavior in unified mode.
- **cm_cli (CLI tool)**: `cm_cli` imports from `legacy/manager_core.py` which does not have unified resolver integration. CLI-based installs always use per-node pip install regardless of the `use_unified_resolver` flag. This is a known limitation, not a defect.
- **Standalone `execute_install_script()`** (`glob/manager_core.py` ~line 1881): Has a unified resolver guard (`manager_util.use_unified_resolver`), identical to the class method guard. Reachable from the glob API via `update-comfyui` tasks (`update_path()` / `update_to_stable_comfyui()`), git-based node pack updates (`git_repo_update_check_with()` / `fetch_or_pull_git_repo()`), and gitclone operations. Also called from CLI and legacy server paths. The guard behaves identically to the class method at all call sites; testing it separately adds no coverage beyond TC-14 Path 1.

## Test Fixture Setup

Each TC that requires node packs should use isolated, deterministic fixtures:

```bash
# Create test node pack
mkdir -p "$COMFY_ROOT/custom_nodes/test_pack_a"
echo "chardet>=5.0" > "$COMFY_ROOT/custom_nodes/test_pack_a/requirements.txt"

# Cleanup after test
rm -rf "$COMFY_ROOT/custom_nodes/test_pack_a"
```

Ensure no other node packs in `custom_nodes/` interfere with expected counts. Use a clean `custom_nodes/` directory or account for existing packs in assertions.

---

## TC-1: Normal Batch Resolution [P0]

**Precondition**: `use_unified_resolver = true`, uv installed, at least one node pack with `requirements.txt`

**Steps**:
1. Create `$COMFY_ROOT/custom_nodes/test_pack_a/requirements.txt` with content: `chardet>=5.0`
2. Start ComfyUI

**Expected log**:
```
[UnifiedDepResolver] Collected N deps from M sources (skipped 0)
[UnifiedDepResolver] running: ... uv pip compile ...
[UnifiedDepResolver] running: ... uv pip install ...
[UnifiedDepResolver] startup batch resolution succeeded
```

**Verify**: Neither `Install: pip packages for` nor `Install: pip packages` appears in output (both per-node pip variants must be absent)

---

## TC-2: Disabled State (Default) [P1]

**Precondition**: `use_unified_resolver = false` or key absent from config.ini

**Steps**: Start ComfyUI

**Verify**: No `[UnifiedDepResolver]` log output at all

---

## TC-3: Fallback When uv Unavailable [P0]

**Precondition**: `use_unified_resolver = true`, uv completely unavailable

**Steps**:
1. Create a venv **without** uv installed (`uv` package not in venv)
2. Ensure no standalone `uv` binary exists in `$PATH` (rename or use isolated `$PATH`)
3. Start ComfyUI

```bash
# Reliable uv removal: both module and binary must be absent
uv pip uninstall uv
# Verify neither path works
python -m uv --version 2>&1 | grep -q "No module" && echo "module uv: absent"
which uv 2>&1 | grep -q "not found" && echo "binary uv: absent"
```

**Expected log**:
```
[UnifiedDepResolver] uv not available at startup, falling back to per-node pip
```

**Verify**:
- `manager_util.use_unified_resolver` is reset to `False`
- Subsequent node pack installations use per-node pip install normally

---

## TC-4: Fallback on Compile Failure [P0]

**Precondition**: `use_unified_resolver = true`, conflicting dependencies

**Steps**:
1. Node pack A `requirements.txt`: `numpy==1.24.0`
2. Node pack B `requirements.txt`: `numpy==1.26.0`
3. Start ComfyUI

**Expected log**:
```
[UnifiedDepResolver] startup batch failed: compile failed: ..., falling back to per-node pip
```

**Verify**:
- `manager_util.use_unified_resolver` is reset to `False`
- Falls back to per-node pip install normally

---

## TC-5: Fallback on Install Failure [P0]

**Precondition**: `use_unified_resolver = true`, compile succeeds but install fails

**Steps**:
1. Create node pack with `requirements.txt`: `numpy<2`
2. Force install failure by making the venv's `site-packages` read-only:
```bash
chmod -R a-w "$(python -c 'import site; print(site.getsitepackages()[0])')"
```
3. Start ComfyUI
4. After test, restore permissions:
```bash
chmod -R u+w "$(python -c 'import site; print(site.getsitepackages()[0])')"
```

**Expected log**:
```
[UnifiedDepResolver] startup batch failed: ..., falling back to per-node pip
```
> The `...` contains raw stderr from `uv pip install` (e.g., permission denied errors).

**Verify**:
- `manager_util.use_unified_resolver` is reset to `False`
- Falls back to per-node pip install

---

## TC-6: install.py Execution Preserved [P0]

**Precondition**: `use_unified_resolver = true`, ComfyUI running with batch resolution succeeded

**Steps**:
1. While ComfyUI is running, install a node pack that has both `install.py` and `requirements.txt` via API:
```bash
curl -X POST http://localhost:8199/v2/manager/queue/task \
  -H "Content-Type: application/json" \
  -d '{
    "ui_id": "test-installpy",
    "client_id": "test-client",
    "kind": "install",
    "params": {
      "id": "<node-pack-id-with-install-py>",
      "version": "latest",
      "selected_version": "latest",
      "mode": "remote",
      "channel": "default"
    }
  }'
```
> Choose a CNR node pack known to have both `install.py` and `requirements.txt`.
> Alternatively, use the Manager UI to install the same pack.

2. Check logs after installation

**Verify**:
- `Install: install script` is printed (install.py runs immediately during install)
- `Install: pip packages` does NOT appear (deps deferred, not installed per-node)
- Log: `[UnifiedDepResolver] deps deferred to startup batch resolution for <path>`
- After **restart**, the new pack's deps are included in batch resolution (`Collected N deps from M sources`)

---

## TC-7: Dangerous Pattern Rejection [P0]

**Precondition**: `use_unified_resolver = true`

**Steps**: Include any of the following in a node pack's `requirements.txt`:
```
-r ../../../etc/hosts
--requirement secret.txt
-e git+https://evil.com/repo
--editable ./local
-c constraint.txt
--constraint external.txt
--find-links http://evil.com/pkgs
-f http://evil.com/pkgs
evil_pkg @ file:///etc/passwd
```

**Expected log**:
```
[UnifiedDepResolver] rejected dangerous line: '...' from <path>
```

**Verify**: Dangerous lines are skipped; remaining valid deps are installed normally

---

## TC-8: Path Separator Rejection [P0]

**Precondition**: `use_unified_resolver = true`

**Steps**: Node pack `requirements.txt`:
```
../evil/pkg
bad\pkg
./local_package
```

**Expected log**:
```
[UnifiedDepResolver] rejected path separator: '...' from <path>
```

**Verify**: Lines with `/` or `\` in the package name portion are rejected; valid deps on other lines are processed normally

---

## TC-9: --index-url / --extra-index-url Separation [P0]

**Precondition**: `use_unified_resolver = true`

Test all four inline forms:

| # | `requirements.txt` content | Expected package | Expected URL |
|---|---------------------------|-----------------|--------------|
| a | `torch --index-url https://example.com/whl` | `torch` | `https://example.com/whl` |
| b | `torch --extra-index-url https://example.com/whl` | `torch` | `https://example.com/whl` |
| c | `--index-url https://example.com/whl` (standalone) | *(none)* | `https://example.com/whl` |
| d | `--extra-index-url https://example.com/whl` (standalone) | *(none)* | `https://example.com/whl` |

**Steps**: Create a node pack with each variant (one at a time or combined with a valid package on a separate line)

**Verify**:
- Package spec is correctly extracted (or empty for standalone lines)
- URL is passed as `--extra-index-url` to `uv pip compile`
- Duplicate URLs across multiple node packs are deduplicated
- Log: `[UnifiedDepResolver] extra-index-url: <url>`

---

## TC-10: Credential Redaction [P0]

**Precondition**: `use_unified_resolver = true`

**Steps**: Node pack `requirements.txt`:
```
private-pkg --index-url https://user:token123@pypi.private.com/simple
```

**Verify**:
- `user:token123` does NOT appear in logs
- Masked as `****@` in log output

---

## TC-11: Disabled Node Packs Excluded [P1]

**Precondition**: `use_unified_resolver = true`

**Steps**: Test both disabled styles:
1. New style: `custom_nodes/.disabled/test_pack/requirements.txt` with content: `numpy`
2. Old style: `custom_nodes/test_pack.disabled/requirements.txt` with content: `requests`
3. Start ComfyUI

**Verify**: Neither disabled node pack's deps are collected (not included in `Collected N`)

---

## TC-12: No Dependencies [P2]

**Precondition**: `use_unified_resolver = true`, only node packs without `requirements.txt`

**Steps**: Start ComfyUI

**Expected log**:
```
[UnifiedDepResolver] No dependencies to resolve
```

**Verify**: Compile/install steps are skipped; startup completes normally

---

## TC-13: Runtime Node Pack Install (Defer Behavior) [P1]

**Precondition**: `use_unified_resolver = true`, batch resolution succeeded at startup

**Steps**:
1. Start ComfyUI and confirm batch resolution succeeds
2. While ComfyUI is running, install a new node pack via API:
```bash
curl -X POST http://localhost:8199/v2/manager/queue/task \
  -H "Content-Type: application/json" \
  -d '{
    "ui_id": "test-defer-1",
    "client_id": "test-client",
    "kind": "install",
    "params": {
      "id": "<node-pack-id>",
      "version": "latest",
      "selected_version": "latest",
      "mode": "remote",
      "channel": "default"
    }
  }'
```
> Replace `<node-pack-id>` with a real CNR node pack ID (e.g., from the Manager UI).
> Alternatively, use the Manager UI to install a node pack.

3. Check logs after installation

**Verify**:
- Log: `[UnifiedDepResolver] deps deferred to startup batch resolution for <path>`
- `Install: pip packages` does NOT appear
- After ComfyUI **restart**, the new node pack's deps are included in batch resolution

---

## TC-14: Both Unified Resolver Code Paths [P0]

Verify both code locations that guard per-node pip install behave correctly in unified mode:

| Path | Guard Variable | Trigger | Location |
|------|---------------|---------|----------|
| Runtime install | `manager_util.use_unified_resolver` | API install while ComfyUI is running | `glob/manager_core.py` class method (~line 846) |
| Startup lazy install | `_unified_resolver_succeeded` | Queued install processed at restart | `prestartup_script.py` `execute_lazy_install_script()` (~line 594) |

> **Note**: The standalone `execute_install_script()` in `glob/manager_core.py` (~line 1881) also has a unified resolver guard but is reachable via `update-comfyui`, git-based node pack updates, gitclone operations, CLI, and legacy server paths. The guard is identical to the class method; see [Out of Scope](#out-of-scope-deferred).

**Steps**:

**Path 1 — Runtime API install (class method)**:
```bash
# While ComfyUI is running:
curl -X POST http://localhost:8199/v2/manager/queue/task \
  -H "Content-Type: application/json" \
  -d '{
    "ui_id": "test-path1",
    "client_id": "test-client",
    "kind": "install",
    "params": {
      "id": "<node-pack-id>",
      "version": "latest",
      "selected_version": "latest",
      "mode": "remote",
      "channel": "default"
    }
  }'
```

> Choose a CNR node pack that has both `install.py` and `requirements.txt`.

**Path 2 — Startup lazy install (`execute_lazy_install_script`)**:
1. Create a test node pack with both `install.py` and `requirements.txt`:
```bash
mkdir -p "$COMFY_ROOT/custom_nodes/test_pack_lazy"
echo 'print("lazy install.py executed")' > "$COMFY_ROOT/custom_nodes/test_pack_lazy/install.py"
echo "chardet" > "$COMFY_ROOT/custom_nodes/test_pack_lazy/requirements.txt"
```
2. Manually inject a `#LAZY-INSTALL-SCRIPT` entry into `install-scripts.txt`:
```bash
SCRIPTS_DIR="$COMFY_ROOT/user/__manager/startup-scripts"
mkdir -p "$SCRIPTS_DIR"
PYTHON_PATH=$(which python)
echo "['$COMFY_ROOT/custom_nodes/test_pack_lazy', '#LAZY-INSTALL-SCRIPT', '$PYTHON_PATH']" \
  >> "$SCRIPTS_DIR/install-scripts.txt"
```
3. Start ComfyUI (with `use_unified_resolver = true`)

**Verify**:
- Path 1: `[UnifiedDepResolver] deps deferred to startup batch resolution for <path>` appears, `install.py` runs immediately, `Install: pip packages` does NOT appear
- Path 2: `lazy install.py executed` is printed (install.py runs at startup), `Install: pip packages for` does NOT appear for the pack (skipped because `_unified_resolver_succeeded` is True after batch resolution)

---

## TC-15: Behavior After Fallback in Same Process [P1]

**Precondition**: Resolver failed at startup (TC-4 or TC-5 scenario)

**Steps**:
1. Set up conflicting deps (as in TC-4) and start ComfyUI (resolver fails, flag reset to `False`)
2. While still running, install a new node pack via API:
```bash
curl -X POST http://localhost:8199/v2/manager/queue/task \
  -H "Content-Type: application/json" \
  -d '{
    "ui_id": "test-postfallback",
    "client_id": "test-client",
    "kind": "install",
    "params": {
      "id": "<node-pack-id>",
      "version": "latest",
      "selected_version": "latest",
      "mode": "remote",
      "channel": "default"
    }
  }'
```

**Verify**:
- New node pack uses per-node pip install (not deferred)
- `Install: pip packages` appears normally
- On next restart with conflicts resolved, unified resolver retries if config still `true`

---

## TC-16: Generic Exception Fallback [P1]

**Precondition**: `use_unified_resolver = true`, an exception escapes before `resolve_and_install()`

This covers the `except Exception` handler at `prestartup_script.py` (~line 793), distinct from `UvNotAvailableError` (TC-3) and `ResolveResult` failure (TC-4/TC-5). The generic handler catches errors in the import, `collect_node_pack_paths()`, `collect_base_requirements()`, or `UnifiedDepResolver.__init__()` — all of which run before the resolver's own internal error handling.

**Steps**:
1. Make the `custom_nodes` directory unreadable so `collect_node_pack_paths()` raises a `PermissionError`:
```bash
chmod a-r "$COMFY_ROOT/custom_nodes"
```
2. Start ComfyUI
3. After test, restore permissions:
```bash
chmod u+r "$COMFY_ROOT/custom_nodes"
```

**Expected log**:
```
[UnifiedDepResolver] startup error: ..., falling back to per-node pip
```

**Verify**:
- `manager_util.use_unified_resolver` is reset to `False`
- Falls back to per-node pip install normally
- Log pattern is `startup error:` (NOT `startup batch failed:` nor `uv not available`)

---

## TC-17: Restart Dependency Detection [P0]

**Precondition**: `use_unified_resolver = true`, automated E2E scripts available

This test verifies that the resolver correctly detects and installs dependencies for node packs added between restarts, incrementally building the dependency set.

**Steps**:
1. Boot ComfyUI with no custom node packs (Boot 1 — baseline)
2. Verify baseline deps only (Manager's own deps)
3. Stop ComfyUI
4. Clone `ComfyUI-Impact-Pack` into `custom_nodes/`
5. Restart ComfyUI (Boot 2)
6. Verify Impact Pack deps are installed (`cv2`, `skimage`, `dill`, `scipy`, `matplotlib`)
7. Stop ComfyUI
8. Clone `ComfyUI-Inspire-Pack` into `custom_nodes/`
9. Restart ComfyUI (Boot 3)
10. Verify Inspire Pack deps are installed (`cachetools`, `webcolors`)

**Expected log (each boot)**:
```
[UnifiedDepResolver] Collected N deps from M sources (skipped S)
[UnifiedDepResolver] running: ... uv pip compile ...
[UnifiedDepResolver] running: ... uv pip install ...
[UnifiedDepResolver] startup batch resolution succeeded
```

**Verify**:
- Boot 1: ~10 deps from ~10 sources; `cv2`, `dill`, `cachetools` are NOT installed
- Boot 2: ~19 deps from ~18 sources; `cv2`, `skimage`, `dill`, `scipy`, `matplotlib` all importable
- Boot 3: ~24 deps from ~21 sources; `cachetools`, `webcolors` also importable
- Both packs show as loaded in logs

**Automation**: Use `tests/e2e/scripts/` (setup → start → stop) with node pack cloning between boots.

---

## TC-18: Real Node Pack Integration [P0]

**Precondition**: `use_unified_resolver = true`, network access to GitHub + PyPI

Full pipeline test with real-world node packs (`ComfyUI-Impact-Pack` + `ComfyUI-Inspire-Pack`) to verify the resolver handles production requirements.txt files correctly.

**Steps**:
1. Set up E2E environment
2. Clone both Impact Pack and Inspire Pack into `custom_nodes/`
3. Direct-mode: instantiate `UnifiedDepResolver`, call `collect_requirements()` and `resolve_and_install()`
4. Boot-mode: start ComfyUI and verify via logs

**Expected behavior (direct mode)**:
```
--- Discovered node packs (3) ---     # Manager, Impact, Inspire
  ComfyUI-Impact-Pack
  ComfyUI-Inspire-Pack
  ComfyUI-Manager

--- Phase 1: Collect Requirements ---
  Total requirements: ~24
  Skipped: 1                          # SAM2 git+https:// URL
  Extra index URLs: set()
```

**Verify**:
- `git+https://github.com/facebookresearch/sam2.git` is correctly rejected with "rejected path separator"
- All other dependencies are collected and resolved
- After install, `cv2`, `PIL`, `scipy`, `skimage`, `matplotlib` are all importable
- No conflicting version errors during compile

**Automation**: Use `tests/e2e/scripts/` (setup → clone packs → start) with direct-mode resolver invocation.

---

## Validated Behaviors (from E2E Testing)

The following behaviors were confirmed during manual E2E testing:

### Resolver Pipeline
- **3-phase pipeline**: Collect → `uv pip compile` → `uv pip install` works end-to-end
- **Incremental detection**: Resolver discovers new node packs on each restart without reinstalling existing deps
- **Dependency deduplication**: Overlapping deps from multiple packs are resolved to compatible versions

### Security & Filtering
- **`git+https://` rejection**: URLs like `git+https://github.com/facebookresearch/sam2.git` are rejected with "rejected path separator" — SAM2 is the only dependency skipped from Impact Pack
- **Blacklist filtering**: `PackageRequirement` objects have `.name`, `.spec`, `.source` attributes; `collected.skipped` returns `[(spec_string, reason_string)]` tuples

### Manager Integration
- **Manager v4 endpoints**: All endpoints use `/v2/` prefix (e.g., `/v2/manager/queue/status`)
- **`Blocked by policy`**: Expected when Manager is pip-installed and also symlinked in `custom_nodes/`; prevents legacy double-loading
- **config.ini path**: Must be at `$COMFY_ROOT/user/__manager/config.ini`, not in the symlinked Manager dir

### Environment
- **PYTHONPATH requirement**: `comfy` is a local package (not pip-installed); `comfyui_manager` imports from `comfy`, so both require `PYTHONPATH=$COMFY_ROOT`
- **HOME isolation**: `HOME=$E2E_ROOT/home` prevents host config contamination during boot

---

## Summary

| TC | P | Scenario | Key Verification |
|----|---|----------|------------------|
| 1 | P0 | Normal batch resolution | compile → install pipeline |
| 2 | P1 | Disabled state | No impact on existing behavior |
| 3 | P0 | uv unavailable fallback | Flag reset + per-node resume |
| 4 | P0 | Compile failure fallback | Flag reset + per-node resume |
| 5 | P0 | Install failure fallback | Flag reset + per-node resume |
| 6 | P0 | install.py preserved | deps defer, install.py immediate |
| 7 | P0 | Dangerous pattern rejection | Security filtering |
| 8 | P0 | Path separator rejection | `/` and `\` in package names |
| 9 | P0 | index-url separation | All 4 variants + dedup |
| 10 | P0 | Credential redaction | Log security |
| 11 | P1 | Disabled packs excluded | Both `.disabled/` and `.disabled` suffix |
| 12 | P2 | No dependencies | Empty pipeline |
| 13 | P1 | Runtime install defer | Defer until restart |
| 14 | P0 | Both unified resolver paths | runtime API (class method) + startup lazy install |
| 15 | P1 | Post-fallback behavior | Per-node pip resumes in same process |
| 16 | P1 | Generic exception fallback | Distinct from uv-absent and batch-failed |
| 17 | P0 | Restart dependency detection | Incremental node pack discovery across restarts |
| 18 | P0 | Real node pack integration | Impact + Inspire Pack full pipeline |

### Traceability

| Feature Requirement | Test Cases |
|---------------------|------------|
| FR-1: Dependency collection | TC-1, TC-11, TC-12 |
| FR-2: Input sanitization | TC-7, TC-8, TC-10 |
| FR-3: Index URL handling | TC-9 |
| FR-4: Batch resolution (compile) | TC-1, TC-4 |
| FR-5: Batch install | TC-1, TC-5 |
| FR-6: install.py preserved | TC-6, TC-14 |
| FR-7: Startup batch integration | TC-1, TC-2, TC-3 |
| Fallback behavior | TC-3, TC-4, TC-5, TC-15, TC-16 |
| Disabled node pack exclusion | TC-11 |
| Runtime defer behavior | TC-13, TC-14 |
| FR-8: Restart discovery | TC-17 |
| FR-9: Real-world compatibility | TC-17, TC-18 |
| FR-2: Input sanitization (git URLs) | TC-8, TC-18 |
