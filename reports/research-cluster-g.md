# Research: Cluster G Semantics — imported_mode + boolean CLI flag

**Scope**: Wave3 Cluster G pre-research for dev assertion design.
**Researcher**: gteam-teng (Explore, read-only)
**Date**: 2026-04-19
**Targets**: 2 | **Status**: both resolved

---

## Target 1 — `/v2/customnode/installed?mode=imported` Semantics

### (i) Current source behavior — FROZEN AT STARTUP confirmed

**Source: `comfyui_manager/glob/manager_server.py`**

```python
# L1510 — module-level evaluation at import time
startup_time_installed_node_packs = core.get_installed_node_packs()

# L1513-1522
@routes.get("/v2/customnode/installed")
async def installed_list(request):
    mode = request.query.get("mode", "default")
    if mode == "imported":
        res = startup_time_installed_node_packs   # frozen
    else:
        res = core.get_installed_node_packs()     # live
```

**Source: `comfyui_manager/glob/manager_core.py:1599-1632`** — `get_installed_node_packs()` scans filesystem via `os.listdir()` on every call (LIVE).

**Design intent**: "imported" mode returns the snapshot captured exactly once, at module import time (when `from .glob import manager_server` runs during ComfyUI startup). Default mode re-scans the filesystem. The divergence surfaces after a runtime install — default grows, imported does not. Used by `TaskQueue` (`manager_server.py:211`) to know what was loaded vs what is now on disk.

### (ii) Test-env expected value

At startup, before any install action, `imported == default` in content (same filesystem state, same scan logic). The seed pack `ComfyUI_SigmoidOffsetScheduler` MUST be present in both.

Schema per entry: `{cnr_id: str, ver: str, aux_id: Optional[str], enabled: bool}` — see `manager_core.py:1614` & `:1630`.

### (iii) Wave3 assertion code snippet (Cluster G)

**Strategy A — schema + seed check (cheap, deterministic, no install needed):**

```python
def test_installed_imported_mode(self, comfyui):
    """GET ?mode=imported returns startup snapshot with documented schema.

    Frozen-at-startup invariant: at test time (no installs have occurred
    since server start), the imported snapshot must match the live listing
    in cardinality + key set, and each entry must carry the documented
    InstalledPack schema.
    """
    # Frozen snapshot
    resp_imp = requests.get(
        f"{BASE_URL}/v2/customnode/installed",
        params={"mode": "imported"}, timeout=10,
    )
    assert resp_imp.status_code == 200
    imported = resp_imp.json()
    assert isinstance(imported, dict), f"expected dict, got {type(imported).__name__}"

    # E2E seed pack must be in the startup snapshot
    seed = "ComfyUI_SigmoidOffsetScheduler"
    assert seed in imported, (
        f"seed pack {seed!r} missing from imported snapshot: keys={list(imported)}"
    )
    # Schema: same as default mode
    entry = imported[seed]
    for required in ("cnr_id", "ver", "enabled"):
        assert required in entry, f"{seed} missing {required!r}: {entry!r}"

    # Frozen invariant (cheap form): imported at startup == default at startup
    # (no install has occurred, so they must agree on keys + core fields)
    resp_def = requests.get(f"{BASE_URL}/v2/customnode/installed", timeout=10)
    default = resp_def.json()
    assert set(imported.keys()) == set(default.keys()), (
        f"imported != default at startup: "
        f"only-imported={set(imported)-set(default)}, "
        f"only-default={set(default)-set(imported)}"
    )
```

**Strategy B — true frozen invariant (expensive, OPTIONAL, skip by default):**

```python
@pytest.mark.skip(reason=
    "Requires post-startup install; E2E runtime install is slow and gated by "
    "security_level. Enable via PYTEST_FULL_IMPORTED_MODE=1 for nightly runs.")
def test_imported_mode_is_frozen_after_install(self, comfyui):
    """After installing a new pack, imported mode MUST still match startup.

    This is the true 'frozen' test — install a pack, then verify default mode
    sees it while imported mode does not (it was snapshotted before install).
    """
    snap_before = requests.get(
        f"{BASE_URL}/v2/customnode/installed", params={"mode": "imported"}, timeout=10,
    ).json()
    # ... trigger install of a fresh pack via /v2/customnode/install or FS manipulation ...
    snap_after = requests.get(
        f"{BASE_URL}/v2/customnode/installed", params={"mode": "imported"}, timeout=10,
    ).json()
    assert snap_before == snap_after, "imported snapshot mutated — frozen invariant broken"
    live_after = requests.get(f"{BASE_URL}/v2/customnode/installed", timeout=10).json()
    assert set(live_after) - set(snap_after), "default mode did not reflect the new install"
```

### (iv) Recommendation

- Adopt **Strategy A** as the WEAK-upgrade replacement — cheap, deterministic, ADEQUATE (positive path + field-level + cross-mode consistency).
- Register **Strategy B** as `[E2E-DEBT]` in the scaffold; keep `@pytest.mark.skip` unless a nightly pipeline enables it.
- Limitation to document: Strategy A cannot distinguish "frozen" from "live-and-coincidentally-equal" without a mid-session install — that's what Strategy B covers.

---

## Target 2 — `/v2/manager/is_legacy_manager_ui` boolean field (NOT /v2/manager/version)

