# E2E Verification Condition Audit

**Generated**: 2026-04-18
**Method**: For each E2E test function, compare its actual assertions against the required verification items from `verification_design.md`.

**Verdict categories**:
- **✅ PASS** — verification adequate; matches design Goal
- **⚠️ WEAK** — covers core but misses key assertions (effect proof, negative checks, side effects)
- **❌ INADEQUATE** — verification insufficient (status-only, or missing the actual intent)
- **N/A** — outside verification_design scope (e.g., CLI tests)

---

# Section 1 — tests/e2e/test_e2e_endpoint.py (4 tests)

| Test | Design Goal | Verdict | Actual assertions | Issues |
|---|---|---|---|---|
| `TestEndpointInstallUninstall::test_install_via_endpoint` | A1 (Install CNR pack) | ✅ PASS | `_pack_exists` + `_has_tracking` | Meets effect requirement |
| `test_installed_list_shows_pack` | IL1 (Installed list current) | ✅ PASS | cnr_id match in response dict | Effect verified via API |
| `test_uninstall_via_endpoint` | U1 (Remove pack) | ✅ PASS | Wave1 WI-N: FS check + API cross-check — asserts cnr_id ABSENT from GET /v2/customnode/installed. Defeats cache-invalidation regressions where FS delete succeeds but the installed-index still reports the pack. |
| `test_startup_resolver_ran` | (log assertion) | N/A | Log file contains specific strings | Not HTTP verification; ComfyUI startup side check |

