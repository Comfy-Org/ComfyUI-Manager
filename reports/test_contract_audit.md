# Test Contract Audit

**Generated**: 2026-04-18
**Contract**:
- **Glob E2E** = endpoint call → effect verification (HTTP POST/GET + verify state change or response correctness)
- **Legacy E2E** = UI interaction → effect verification (click/select/fill + verify state change)

Tests that call HTTP endpoints directly in the Playwright suite VIOLATE the legacy contract. Tests that check only status code without verifying effect VIOLATE the glob contract.

## Summary

| Contract violation | Count | Severity |
|---|---:|---|
| Playwright tests using direct API (bypass UI) | ~~9~~ → 5 | 🔴 contract breach (4 resolved in Stage2 WI-F; remaining 5 are in legacy-ui-snapshot helper functions + other files — see updated Section 1) |
| Playwright tests partially UI-driven (mixed) | 2 | 🟡 weakened |
| Glob tests missing effect verification | ~~1~~ → 0 | 🟡 status-only (resolved in Stage2 WI-D) |
| Glob tests fully effect-verifying | 80 | ✓ compliant |
| Security-contract tests (CSRF method-reject — 8 functions / 52 invocations — 26 glob + 26 legacy) | 8 | ✓ compliant (separate negative contract; glob + legacy server coverage) |

---

# Section 1 — Playwright Contract Audit (Legacy UI → Effect)

## ✅ VIOLATIONS — all 4 listed tests resolved in Stage2 WI-F

Historical record (2026-04-18, Stage2 WI-F). All 4 direct-API Playwright tests that previously violated the legacy contract have been removed from the suite or rewritten to click real UI elements:

