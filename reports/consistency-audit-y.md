# Report Y — Cross-Artifact Consistency Audit

**Generated**: 2026-04-19
**Auditor**: gteam-doc
**Scope**: 9 markdown files in `reports/` directory (post-Wave3 PR preparation stage)
**Mandate**: Audit-only — fixes deferred to follow-up WIs
**Baseline gate**: `python scripts/verify_audit_counts.py` → **PASS** (94/0/0/15/109 matches between Summary Matrix and per-file rows)

---

## 📌 Status update (WI-Z, 2026-04-19)

All 13 drift items identified below have been **RESOLVED** via WI-Z patch application (consolidated Y1+Y2+Y3+Y4). Final verify: `(100, 0, 0, 15, 115)` — PASS.

> **WI-II note (2026-04-20)**: The `test_e2e_csrf.py` function/parametrization tally recorded below as `4 functions / 29 parametrized invocations (16+2+11)` — see L47, L75, L236 — reflects the pre-WI-HH state. WI-HH removed 3 dual-purpose endpoints (`db_mode`, `policy/update`, `channel_url_list`) from the reject-GET fixture (they legitimately answer GET on the read-path and are covered only in the allow-GET class), bringing the current count to `4 functions / 26 parametrized invocations (13+2+11)`. This audit's historical figures are preserved as a time-stamped snapshot of the 2026-04-19 state; the current state is recorded in `e2e_verification_audit.md` §18, `test_contract_audit.md` §1.5, `coverage_gaps.md` CSRF-Mitigation Layer Coverage, `e2e_test_coverage.md` test_e2e_csrf.py subsection, and `verification_design.md` §10.

