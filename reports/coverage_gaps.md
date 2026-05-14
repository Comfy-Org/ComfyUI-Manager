# Coverage Gap Analysis — Report A × Report B

**Generated**: 2026-04-18 (WI-AA inventory update 2026-04-19: +2 LB1/LB2 tests → 119 total; WI-GG update 2026-04-20: +26 legacy CSRF parametrized rows → 145 total; WI-JJ update 2026-04-20: +3 legacy CSRF parity/install rows; WI-LL update 2026-04-20: +2 SECGATE rows → 148 audit rows / 126 test functions)
**Inputs**: `reports/endpoint_scenarios.md` (39 handlers, 154 scenarios) + `reports/e2e_test_coverage.md` (126 test functions / 148 audit rows — the row-count delta reflects audit-side per-invocation rendering of legacy CSRF plus the 2 new SECGATE PoC rows; function-level progression is recorded in `e2e_test_coverage.md`)

> **WI-AA (2026-04-19)**: `tests/playwright/legacy-ui-install.spec.ts` (2 tests: LB1 Install button triggers install effect, LB2 Uninstall button triggers uninstall effect) has been **integrated into the audit** (see `e2e_verification_audit.md` §16). These tests drive the install/uninstall action via the Custom Nodes Manager dialog UI and verify the resulting backend state via `/v2/customnode/installed`. They close the long-standing gap noted in this document's Section 4 for UI-driven install/uninstall effect coverage on the legacy UI. Prior coverage-gap mentions of "missing UI→effect for install/uninstall buttons" are now RESOLVED.
>
> **WI-GG (2026-04-20)**: `tests/e2e/test_e2e_csrf_legacy.py` (4 test functions / 26 parametrized invocations: 13 reject-GET + 2 POST-works + 11 allow-GET) — from WI-FF — has been **integrated into the audit** (see `e2e_verification_audit.md` §19). This extends the CSRF-Mitigation Layer Coverage block below from glob-only to glob + legacy, closing the regression-guard gap that a legacy-side `@routes.post` revert would have slipped past CI. LB1/LB2 classification as RESOLVED is unchanged.
>
> **WI-LL (2026-04-20)**: `tests/e2e/test_e2e_secgate_strict.py` (SR4 PoC — strict-mode fixture) + `tests/e2e/test_e2e_secgate_default.py` (CV4 demo — no harness needed) — from WI-KK — have been **integrated into the audit** (see `e2e_verification_audit.md` §20, §21). Two of the original 8 T2 SECGATE-PENDING Goals are now RESOLVED (SR4, CV4); the remaining 6 are reclassified into 4 sub-tiers (T2-pending-harness-ready: SR6/V5/UA2; NORMAL-legacy: LGU2/LPP2; T2-TASKLEVEL: IM4). Section 4 🟢 Low Priority "Security level 403 gates ... impractical in standard E2E env" is now PARTIAL — see the classification policy + propagation plan in `e2e_verification_audit.md`.

## Summary

| Metric | Count |
|---|---:|
| Glob v2 endpoints fully covered (row has no ✗ in Missing scenarios) | 15/30 |
| Glob v2 endpoints partially covered (some ✓ + some ✗) | 14/30 |
| Glob v2 endpoints NOT covered (positive) | 1/30 |
| Legacy-only endpoints fully covered | 0/9 |
| Legacy-only endpoints partially covered (indirect only) | 4/9 |
| Legacy-only endpoints NOT covered | 5/9 |
| Orphan tests (non-endpoint-direct; pytest + Playwright UI-only) | 29 |

---

# Section 1 — Endpoint × Test Coverage Matrix (Glob v2)

Legend: **✓** direct assertion test, **~** indirect / partial, **✗** not tested