| File | Test | Original violation | Resolution |
|---|---|---|---|
| legacy-ui-snapshot.spec.ts | `lists existing snapshots` | Direct `page.request.get('/v2/snapshot/getlist')` — no UI click | **DELETED**; backend `getlist` coverage owned by pytest `test_e2e_snapshot_lifecycle.py::test_getlist_after_save` (12/12 pytest regression PASS). |
| legacy-ui-snapshot.spec.ts | `save snapshot via API and verify in list` | 100% `page.request.post/get` — zero UI interaction | **REWRITTEN** as `SS1 Save button creates a new snapshot row`: clicks dialog Save/Create button, polls `getlist` only as backend-effect confirmation helper (not as the test's primary action), cleans up via afterEach. Bonus: `UI Remove button deletes a snapshot row` added for row-delete UI coverage. |
| legacy-ui-navigation.spec.ts | `API health check while dialogs are open` | `page.request.get('/v2/manager/version')` — direct API, not UI | **DELETED**; version coverage owned by `test_e2e_system_info.py::test_version_returns_string/test_version_is_stable`. |
| legacy-ui-navigation.spec.ts | `system endpoints accessible from browser context` | 2× `page.request.get` — direct API | **DELETED**; fully redundant with `test_e2e_system_info.py` suite. |

**Verification**: `npx playwright test --list --grep '<any of the 4 titles>'` → `Total: 0 tests in 0 files`. Current spec listing: 5 tests in 2 files, all UI-driven.

**Residual note**: The snapshot spec still uses `page.request.get('/v2/snapshot/getlist')` inside the `getSnapshotNames` helper and in the `beforeEach/afterEach` for deterministic seeding/cleanup. This is acceptable because (a) the TEST ACTION is a UI button click, and (b) the API use is confined to backend-effect observation, matching the hybrid pattern also used in legacy-ui-manager-menu's dropdown tests (the mixed-pattern row below, which remains WEAKENED but is a known follow-up).

## 🟡 WEAKENED — tests that mix UI + direct API

These tests DO perform UI interaction (e.g., `selectOption`) but use direct API for verification/cleanup. The UI→effect part is present but the effect is validated via API, not via UI rendering.

| File | Test | Mixed pattern | Recommended |
|---|---|---|---|
| legacy-ui-manager-menu.spec.ts | `DB mode dropdown round-trips via API` | `selectOption(newValue)` (UI ✓) → `page.request.get` (verify ✗) | Verify via UI: re-open dialog, read `.value` from `<select>` element. Optional: also check page reload reflects persisted value. |
| legacy-ui-manager-menu.spec.ts | `Update Policy dropdown round-trips via API` | Same pattern | Same |

## ✓ CORRECT — pure UI→effect tests

| File | Test | UI action | Effect verified |
|---|---|---|---|
| legacy-ui-manager-menu.spec.ts | `opens via Manager button and shows 3-column layout` | Click Manager button | Dialog `#cm-manager-dialog` visible + expected buttons |
| legacy-ui-manager-menu.spec.ts | `shows settings dropdowns (DB, Channel, Policy)` | Open Manager menu | 3 `<select>` elements visible |
| legacy-ui-manager-menu.spec.ts | `closes and reopens without duplicating` | Close + reopen dialog | ≤2 dialog instances in DOM |
| legacy-ui-custom-nodes.spec.ts | `opens from Manager menu and renders grid` | Click "Custom Nodes Manager" | `#cn-manager-dialog` + grid visible |
| legacy-ui-custom-nodes.spec.ts | `loads custom node list (non-empty)` | Open dialog, wait | `.tg-row` count > 0 |
| legacy-ui-custom-nodes.spec.ts | `filter dropdown changes displayed nodes` | `selectOption('Installed')` | Filtered count ≤ initial |
| legacy-ui-custom-nodes.spec.ts | `search input filters the grid` | `fill('ComfyUI-Manager')` | Filtered count ≤ initial |
| legacy-ui-custom-nodes.spec.ts | `footer buttons are present` | Open dialog | Install via Git URL / Restart button visible |
| legacy-ui-model-manager.spec.ts | `opens from Manager menu and renders grid` | Click "Model Manager" | `#cmm-manager-dialog` + grid |
| legacy-ui-model-manager.spec.ts | `loads model list (non-empty)` | Open dialog | Rows > 0 |
| legacy-ui-model-manager.spec.ts | `search input filters the model grid` | `fill('stable diffusion')` | Filtered ≤ initial |
| legacy-ui-model-manager.spec.ts | `filter dropdown is present with expected options` | Open dialog | Options length > 0 |
| legacy-ui-snapshot.spec.ts | `opens snapshot manager from Manager menu` | Click "Snapshot Manager" | `#snapshot-manager-dialog` visible |
| legacy-ui-snapshot.spec.ts | `SS1 Save button creates a new snapshot row` | Click dialog Save/Create button | New snapshot appears in UI row + backend list (hybrid UI-action + backend-effect confirm) |
| legacy-ui-snapshot.spec.ts | `UI Remove button deletes a snapshot row` | Click in-row Remove/Delete button (dialog confirm accepted) | Snapshot absent from UI row AND backend list |
| legacy-ui-navigation.spec.ts | `Manager menu → Custom Nodes → close → Manager still visible` | Nested dialog nav | Manager reopenable |
| legacy-ui-navigation.spec.ts | `Manager menu → Model Manager → close → reopen` | Close + reopen | Model Manager reappears |
| debug-install-flow.spec.ts | `capture install button API flow` | Click Install → select version → Select | Captures full API sequence (debug) |

## Playwright Contract Summary (post Stage2 WI-F)

- **Compliant** (UI→effect): 17 / 20 tests (85%)
- **Mixed** (UI + direct API): 2 / 20 tests (10%)
- **Violating** (direct API only): 0 / 20 tests (0%) ✅ — WI-F resolved all 4
- **Debug/instrumentation** (acceptable exception): 1 / 20 tests (5%)

Net change from previous audit (22 tests → 20 tests): `legacy-ui-navigation` lost 2 deleted INADEQUATE tests; `legacy-ui-snapshot` kept 3 total (1 existing PASS + 2 new UI-driven PASS that replaced the 2 original INADEQUATE). The "Mixed" WEAKENED rows (2 manager-menu dropdown tests) remain and should be addressed in a follow-up WI.

---

# Section 1.5 — Security-Contract Tests (CSRF Method-Reject)

`tests/e2e/test_e2e_csrf.py` follows a NEGATIVE-assertion contract:
state-changing POST endpoints MUST reject HTTP GET. Unlike the glob
endpoint→effect contract (positive response + state change), the CSRF
contract verifies ABSENCE of acceptance.

**Contract**:
- GET on state-changing POST endpoint → status_code ∈ (400,403,404,405)
- POST counterpart → status_code == 200 (sanity)
- GET on read-only endpoint → status_code == 200 (negative control)

**Reference**: commit 99caef55 — "mitigate CSRF on state-changing
endpoints + version SSOT" (CVSS 8.1, reported by XlabAI-Tencent-Xuanwu).
Commit applied the GET→POST conversion to BOTH `glob/manager_server.py`
(~91 lines) and `legacy/manager_server.py` (~92 lines); the legacy-side
regression guard is exercised by `test_e2e_csrf_legacy.py` (added in WI-FF,
integrated into this audit in WI-GG).

**Scope clarification per file docstrings**:
ONLY the GET-rejection layer. NOT covered: Origin/Referer validation,
same-site cookies, anti-CSRF tokens, cross-site form POST. Do NOT
read a PASS here as "CSRF fully solved". Both glob and legacy suites
share the same scope — the split exists solely because `comfyui_manager/__init__.py`
loads `glob.manager_server` XOR `legacy.manager_server` (mutex via
`--enable-manager-legacy-ui`), so each route table requires its own server
lifecycle to exercise.

| File | Tests | Contract verdict |
|---|---:|---|
| test_e2e_csrf.py::TestStateChangingEndpointsRejectGet | 13 (parametrized; 3 dual-purpose endpoints removed in WI-HH — legitimately covered only in the allow-GET class) | ✓ compliant — negative-path security contract (glob) |
| test_e2e_csrf.py::TestCsrfPostWorks | 2 | ✓ compliant — positive sanity (glob) |
| test_e2e_csrf.py::TestCsrfReadEndpointsStillAllowGet | 11 (parametrized) | ✓ compliant — negative control for over-correction (glob) |
| test_e2e_csrf_legacy.py::TestLegacyStateChangingEndpointsRejectGet | 13 (parametrized — queue/task→queue/batch; 3 dual-purpose excluded) | ✓ compliant — negative-path security contract (legacy) |
| test_e2e_csrf_legacy.py::TestLegacyCsrfPostWorks | 2 | ✓ compliant — positive sanity (legacy) |
| test_e2e_csrf_legacy.py::TestLegacyCsrfReadEndpointsStillAllowGet | 11 (parametrized) | ✓ compliant — negative control (legacy) |

**Endpoint-list differences** (legacy vs glob, per `test_e2e_csrf_legacy.py` docstring L23–36):
- `/v2/manager/queue/task` → dropped (glob-only; legacy uses `queue/batch`)
- `/v2/manager/queue/batch` → added (legacy task-enqueue)
- `/v2/manager/db_mode`, `/v2/manager/policy/update`, `/v2/manager/channel_url_list` → dropped from reject-GET (CSRF contract applies only to POST write-path; same GET-read + POST-write split as glob, so these 3 legitimately appear in the allow-GET class only). `test_e2e_csrf.py` currently lists them in BOTH classes; WI-HH tracks the glob-side correction.

---

# Section 2 — Glob pytest Contract Audit (Endpoint → Effect)

## 🟡 Missing effect verification

| File | Test | Missing effect |
|---|---|---|
| test_e2e_task_operations.py | `test_install_model_accepts_valid_request` | Only checks 200 status. Does NOT verify task was actually queued (could be via GET queue/status total_count≥1). | 

Adding one line (`status check`) would fix this.

## ✓ Effect-verifying tests (80 of 81)

### Install/Uninstall (pack-level effects)
- test_e2e_endpoint.test_install_via_endpoint → `_pack_exists` + `_has_tracking` ✓
- test_e2e_endpoint.test_uninstall_via_endpoint → `_pack_exists == False` ✓
- test_e2e_endpoint.test_install_uninstall_cycle → both ✓
- test_e2e_git_clone.test_01_nightly_install → `_pack_exists` + `.git` dir ✓
- test_e2e_git_clone.test_03_nightly_uninstall → `_pack_exists == False` ✓

### Disable/Enable (state-level effects)
- test_e2e_task_operations.test_disable_pack → `_pack_disabled` + `_pack_exists == False` ✓
- test_e2e_task_operations.test_enable_pack → `_pack_exists` + `!_pack_disabled` ✓
- test_e2e_task_operations.test_disable_enable_cycle → both transitions ✓

### Update/Fix (post-state verification)
- test_e2e_task_operations.test_update_installed_pack → `_pack_exists` after ✓
- test_e2e_task_operations.test_fix_installed_pack → `_pack_exists` after ✓

### Queue state
- test_e2e_queue_lifecycle.test_reset_queue → status.pending_count == 0 ✓
- test_e2e_queue_lifecycle.test_queue_task_and_history → done_count > 0 ✓
- test_e2e_queue_lifecycle.test_start_queue_already_idle → status code ✓ (idempotent effect)
- test_e2e_task_operations.test_update_comfyui_queues_task → total_count ≥ 1 ✓

### Config round-trips (persistence effect)
- test_e2e_config_api.test_set_and_restore_db_mode → GET reflects POST ✓
- test_e2e_config_api.test_set_and_restore_update_policy → same ✓
- test_e2e_config_api.test_set_and_restore_channel → same ✓

### Snapshot state
- test_e2e_snapshot_lifecycle.test_save_snapshot + test_getlist_after_save → save creates, getlist reflects ✓
- test_e2e_snapshot_lifecycle.test_remove_snapshot → removed item absent from list ✓

### System state
- test_e2e_system_info.test_reboot_and_recovery → health check recovers ✓
- test_e2e_system_info.test_version_is_stable → consecutive calls idempotent ✓

### Response-correctness (read endpoints)
All GET endpoint tests verify response schema and content. Examples:
- getmappings, installed, queue/status, queue/history, snapshot/get_current, etc. → response shape + field presence asserted ✓

### Validation/Negative (error-path effects)
- All `test_*_invalid_body`, `test_*_missing_params`, `test_*_returns_400`, `test_fetch_updates_returns_deprecated` verify the error RESPONSE effect (status code + optional body fields) ✓

## Glob pytest Contract Summary

- **Compliant** (endpoint→effect, positive contract): 81 / 81 tests (100%) — Stage2 WI-D upgraded `test_install_model_accepts_valid_request` to effect-verifying.
- **Weak** (status-only, no effect): ~~1~~ → 0 / 81 tests (resolved)
- **Security-contract** (CSRF method-reject, separate negative contract): 8 / 8 test functions (52 / 52 parametrized invocations — 26 glob + 26 legacy) — all compliant. References: `tests/e2e/test_e2e_csrf.py` (glob, 99caef55 ~91-line diff; 3 dual-purpose endpoints removed from reject-GET fixture in WI-HH to match the GET-read + POST-write split, so glob count dropped from 29 → 26) + `tests/e2e/test_e2e_csrf_legacy.py` (legacy, 99caef55 ~92-line diff — added in WI-FF, audited in WI-GG). See Section 1.5 above.

---

# Section 3 — Reclassification Plan

## Tests to move out of Playwright suite (STATUS: ALL 4 RESOLVED — Stage2 WI-F)

1. ~~`legacy-ui-snapshot.spec.ts::lists existing snapshots`~~ → **DELETED**; backend `getlist` coverage owned by `test_e2e_snapshot_lifecycle.py::test_getlist_after_save`.
2. ~~`legacy-ui-snapshot.spec.ts::save snapshot via API and verify in list`~~ → **REWRITTEN** as UI-driven `SS1 Save button creates a new snapshot row`; also `UI Remove button deletes a snapshot row` added.
3. ~~`legacy-ui-navigation.spec.ts::API health check while dialogs are open`~~ → **DELETED**; version coverage in `test_e2e_system_info.py::test_version_returns_string`.
4. ~~`legacy-ui-navigation.spec.ts::system endpoints accessible from browser context`~~ → **DELETED**; redundant with pytest system_info suite.

Verification: `npx playwright test --list --grep '<any of the 4 titles>'` → 0 tests. pytest counterparts regression: 12/12 PASS (`test_e2e_snapshot_lifecycle.py` + `test_e2e_system_info.py`).

## Tests to rewrite for UI-only verification

2 mixed tests in `legacy-ui-manager-menu.spec.ts` should verify via UI instead of API:

1. `DB mode dropdown round-trips via API` → after selectOption, re-open dialog and check `<select>.value` matches
2. `Update Policy dropdown round-trips via API` → same pattern

Keep the restore step (via API) for cleanup — that is acceptable as teardown.

## New UI→effect tests needed (currently missing)

Based on Report A legacy endpoints and legacy UI flows, these UI→effect tests are missing:

| Legacy UI flow | Endpoint triggered | Effect to verify |
|---|---|---|
| Click "Install" in Custom Nodes Manager row | POST queue/batch | Pack appears in filesystem (via test hooks) + "Installed" badge in UI |
| Click "Uninstall" button | POST queue/batch | Pack removed + row shows "Not Installed" |
| Click "Update All" in Manager menu | POST queue/update_all | "Updating" indicator appears + queue progress WebSocket |
| Click "Install via Git URL" button + enter URL | POST customnode/install/git_url | Pack cloned (if endpoint still exists) |
| Click "Restart" in Manager menu | POST manager/reboot | Server restart + UI reconnect |
| Click "Save" in Snapshot Manager | POST snapshot/save | Snapshot row appears in UI list |
| Click "Delete" row action in Snapshot Manager | POST snapshot/remove?target=X | Row disappears from UI list |

→ The existing `debug-install-flow.spec.ts` provides the instrumentation template. These can be built from it with assertions added.

---

# Section 4 — Revised Coverage Verdict

Applying the strict contract:

## Glob v2 coverage (endpoint → effect)

| Status | Count |
|---|---:|
| Effect-verified | 27/30 |
| Status-only (weakened) | 1/30 (install_model) |
| Intentionally skipped destructive | 2/30 (snapshot/restore, switch_version positive) |

## Legacy coverage (UI → effect)

Strict UI→effect tests for legacy endpoints:

| Endpoint | UI→effect test exists? |
|---|---|
| POST queue/batch | ⚠️ debug only (no assertion); NO production test |
| GET customnode/getlist | ✓ via `loads custom node list (non-empty)` |
| GET /customnode/alternatives | ✗ |
| GET externalmodel/getlist | ✓ via `loads model list (non-empty)` |
| GET customnode/versions/{node_name} | ⚠️ debug only |
| GET customnode/disabled_versions/{node_name} | ✗ |
| POST customnode/install/git_url | ✗ (no "Install via Git URL" test) |
| POST customnode/install/pip | ✗ |
| GET manager/notice | ✗ |
| GET db_mode / POST db_mode (via UI) | 🟡 mixed (UI selectOption + API verify) |
| GET policy/update / POST policy/update (via UI) | 🟡 mixed |
| GET snapshot/getlist (via dialog) | ✓ (opens dialog) |
| POST snapshot/save (via UI button) | ✗ (only API-driven test exists) |
| POST snapshot/remove (via UI) | ✗ (only API-driven cleanup) |
| POST manager/reboot (via UI "Restart" button) | ✗ |

**Strict legacy coverage**: 3/15 endpoints fully UI→effect verified.

---

# Section 5 — Action Items (Prioritized)

## 🔴 Contract violations (fix or remove)

1. DELETE 2 Playwright tests in `legacy-ui-snapshot.spec.ts` (API-only — redundant with pytest E2E)
2. DELETE 2 Playwright tests in `legacy-ui-navigation.spec.ts` (API-only health checks)
3. FIX install_model status-only test in `test_e2e_task_operations.py`

## 🟡 Weaken→strengthen

4. Rewrite 2 mixed `legacy-ui-manager-menu.spec.ts` dropdown tests to verify UI state (not API round-trip)

## 🟢 New UI→effect tests (recommended)

5. Add UI-driven install/uninstall test (click button → verify pack effect + UI state)
6. Add UI-driven snapshot save/remove test (via Snapshot Manager dialog buttons)
7. Add UI-driven "Restart" button test (verify server restart)
8. Add UI-driven "Update All" flow test

## ✓ JS call-site verification (2026-04-18 re-audit)

All 5 endpoints initially flagged as "dead code" are CONFIRMED ACTIVE in legacy UI JS:

| Endpoint | JS file:line |
|---|---|
| /customnode/alternatives | custom-nodes-manager.js:1885 |
| /v2/customnode/disabled_versions/{name} | custom-nodes-manager.js:1401 |
| /v2/customnode/install/git_url | common.js:248 |
| /v2/customnode/install/pip | common.js:213 |
| /v2/manager/notice | comfyui-manager.js:418 |

→ Action: **add UI→effect tests** (not remove). Previous "dead code candidate" recommendation retracted.

---
*End of Test Contract Audit*