| Patch | Scope | Items resolved | Net effect |
|-------|-------|----------------|------------|
| **Y1** | snapshot_lifecycle audit §7 add path-traversal row | B-3, B-4, D-1 | §7: 6→7 PASS; SR3 Key gap → RESOLVED |
| **Y2** | e2e_test_coverage.md stale sync | A-1, A-2, A-3, A-4, B-1, B-2 | Summary 119→117; customnode header 9→11; snapshot rows swapped; navigation 4→2 |
| **Y3** | config_api audit §4 add 5 uncounted rows | B-5 | §4: 10→15 PASS (junk_value ×3 + persists_to_config_ini ×2) |
| **Y4** | do_fix security level middle→high | C-1, C-2, C-3 | 3 locations updated: endpoint_scenarios L18/L380 + verification_design L666 |
| **Y5** | do_fix subsequent upgrade high→high+ (follow-up to Y4) | — (no new C-items; re-sync of Y4 locations after code state advanced) | 4 locations re-synced: endpoint_scenarios §Security list + §Security Level Matrix + §Note + verification_design Security tiers. README 'Risky Level Table' `Fix nodepack` moved from `high` row into `high+` row (`high` row now marked empty). Aligns enforcement gate with `SECURITY_MESSAGE_HIGH_P` log text (WI-#235, gate lifted from `'high'` to `'high+'` at `glob/manager_server.py:974` + `legacy/manager_server.py:560`). Y4 rows above are preserved as historical record of the middle→high transition. |

Summary Matrix: `(94,0,0,15,109)` → `(100,0,0,15,115)`. Upgrade count unchanged at 27 (WI-Z is inventory reconciliation, not new upgrades). Y5 is a follow-up re-sync triggered by a subsequent code change (WI-#235), not a new drift detection; it does not alter the Summary Matrix counts.

---

## 1. Inventory

| # | File | Lines | Modified | Role |
|---|------|------:|----------|------|
| 1 | `endpoint_scenarios.md` | 425 | 2026-04-18 23:53 | Report A — Endpoint extraction + scenarios |
| 2 | `scenario_intents.md` | 424 | 2026-04-18 08:29 | Intent (why endpoint exists) |
| 3 | `scenario_effects.md` | 514 | 2026-04-18 08:27 | Effect (observable result) |
| 4 | `verification_design.md` | 824 | 2026-04-18 23:53 | Design Goals (92 + CSRF-M1/M2/M3 = 95) |
| 5 | `e2e_test_coverage.md` | 358 | 2026-04-18 22:39 | Report B — E2E test inventory |
| 6 | `e2e_verification_audit.md` | 469 | 2026-04-19 22:36 | Audit verdicts (109 tests; 94 PASS / 15 N/A) |
| 7 | `test_contract_audit.md` | 282 | 2026-04-18 23:09 | Pytest/Playwright contract compliance |
| 8 | `coverage_gaps.md` | 182 | 2026-04-18 22:45 | Coverage gap rollup |
| 9 | `research-cluster-g.md` | 215 | 2026-04-19 07:30 | Cluster G research (imported_mode + boolean CLI) |

Total: **3 693 lines** across **9 files**.

Actual test-file reality (`grep -c "def test_"` / `grep "^\s*test("`) at audit time:

| Test file | `def test_` count | Audit claim | Coverage claim |
|-----------|------------------:|------------:|---------------:|
| `test_e2e_config_api.py` | 15 | 10 | 10 |
| `test_e2e_csrf.py` | 4 | 4 | 4 (29 parametrized) |
| `test_e2e_customnode_info.py` | 12 (11 + 1 `@pytest.mark.skip`) | 11 | 9 |
| `test_e2e_endpoint.py` | 7 | 7 | 7 |
| `test_e2e_git_clone.py` | 3 | 3 | 3 |
| `test_e2e_queue_lifecycle.py` | 10 | 9 (+ 1 noted in Key gaps) | 9 |
| `test_e2e_snapshot_lifecycle.py` | 7 | 6 | 7 (contains 1 deleted + missing 1 new) |
| `test_e2e_system_info.py` | 4 | 4 | 4 |
| `test_e2e_task_operations.py` | 16 | 16 | 16 |
| `tests/cli/test_uv_compile.py` (relocated WI-PP; was `test_e2e_uv_compile.py`) | 8 | N/A (out of E2E scope) | 8 |
| `test_e2e_version_mgmt.py` | 7 | 7 | 7 |
| `legacy-ui-manager-menu.spec.ts` | 5 | 5 | 5 |
| `legacy-ui-custom-nodes.spec.ts` | 5 | 5 | 5 |
| `legacy-ui-model-manager.spec.ts` | 4 | 4 | 4 |
| `legacy-ui-snapshot.spec.ts` | 3 | 3 | 3 |
| `legacy-ui-navigation.spec.ts` | 2 | 2 | 4 |
| `debug-install-flow.spec.ts` | 1 | 1 | 1 |

---

## 2. Internal Cross-Reference Consistency (reports ↔ reports)

### 2.1 Counts that agree across all reports (✅ consistent)

| Claim | Values | Files involved |
|-------|--------|----------------|
| Total tests counted in audit | **109** (94 P / 0 W / 0 I / 15 N) | `e2e_verification_audit.md` L330, L334, L462, L466 |
| Design Goals | **92** base + **3** CSRF-M (M1/M2/M3) = **95** superset | `verification_design.md` §10, `e2e_verification_audit.md` L335, L337, L378 |
| Design-Goal coverage | **68/92** (73.9%) base / **71/95** (74.7%) superset | `e2e_verification_audit.md` L337 |
| `test_e2e_csrf.py` structure | 4 test functions / **29** parametrized invocations (16 + 2 + 11) | `e2e_test_coverage.md` L18, L188; `test_contract_audit.md` L104-106, L168; `verification_design.md` L797, L805, L813; `e2e_verification_audit.md` L323 |
| `STATE_CHANGING_POST_ENDPOINTS` line range | L92–L109 in `test_e2e_csrf.py` | `endpoint_scenarios.md` L396 — **verified against source** |
| Security Level Matrix line range | L378–L382 in `endpoint_scenarios.md` | `endpoint_scenarios.md` L396 — **verified** |
| `comfyui_switch_version` → `high+` | Consistent at L382 of `endpoint_scenarios.md`, L668 of `verification_design.md`, L410 of `endpoint_scenarios.md` (CSRF inventory) | Cross-checked with commit `9c9d1a40` |
| `verify_audit_counts.py` gate | Summary Matrix computed vs reported — both `(94, 0, 0, 15, 109)` | Script output PASS |

### 2.2 Playwright test-count cross-report check (⚠️ drift in one file)

| File | manager-menu | custom-nodes | model-manager | snapshot | navigation | debug | Total |
|------|---:|---:|---:|---:|---:|---:|---:|
| `e2e_verification_audit.md` L318-328 | 5 | 5 | 4 | 3 | **2** | 1 | **20** |
| `test_contract_audit.md` L73 (20 tests) | (aggregated) | | | | | | **20** |
| `e2e_test_coverage.md` L14 (Summary) | | | | | | | **21** ❌ |
| `e2e_test_coverage.md` per-section | 5 | 5 | 4 | 3 | **4** ❌ | 1 | **22** ❌ |
| Actual spec files (`grep "^\s*test("`) | 5 | 5 | 4 | 3 | **2** | 1 | **20** |

Only `e2e_test_coverage.md` is out of sync with the Playwright post-WI-F reality. All other reports (audit + contract + actual) agree on 20.

---

## 3. Discovered Drift (by category and severity)

### Category A — Simple typo / stale number (MINOR)

| # | Location | Current text | Should be | Evidence |
|---|----------|--------------|-----------|----------|
| A-1 | `e2e_test_coverage.md` L86 | `## tests/e2e/test_e2e_customnode_info.py (9 tests)` | `(11 tests)` | Section body lists 11 rows (L92–L102); audit §5 header is `(11 tests)` |
| A-2 | `e2e_test_coverage.md` L14 | `Playwright (legacy UI) \| 5 \| 21` | `\| 5 \| 19` | Post-WI-F deletion of 2 navigation tests; audit Summary Matrix reports 20 (19 legacy + 1 debug) |
| A-3 | `e2e_test_coverage.md` L16 | `TOTAL \| 17 \| 119` | `\| 17 \| 117` | Downstream of A-2 |
| A-4 | `e2e_test_coverage.md` L258 | `## tests/playwright/legacy-ui-navigation.spec.ts (4 tests)` | `(2 tests)` | Actual spec: 2 `test(...)` calls — `API health check` and `system endpoints accessible` deleted per WI-F (Stage2) |

### Category B — Structural drift (OBSOLETE rows / MISSING rows, MAJOR)

| # | Location | Drift | Evidence |
|---|----------|-------|----------|
| B-1 | `e2e_test_coverage.md` L266–L267 | **OBSOLETE rows** — references deleted tests `API health check while dialogs are open` and `system endpoints accessible from browser context` | `test_contract_audit.md` L32-33: both marked `**DELETED**`; verify: `grep '^\s*test(' tests/playwright/legacy-ui-navigation.spec.ts` returns only 2 matches |
| B-2 | `e2e_test_coverage.md` L131 | **OBSOLETE row** — `TestSnapshotGetCurrentSchema::test_get_current_returns_dict` | `e2e_verification_audit.md` L128: struck-through `~~test_get_current_returns_dict~~ ~~REMOVED~~` via Wave1 WI-M dedup (file count 7→6 for §7) |
| B-3 | `e2e_test_coverage.md` L120–L132 | **MISSING row** — `test_remove_path_traversal_rejected` (file L300) not listed, though `snapshot_lifecycle.py` file count claims 7 tests | `grep "def test_" tests/e2e/test_e2e_snapshot_lifecycle.py` shows 7 functions; this test (SR3 — path traversal rejection) implements the "NORMAL add (Priority 🔴)" Key gap |
| B-4 | `e2e_verification_audit.md` L119 (§7 header + body) | **MISSING row** — same as B-3. Section 7 table lists 6 active rows (+ 1 struck REMOVED) but `test_remove_path_traversal_rejected` not represented. Summary Matrix row 319 therefore reports `6 \| 0 \| 0 \| 0 \| 6` for a file that now has 7 PASSing tests. Key gaps at L134 still lists **SR3** (path traversal on remove) as "NORMAL add (Priority 🔴 per §Priority Fixes)" even though the test is implemented and would PASS. | Source file `tests/e2e/test_e2e_snapshot_lifecycle.py` L300–L328 contains the test |
| B-5 | `e2e_verification_audit.md` §4 (L56–L71) | **MISSING rows** — Section 4 tracks 10 config_api tests, but `tests/e2e/test_e2e_config_api.py` contains **15** `def test_` functions. Five tests are not represented: `test_set_db_mode_junk_value_rejected`, `test_db_mode_persists_to_config_ini`, `test_set_policy_junk_value_rejected`, `test_policy_persists_to_config_ini`, `test_set_channel_unknown_name_rejected` (source L411, L438, L727, and related). These are distinct from the `invalid_body` rows (malformed JSON) — they are whitelist-rejection and on-disk-persistence assertions introduced by WI-E / WI-I. | `grep "def test_" tests/e2e/test_e2e_config_api.py` returns 15 matches; audit § 4 body only references 10 |

### Category C — Semantic drift (claim contradicts current code, MAJOR)

| # | Location | Drift | Evidence |
|---|----------|-------|----------|
| C-1 | `endpoint_scenarios.md` L18 | Lists `_fix_custom_node` under security level `middle`. Commit **c8992e5d** (2026-04-04, "fix(security): correct do_fix security level from middle to high") changed do_fix in both `comfyui_manager/glob/manager_server.py` and `comfyui_manager/legacy/manager_server.py` from `middle` → `high`. Report was last modified 2026-04-18 (2 weeks after the commit) but still reflects pre-commit state. | `git show c8992e5d` diff; source at `glob/manager_server.py:966` (`is_allowed_security_level('high')`); README documents fix nodepack as `high` risk |
| C-2 | `endpoint_scenarios.md` L380 (Security Level Matrix, Legacy column) | `_fix` listed under `middle` — same issue as C-1 for the legacy handler | Same commit c8992e5d: `legacy/manager_server.py:550-555` now has `is_allowed_security_level('high')` gate |
| C-3 | `verification_design.md` L666 | `middle — reboot, snapshot/remove, _fix, _uninstall, _update` — `_fix` should be at `high+` tier | Same evidence as C-1/C-2 |

### Category D — Key-gap staleness (MINOR, observational)

| # | Location | Drift | Note |
|---|----------|-------|------|
| D-1 | `e2e_verification_audit.md` L134 (§7 Key gaps) | Claims **SR3** (path traversal on remove) is "NORMAL add (Priority 🔴 per §Priority Fixes)" — but the test IS implemented (see B-3/B-4) and the file count should be 7/7 ✅ | Either the Key gaps line is stale, or Section 7 should add the new row, update the total to 7/7, and resolve SR3 in §Priority Fixes |

---

## 4. Suggested Fixes (patch sketches, NOT applied — deferred to follow-up WI)

> These are line-level recommendations. Verify count-changes against `verify_audit_counts.py` before applying.

### Patch Y1 — Resolve B-3 + B-4 + D-1 (add `test_remove_path_traversal_rejected`)

```diff
--- a/reports/e2e_verification_audit.md
+++ b/reports/e2e_verification_audit.md
@@ -119 +119 @@
-# Section 7 — tests/e2e/test_e2e_snapshot_lifecycle.py (6 tests)
+# Section 7 — tests/e2e/test_e2e_snapshot_lifecycle.py (7 tests)
@@ -127,0 +128,1 @@
+| `test_remove_path_traversal_rejected` | SR3 | ✅ PASS | Path-traversal targets (`../../...`, `/etc/passwd`) return 400; sentinel file outside snapshot dir is NOT deleted. Resolves SR3 (path traversal on remove) — previously NORMAL-add. |
@@ -131 +131 @@
-**File verdict**: 6/6 ✅ (…)
+**File verdict**: 7/7 ✅ (Wave1 WI-M dedup + Wave2 WI-Q disk/content verification + SR3 path-traversal coverage implemented; file count 7→6→7.)
@@ -134 +134 @@
-- **SR3** (path traversal on remove) — NORMAL add (Priority 🔴 per §Priority Fixes).
+(remove line — SR3 resolved by `test_remove_path_traversal_rejected`)
@@ -319 +319 @@
-| test_e2e_snapshot_lifecycle.py | 6 | 0 | 0 | 0 | 6 |
+| test_e2e_snapshot_lifecycle.py | 7 | 0 | 0 | 0 | 7 |
@@ -330 +330 @@
-| **TOTAL** | **94** | **0** | **0** | **15** | **109** |
+| **TOTAL** | **95** | **0** | **0** | **15** | **110** |
```

Also update `§ Priority Fixes` for SR3 entry, and update the narrative totals on L334, L462, L466 (109 → 110). The 71/95 superset tally remains unchanged (SR3 is an existing Goal already inside the 92 base, not a new Goal).

### Patch Y2 — Resolve A-1 / A-2 / A-3 / A-4 / B-1 / B-2 / B-3 (e2e_test_coverage.md sync with reality)

```diff
--- a/reports/e2e_test_coverage.md
+++ b/reports/e2e_test_coverage.md
@@ -12,4 +12,4 @@
-| pytest E2E (HTTP API) | 10 | 85 |
-| pytest E2E (CLI — uv-compile) | 1 | 12 |
-| Playwright (legacy UI) | 5 | 21 |
-| Playwright (debug) | 1 | 1 |
-| **TOTAL** | **17** | **119** |
+| pytest E2E (HTTP API) | 10 | 86 |     # +1 = test_remove_path_traversal_rejected (see Patch Y1)
+| pytest E2E (CLI — uv-compile) | 1 | 12 |
+| Playwright (legacy UI) | 5 | 19 |
+| Playwright (debug) | 1 | 1 |
+| **TOTAL** | **17** | **118** |
@@ -86 +86 @@
-## tests/e2e/test_e2e_customnode_info.py (9 tests)
+## tests/e2e/test_e2e_customnode_info.py (11 tests)
@@ -120 +120 @@
-## tests/e2e/test_e2e_snapshot_lifecycle.py (7 tests)
+## tests/e2e/test_e2e_snapshot_lifecycle.py (7 tests)
@@ -131 +131 @@
-| `TestSnapshotGetCurrentSchema::test_get_current_returns_dict` | GET snapshot/get_current | Response schema | dict type |
+| `TestSnapshotRemove::test_remove_path_traversal_rejected` | POST snapshot/remove?target=../... | Path traversal rejected | 400 + sentinel file preserved |
@@ -258 +258 @@
-## tests/playwright/legacy-ui-navigation.spec.ts (4 tests)
+## tests/playwright/legacy-ui-navigation.spec.ts (2 tests)
@@ -266,2 +266,0 @@
-| `> API health check while dialogs are open` | GET manager/version | … | … |
-| `> system endpoints accessible from browser context` | GET manager/version + GET is_legacy_manager_ui | … | … |
```

Note: if Patch Y1 is NOT applied, change `86 → 85`, `118 → 117`, and keep `(7 tests)` but still drop the obsolete `test_get_current_returns_dict` row and add `test_remove_path_traversal_rejected` row (net 7 tests).

### Patch Y3 — Resolve B-5 (config_api 5 missing rows in audit § 4)

This requires per-row verdict content (PASS + issue notes) for each of the 5 new tests. Recommend spawning a verification sub-WI that either (a) runs `pytest tests/e2e/test_e2e_config_api.py` and maps each new test to a Goal (C2 / C3 / C5 variants — whitelist rejection, disk persistence), or (b) marks them as "tracked but uncounted" with a preamble note.

Summary-matrix delta if all 5 added as PASS: `test_e2e_config_api.py: 10 → 15`, Grand TOTAL: `109 → 114` (independent of Patch Y1). Combined with Y1: `109 → 115`.

### Patch Y4 — Resolve C-1 / C-2 / C-3 (do_fix security level from middle → high)

```diff
--- a/reports/endpoint_scenarios.md
+++ b/reports/endpoint_scenarios.md
@@ -18 +18 @@
-- `middle`: reboot, snapshot/remove, _fix_custom_node, _uninstall_custom_node, _update_custom_node
+- `middle`: reboot, snapshot/remove, _uninstall_custom_node, _update_custom_node
+- `high`: _fix_custom_node (commit c8992e5d — aligned with README risk matrix)
@@ -380 +380 @@
-| **middle** | snapshot/remove, reboot | snapshot/remove, reboot, _uninstall, _update, _fix |
+| **middle** | snapshot/remove, reboot | snapshot/remove, reboot, _uninstall, _update |
+| **high** | _fix_custom_node | _fix |
```

```diff
--- a/reports/verification_design.md
+++ b/reports/verification_design.md
@@ -666 +666 @@
-- `middle` — reboot, snapshot/remove, _fix, _uninstall, _update
+- `middle` — reboot, snapshot/remove, _uninstall, _update
+- `high` — _fix (commit c8992e5d, aligned with README 'fix nodepack' risk tier)
```

---

## 5. Final Consistency Status Summary

| Check | Result |
|-------|--------|
| `verify_audit_counts.py` exit code | **0 (PASS)** |
| Audit Summary Matrix ↔ per-section rows | **Internally consistent** (94/0/0/15/109) |
| Design Goal counts (92 base, 95 superset) | **Consistent** across `verification_design.md`, `e2e_verification_audit.md` |
| `test_e2e_csrf.py` function/parametrization tally | **Consistent** across 4 cross-referencing reports (4 functions / 29 invocations / 16+2+11) |
| Cross-file test-count tally (Playwright) | **1 file out-of-sync** (`e2e_test_coverage.md` claims 21 / 22, rest agree on 20) |
| Audit ↔ actual test files (code-level drift) | **3 files out-of-sync**: config_api (+5 rows missing), snapshot_lifecycle (+1 row missing), customnode_info (+1 skip companion, acceptable) |
| Security Level Matrix ↔ source code | **Stale for do_fix**: middle vs actual high (commit c8992e5d) |

### Drift counts by severity

| Severity | Count | Items |
|---------:|------:|-------|
| MAJOR (Category B, structural) | **5** | B-1, B-2, B-3, B-4, B-5 |
| MAJOR (Category C, semantic/code drift) | **3** | C-1, C-2, C-3 |
| MINOR (Category A, cosmetic count/typo) | **4** | A-1, A-2, A-3, A-4 |
| MINOR (Category D, observational) | **1** | D-1 (tied to B-4) |
| **TOTAL** | **13** | |

### Interpretation

The **internal cross-report consistency is strong** — the audit's Summary Matrix parser passes, Design Goal / test-count / CSRF-contract numbers agree across 4–6 cross-referencing reports, and line-range citations (L92–L109, L378–L382) are verified accurate against source code.

The **external drift** (reports ↔ actual code) is concentrated in two places:

1. **Newly added tests not yet reflected in the audit matrix** — `test_remove_path_traversal_rejected` (snapshot), 5 new config_api tests (junk_value + disk-persistence), and a skip-companion in customnode_info. These are real, passing tests that should be audited and counted.
2. **do_fix security level semantic drift** — commit c8992e5d (2026-04-04) moved the gate from `middle` to `high`, but three reports still document the pre-commit state.

Neither class of drift invalidates the existing numbered conclusions (the audit passes its own checker); both are about **undercount / stale** rather than contradiction. Priority recommendation: apply Patch Y1 + Y4 before PR (minimal, high-value), defer Patch Y2 + Y3 to a follow-up WI if PR scope is tight.

---

*End of Consistency Audit Report Y*