| # | Endpoint | Direct test | Missing scenarios |
|---|---|---|---|
| 1 | POST queue/task (install) | ✓ test_e2e_endpoint, test_e2e_git_clone, test_e2e_task_operations | ✗ 400 ValidationError (bad kind/schema), ✗ 500 on malformed JSON |
| 2 | POST queue/task (uninstall) | ✓ test_e2e_endpoint, test_e2e_task_operations | (shared with #1) |
| 3 | POST queue/task (update/fix/disable/enable) | ✓ test_e2e_task_operations | (shared) |
| 4 | GET queue/history_list | ✓ test_e2e_queue_lifecycle | ✗ 400 on inaccessible history path |
| 5 | GET queue/history | ✓ test_e2e_queue_lifecycle, test_e2e_task_operations | ✗ `id=<batch_id>` file-based query, ✗ path traversal rejection |
| 6 | GET customnode/getmappings | ✓ test_e2e_customnode_info | ✗ `mode=nickname`, ✗ missing `mode` KeyError→500 |
| 7 | GET customnode/fetch_updates | ✓ test_e2e_customnode_info (410) | (fully covered — deprecated endpoint) |
| 8 | POST queue/update_all | ✓ test_e2e_task_operations | ✗ 403 security gate, ✗ `mode=local` vs remote distinction |
| 9 | GET is_legacy_manager_ui | ✓ test_e2e_system_info, playwright navigation | (fully covered) |
| 10 | GET customnode/installed | ✓ test_e2e_endpoint, test_e2e_customnode_info (both modes) | (fully covered) |
| 11 | GET snapshot/getlist | ✓ test_e2e_snapshot_lifecycle, playwright snapshot | (fully covered) |
| 12 | POST snapshot/remove | ✓ test_e2e_snapshot_lifecycle | ✗ path traversal "Invalid target" 400, ✗ 403 security gate, ✗ missing `target` query |
| 13 | POST snapshot/restore | ✗ **intentionally skipped (destructive)** | ALL scenarios (positive, path traversal, 403) |
| 14 | GET snapshot/get_current | ✓ test_e2e_snapshot_lifecycle | (fully covered) |
| 15 | POST snapshot/save | ✓ test_e2e_snapshot_lifecycle, playwright snapshot | (fully covered) |
| 16 | POST customnode/import_fail_info | ✓ test_e2e_customnode_info (negative only) | ✗ positive path (returning actual failure info) — requires seed failed import |
| 17 | POST customnode/import_fail_info_bulk | ✓ test_e2e_customnode_info | ✗ positive path with real failure info |
| 18 | POST queue/reset | ✓ test_e2e_queue_lifecycle | (fully covered) |
| 19 | GET queue/status | ✓ test_e2e_queue_lifecycle | (fully covered) |
| 20 | POST queue/start | ✓ test_e2e_queue_lifecycle (idle + lifecycle) | (fully covered) |
| 21 | POST queue/update_comfyui | ✓ test_e2e_task_operations | (fully covered) |
| 22 | GET comfyui_versions | ✓ test_e2e_version_mgmt (4 tests) | ✗ 400 on git-access failure |
| 23 | POST comfyui_switch_version | ✓ test_e2e_version_mgmt (negative only) | ✗ **positive path (intentionally skipped)**, ✗ 403 security gate |
| 24 | POST queue/install_model | ✓ test_e2e_task_operations | (fully covered) |
| 25 | GET db_mode | ✓ test_e2e_config_api, playwright manager-menu | (fully covered) |
| 26 | POST db_mode | ✓ test_e2e_config_api, playwright manager-menu | ✗ missing `value` KeyError→400 (only malformed JSON tested) |
| 27 | GET policy/update | ✓ test_e2e_config_api, playwright | (fully covered) |
| 28 | POST policy/update | ✓ test_e2e_config_api, playwright | ✗ missing `value` key |
| 29 | GET channel_url_list | ✓ test_e2e_config_api | (fully covered) |
| 30 | POST channel_url_list | ✓ test_e2e_config_api | ✗ unknown channel name (silent no-op) |
| 31 | POST manager/reboot | ✓ test_e2e_system_info | ✗ __COMFY_CLI_SESSION__ env branch |
| 32 | GET manager/version | ✓ test_e2e_system_info, playwright navigation | (fully covered) |

Note: queue/task has 3 rows above per kind; 30 glob endpoints = 32 row entries (queue/task counted per-kind).

## Glob v2 Summary

- **Fully covered** (row has no ✗ in Missing scenarios column): 15 endpoints
  (is_legacy_manager_ui, customnode/installed, snapshot/getlist, snapshot/get_current, snapshot/save, queue/reset, queue/status, queue/start, queue/update_comfyui, queue/install_model, fetch_updates, get db_mode, get policy/update, get channel_url_list, get manager/version)
- **Partially covered** (some ✓ + some ✗ in Missing scenarios): 14 endpoints (row-level collapse of per-kind queue/task into 1 endpoint)
- **Intentionally skipped** (destructive, counted under NOT covered): 1 (snapshot/restore); switch_version has ✓ negative + skipped-positive so it falls under partial, not skipped
- Sum: 15 + 14 + 1 = 30 ✓

### CSRF-Mitigation Layer Coverage (separate from positive-path coverage above)

The 16 state-changing POST endpoints — commit 99caef55 converted 12+ of
these from GET→POST (the remainder such as queue/task, import_fail_info,
and import_fail_info_bulk were already POST but are included for contract
completeness) — are independently covered. Commit 99caef55 applied the
conversion to BOTH `comfyui_manager/glob/manager_server.py` (~91 lines)
and `comfyui_manager/legacy/manager_server.py` (~92 lines), so two test
files are required (the server-loading is mutex on `--enable-manager-legacy-ui`):

**Glob server**: `tests/e2e/test_e2e_csrf.py` (4 functions / 26 parametrized invocations — post-WI-HH; was 29 before the 3 dual-purpose endpoints were scoped out of the reject-GET fixture)

| Contract | Test | Coverage |
|---|---|---|
| Reject GET on 13 state-changing POST endpoints (glob; post-WI-HH) | TestStateChangingEndpointsRejectGet (parametrized ×13) | ✓ full |
| POST counterpart sanity (glob) | TestCsrfPostWorks (2 tests) | ~ spot-check (queue/reset + snapshot/save only) |
| Read-only GET still allowed — negative control (glob) | TestCsrfReadEndpointsStillAllowGet (parametrized ×11) | ✓ full |

**Legacy server** (WI-FF, audit-integrated in WI-GG): `tests/e2e/test_e2e_csrf_legacy.py` (4 functions / 26 parametrized invocations)

| Contract | Test | Coverage |
|---|---|---|
| Reject GET on 13 state-changing POST endpoints (legacy; queue/task→queue/batch, dual-purpose endpoints scoped to ALLOW-GET only) | TestLegacyStateChangingEndpointsRejectGet (parametrized ×13) | ✓ full |
| POST counterpart sanity (legacy) | TestLegacyCsrfPostWorks (2 tests — queue/reset + snapshot/save) | ~ spot-check |
| Read-only GET still allowed — negative control (legacy) | TestLegacyCsrfReadEndpointsStillAllowGet (parametrized ×11) | ✓ full |

**Important**: POST `snapshot/restore` and POST `comfyui_switch_version` are
listed as "intentionally skipped (destructive)" for POSITIVE-path coverage,
but their CSRF reject-GET contract IS covered by BOTH test files —
the destructive-skip only applies to the success-path assertion, not to
the security layer. The legacy-side coverage closes the regression-guard
gap that a revert of any legacy `@routes.post` back to `@routes.get` would
otherwise have slipped past CI.

---

# Section 2 — Endpoint × Test Coverage Matrix (Legacy-only)

| # | Endpoint | Test coverage | Gap |
|---|---|---|---|
| 1 | POST queue/batch | ~ debug-install-flow captures API sequence indirectly | ✗ No dedicated assertion test for batch semantics |
| 2 | GET customnode/getlist | ~ playwright custom-nodes triggers it via UI | ✗ No direct assertion on response shape, `skip_update` param, channel resolution |
| 3 | GET /customnode/alternatives | ✗ NOT COVERED | ALL scenarios |
| 4 | GET externalmodel/getlist | ~ playwright model-manager triggers via UI | ✗ No direct assertion on `installed` flag population, save_path resolution |
| 5 | GET customnode/versions/{node_name} | ~ debug-install-flow captures it | ✗ 400 on unknown pack, no direct test |
| 6 | GET customnode/disabled_versions/{node_name} | ✗ NOT COVERED | ALL scenarios |
| 7 | POST customnode/install/git_url | ✗ NOT COVERED | ALL (high+ security, may be intentional) |
| 8 | POST customnode/install/pip | ✗ NOT COVERED | ALL (high+ security, may be intentional) |
| 9 | GET manager/notice | ✗ NOT COVERED | ALL scenarios |

## Legacy-only Summary

- **Fully covered**: 0/9
- **Indirect-only** (triggered via UI flow but no direct assertion): 4/9
- **Not covered**: 5/9

---

# Section 3 — Orphan Tests (not mapped to HTTP endpoints)

Tests that do not directly assert HTTP endpoint behavior:

| Test file | Tests | Purpose |
|---|---:|---|
| `tests/cli/test_uv_compile.py` | 8 | `cm-cli --uv-compile` CLI entrypoint (not HTTP). Relocated from `tests/e2e/` in WI-PP (see Recommendations §4 — now ACTIONED). |
| `test_e2e_endpoint.py::test_startup_resolver_ran` | 1 | Log file assertion (server log contains UnifiedDepResolver) |
| `test_e2e_endpoint.py::test_comfyui_started` | 1 | `/system_stats` (ComfyUI core endpoint, not Manager) |
| `test_e2e_git_clone.py::test_02_no_module_error` | 1 | Log file regression check |
| Playwright UI-only tests (no API assertion) | ~14 of 22 | UI rendering, dialog lifecycle, filter/search — no HTTP assertion |

Total orphan tests (non-endpoint-direct): ~29 / 115 (25%)

---

# Section 4 — Critical Gaps (Prioritized)

## 🔴 High Priority — Legacy Endpoints with ZERO UI→effect Test Coverage

These endpoints ARE actively called by legacy UI JavaScript but have no Playwright test exercising the UI flow:

| Endpoint | JS call site | Missing UI→effect test |
|---|---|---|
| POST /v2/customnode/install/git_url | `common.js:248` | "Install via Git URL" button flow |
| POST /v2/customnode/install/pip | `common.js:213` | pip install UI flow |
| GET /v2/customnode/disabled_versions/{node_name} | `custom-nodes-manager.js:1401` | Node row "Disabled Versions" dropdown |
| GET /customnode/alternatives | `custom-nodes-manager.js:1885` | Alternatives display in custom nodes dialog |
| GET /v2/manager/notice | `comfyui-manager.js:418` | Notice display on Manager menu open |

→ These are **NOT dead code** — they require **UI→effect tests added**, not removal.

## 🟡 Medium Priority — Missing Scenarios (Covered Endpoints)

1. **queue/task 400 ValidationError** — no test verifies schema rejection. Adding `test_queue_task_invalid_body` with malformed `kind` value would be trivial.
2. **queue/history with `id=<batch_id>` + path traversal** — file-based history path not exercised.
3. **snapshot/remove path traversal** — security-critical but not asserted.
4. **comfyui_versions 400 on git failure** — would need to simulate git unavailable.
5. **POST db_mode/policy/update missing `value` key** — currently only tests malformed JSON; KeyError path untested.

## 🟢 Low Priority — Acceptable Gaps

1. **snapshot/restore + switch_version positive** — intentionally skipped (destructive). Acceptable.
2. ~~**Security level 403 gates** — require running with locked-down security_level; impractical in standard E2E env.~~ **PARTIAL (WI-LL via WI-KK, 2026-04-20)**: SR4 (snapshot/remove middle) + CV4 (comfyui_switch_version high+) are now covered via `test_e2e_secgate_strict.py` and `test_e2e_secgate_default.py` respectively. Remaining SECGATE Goals are reclassified (`e2e_verification_audit.md` classification-policy block): SR6/V5/UA2 are T2-pending-harness-ready (mechanical additions to strict.py); LGU2/LPP2 are NORMAL-legacy (needs `start_comfyui_legacy.sh`); IM4 is T2-TASKLEVEL (queue-observation pattern, not HTTP 403).
3. **import_fail_info positive path** — would require seeding a failed module import; complex setup.

---

# Section 5 — Recommendations

1. **Add UI→effect Playwright tests** for the 5 JS-called legacy endpoints (install/git_url, install/pip, disabled_versions, alternatives, manager/notice). All are live in legacy UI flows.
2. **Add minimal gap tests** for queue/task ValidationError + snapshot/remove path traversal — both are security-relevant.
3. **Convert debug-install-flow.spec.ts** from logging-only into an assertion test (verify queue/batch payload structure + cm-queue-status WebSocket events).
4. ~~**Consider moving uv_compile tests** to a separate CLI test directory (tests/cli/) — they are not E2E HTTP tests.~~ **ACTIONED (WI-PP)**: file now lives at `tests/cli/test_uv_compile.py`. CI workflow `.github/workflows/e2e.yml` updated to the new path. Placement hygiene restored.

---

# Section 6 — Cross-Report Consistency Check

| Report A claim | Report B claim | Status |
|---|---|---|
| 30 glob v2 endpoints | Row-level: 15 fully + 14 partial + 1 NOT covered = 30 (matches Summary L10-12) | ✓ consistent under row-no-✗ definition |
| 9 legacy-only endpoints | "4 covered, 5 not covered" | ✓ consistent |
| 154 scenarios total | (per-test scenario breakdown) | ⚠️ scenario-level count not aggregated in Report B; recommend adding |
| Security gates (middle/middle+/high+) | Security 403 paths not tested | ⚠️ gap confirmed |
| Deprecated endpoints flagged | fetch_updates 410 tested | ✓ consistent |

Internal accounting reconciled under the single "row has no ✗ in Missing scenarios column" definition for "fully covered". Earlier drafts of this report mixed three counting schemes (Summary 24/5/1, body-list 11/15/2, Section 6 27/30) that did not agree; this revision uses the row-level count uniformly (15/14/1 = 30 glob v2 endpoints) and aligns Summary L10-12, body L63-66, and Section 6 L172. Report A (endpoint_scenarios.md) and Report B (e2e_test_coverage.md) align on endpoint counts (30 glob v2 + 9 legacy = 39) and coverage categories under this definition.

---
*End of Coverage Gap Analysis*