**CORRECTION**: Dispatch text suggested `/v2/manager/version` as an example, but `test_returns_boolean_field` is defined inside `class TestIsLegacyManagerUI` (`tests/e2e/test_e2e_system_info.py:151-166`) and actually hits `/v2/manager/is_legacy_manager_ui`. `test_e2e_system_info.py::TestManagerVersion::test_version_returns_string` handles `/v2/manager/version` separately (returns `text/plain`, not JSON bool).

### (i) Current source behavior

**Source: `comfyui_manager/glob/manager_server.py:1500-1506`**

```python
@routes.get("/v2/manager/is_legacy_manager_ui")
async def is_legacy_manager_ui(request):
    return web.json_response(
        {"is_legacy_manager_ui": args.enable_manager_legacy_ui},
        content_type="application/json",
        status=200,
    )
```

**`args`** is imported from `comfy.cli_args` (upstream ComfyUI argparse — `comfyui_manager/__init__.py:6`). The flag `--enable-manager-legacy-ui` is registered by ComfyUI's own cli_args module (not in this repo). `action='store_true'` means default is `False` (bool), not `None`.

**Same handler exists in legacy server** at `comfyui_manager/legacy/manager_server.py:995-1001` — identical body.

**Also read in glob at `__init__.py:19`** to gate `from .legacy import manager_server` import. This confirms the value is bool at module load time (used as an `if`).

### (ii) Test-env expected value — DETERMINISTIC

**Source: `tests/e2e/scripts/start_comfyui.sh:73-79`** (launch command):

```bash
nohup "$PY" "$COMFY_DIR/main.py" \
    --cpu \
    --enable-manager \
    --port "$PORT" \
> "$LOG_FILE" 2>&1 &
```

The E2E launcher passes NO `--enable-manager-legacy-ui` flag. Therefore in every E2E run: `args.enable_manager_legacy_ui = False`.

No `tests/e2e/**` file references the flag (grep confirmed: 0 matches).

### (iii) Wave3 assertion code snippet

**Strengthen from `isinstance(bool)` → exact-value `is False`:**

```python
def test_returns_boolean_field(self, comfyui):
    """GET /v2/manager/is_legacy_manager_ui returns {is_legacy_manager_ui: False} in E2E.

    E2E env deterministically omits --enable-manager-legacy-ui
    (start_comfyui.sh passes only --cpu --enable-manager --port),
    so args.enable_manager_legacy_ui defaults to False (store_true default).
    Strengthened from type-only check to exact-value check.
    """
    resp = requests.get(
        f"{BASE_URL}/v2/manager/is_legacy_manager_ui", timeout=10,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert "is_legacy_manager_ui" in data, (
        f"Response missing 'is_legacy_manager_ui' field: {data}"
    )
    assert data["is_legacy_manager_ui"] is False, (
        f"E2E env omits --enable-manager-legacy-ui; expected False, "
        f"got {data['is_legacy_manager_ui']!r}. If E2E launcher changed, update assertion."
    )
```

**Optional companion test (true-path coverage, currently out of scope):** A parametrized variant that restarts ComfyUI with `--enable-manager-legacy-ui` and asserts `is True`. Not recommended for Cluster G — server restart doubles suite runtime and the legacy path is already exercised by playwright `legacy-ui-*.spec.ts` tests.

### (iv) Recommendation

- Upgrade `isinstance(bool)` → `is False` as above. ADEQUATE (positive-path + field + exact value).
- Document the launcher dependency in a comment (already in the snippet).
- If the E2E launcher ever passes `--enable-manager-legacy-ui`, the assertion fails loudly with a clear message — correct behavior.

---

## Summary Table

| Target | Current test | Upgrade path | Complexity | E2E-debt? |
|---|---|---|---|---|
| T1 imported_mode (`test_installed_imported_mode`) | dict-type only (WEAK) | Schema + seed + cross-mode keyset equality (ADEQUATE) | LOW | Yes — frozen-after-install invariant skipped (Strategy B) |
| T2 boolean flag (`test_returns_boolean_field`) | `isinstance(bool)` (WEAK) | `is False` with launcher-deterministic comment (ADEQUATE) | LOW | No |

## Constraints / Limitations

- Research performed as Explore agent (read-only). No tests executed, no code modified.
- `comfy.cli_args` is upstream (ComfyUI), not in manager repo — flag default verified via usage pattern (store_true action) and the `if args.enable_manager_legacy_ui:` truthiness check at `__init__.py:19`, which would crash with `TypeError` on `None` truthiness on integer comparisons but works on falsy-default bool.
- Target 2 CORRECTION: dispatch referenced `/v2/manager/version` but the target test actually hits `/v2/manager/is_legacy_manager_ui` — verified via source inspection of test class.

## Grep/Read evidence index

| # | Command | Finding |
|---|---|---|
| 1 | `Grep pattern=/customnode/installed path=glob/manager_server.py` | L1510 snapshot init, L1513-1520 handler |
| 2 | `Read tests/e2e/test_e2e_customnode_info.py` | L224-237 current WEAK test |
| 3 | `Grep pattern=is_legacy_manager_ui path=comfyui_manager` | L1500-1506 glob handler, L995-1001 legacy handler |
| 4 | `Grep pattern=enable-manager-legacy-ui path=tests/e2e` | 0 matches — flag not passed in E2E |
| 5 | `Read tests/e2e/scripts/start_comfyui.sh` | L73-79 launch command (no legacy flag) |
| 6 | `Read comfyui_manager/__init__.py` | L19 uses flag as truthy gate |
| 7 | `Read glob/manager_core.py:1599-1632` | `get_installed_node_packs()` live filesystem scan |
