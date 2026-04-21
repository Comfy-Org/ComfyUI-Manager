# Test Bloat Inventory — Sweep Aggregate

**Generated**: 2026-04-20 (via `/pair-sweep test bloat identification`)
**Scope**: 127 test functions across 21 files (14 pytest E2E + 7 Playwright specs)
**Method**: Static analysis by 4-member team (4 chunks, 127 items, `cl-20260419-bloat-{teng,review,dev,dbg}`)
**References**: `goal-report-bloat-sweep.md` (10 bloat code definitions B1-BA)

---

## Executive Summary

| Metric | Count | Rate |
|---|---:|---:|
| Total analyzed | **127** | 100% |
| ✅ CLEAN | **94** | 74.0% |
| ⚠️ BLOAT | **33** | 26.0% |
| 🔴 Immediate remove/merge | **16** | 12.6% |
| 🟡 Refactor / consolidate | **~10** | 7.9% |
| 🟢 Borderline (retained with note) | **~7** | 5.5% |

**Post-action projection**: 127 → ~115 tests (−12 via remove/merge) with zero coverage loss. Bloat rate drops from 26% to ≤5%.

---

## Chunk Distribution

| Chunk | Member | Total | CLEAN | BLOAT | Top codes |
|---|---|---:|---:|---:|---|
| A (csrf/secgate/version) | dbg | 19 | 17 | 2 | B7, B9 |
| B (endpoint/customnode/snapshot/git_clone) | reviewer | 29 | 23 | 6 | B1 (×4), B1/B5 (×1), B7 (×1) |
| C (config_api/queue/task_ops/system) | teng | 45 | 30 | 15 | B1 (×5), B9 (×9), B8 (×1) |
| D (uv_compile + Playwright) | dev | 34 | 24 | 10 | B9 (×5), B5 (×2), B1, B4+B5+BA, B8 |
| **TOTAL** | — | **127** | **94** | **33** | B9 (primary) |

**Top bloat code**: **B9 Copy-paste** (14 occurrences across chunks) — largely from copy-paste test skeletons that can be parametrized.

---

## 🔴 Priority 1 — Immediate Remove (1 item)

| ID | File | Function | Reason | Verdict |
|---|---|---|---|---|
| dev:ci-013 | debug-install-flow.spec.ts | `capture install button API flow` | Zero `expect()` calls, only `console.log`. Diagnostic script committed as test — cannot fail. | B4+B5+BA |

**Action**: Delete the entire spec file OR move to `tools/` directory.

---

## 🔴 Priority 2 — Remove (subsumed by other tests) — 7 items

| ID | File | Function | Subsumed by | Code |
|---|---|---|---|---|
| reviewer:ci-004 | endpoint.py | (install_uninstall related)1 | ci-003 (WI-N strengthening adds API cross-check) | B1 |
| reviewer:ci-005 | endpoint.py | install-uninstall-cycle | concat of ci-001+ci-002+ci-003 | B1 |
| reviewer:ci-006 | endpoint.py | /system_stats smoke | fixture already polls until 200 | B5 |
| reviewer:ci-009 | customnode_info.py | getmappings | subsumed by ci-008 first-5 schema (post-WI-M) | B1 |
| teng:ci-005 | (config_api or queue) | strict subset of ci-002 disk check | ci-002 | B1 |
| teng:ci-010 | subset of ci-007 + dup of ci-005 | ci-007 | B1 |
| teng:ci-017 | weaker subset of ci-016 | ci-016 | B1 |
| teng:ci-024 | subset of ci-016, misleading 'final' | ci-016 | B1, B8 |
| teng:ci-028 | cycle covered by ci-026+ci-027 | ci-026+ci-027 | B1 |
| dev:ci-010 | uv_compile.py | `test_uv_compile_conflict_attribution` | ci-012 (strict superset) | B1 |

**Action**: Delete these tests individually; confirm no unique assertion.

---

## 🟡 Priority 3 — Merge / Parametrize Clusters — 5 clusters (~12 tests → 4 tests)

### Cluster 1 — config_api roundtrip (3 → 1)
`teng:ci-002, ci-007, ci-013` → `@pytest.mark.parametrize("endpoint,key,values", ...)`
Estimated savings: 3 × ~60 lines → 1 parametrized test.

### Cluster 2 — config_api invalid-body (3 → 1)
`teng:ci-003, ci-008, ci-015` → parametrize across `(endpoint, key)`.

### Cluster 3 — config_api junk-value (3 → 1)
`teng:ci-004, ci-009, ci-014` → parametrize across `(endpoint, key, values)`.

### Cluster 4 — task_operations history (2 → 1)
`teng:ci-030, ci-032` → parametrize across `(kind, ui_id)`.

### Cluster 5 — uv_compile verb (5 → 1)
`dev:ci-004, ci-005, ci-006, ci-007, ci-011` → parametrize across verb (update/update_all/fix/fix_all/restore-dependencies).

### Cluster 6 — install_model missing-field (2 → 1)
`teng:ci-034, ci-035` → parametrize across missing_field.

### Cluster 7 — version_mgmt response contract (4 → 1)
`dbg:ci-013, ci-014, ci-015, ci-016` → merge into single `test_versions_response_contract`.

### Cluster 8 — snapshot: reviewer:ci-026 merge-with ci-022

**Total merge savings**: ~12 tests → 8 tests (−4 net).

---

## 🟡 Priority 4 — Refactor In-Place (3 items)