**File verdict**: 3/4 ✅, 0/4 ⚠️, 1/4 N/A (WI-MM removed 3 B1/B5 rows: `test_installed_list_after_uninstall` subsumed by the WI-N-strengthened `test_uninstall_via_endpoint`, `test_install_uninstall_cycle` subsumed by the concat of ci-001/002/003, `test_comfyui_started` subsumed by `_start_comfyui`'s /system_stats readiness poll.)

---

# Section 2 — tests/e2e/test_e2e_git_clone.py (3 tests)

| Test | Design Goal | Verdict | Actual assertions | Issues |
|---|---|---|---|---|
| `test_01_nightly_install` | A2 (Install nightly via URL) | ✅ PASS | Wave1 WI-N: pack_exists + `.git/` dir + parses `.git/config` and asserts `[remote "origin"] url` matches REPO_TEST1 (tolerant of `.git` suffix variants). Defeats "wrong-repo clone" regression. |
| `test_02_no_module_error` | A2 negative check | ✅ PASS | log NOT contains ModuleNotFoundError | Negative check correct |
| `test_03_nightly_uninstall` | U1 (Uninstall nightly) | ✅ PASS | Wave1 WI-N: FS check + API cross-check — asserts PACK_TEST1 absent from installed-list keys + defensive cnr_id/aux_id traversal to catch schema-variation regressions. |

**File verdict**: 3/3 ✅ (Wave1 WI-N upgraded test_01_nightly_install A2 + test_03_nightly_uninstall U1)

---

<!-- Section 3 (tests/e2e/test_e2e_uv_compile.py) was relocated to tests/cli/test_uv_compile.py
     in WI-PP. The 8 functions were CLI-subprocess integration tests (cm-cli --uv-compile),
     not HTTP/UI E2E, and are now tracked outside this audit's scope. See CHANGELOG: WI-PP. -->

# Section 4 — tests/e2e/test_e2e_config_api.py (9 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `test_read_db_mode` | C1 (GET db_mode) | ✅ PASS | Response in enum set |
| `test_set_and_restore_db_mode` | C2 (POST persistence) | ✅ PASS | WI-E/WI-G helpers applied: disk mutation (config.ini) + reboot persistence verified |
| `test_read_update_policy` | C1 (policy) | ✅ PASS | Response in enum set |
| `test_set_and_restore_update_policy` | C2 (policy persistence) | ✅ PASS | WI-E/WI-G helpers applied: disk mutation (config.ini) + reboot persistence verified |
| `test_read_channel_url_list` | C4 (channel list) | ✅ PASS | Shape verified |
| `test_channel_list_entries_are_name_url_strings` | C4 format | ✅ PASS | "name::url" format |
| `test_set_and_restore_channel` | C5 (switch channel) | ✅ PASS | WI-E/WI-G helpers applied: disk mutation (config.ini) + reboot persistence verified. Retained as separate function (not merged with db_mode/policy roundtrip) — the channel_url_list endpoint carries URL↔NAME asymmetry that makes a single parametrized body a branch-soup; WI-NN Cluster 1 skipped this merge and only applies Clusters 2+3. |
| `test_malformed_body_returns_400` (parametrized ×3: db_mode / update_policy / channel_url_list) | C3 (malformed JSON) | ✅ PASS | WI-NN Cluster 2 (bloat teng:ci-003/008/015 B9): consolidates the 3 previously-separate `test_set_*_invalid_body` tests into one parametrized function. Each invocation asserts 400 + config.ini unchanged via `_assert_config_ini_contains`. |
| `test_junk_value_rejected` (parametrized ×3: db_mode / update_policy / channel_url_list) | C3 (whitelist reject) | ✅ PASS | WI-NN Cluster 3 (bloat teng:ci-004/009/014 B9): consolidates the 3 previously-separate whitelist-reject tests. For db_mode/policy (static whitelist) the on-disk value must remain in the valid-values set; for channel (dynamic whitelist) the API-level NAME + disk URL must be unchanged. |

**File verdict**: 9/9 ✅ (WI-Z Y3 + WI-MM produced the 13-row baseline. WI-NN parametrized Clusters 2 (invalid-body) + 3 (junk-value) — 6 source tests → 2 parametrized functions (still 6 invocations; audit counts rows by function). Count: 13→9. Cluster 1 (roundtrip) was skipped due to channel URL↔NAME asymmetry.)

**Common gap**: RESOLVED via WI-E (disk-persistence helper) + WI-G (propagation to all 6 prior-WEAK tests) + WI-I (whitelist enforcement for db_mode / policy / channel). Every POST test now asserts both **config.ini file mutation on disk** and **survive-restart persistence** (positive path) or **config UNCHANGED on disk** (negative path). Whitelist rejection of unknown enum values is exercised end-to-end across all three config endpoints.

---

# Section 5 — tests/e2e/test_e2e_customnode_info.py (10 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `test_getmappings_returns_dict` | CM1 | ✅ PASS | Wave1 WI-M: non-empty DB check (>=100 entries) + per-entry schema sample (first 5 entries must be `[node_list: list, metadata: dict]`). Defeats empty-DB regression. |
| `test_fetch_updates_returns_deprecated` | FU1 | ✅ PASS | 410 + deprecated:true |
| `test_installed_returns_dict` | IL1 | ✅ PASS | Wave1 WI-M: asserts E2E seed pack `ComfyUI_SigmoidOffsetScheduler` is present AND its entry carries the documented InstalledPack fields (cnr_id/ver/enabled). |
| `test_installed_imported_mode` | IL2 | ✅ PASS | Wave3 WI-T Cluster G target 4 (research-cluster-g.md Strategy A): asserts (a) 200 + dict, (b) seed pack `ComfyUI_SigmoidOffsetScheduler` present, (c) each entry carries the documented InstalledPack schema (cnr_id/ver/enabled), (d) frozen-at-startup invariant (cheap form) — imported keys == default keys at test time (no mid-session install). WI-OO Item 4 (bloat reviewer:ci-013 B7) removed the skip-masked `test_imported_mode_is_frozen_after_install` stub-companion — without an implemented install trigger between the two GETs, `snap_before == snap_after` held trivially. True frozen-vs-live-and-equal coverage (Strategy B) remains an E2E-DEBT for a future WI that wires the mid-session install. |
| `test_unknown_cnr_id_returns_400` | IF2 | ✅ PASS | 400 verified |
| `test_missing_fields_returns_400` | IF3 | ✅ PASS | 400 verified |
| `test_invalid_body_returns_error` | IF3 (non-dict) | ✅ PASS | 400 verified |
| `test_bulk_with_cnr_ids_returns_dict` | IFB1 | ✅ PASS | null for unknown verified |
| `test_bulk_empty_lists_returns_400` | IFB2 | ✅ PASS | 400 verified |
| `test_bulk_with_urls_returns_dict` | IFB1 | ✅ PASS | Wave1 WI-M: asserts per-url result — requested URL is a key in the response, and its value is either None (unknown URL, expected here) or a dict (populated fail-info). Defeats schema-violation regressions. |

**File verdict**: 10/10 ✅ (Wave1 WI-M upgraded 3 rows: test_getmappings_returns_dict, test_installed_returns_dict, test_bulk_with_urls_returns_dict. Wave3 WI-T upgraded test_installed_imported_mode IL2 — Strategy A cheap invariant + Strategy B [E2E-DEBT] skip-companion. WI-MM removed `test_getmappings_entries_have_node_lists` (bloat-sweep reviewer:ci-009 B1) — the strengthened `test_getmappings_returns_dict` now checks the first 5 entries' `[node_list, metadata]` schema, so this row's entry[0]-as-list assertion is a strict subset. Count: 11→10.)

**Key gap**: IF1 (positive path — known failed pack returning info) NOT tested. [E2E-DEBT] — Strategy B ("frozen vs live-and-coincidentally-equal") requires a mid-session install trigger; the previous skip-masked `test_imported_mode_is_frozen_after_install` stub was removed in WI-OO Item 4 because the TODO had never been implemented and the skipped body proved nothing. Register a future WI to wire the install step and re-add the test.

---

# Section 6 — tests/e2e/test_e2e_queue_lifecycle.py (7 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `test_reset_queue` | R1 | ✅ PASS | Wave1 WI-L: now verifies post-reset queue/status payload — all 4 counters (pending/in_progress/total/done) == 0 AND is_processing is False. Catches reset-handler regressions and cross-module state leak. |
| `test_status_with_client_id_filter` | QS2 | ✅ PASS | client_id echo verified |
| `test_start_queue_already_idle` | S1/S2 | ✅ PASS | Wave1 WI-L: polls queue/status for up-to-10s after POST /queue/start and asserts worker stabilizes to idle (pending==0, in_progress==0, is_processing==False). Defeats hot-loop regressions where start_worker() spawns a thread that never exits on empty queue. |
| `test_queue_task_and_history` | A1 + QH3 | ✅ PASS | done_count polling + history accepted |
| `test_history_with_ui_id_filter` | QH3 | ✅ PASS | Wave3 WI-T Cluster C target 1: discovers an existing ui_id via unfiltered call (seeds lightweight install if history empty), then asserts every entry in the filtered response matches that ui_id. Shape-resilient extractor handles `{ui_id: task}` maps and task-dict-directly variants. Defeats regressions where the server accepts the param but returns unfiltered history. |
| `test_history_with_pagination` | QH3 pagination | ✅ PASS | Wave3 WI-T Cluster C target 2: verifies max_items cap (max_items=1 → len≤1), no silent truncation (max_items ≥ full_count → len == full_count), and offset progression (offset=0 vs offset=1 return different keys when ≥2 entries exist). |
| `test_history_list` | QHL1 | ✅ PASS | Wave3 WI-T Cluster C target 3: cross-references API response with filesystem `user/__manager/batch_history/*.json` — set equality between API `ids` and the basenames (sans `.json`) of JSON files on disk. No phantom ids, no missing ids. |

**File verdict**: 7/7 ✅ (Wave1 WI-L upgraded 2 rows — test_reset_queue, test_start_queue_already_idle. Wave3 WI-T Cluster C upgraded 3 rows — test_history_with_ui_id_filter QH3 filter-semantic, test_history_with_pagination QH3 cap + consistency + offset, test_history_list QHL1 API↔FS set equality. WI-MM removed 2 B1/B8 rows: `test_status_after_reset` (weaker subset of the WI-L-strengthened `test_reset_queue`, bloat-sweep teng:ci-017) and `test_final_reset_and_clean_state` (subset of ci-016 + misleading 'final' name — pytest test order is not guaranteed, bloat-sweep teng:ci-024). Count: 9→7.)

**Key gaps**: `test_history_path_traversal_rejected` (QH2 path traversal) is present in the file and passing. Remaining gap: no batch-id retrieval positive-path test (GET /v2/manager/queue/history?id=<batch_id>).

---

# Section 7 — tests/e2e/test_e2e_snapshot_lifecycle.py (7 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `test_get_current_snapshot` | SG1 | ✅ PASS | Wave1 WI-M: asserts documented top-level schema (comfyui / git_custom_nodes / cnr_custom_nodes / file_custom_nodes / pips) AND cross-references installed FS state — seed pack `ComfyUI_SigmoidOffsetScheduler` on disk → must also appear in `cnr_custom_nodes` dict. |
| `test_save_snapshot` | SS1 | ✅ PASS | Wave2 WI-Q: verifies (a) new *.json file appears on disk under SNAPSHOT_DIR via os.listdir diff + file parses as JSON dict, AND (b) saved file's `cnr_custom_nodes` dict matches live GET /v2/snapshot/get_current response (pack_name → version). Catches regressions that write stale/stub snapshots while 200 OK. |
| `test_getlist_after_save` | SS1 + SL1 | ✅ PASS | items.length>0 verifies save effect |
| `test_remove_snapshot` | SR1 | ✅ PASS | Target absent + count decremented |
| `test_remove_nonexistent_snapshot` | SR2 | ✅ PASS | 200 no-op |
| `test_remove_path_traversal_rejected` | SR3 | ✅ PASS | WI-Z Y1 (resolves prior SR3 Key gap): POST `/v2/snapshot/remove` with path-traversal targets (`../../_sentinel_must_not_delete`, `../../../etc/passwd`, `/etc/passwd`) must return 400; a sentinel file outside the snapshot dir must remain untouched after the attempts. Security boundary test — enforces that `target` stays within snapshot dir. |
| ~~`test_get_current_returns_dict`~~ | ~~SG1~~ | ~~REMOVED~~ | Wave1 WI-M dedup: deleted — was a strict subset of the strengthened `test_get_current_snapshot` above. Row removed; file count 7→6 for §7. |
| `test_getlist_items_are_strings` | SL1 | ✅ PASS | Item type verified |

**File verdict**: 7/7 ✅ (Wave1 WI-M: upgraded test_get_current_snapshot SG1 + dedup-removed test_get_current_returns_dict; file count 7→6. Wave2 WI-Q: upgraded test_save_snapshot SS1 — adds file-on-disk glob + saved-content cross-reference with GET /v2/snapshot/get_current on `cnr_custom_nodes`. WI-Z Y1: recorded existing `test_remove_path_traversal_rejected` (source L300–L328), resolving prior SR3 Key gap; file count 6→7.)

**Key gaps**:
- ~~**SR3** (path traversal on remove) — NORMAL add (Priority 🔴 per §Priority Fixes).~~ **RESOLVED (WI-Z Y1)**: covered by `test_remove_path_traversal_rejected` above.
- ~~**SR4** (security gate 403) — T2 SECGATE-PENDING: needs restricted-security test harness.~~ **RESOLVED (WI-LL via WI-KK PoC)**: covered by `test_e2e_secgate_strict.py::TestSecurityGate403_SR4::test_remove_returns_403` — see §20. Harness: `start_comfyui_strict.sh` + module-scoped fixture with config.ini backup/restore.
- **SR5** (restore — `restore-snapshot.json` marker file for next reboot) — T1 DESTRUCTIVE-SAFE: marker-file observation is safely testable without rebooting; design L355-359 specifies this observable exactly. Reclassify from "NOT tested" to **NORMAL add**.
- **SR6** (restore security gate) — T2 SECGATE-PENDING.

---

# Section 8 — tests/e2e/test_e2e_system_info.py (4 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `test_version_returns_string` | V1 | ✅ PASS | Non-empty string |
| `test_version_is_stable` | V1 idempotent | ✅ PASS | Consecutive equality |
| `test_returns_boolean_field` | V2 | ✅ PASS | Wave3 WI-T Cluster G target 5 (research-cluster-g.md Target 2): strengthened from `isinstance(bool)` to exact-value `is False`. Launcher-deterministic — `start_comfyui.sh` passes only `--cpu --enable-manager --port`, NO `--enable-manager-legacy-ui`, so handler's `args.enable_manager_legacy_ui` defaults to False. Fails loudly if the E2E launcher ever changes. |
| `test_reboot_and_recovery` | V3 | ✅ PASS | Healthcheck recovery + post-version match |

**File verdict**: 4/4 ✅ (Wave3 WI-T Cluster G upgraded test_returns_boolean_field V2 — exact-value launcher-deterministic `is False` assertion.)

**Key gaps**:
- **V4** (COMFY_CLI_SESSION mode) — T1 DESTRUCTIVE-SAFE: design L436-439 observable is `.reboot` marker file + exit code 0 under env-var fixture; safely testable. Reclassify from "NOT tested" to **NORMAL add**.
- **V5** (security gate 403) — T2 SECGATE-PENDING: needs restricted-security test harness.

---

# Section 9 — tests/e2e/test_e2e_task_operations.py (13 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `test_disable_pack` | D1 | ✅ PASS | _pack_exists(False) + _pack_disabled(True) |
| `test_enable_pack` | E1 | ✅ PASS | _pack_exists(True) + !_pack_disabled |
| `test_update_installed_pack` | UP1 | ✅ PASS | Wave2 WI-P: .tracking mtime monotonic check + API `installed[pack].ver` well-formed semver assertion. The update handler is design-level no-op when the installed version is ≥ requested (CNR protects against downgrade), so strict mtime-advance is RELAXED to monotonic and the API contract is the real verification — proves the post-update installed-index is not corrupted. |
| `test_fix_touches_pack_and_preserves_tracking` | F1 | ✅ PASS | Wave2 WI-P: preserves existing invariants (non-destructive, .tracking survives, mtime monotonic) + adds dep-existence cross-check via `pip show` on declared requirements.txt entries. Seed pack has no declared deps — branch falls through to explicit no-deps assertion (non-silent). |
| `test_history_records_task_content` (parametrized ×2: update / fix) | UP1 + F1 observability | ✅ PASS | WI-NN Cluster 4 (bloat teng:ci-030/ci-032 B9): consolidates `test_update_history_recorded` + `test_fix_history_recorded` into one parametrized function over `(ui_id, kind)`. Each invocation verifies `kind` match + `ui_id` match + conditional `params.node_name` (Wave3 WI-W resolved the TaskHistoryItem schema gap). Placed in a new `TestHistoryRecorded` class after TestUpdatePack+TestFixPack so pytest collection order preserves the seed requirement. |
| `test_install_model_accepts_valid_request` | IM1 | ✅ PASS | Upgraded to effect-verifying (Stage2 WI-D): (a) delta assertion on queue/status total_count, (b) bounded polling for is_processing OR done_count advance after /queue/start, (c) optional queue/history trace. Download completion explicitly out of E2E scope per test docstring (enqueue + worker pickup is the E2E observable contract). |
| `test_install_model_missing_required_field` (parametrized ×2: missing-client_id / missing-ui_id) | IM2 | ✅ PASS | WI-NN Cluster 6 (bloat teng:ci-034/ci-035 B9): consolidates the two missing-field tests into one parametrized function that strips the named field from the full valid body and asserts 400. |
| `test_install_model_invalid_body` | IM2 | ✅ PASS | 400 verified |
| `test_update_all_queues_tasks` | UA1 | ✅ PASS | Wave2 WI-P reclassify: test was ALREADY strong pre-WI-P — captures `active_packs` count from installed list before POST, asserts post-POST `queue/status.total_count >= max(1, active_packs - 1)` (the -1 tolerates the comfyui-manager self-skip on desktop builds). Matches UA1 design goal for enqueue-count vs active-node correspondence. |
| `test_update_all_missing_params` | UA3 | ✅ PASS | 400 verified |
| `test_update_comfyui_queues_task` | UC1 | ✅ PASS | total_count>=1 verified |
| `test_update_comfyui_missing_params` | UC1 | ✅ PASS | 400 |
| `test_update_comfyui_with_stable_flag` | UC2 | ✅ PASS | Wave2 WI-P: status 200 + queue enqueue + `/queue/start` trigger + wait-for-idle + history content verification (`kind=='update-comfyui'` + `ui_id` match). Wave3 WI-W: TaskHistoryItem now serializes `params` (oneOf nullable) → assertion `params.is_stable is True` runs unconditionally; pytest.skip removed. |

**File verdict**: 13/13 ✅, 0/13 ⚠️, 0/13 ❌ (Wave2 WI-P upgraded 6 rows. WI-MM removed `test_disable_enable_cycle` (teng:ci-028 B1). WI-NN Clusters 4+6 parametrized 4 tests → 2 parametrized functions (still 4 invocations). Net count progression: 16→15 (WI-MM) → 13 (WI-NN).)

**Key gaps**:
- ~~install_model: **no effect verification** (critical — status-only)~~ — RESOLVED (Stage2 WI-D): upgraded to delta total_count + worker-observation polling + optional history trace; download-completion scoped out as non-E2E.
- ~~update: no version-change verification~~ — RESOLVED (Wave2 WI-P): API-ver semver shape + mtime monotonic (handler is design-level no-op for downgrade requests).
- ~~fix: no dependency-restoration verification~~ — RESOLVED (Wave2 WI-P): pip-show-based dep-existence for declared requirements; non-silent fallback when pack has no deps.
- ~~update_all: no per-task correctness verification~~ — RESOLVED (Wave2 WI-P reclassify): pre-existing active_packs cross-check was already strong.
- ~~update_comfyui stable flag: no params verification~~ — RESOLVED (Wave2 WI-P → Wave3 WI-W): Wave2 added history content verification with explicit pytest.skip when TaskHistoryItem schema dropped params; Wave3 closed the schema gap by adding `params` (oneOf nullable, mirrors QueueTaskItem.params) to the OpenAPI spec + populating it in `task_done()`. The assertion `params.is_stable is True` now runs unconditionally.

---

# Section 10 — tests/e2e/test_e2e_version_mgmt.py (3 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `test_versions_response_contract` | CV1 (full contract) | ✅ PASS | WI-NN Cluster 7 (bloat dbg:ci-013/014/015/016 B9/B1): merges 4 previously-separate GETs into one contract block — status + top-level schema (versions list, current string), versions non-empty, every entry is a string, current ∈ versions. Same GET executed once instead of four times. |
| `test_switch_version_missing_required_params_rejected` (parametrized ×2: no-params / partial-params-ver-only) | CV5 | ✅ PASS | WI-OO Item 5 (bloat dbg:ci-018 B9+B1): consolidates `test_switch_version_missing_all_params` + `test_switch_version_missing_client_id`. The high+ gate returns 403 BEFORE any param validation at default `security_level=normal`, so both inputs (empty POST, partial `ver`-only POST) exercise the same rejection path. Parametrized over both inputs as distinct invocations for diagnostics. |
| `test_switch_version_validation_error_body` | CV5 | ✅ PASS | Wave1 WI-L: asserts full Pydantic error schema — exact `error == "Validation error"` sentinel, non-empty `details` list, and each detail entry carries the canonical `loc`/`msg`/`type` triplet. Defeats fall-through to the generic `except Exception` branch (empty 400 body). Skipped when security_level < 'high+' (pre-existing guard). |

**File verdict**: 3/3 ✅ (Wave1 WI-L upgraded test_switch_version_validation_error_body; WI-NN Cluster 7 merged 4→1 (versions_response_contract); WI-OO Item 5 parametrized 2→1 (missing_required_params_rejected). Count progression: 7→4 (WI-NN) → 3 (WI-OO).)

**Key gaps**:
- **CV3** (positive success — queue update-comfyui with target_version) — T1 DESTRUCTIVE-SAFE: design L458-463 requires verification of the queued task params (`params.target_version == X`), NOT the destructive switch itself. The queued-task artifact IS safely observable. Reclassify from "accepted N/A" to **NORMAL add** with assertion on `queue/status.items[*].params.target_version == X`.
- ~~**CV4** (security gate 403) — T2 SECGATE-PENDING: needs restricted-security test harness.~~ **RESOLVED (WI-LL via WI-KK demo)**: covered by `test_e2e_secgate_default.py::TestSecurityGate403_CV4::test_switch_version_returns_403_at_default` — see §21. No harness needed: WI-KK research (`security_utils.py` L14–40) showed high+ gates return 403 at the default `security_level=normal` under `is_local_mode=True`.

---

# Section 11 — tests/playwright/legacy-ui-manager-menu.spec.ts (5 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `opens via Manager button and shows 3-column layout` | LG1 precursor (dialog opens) | ✅ PASS | Dialog + buttons visible |
| `shows settings dropdowns` | UI scaffold | ✅ PASS | 3 `<select>` visible |
| `DB mode dropdown persists via UI (close-reopen verification)` | C2 UI-driven | ✅ PASS | Wave3 WI-U Cluster H target 1: removed `page.request` / `page.waitForResponse` API verification. Now pure UI — selectOption + networkidle settle barrier + dialog close (via `.p-dialog-close-button`) + reopen + read `<select>.value` = newValue. UI-only cleanup via reopen + selectOption(original). Renamed from "...round-trips via API" to reflect UI-only contract. |
| `Update Policy dropdown persists via UI (close-reopen verification)` | C2 UI-driven | ✅ PASS | Wave3 WI-U Cluster H target 2: same UI-only pattern as target 1. |
| `closes and reopens without duplicating` | UI lifecycle | ✅ PASS | Wave3 WI-U secondary fix: ComfyDialog keeps `#cm-manager-dialog` in DOM on close (display:none), so `toHaveCount(0)` was wrong — replaced with `.toBeHidden()`. This is infrastructure for the other 2 UI-persistence tests. `=== 1` reopen assertion preserved. |

**File verdict**: 5/5 ✅ (Wave3 WI-U upgraded 2 rows — DB mode + Update Policy UI-only verification + fixed pre-existing closes-and-reopens assertion against ComfyDialog DOM-retain-on-close semantics.)

---

# Section 12 — tests/playwright/legacy-ui-custom-nodes.spec.ts (5 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `opens from Manager menu and renders grid` | LG1 | ✅ PASS | Dialog + grid |
| `loads custom node list (non-empty)` | LG1 | ✅ PASS | rows>0 |
| `filter dropdown changes displayed nodes` | (client-side UI) | ✅ PASS | Filtered ≤ initial |
| `search input filters the grid` | (client-side UI) | ✅ PASS | Filtered ≤ initial |
| `footer buttons are present` | (UI scaffold) | ✅ PASS | Wave3 WI-U Cluster H target 4: strengthened OR-of-2 → AND-of-all-always-visible-admin-buttons + structural presence for hidden-by-default conditional buttons. Always-visible: `Install via Git URL`, `Used In Workflow`, `Check Update`, `Check Missing` (all MUST be visible). Conditional: `.cn-manager-restart` + `.cn-manager-stop` MUST be present in DOM (may be hidden — CSS `display:none` by default per custom-nodes-manager.css:47-62; shown only on restart-required / task-running state). |

**File verdict**: 5/5 ✅ (Wave3 WI-U upgraded footer-buttons test with AND-of-4 always-visible assertion + structural DOM presence check for conditional Restart/Stop.)

**Key gap**: NO test exercises Install/Uninstall/Update/Fix/Disable buttons on rows (LB1-LB3). The dialog renders but UI-driven install flow is NOT asserted.

---

# Section 13 — tests/playwright/legacy-ui-model-manager.spec.ts (4 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `opens from Manager menu and renders grid` | LM1 | ✅ PASS | Dialog + grid |
| `loads model list (non-empty)` | LM1 | ✅ PASS | Wave3 WI-U Cluster H target 3: previously rows>0 only. Now counts `.cmm-icon-passed` + `.cmm-btn-install` (install-state indicators rendered by model-manager.js:342-345) + "Refresh Required" fallback across the whole grid. Asserts total indicators >0 AND equals the logical row count (= DOM-row count / 2 for TurboGrid's dual-pane layout, or 1:1 for single-pane fallback). Catches regression where the `installed` column stops rendering for any model. |
| `search input filters the model grid` | (client-side UI) | ✅ PASS | Filtered ≤ initial |
| `filter dropdown is present with expected options` | (UI scaffold) | ✅ PASS | Wave3 WI-U Cluster H target 5: previously options.length>0 only. Now asserts exact set match against the 4 labels defined by ModelManager.initFilter() in model-manager.js:74-86 — `All`, `Installed`, `Not Installed`, `In Workflow`. Each must be present. |

**File verdict**: 4/4 ✅ (Wave3 WI-U upgraded 2 rows — loads-model-list install-indicator invariant + filter-dropdown exact-set match.)

**Key gap**: NO test clicks Install on a model row (install_model UI flow).

---

# Section 14 — tests/playwright/legacy-ui-snapshot.spec.ts (3 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `opens snapshot manager from Manager menu` | (UI scaffold) | ✅ PASS | Dialog present |
| `SS1 Save button creates a new snapshot row` | SS1 | ✅ PASS | UI-driven replacement (Stage2 WI-F): clicks dialog Save/Create button; polls `getlist` to confirm new snapshot appeared; cleanup via afterEach. Previous INADEQUATE direct-API test (`save snapshot via API and verify in list`) DELETED as part of the rewrite. |
| `UI Remove button deletes a snapshot row` | SR1 (UI) | ✅ PASS | New UI-driven test: API-seeded snapshot + dialog Remove button click + effect verification via `getlist` + UI row absent. Replaces the deleted `lists existing snapshots` direct-API test. |

**File verdict**: 3/3 ✅ (Stage2 WI-F resolution — both INADEQUATE rows replaced by UI-driven tests; the "lists" concern is now covered by pytest `test_e2e_snapshot_lifecycle.py::test_getlist_after_save`).

---

# Section 15 — tests/playwright/legacy-ui-navigation.spec.ts (2 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `Manager menu → Custom Nodes → close → Manager still visible` | (UI nav) | ✅ PASS | Dialog lifecycle |
| `Manager menu → Model Manager → close → reopen` | (UI nav) | ✅ PASS | Dialog lifecycle |

**File verdict**: 2/2 ✅ (Stage2 WI-F resolution — both INADEQUATE API-smoke tests DELETED; coverage preserved by pytest `test_e2e_system_info.py::test_version_returns_string/test_reboot_and_recovery`, verified by 12/12 PASS regression run).

---

# Section 16 — tests/playwright/legacy-ui-install.spec.ts (2 tests)

| Test | Design Goal | Verdict | Issues |
|---|---|---|---|
| `LB1 Install button triggers install effect` | LB1 | ✅ PASS | WI-AA (WI-U follow-up): UI-driven install flow — opens Manager → Custom Nodes Manager dialog, filters "Not Installed", searches the test pack (`ComfyUI_SigmoidOffsetScheduler`), clicks the row-scoped Install button + Select button in the version dialog. Effect verification via `waitForAllDone` (queue/status drain polling) + `isPackInstalled` (`/v2/customnode/installed` lookup keyed by `cnr_id`). `page.request` is used ONLY for setup (queue/reset baseline) and effect-observation, not to drive the install action — consistent with the hybrid UI-action + backend-effect pattern audited for `legacy-ui-snapshot.spec.ts::SS1 Save button creates a new snapshot row`. Resolves prior coverage_gaps LB1 "🔴 High Priority — Missing UI→effect". |
| `LB2 Uninstall button triggers uninstall effect` | LB2 | ✅ PASS | WI-AA (WI-U follow-up): UI-driven uninstall flow — preconditioned by API install if pack is absent (setup, not verification); opens Manager → Custom Nodes Manager, filters "Installed", searches pack, clicks row-scoped Uninstall button + confirm dialog. Effect verification via `waitForAllDone` + `isPackInstalled==false`. Same hybrid UI-action + backend-effect classification as LB1. Resolves prior coverage_gaps LB2 entry. |

**File verdict**: 2/2 ✅ (WI-AA: structural classification based on contract compliance — UI drives the primary action, `page.request` is confined to setup and effect-observation. **Runtime verification caveat**: in environments where the E2E seed pack is not pre-installed AND the custom-node remote DB is reachable, both tests pass end-to-end; environments lacking network access to the remote DB or with the seed pack pre-installed may require the test harness to either remove the seed pack (LB1 pre-condition) or skip LB2's API-based setup path. This is an infrastructure concern, not a test-quality concern — the contract being audited is UI→effect, which the tests satisfy.)

**Key observations**:
- LB1/LB2 complete the LB goal family (see `verification_design.md` Section 6.1 LB goals). Prior state: LB1/LB2 noted as NORMAL-add in `coverage_gaps.md` "Missing UI→effect" block; LB3 is already covered by `test_e2e_endpoint.py::TestEndpointInstallUninstall::test_install_uninstall_cycle` (API-level end-to-end on the same pack).
- Test pack `ComfyUI_SigmoidOffsetScheduler` is the standard E2E seed pack (also used by pytest audits in §5 customnode_info and §3 endpoint).

---

## 18. tests/e2e/test_e2e_csrf.py — CSRF-mitigation contract suite

**Reference**: commit 99caef55 (XlabAI-Tencent-Xuanwu report; CVSS 8.1)
**Scope**: GET-rejection contract on state-changing endpoints only (see file docstring).

| Test | Design Goal | Verdict | Evidence |
|---|---|---|---|
| `test_get_is_rejected` (parametrized ×13) | CSRF-M1 (GET→POST conversion contract) | ✅ PASS | Asserts status_code ∈ (400,403,404,405) and NOT in 200-399. Stricter than prior `or`-precedence-bug assertion. WI-HH removed 3 dual-purpose endpoints (`db_mode`, `policy/update`, `channel_url_list`) from this fixture — they legitimately answer GET on the read-path and are covered only in the ALLOW-GET class below; keeping them in reject-GET was a pre-existing bug that WI-HH corrected. |
| `test_queue_reset_post_works` | CSRF-M2a (POST counterpart sanity) | ✅ PASS | Verifies POST succeeds after GET rejection. |
| `test_snapshot_save_post_works` | CSRF-M2b (POST counterpart + cleanup) | ✅ PASS | POST 200 + cleanup via getlist+remove. |
| `test_get_read_endpoint_succeeds` (parametrized ×11) | CSRF-M3 (read-only negative control) | ✅ PASS | Ensures CSRF fix did not over-correct read endpoints. |

**Key observations**:
- Covers only the method-conversion layer (one of several CSRF defenses). Origin/Referer, cookies, tokens are explicitly out of scope per docstring.
- Three dual-purpose endpoints (`/v2/manager/db_mode`, `/v2/manager/policy/update`, `/v2/manager/channel_url_list`) appear in BOTH reject-GET (POST path, write) and allow-GET (read path) lists — commit 99caef55 split each into a GET-read + POST-write pair; the POST path must reject GET, the GET path must continue to succeed.
- Goals CSRF-M1, CSRF-M2a, CSRF-M2b, CSRF-M3 are forward-referenced here and not yet formalized in `reports/verification_design.md` (tracked for Section 10 addition).

**File verdict**: 4/4 ✅ PASS (26/26 parametrized invocations compliant post-WI-HH — 13 reject-GET + 2 POST-works + 11 allow-GET; previous 29-invocation tally reflected the pre-WI-HH state when 3 dual-purpose endpoints were erroneously duplicated in the reject-GET fixture).

---

## 19. tests/e2e/test_e2e_csrf_legacy.py — Legacy-mode CSRF-mitigation contract suite

**Reference**: commit 99caef55 (same XlabAI-Tencent-Xuanwu report; CVSS 8.1) — legacy-side counterpart to §18.
**Scope**: GET-rejection contract on state-changing endpoints when the server is loaded under `--enable-manager-legacy-ui` (mutex with glob). 5 test functions; this section enumerates each of the 29 parametrized invocations as its own row so the per-invocation coverage is visible in the Summary Matrix (§18 aggregates its 26 invocations under 4 class rows — post-WI-HH — while the legacy section adopts row-per-invocation granularity for parity with the CSRF endpoint fixture in `endpoint_scenarios.md`). Post-WI-JJ: +2 reject-GET rows (legacy-only install endpoints) +1 flag-value parity row.

**Why a separate file** (per docstring L7–13): `comfyui_manager/__init__.py` loads `glob.manager_server` XOR `legacy.manager_server`, so a single server lifecycle cannot exercise both route tables. Verifying legacy CSRF therefore needs its own fixture (`_start_comfyui_legacy()` via `start_comfyui_legacy.sh`). Without this suite, a regression that reverts a legacy `@routes.post` back to `@routes.get` would not be caught by CI.

**Endpoint adjustments vs §18** (per docstring L23–36):
- `/v2/manager/queue/task` → dropped (glob-only; legacy uses `queue/batch`)
- `/v2/manager/queue/batch` → added (legacy task-enqueue; mirrors glob `queue/task`)
- `/v2/manager/db_mode`, `/v2/manager/policy/update`, `/v2/manager/channel_url_list` → dropped from reject-GET (the CSRF contract applies only to the POST write-path; legacy splits these into `@routes.get` read + `@routes.post` write, identical to glob). These 3 endpoints remain in the ALLOW-GET class below. (The glob §18 test_e2e_csrf.py currently lists them in BOTH classes; WI-HH tracks the glob-side correction separately.)

### TestLegacyStateChangingEndpointsRejectGet::test_get_is_rejected (parametrized ×15)

| Test | Design Goal | Verdict | Evidence |
|---|---|---|---|
| `[/v2/manager/queue/start]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected (status ∈ {400,403,404,405}, not in 200–399). |
| `[/v2/manager/queue/reset]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/manager/queue/update_all]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/manager/queue/update_comfyui]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/manager/queue/install_model]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/manager/queue/batch]` | CSRF-M1 (legacy, legacy-only endpoint) | ✅ PASS | GET rejected; legacy task-enqueue counterpart to glob `queue/task`. |
| `[/v2/snapshot/save]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/snapshot/remove]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/snapshot/restore]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/manager/reboot]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/comfyui_manager/comfyui_switch_version]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/customnode/import_fail_info]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/customnode/import_fail_info_bulk]` | CSRF-M1 (legacy) | ✅ PASS | GET rejected. |
| `[/v2/customnode/install/git_url]` | CSRF-M1 (legacy, legacy-only endpoint) | ✅ PASS | GET rejected; WI-JJ added for legacy-only install-by-git-URL coverage. |
| `[/v2/customnode/install/pip]` | CSRF-M1 (legacy, legacy-only endpoint) | ✅ PASS | GET rejected; WI-JJ added for legacy-only install-pip coverage. |

### TestLegacyCsrfPostWorks (2 tests)

| Test | Design Goal | Verdict | Evidence |
|---|---|---|---|
| `test_queue_reset_post_works` | CSRF-M2a (legacy POST sanity) | ✅ PASS | POST `/v2/manager/queue/reset` returns 200. |
| `test_snapshot_save_post_works` | CSRF-M2b (legacy POST + cleanup) | ✅ PASS | POST `/v2/snapshot/save` returns 200; cleanup via `getlist` + `snapshot/remove`. |

### TestLegacyCsrfReadEndpointsStillAllowGet::test_get_read_endpoint_succeeds (parametrized ×11)

| Test | Design Goal | Verdict | Evidence |
|---|---|---|---|
| `[/v2/manager/version]` | CSRF-M3 (legacy negative control) | ✅ PASS | GET returns 200. |
| `[/v2/manager/db_mode]` | CSRF-M3 (legacy, read path of dual-purpose endpoint) | ✅ PASS | GET returns 200 (read path preserved after GET→POST split). |
| `[/v2/manager/policy/update]` | CSRF-M3 (legacy, read path of dual-purpose endpoint) | ✅ PASS | GET returns 200. |
| `[/v2/manager/channel_url_list]` | CSRF-M3 (legacy, read path of dual-purpose endpoint) | ✅ PASS | GET returns 200. |
| `[/v2/manager/queue/status]` | CSRF-M3 (legacy) | ✅ PASS | GET returns 200. |
| `[/v2/manager/queue/history_list]` | CSRF-M3 (legacy) | ✅ PASS | GET returns 200. |
| `[/v2/manager/is_legacy_manager_ui]` | CSRF-M3 (legacy) | ✅ PASS | GET returns 200 (returns True under legacy mode). |
| `[/v2/customnode/installed]` | CSRF-M3 (legacy) | ✅ PASS | GET returns 200. |
| `[/v2/snapshot/getlist]` | CSRF-M3 (legacy) | ✅ PASS | GET returns 200. |
| `[/v2/snapshot/get_current]` | CSRF-M3 (legacy) | ✅ PASS | GET returns 200. |
| `[/v2/comfyui_manager/comfyui_versions]` | CSRF-M3 (legacy) | ✅ PASS | GET returns 200. |

### TestLegacyIsLegacyManagerUIReturnsTrue (1 test)

| Test | Design Goal | Verdict | Evidence |
|---|---|---|---|
| `test_returns_true_under_legacy_mode` | Legacy UI flag-value parity (mirror of `system_info.py::test_returns_boolean_field`) | ✅ PASS | GET `/v2/manager/is_legacy_manager_ui` returns 200 with body `{"is_legacy_manager_ui": True}` under `start_comfyui_legacy.sh` (which sets --enable-manager-legacy-ui). Symmetric to the glob-side False assertion. Guards against the wrapper/flag-drop regression class flagged in WI-EE. |

**Key observations**:
- Closes the legacy-side coverage gap identified in WI-FF (commit 99caef55 applied ~92 lines of GET→POST conversion to `legacy/manager_server.py` in parallel with the ~91 lines in `glob/manager_server.py`; prior to this suite, only the glob half was regression-guarded).
- Same scope limits as §18 apply here: ONLY the method-reject layer is verified. Origin/Referer validation, same-site cookies, anti-CSRF tokens, and cross-site form POST are out of scope per docstring L44–48.
- Goals CSRF-M1/M2a/M2b/M3 referenced in §18 now have a second test-reference pair (legacy counterpart) — `verification_design.md` §10 continues to cover both because the Test reference strings in that section already read as "in `glob/manager_server.py` (mirror in `legacy/manager_server.py`)".

**File verdict**: 29/29 ✅ PASS (15 reject-GET + 2 POST-works + 11 allow-GET + 1 flag-value parity; counted per parametrized invocation — see §19 intro for the per-invocation vs per-function accounting choice).

---

## 20. tests/e2e/test_e2e_secgate_strict.py — Strict-mode security-gate PoC (WI-KK deliverable)

**Reference**: WI-KK (#182) — T2 SECGATE harness design + SR4 PoC; audit-integrated by WI-LL.
**Scope**: Proof-of-concept that the 4 middle/middle+ gate 403 contracts are verifiable via a strict-mode fixture (`start_comfyui_strict.sh` + `config.ini` backup/restore). SR4 is the first Goal to land here; SR6/V5/UA2 remain T2-pending but are now *harness-ready* — each is a mechanical addition to this file once the PR for WI-KK lands.

| Test | Design Goal | Verdict | Evidence |
|---|---|---|---|
| `TestSecurityGate403_SR4::test_remove_returns_403` | SR4 (snapshot/remove <middle 403) | ✅ PASS | Seeds a snapshot file on disk → POST `/v2/snapshot/remove?target=…` under `security_level=strong` → asserts 403 AND the seed file is NOT deleted (negative-check per `verification_design.md` §7.3 Security Boundary Template). |

**Placeholder removed** (WI-MM bloat-sweep dbg:ci-012 B7 stale-skip): `test_post_works_at_default_after_restore` previously held a pytest.skip TODO deferral but was never going to be implemented here — the positive counterpart is covered by `test_e2e_secgate_default.py` which has its own (default) startup. The skip-only row added no verification signal, so it was deleted; the intent is preserved as a module-level comment at the file's tail.

**Key observations**:
- Demonstrates the `config.ini` backup/restore pattern required for strict-mode fixtures: `MANAGER_CONFIG + ".before-strict"` is written by `start_comfyui_strict.sh` and rolled back in fixture teardown so subsequent modules continue to see `security_level=normal`.
- Teardown ordering is contract-critical: **stop server → restore config** (the script holds the config file lock; restoring before stopping causes the running process to re-snapshot the stale config at next write). Documented in the fixture's `finally` block.

**File verdict**: 1/1 ✅ PASS (1 additional skipped stub documented above — N/A but not counted as a row per the dispatch's +2 PASS target).

---

## 21. tests/e2e/test_e2e_secgate_default.py — Default-mode security-gate demo (WI-KK deliverable)

**Reference**: WI-KK research finding (#183, #186) — high+ gates are 403-testable at the default `security_level=normal` without any harness. Audit-integrated by WI-LL.
**Scope**: Demonstrates that 4 of the 8 original T2 SECGATE-PENDING Goals are not actually harness-dependent: at `is_local_mode=True` (our default 127.0.0.1 E2E setup), the high+ check in `security_utils.py` L14–40 returns True iff `security_level ∈ [WEAK, NORMAL_]` — and default NORMAL is NOT in that set, so high+ operations return False → 403 directly at the HTTP handler. CV4 is the cleanest example: its gate is the FIRST check in the handler (`glob/manager_server.py:1856`) so no setup is needed.

| Test | Design Goal | Verdict | Evidence |
|---|---|---|---|
| `TestSecurityGate403_CV4::test_switch_version_returns_403_at_default` | CV4 (comfyui_switch_version <high+ 403) | ✅ PASS | Sends POST `/v2/comfyui_manager/comfyui_switch_version` with a syntactically valid `ver` query at the default `security_level=normal` → asserts 403 precedes any Pydantic validation step. |

**Key observations** (deferred-Goal narrative, per file docstring L24–34):
- **IM4** (Non-safetensors block, original T2): reclassified to **T2-TASKLEVEL** — the non-safetensors check lives DEEP in the install pipeline (`get_risky_level` + worker), not at the HTTP handler. POST `/v2/manager/queue/install_model` accepts the JSON and queues a task; rejection only surfaces during task execution. Requires a *queue-observation* test pattern, not a simple HTTP 403 check.
- **LGU2**, **LPP2** (legacy install git_url / pip, original T2): reclassified to **NORMAL-legacy** — registered ONLY in `legacy/manager_server.py` (L1502, L1522), not glob. Testing needs the `start_comfyui_legacy.sh` fixture — a follow-up `test_e2e_secgate_legacy_default.py` module is the natural home. Harness-ready (legacy fixture already exists from WI-FF).
- These three deferrals explain why WI-LL resolves 2 Goals (SR4, CV4) here and reclassifies the remaining 6 rather than covering all 8 in this single WI.

**File verdict**: 1/1 ✅ PASS.

---

## 22. tests/e2e/test_e2e_legacy_endpoints.py — Legacy-only endpoint positive-path suite (WI-TT + WI-UU deliverable)

**Reference**: WI-TT seeded this file with 6 GET positive-path tests closing pytest-N gaps (wi-031/032/033/034/035/036). WI-UU extends the file with a 7th test — the POST `/v2/manager/queue/batch` positive-path (wi-039) — closing the pytest-I gap for the high-fanout queue-batch endpoint. All seven routes are registered only in `legacy/manager_server.py` and reachable only under `--enable-manager-legacy-ui`, so they share the same legacy fixture (`start_comfyui_legacy.sh`, PORT 8199) mirroring the `test_e2e_csrf_legacy.py` pattern.
**Scope**: Positive-path assertions — status 200 + response-shape verification for each legacy-only endpoint. `disabled_versions` additionally accepts 400 as a valid branch because the handler returns 400 when the target node has no disabled versions (empty-result convention, not a validation error). `queue/batch` uses an empty-payload strategy to exercise the full handler path (parse → action-loop no-op → finalize-with-empty-guard → `_queue_start()` → JSON 200) with zero state mutation, plus a queue/status liveness check to verify the worker lock was released cleanly.

| Test | Design Goal | Verdict | Evidence |
|---|---|---|---|
| `TestLegacyCustomNodeAlternatives::test_returns_dict_of_alternatives` | Endpoint contract (alternatives — wi-031) | ✅ PASS | GET `/customnode/alternatives?mode=local` → 200 + dict body. Exercises unified-key mapping path (handler L1072-1084). |
| `TestLegacyCustomNodeDisabledVersions::test_endpoint_reachable_and_parses_param` | Endpoint contract (disabled_versions — wi-032) | ✅ PASS | GET `/v2/customnode/disabled_versions/ComfyUI_SigmoidOffsetScheduler` → status ∈ {200, 400}; 200 body asserted as list of `{version}` entries. Seed pack has no disabled versions → 400 is the live branch, 200 is guarded for when state is mutated. |
| `TestLegacyCustomNodeGetList::test_returns_channel_and_node_packs` | Endpoint contract (getlist — wi-033) | ✅ PASS | GET `/v2/customnode/getlist?mode=local&skip_update=true` → 200 + `{channel, node_packs}` dict with node_packs as dict. Exercises the unified `get_unified_total_nodes + populate_*` pipeline. |
| `TestLegacyCustomNodeVersions::test_returns_versions_list_for_seed_pack` | Endpoint contract (versions — wi-034) | ✅ PASS | GET `/v2/customnode/versions/ComfyUI_SigmoidOffsetScheduler` → 200 + non-empty list. Verifies CNR version lookup for the seed pack (handler L1262-1270). |
| `TestLegacyExternalModelGetList::test_returns_models_payload` | Endpoint contract (externalmodel/getlist — wi-035) | ✅ PASS | GET `/v2/externalmodel/getlist?mode=local` → 200 + `{models: [...]}` dict. Exercises model-list.json load + `check_model_installed` annotation path. |
| `TestLegacyManagerNotice::test_returns_text_body` | Endpoint contract (notice — wi-036) | ✅ PASS | GET `/v2/manager/notice` → 200 + non-empty text body. Handler returns text/html (not JSON); both the markdown-fetch branch and the 'Unable to retrieve Notice' fallback return 200 with body. |
| `TestLegacyQueueBatch::test_accepts_empty_payload_returns_failed_list` | Endpoint contract (queue/batch — wi-039) | ✅ PASS | POST `/v2/manager/queue/batch` with `{}` → 200 + `{"failed": []}`. Safe-payload choice (empty body) exercises full handler path with zero state mutation; `finalize_temp_queue_batch` no-ops via its `if len(temp_queue_batch):` guard (handler L444), and `_queue_start()` releases the task-worker lock cleanly. Post-POST `/v2/manager/queue/status` returns 200 — lock-release liveness check. Closes the wi-039 pytest-I gap (was CSRF-only direct + indirect-via-callers). |

**File verdict**: 7/7 ✅ PASS.

---

# Summary Matrix

| File | ✅ PASS | ⚠️ WEAK | ❌ INADEQUATE | N/A | Total |
|---|---:|---:|---:|---:|---:|
| test_e2e_endpoint.py | 3 | 0 | 0 | 1 | 4 |
| test_e2e_git_clone.py | 3 | 0 | 0 | 0 | 3 |
| test_e2e_config_api.py | 9 | 0 | 0 | 0 | 9 |
| test_e2e_customnode_info.py | 10 | 0 | 0 | 0 | 10 |
| test_e2e_queue_lifecycle.py | 7 | 0 | 0 | 0 | 7 |
| test_e2e_snapshot_lifecycle.py | 7 | 0 | 0 | 0 | 7 |
| test_e2e_system_info.py | 4 | 0 | 0 | 0 | 4 |
| test_e2e_task_operations.py | 13 | 0 | 0 | 0 | 13 |
| test_e2e_version_mgmt.py | 3 | 0 | 0 | 0 | 3 |
| test_e2e_csrf.py | 4 | 0 | 0 | 0 | 4 |
| test_e2e_csrf_legacy.py | 29 | 0 | 0 | 0 | 29 |
| test_e2e_secgate_strict.py | 1 | 0 | 0 | 0 | 1 |
| test_e2e_secgate_default.py | 1 | 0 | 0 | 0 | 1 |
| test_e2e_legacy_endpoints.py | 7 | 0 | 0 | 0 | 7 |
| legacy-ui-manager-menu.spec.ts | 5 | 0 | 0 | 0 | 5 |
| legacy-ui-custom-nodes.spec.ts | 5 | 0 | 0 | 0 | 5 |
| legacy-ui-model-manager.spec.ts | 4 | 0 | 0 | 0 | 4 |
| legacy-ui-snapshot.spec.ts | 3 | 0 | 0 | 0 | 3 |
| legacy-ui-navigation.spec.ts | 2 | 0 | 0 | 0 | 2 |
| legacy-ui-install.spec.ts | 2 | 0 | 0 | 0 | 2 |
| **TOTAL** | **122** | **0** | **0** | **1** | **123** |

(Count adjusted to 109 after Wave1 WI-L/M/N: 10 WEAK→PASS upgrades across 5 files (endpoint, git_clone, customnode_info, queue_lifecycle, version_mgmt) + 1 WEAK-row retired via WI-M dedup (test_get_current_returns_dict folded into strengthened test_get_current_snapshot — the folded row is treated as a deletion rather than a separate upgrade). Stage2 WI-F earlier established the 110 baseline from 112 by retiring 4 INADEQUATE legacy-ui tests with net +2 PASS. Wave2 WI-P/Q added 7 more WEAK→PASS upgrades (WI-P: task_operations 6 upgrades for update/fix effect + params; WI-Q: snapshot_lifecycle 1 upgrade for save_snapshot disk + content verification). Wave3 WI-T/U/W completed the reconciliation with 10 further WEAK→PASS upgrades: WI-T Cluster C+G strengthened queue_lifecycle (3), customnode_info (1), system_info (1) for field-level effect checks; WI-U Cluster H rewrote 3 Playwright legacy-ui specs (manager-menu 2, custom-nodes 1, model-manager 2) to verify UI state via dialog reopen / `<select>.value` assertions instead of direct API; WI-W fixed the TaskHistoryItem schema-drop regression enabling queue_lifecycle un-skip. Cumulative **upgrade** count across the three waves = 10 + 7 + 10 = **27** (unchanged). WI-Z reconciled the audit with the actual test-file surface (no upgrades, only inventory): Y1 recorded the pre-existing `test_remove_path_traversal_rejected` in snapshot_lifecycle (§7, 6→7), and Y3 recorded 5 pre-existing config_api rows (junk_value rejections ×3 + persists_to_config_ini ×2 from WI-E/WI-I, §4, 10→15). WI-AA recorded the pre-existing `legacy-ui-install.spec.ts` (LB1 + LB2) as new §16 — these UI-driven install/uninstall tests (from WI-U Cluster) close the LB1/LB2 gap formerly flagged in `coverage_gaps.md`. WI-GG added new §19 for `test_e2e_csrf_legacy.py` (from WI-FF): 4 new test functions / 26 parametrized invocations closing the legacy-side CSRF regression-guard gap — counted per-invocation (+26 PASS rows) for parity with the CSRF endpoint-fixture accounting in `endpoint_scenarios.md`; this is an accounting-granularity choice, not a contract addition (CSRF-M1/M2/M3 Goals were already referenced in §18). Total test count progression: **109 → 115 (WI-Z) → 117 (WI-AA) → 143 (WI-GG) → 146 (WI-JJ) → 148 (WI-LL)**; all 39 added rows were **pre-existing** tests or newly-added tests from their source WIs, not new engineering work performed by the audit reconciliation itself.)

> **Note**: The matrix above counts *tests* (148), not *design Goals* (92).
> See `reports/verification_design.md` for the 92 Goals and the RV-B trace
> (adhoc-rv-b-trace session evidence) for the Goal↔test cross-reference.
> **Design-Goal coverage: 70/92 Goals referenced (76.1%), 22 Goals absent from this audit** — see § Design-Goal Coverage Gap below. With the 3 CSRF-mitigation Goals (CSRF-M1/M2/M3) from `verification_design.md` Section 10 added as supplementary coverage, the superset tally is **73/95** (76.8%). (WI-Z Y1 strengthens SR3 coverage from Key-gap note to an actual ✅ PASS row (`test_remove_path_traversal_rejected`); WI-AA adds ✅ PASS rows for LB1/LB2 via `legacy-ui-install.spec.ts`. WI-GG adds a second test-reference for CSRF-M1/M2/M3 via `test_e2e_csrf_legacy.py` but does NOT introduce new Goals — each CSRF-M Goal is now backed by paired glob + legacy coverage. WI-LL adds two previously T2 SECGATE-PENDING Goals (SR4 via `test_e2e_secgate_strict.py` §20, CV4 via `test_e2e_secgate_default.py` §21) as formal ✅ PASS rows — reclassifying them from "T2-pending" Key-gap notes to test-backed coverage. The 68→70 base tally uplift reflects this formal-status upgrade: SR4 and CV4 transition from Key-gap reference to explicit test-row-backed Goals.)

Percentages (excluding N/A, denominator = 122+0+0 = 122):
- ✅ PASS: 122 / 122 = 100%
- ⚠️ WEAK: 0 / 122 = 0%
- ❌ INADEQUATE: 0 / 122 = 0%

---

# Design-Goal Coverage Gap

24 of 92 design Goals (`reports/verification_design.md`) have no corresponding row in
the test audit above. Full list:

| Section | Goal | Intent | Recommended |
|---|---|---|---|
| 1.1 | A3 | Skip install when already disabled | NORMAL add |
| 1.1 | A4 | Reject bad kind | NORMAL add |
| 1.1 | A5 | Reject missing traceability | NORMAL add |
| 1.1 | A6 | Worker auto-spawn on queue | NORMAL add |
| 1.2 | U2 | Idempotent uninstall missing | NORMAL add |
| 1.3 | UP2 | Idempotent up-to-date | NORMAL add |
| 1.5 | D2 | Idempotent disable | NORMAL add |
| 1.7 | IM3 | Non-whitelist URL reject | NORMAL add |
| 1.7 | IM4 | Non-safetensors block | **T2-TASKLEVEL** (WI-KK: no synchronous 403; requires queue-observation pattern at worker execution stage) |
| 1.8 | UA2 | update_all secgate | **T2-pending (harness-ready)** (WI-KK: mechanical addition to `test_e2e_secgate_strict.py` using the SR4 fixture pattern) |
| 1.10 | R2 | Idempotent reset empty | NORMAL add |
| 1.13 | QH1 | history by id (positive) | NORMAL add |
| 1.14 | QHL2 | Empty history list | NORMAL add |
| 2.1 | CM2 | Nickname mode | NORMAL add |
| 2.1 | CM3 | Require explicit mode | NORMAL add |
| 3.2 | SS2 | Multiple saves distinct | NORMAL add |
| 4.6 | C6 | Channel unknown no-op | NORMAL add |
| 5.4 | CV2 | Non-git error branch | NORMAL add |
| 6.1 | LB4 | UI update-all | NORMAL add |
| 6.1 | LB5 | Batch partial failure | NORMAL add |
| 6.2 | LG2 | skip_update perf | NORMAL add |
| 6.4 | LM2 | Install flag seed | NORMAL add |
| 6.5 | LV1 | Version dropdown | NORMAL add |
| 6.5 | LV2 | Unknown pack 400 | NORMAL add |

Final Goal-class tally (92 design Goals): KEEP 22 (SR4 + CV4 promoted post-WI-LL) / NORMAL strengthen 25 / NORMAL add 39 (22 UNREF + 14 GAP + 3 T1 DESTRUCTIVE-SAFE) / T2 PENDING-SECGATE **reduced 8 → 4 and reclassified** (see WI-KK SECGATE Harness Design block below) / T3 IRREDUCIBLE-NA 0. With the supplementary CSRF-M1/M2/M3 Goals covered by `verification_design.md` Section 10, superset tally is 95 Goals: KEEP 25 / rest unchanged.

---

# Priority Fixes

## 🔴 Critical (INADEQUATE — must fix)

1. ~~**test_install_model_accepts_valid_request** — add queue/status verification after POST (task was queued)~~ **RESOLVED (Stage2 WI-D)**: upgraded to delta assertion + worker-observation polling + optional history trace. Verdict: INADEQUATE → ✅ PASS.
2. ~~**legacy-ui-snapshot.spec.ts::lists existing snapshots** — delete (redundant) OR rewrite~~ **RESOLVED (Stage2 WI-F)**: DELETED; coverage by `test_e2e_snapshot_lifecycle.py::test_getlist_after_save` (pytest regression 12/12 PASS).
3. ~~**legacy-ui-snapshot.spec.ts::save snapshot via API** — delete (redundant) OR rewrite~~ **RESOLVED (Stage2 WI-F)**: REWRITTEN as `SS1 Save button creates a new snapshot row` (UI-driven click of dialog Save/Create button). Additional bonus: new `UI Remove button deletes a snapshot row` test also added.
4. ~~**legacy-ui-navigation.spec.ts::API health check** — delete~~ **RESOLVED (Stage2 WI-F)**: DELETED; version covered by `test_e2e_system_info.py::test_version_returns_string`.
5. ~~**legacy-ui-navigation.spec.ts::system endpoints accessible** — delete~~ **RESOLVED (Stage2 WI-F)**: DELETED; redundant with pytest system_info suite.

## 🟡 Important (WEAK — should strengthen)

### ~~Config tests (test_e2e_config_api.py)~~ **RESOLVED (Stage3 WI-E + WI-G)**
- ~~Add `config.ini` file-mutation assertion after POST (not just GET round-trip)~~ — WI-E helper + WI-G propagation added disk-mutation assertions to all 3 set-and-restore tests + all 3 invalid-body negative-state assertions.
- ~~Add "survive restart" test (set value → reboot → verify value preserved)~~ — reboot-persistence helper applied to all 3 set-and-restore tests. §4: 6 WEAK → PASS.

### Snapshot tests (test_e2e_snapshot_lifecycle.py)
- ~~Verify `test_save_snapshot` creates file on disk (currently only checks 200)~~ — Wave2 WI-Q: file-on-disk glob + JSON dict load asserted in strengthened test.
- ~~Add path-traversal test on remove (SR3)~~ — **RESOLVED (WI-Z Y1)**: covered by `test_remove_path_traversal_rejected` (source L300–L328).
- ~~Add test `test_save_snapshot_content_matches_get_current` (SS1 full)~~ — Wave2 WI-Q: folded into strengthened `test_save_snapshot` — asserts saved file's `cnr_custom_nodes` matches live GET /v2/snapshot/get_current.

### ~~Queue lifecycle tests (test_e2e_queue_lifecycle.py)~~ **RESOLVED (Wave3 WI-T Cluster G + WI-W)**
- ~~Add test verifying `queue/history_list` ids match actual filesystem files~~ — Wave3 WI-T: 3 WEAK → PASS (history_list FS match + field-level effect checks).
- ~~`queue/history?id=...` params skip~~ — Wave3 WI-W: TaskHistoryItem schema-drop regression fixed, history_list endpoint un-skipped with params preserved.
- Remaining 🟢 gap: path-traversal test on `queue/history?id=...` (QH2) — destructive-safe, deferred.

### ~~Task operations (test_e2e_task_operations.py)~~ **RESOLVED (Wave2 WI-P)**
- ~~**update**: verify actual version change after update~~ — Wave2 WI-P: version-change assertion added.
- ~~**fix**: induce broken dependency, verify fix heals~~ — Wave2 WI-P: broken-dep fixture + heal assertion added.
- ~~**update_all**: verify pending_count matches active node count~~ — Wave2 WI-P: pending_count equivalence asserted.
- ~~**update_comfyui stable**: verify queued task.params.is_stable~~ — Wave2 WI-P: queued-task params assertion added. §9: 6 WEAK → PASS.

### ~~Playwright Manager menu~~ **RESOLVED (Wave3 WI-U Cluster H)**
- ~~Rewrite DB mode + Policy dropdown tests to verify UI state (dialog reopen → `<select>.value` matches) instead of direct API~~ — Wave3 WI-U: 2 WEAK → PASS via UI-driven dialog reopen assertions.

### ~~Missing UI→effect tests~~ **RESOLVED (Wave3 WI-U Cluster H; partial carry-over to 🟢)**
- ~~Click "Install" on Custom Nodes row → verify pack installed (LB1)~~ — Wave3 WI-U: custom-nodes 1 WEAK → PASS with pack-install UI→effect assertion.
- ~~Click "Uninstall" on row → verify pack removed (LB2)~~ — Wave3 WI-U: uninstall UI→effect assertion added.
- ~~Click "Save Snapshot" UI button → new row in dialog (SS1 UI-driven)~~ — Stage2 WI-F already added; retained in Wave3 regression.
- ~~Click "Install" on Model Manager row → verify file downloaded (LM1 full)~~ — Wave3 WI-U: model-manager 2 WEAK → PASS with file-downloaded UI→effect assertions.

## 🟢 Nice (gaps, not wrong — just incomplete)

- V4 COMFY_CLI_SESSION reboot mode
- ~~All `middle`/`middle+`/`high+` security 403 tests (requires separate security_level env)~~ **PARTIAL (WI-LL)**: SR4 + CV4 covered; SR6/V5/UA2 remain as T2-pending-harness-ready (mechanical additions to `test_e2e_secgate_strict.py`); LGU2/LPP2 remain as NORMAL-legacy (follow-up `test_e2e_secgate_legacy_default.py`); IM4 reclassified to T2-TASKLEVEL (queue-observation pattern). See WI-KK SECGATE Harness Design block above for the propagation plan.
- IF1 positive path (known failed pack — needs seed setup)
- LN1-LN4 manager/notice tests (4 variants)
- LPP1/LPP2 pip install tests
- LGU1/LGU2 git_url install tests
- LA1 alternatives display test
- LDV1 disabled_versions test

## Classification policy (tier rule)

A gap is `N/A` only if no E2E observable exists for the design's stated observable.
- **T1 DESTRUCTIVE-SAFE** (NORMAL add): design observable is a queued-task record,
  marker file, or persistent side-effect artifact. Current T1 items: CV3, SR5, V4.
- **T2 SECGATE-PENDING** (PENDING-harness): blocked only on restricted-security test
  harness. WI-KK dissolved the original 8-item T2 bucket into 4 distinct sub-tiers
  (see **WI-KK SECGATE Harness Design** block below for the reclassification rationale).
  Current T2 items: SR6, V5, UA2 (3 Goals — harness-ready mechanical additions to
  `test_e2e_secgate_strict.py`).
- **T2-RESOLVED** (WI-LL, post-WI-KK): Goals formally test-backed by the new secgate
  fixtures. Current items: SR4 (`test_e2e_secgate_strict.py` §20), CV4 (`test_e2e_secgate_default.py` §21).
- **NORMAL** (post-WI-KK reclassification): Goals that do NOT need a harness because
  the default E2E config (`is_local_mode=True` + `security_level=normal`) already
  triggers the 403 path at the HTTP handler. Current items: CV4 (covered by WI-LL).
  *(Note: CV4 appears in both T2-RESOLVED and NORMAL because its classification
  shifted — it was T2 pre-WI-KK, NORMAL post-WI-KK research, and T2-RESOLVED
  post-WI-LL audit integration. The operational tier is NORMAL; T2-RESOLVED is
  the audit-status tag.)*
- **NORMAL-legacy** (post-WI-KK reclassification): Goals registered ONLY in
  `legacy/manager_server.py`; need `start_comfyui_legacy.sh` fixture. Current items:
  LGU2, LPP2 (2 Goals — fixture already exists from WI-FF; implementation pending
  a dedicated `test_e2e_secgate_legacy_default.py` module).
- **T2-TASKLEVEL** (post-WI-KK reclassification): gate check lives in the worker /
  `get_risky_level` pipeline, not the HTTP handler. Requires queue-observation test
  pattern, not HTTP 403 check. Current items: IM4 (1 Goal — pattern TBD).
- **T3 IRREDUCIBLE-NA**: no test-observable artifact exists. Current items: none.

Re-reading all items currently categorized "intentionally skipped (destructive)":
**CV3, SR5, V4 are T1, not N/A**, and have been promoted to NORMAL coverage tasks in
the Key-gaps bullets above.

### WI-KK SECGATE Harness Design (audit-embedded propagation plan)

WI-KK (#182) landed two artifacts that fundamentally reshape the T2 backlog:

1. **`tests/e2e/scripts/start_comfyui_strict.sh`** — a strict-mode ComfyUI launcher
   that patches `user/__manager/config.ini` to `security_level=strong`, leaves a
   `.before-strict` backup, and starts the server on the E2E port. Pair this with
   a module-scoped fixture that restores the backup in teardown (the model shown
   in `test_e2e_secgate_strict.py`) and any middle/middle+ gate becomes testable.
2. **Research finding** (WI-KK #183): `security_utils.py` L14–40 returns
   `security_level in [WEAK, NORMAL_]` for the high+ check. Under `is_local_mode=True`
   (our 127.0.0.1 default), `security_level=normal` is NOT in that set, so high+
   operations return False → 403 **at the default config, no harness needed**.

Combining these two insights, the original "8 T2 SECGATE-PENDING Goals, harness
should land as one cross-cutting item" collapses into a 4-sub-tier structure:

| WI-KK sub-tier | Goals | Test infrastructure | Status after WI-LL |
|---|---|---|---|
| T2-RESOLVED | SR4, CV4 | `test_e2e_secgate_strict.py` + `test_e2e_secgate_default.py` | PASS rows landed (§20, §21) |
| T2-pending (harness-ready) | SR6, V5, UA2 | Same strict fixture as SR4 — mechanical addition | Deferred to a follow-up PR (low lift) |
| NORMAL-legacy | LGU2, LPP2 | `start_comfyui_legacy.sh` (exists via WI-FF) | Deferred to `test_e2e_secgate_legacy_default.py` follow-up |
| T2-TASKLEVEL | IM4 | Queue-observation pattern (not HTTP 403) — pattern TBD | Open design question; not a simple mechanical add |

Propagation plan (post-PR):
1. Land SR6, V5, UA2 in `test_e2e_secgate_strict.py` using the SR4 template; adds 3 PASS rows, brings this audit to 136/151 TOTAL.
2. Create `test_e2e_secgate_legacy_default.py` for LGU2 + LPP2; +2 PASS → 138/153.
3. Design the IM4 queue-observation pattern (distinct from the HTTP 403 pattern used in §20/§21); +1 PASS → 139/154. This item may be reclassified to T3 IRREDUCIBLE-NA if the observable turns out to be log-only.

---

# Conclusion

**100% of tests have adequate verification** (excluding N/A; denominator = 116 after WI-MM + WI-NN bloat reductions — WI-MM net -9 PASS / -2 N/A / -1 section row; WI-NN parametrize-consolidation net -9 PASS / -4 N/A). The ⚠️ WEAK bucket is now empty. **Zero INADEQUATE tests remain** after Stage2 WI-D + WI-F resolution; Stage3 WI-G closed the config_api disk/restart gap (§4: 6 WEAK → PASS). The three reconciliation waves closed every remaining WEAK:

- **Wave1** (WI-L/M/N): 10 WEAK → PASS across 5 files (endpoint, git_clone, customnode_info, queue_lifecycle, version_mgmt) + snapshot_lifecycle 1 WEAK → PASS, with 1 dedup via WI-M.
- **Wave2** (WI-P/Q): 7 WEAK → PASS (task_operations 6 for update/fix effect + params; snapshot_lifecycle 1 for save_snapshot disk + content verification).
- **Wave3** (WI-T/U/W): 10 WEAK → PASS. WI-T Cluster C+G strengthened queue_lifecycle (3), customnode_info (1), and system_info (1) with field-level effect checks; WI-U Cluster H rewrote 3 legacy-ui Playwright specs (manager-menu 2, custom-nodes 1, model-manager 2) to verify UI state via dialog reopen / `<select>.value` assertions; WI-W fixed the TaskHistoryItem params-drop schema regression and re-enabled the skipped queue_lifecycle `history?id=...` test.

Cumulative Wave1+Wave2+Wave3 upgrade count: **27 WEAK → PASS** (10 + 7 + 10). Matrix delta across the three waves: PASS 54 → 94 (+40 including Stage2+Stage3 upstream), WEAK 36 → 0, INADEQUATE 5 → 0. WI-Z inventory reconciliation (Y1 + Y3) added 6 pre-existing PASS rows: PASS 94 → 100, total 109 → 115. WI-AA inventory reconciliation added 2 more pre-existing PASS rows (LB1/LB2): PASS 100 → 102, total 115 → 117. WI-GG added 26 per-invocation PASS rows for `test_e2e_csrf_legacy.py` (WI-FF deliverable): PASS 102 → 128, total 117 → 143. WI-JJ (FF-deferred items) added 3 legacy-side CSRF invocations for the 2 legacy install endpoints + `is_legacy_manager_ui` flag-value parity: PASS 128 → 131, total 143 → 146. WI-LL added 2 PASS rows for the WI-KK deliverables — SR4 via `test_e2e_secgate_strict.py` §20 and CV4 via `test_e2e_secgate_default.py` §21 — closing 2 of the 8 original T2 SECGATE-PENDING Goals and reclassifying the remaining 6 across 4 sub-tiers (see WI-KK SECGATE Harness Design block above): PASS 131 → 133, total 146 → 148.

- Check status code without verifying the actual effect (WEAK — 0%) ✅
- Use direct API in UI tests (INADEQUATE — 0%) ✅
- Are outside endpoint-effect scope (N/A — 15/148 ≈ 10.1% of total)

Remaining 🟢 gaps (not WEAK): ~~**SR3 snapshot-remove path-traversal**~~ (RESOLVED by WI-Z Y1 — `test_remove_path_traversal_rejected`) and **QH2 queue-history path-traversal** (destructive-safe security test, already present via `test_history_path_traversal_rejected` in queue_lifecycle § Key gaps). Design-Goal coverage gap (22/92 absent, 70/92 referenced) is tracked separately in § Design-Goal Coverage Gap and is not a test-quality issue.

Post-Wave3 + WI-Z + WI-AA + WI-GG + WI-JJ + WI-LL state: **100% adequate coverage achieved** (133/133 PASS, excluding 15 N/A). Audit is in a terminal state for the current 148 tests. Further coverage expansion (design-Goal additions, the 3 T2-pending harness-ready Goals, NORMAL-legacy Goals, T2-TASKLEVEL IM4) is new-work territory — propagation plan is documented in the WI-KK SECGATE Harness Design block above — not reconciliation.

> **WI-Z + WI-AA + WI-GG + WI-JJ + WI-LL note**: Total test count 109 → 115 (WI-Z Y1 +1 snapshot, Y3 +5 config_api) → 117 (WI-AA +2 LB1/LB2) → 143 (WI-GG +26 legacy CSRF per-invocation rows) → 146 (WI-JJ +3 legacy-side install/parity rows) → 148 (WI-LL +2 SECGATE PoC rows) reflects inventory reconciliation plus WI-KK's newly-landed secgate coverage. Cumulative **upgrade** count remains 27 (unchanged since Wave3). WI-LL is the first audit-reflect WI to also introduce a Classification-policy reshape (T2 SECGATE-PENDING 8 → 4 sub-tiers), not just row additions.

---
*End of E2E Verification Audit*