| ID | File | Function | Issue | Recommendation |
|---|---|---|---|---|
| dev:ci-003 | uv_compile.py | `test_reinstall_with_uv_compile` | OR-fallback masks "known issue — purge_node_state bug" | `@pytest.mark.xfail(reason=...)` OR split positive/already-exists |
| dev:ci-008 | uv_compile.py | `test_uv_compile_no_packs` | `rc==0 OR "No custom node packs"` — OR-fallback | Split into 2 tests (empty tree rc==0 / non-empty rc==0 + substring) |
| dev:ci-022 | manager-menu.spec.ts | `shows settings dropdowns (DB, Channel, Policy)` | Title promises 3 dropdowns, only asserts 2 | Add `channelCombo` assertion OR rename |
| reviewer:ci-013 | customnode_info.py | (TODO stub) | L303 TODO makes test stub; skip mask hides incomplete impl | Resolve TODO or drop skip |
| dbg:ci-012 | secgate_strict.py | `test_post_works_at_default_after_restore` | Entire body is `pytest.skip()` placeholder | **DELETE** function, preserve intent in module comment |
| dbg:ci-018 | version_mgmt.py | `test_switch_version_missing_client_id` | Duplicates ci-017 (gate 403 before param validation) | Remove or parametrize with ci-017 |

---

## 🟢 Priority 5 — Borderline B9 Retained (intentional parallels) — 7 items

| ID | Reason for retention |
|---|---|
| dbg:ci-005-008 (csrf_legacy mirror csrf) | Different fixture → different SUT (legacy XOR glob mutex). Coverage necessary, not redundant. |
| dev:ci-024 (Policy persist vs ci-023 DB) | Orthogonal target dropdowns; rollback paths differ. |
| dev:ci-026 (model-manager open vs ci-014 custom-nodes open) | Different dialog id; structural-open verification per dialog is cheap. |
| dev:ci-028 (model-manager search vs ci-017 custom-nodes search) | Different backend queries. |
| dev:ci-032 (snapshot open vs ci-014/026) | Third dialog; each has distinct open-path pinning. |

---

## Key Findings / Patterns

1. **B9 Copy-paste dominates bloat** (~14 of 33 BLOAT items) — all concentrated in pytest uv_compile (5), config_api (9), version_mgmt (4). Parametrization fixes all.
2. **Playwright >>> pytest for bloat rate**: Playwright 91% CLEAN vs pytest uv_compile 42% CLEAN. Playwright has `expect.poll` + `beforeEach` hoisting + state-based assertions. pytest uv_compile uses substring `in combined` as sole assertion in 5/12.
3. **OR-fallback pattern** (2 tests: dev:ci-003, ci-008) masks which branch runs — AP-3-adjacent.
4. **Intentional mutex parallels** (dbg chunk) kept as CLEAN — csrf.py + csrf_legacy.py test different SUT loaded via `__init__.py` mutex. Not redundant despite structural similarity.
5. **`debug-install-flow.spec.ts`** is the single most egregious bloat — zero assertions, pure `console.log`. Not a test.

## Secondary Observations (non-bloat but flagged)

| Target | Observation | Scope |
|---|---|---|
| `test_e2e_uv_compile.py` | 12 CLI subprocess tests mis-filed under `tests/e2e/` (should be `tests/cli/`). Not B4 Dead — real functionality. | Relocation WI candidate |
| `test_e2e_csrf.py` | Post-WI-HH correctly excludes 3 dual-purpose endpoints from STATE_CHANGING_POST_ENDPOINTS. | (already resolved) |
| `test_e2e_secgate_strict.py::SR4 PoC` | Strongest negative-side check pattern (file-unchanged on disk). | Propagate pattern to SR6/V5/UA2 follow-ups |
| `test_e2e_csrf_legacy.py` | 2 legacy-only endpoints (install/git_url, install/pip) per WI-JJ-B. | (already added) |

---

## Post-Action Projection

Applying 🔴 + 🟡:
- 127 current tests
- −1 remove (dev:ci-013 debug-install-flow)
- −9 remove (subsumed tests, reviewer+teng+dev)
- −4 merge/parametrize (7 clusters net savings: from 23 tests into 11 parametrized)

**Projected final count**: ~**113 tests** (−14, ~11% reduction) with zero coverage loss. Bloat rate target: ≤5%.

---

## Next Steps (follow-up WI candidates)

1. **WI-MM**: Apply 🔴 removals (1 remove + 9 subsumed + 1 delete PoC stub = 11 deletions) — low risk, high value
2. **WI-NN**: Apply 🟡 parametrize clusters (5-7 clusters → significant line reduction)
3. **WI-OO**: Apply 🟡 refactors (ci-003 xfail, ci-008 split, ci-022 rename/add, ci-013 TODO resolve, ci-018 merge/parametrize)
4. **WI-PP (optional)**: Relocate `test_e2e_uv_compile.py` from `tests/e2e/` to `tests/cli/`

Each WI should update `reports/e2e_verification_audit.md` Summary Matrix + TOTAL (tests will decrease) and run `verify_audit_counts.py` PASS at completion.

---

## Validation

- ✅ `cl-20260419-bloat-dbg`: 19/19 done
- ✅ `cl-20260419-bloat-review`: 29/29 done
- ✅ `cl-20260419-bloat-teng`: 45/45 done
- ✅ `cl-20260419-bloat-dev`: 34/34 done
- ✅ **Total**: 127/127 (100%)

Every item has verdict + evidence + recommendation in its respective checklist YAML.

---

*End of Test Bloat Inventory*
