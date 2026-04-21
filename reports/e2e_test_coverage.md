# Report B — E2E Test Inventory + Coverage Mapping

**Generated**: 2026-04-18
**Source directories**:
- `tests/e2e/*.py` (pytest — HTTP + CLI E2E)
- `tests/playwright/*.spec.ts` (Playwright — legacy UI E2E)

## Summary

| Category | Files | Test Functions |
|---|---:|---:|
| pytest E2E (HTTP API) | 13 | 92 |
| pytest E2E (CLI — uv-compile) | 1 | 12 |
| Playwright (legacy UI) | 6 | 21 |
| Playwright (debug) | 1 | 1 |
| **TOTAL** | **21** | **126** |

> **Note**: +1 file / +4 functions vs prior counts reflect inclusion of `tests/e2e/test_e2e_csrf.py` (CSRF-mitigation contract suite, commit 99caef55). That suite's 4 test functions parametrize to 26 pytest invocations (13+2+11) after WI-HH removed 3 dual-purpose endpoints from the reject-GET fixture (they legitimately answer GET on the read-path and are covered only in the allow-GET class).
>
> **WI-Z Y2 sync (2026-04-19)**: Playwright legacy UI count 21 → 19 reflected Stage2 WI-F deletion of two `legacy-ui-navigation.spec.ts` tests (`API health check while dialogs are open`, `system endpoints accessible from browser context`) that were rewritten as direct-API violators; their coverage is now owned by `test_e2e_system_info.py`. TOTAL 119 → 117 was a downstream correction.
>
> **WI-AA sync (2026-04-19)**: Playwright legacy UI count 19 → 21 reflects addition of `tests/playwright/legacy-ui-install.spec.ts` (2 tests: LB1 Install button + LB2 Uninstall button) previously implemented but not inventoried. TOTAL 117 → 119. See dedicated subsection below.
>
> **WI-GG sync (2026-04-20)**: pytest E2E (HTTP API) file count 10 → 11 and function count 85 → 89 reflects addition of `tests/e2e/test_e2e_csrf_legacy.py` (4 new test functions / 26 parametrized invocations: 13 reject-GET + 2 POST-works + 11 allow-GET) from WI-FF. TOTAL 119 → 123 test functions. The legacy suite is the counterpart to `test_e2e_csrf.py` for the `--enable-manager-legacy-ui` server variant — required because `comfyui_manager/__init__.py` loads `glob.manager_server` XOR `legacy.manager_server`. See dedicated subsection below. (Accounting note: the higher-level audit `reports/e2e_verification_audit.md` Summary Matrix renders the 26 legacy invocations per-row, reaching TOTAL 143; both counts refer to the same underlying tests at different granularities — function-level here, invocation-level there.)
>
> **WI-LL sync (2026-04-20)**: pytest E2E (HTTP API) file count 11 → 13 and function count 89 → 92 reflects addition of two new SECGATE-coverage files (WI-KK deliverables, audit-integrated by WI-LL): `tests/e2e/test_e2e_secgate_strict.py` (strict-mode harness + SR4 PoC — 2 functions: `test_remove_returns_403` PASS + `test_post_works_at_default_after_restore` pytest.skip'd positive counterpart stub) + `tests/e2e/test_e2e_secgate_default.py` (default-mode demo + CV4 — 1 function: `test_switch_version_returns_403_at_default` PASS). TOTAL 123 → 126 test functions. These close 2 of the original 8 T2 SECGATE-PENDING Goals (SR4, CV4) and establish the strict-mode harness pattern (`start_comfyui_strict.sh` + config.ini backup/restore) for the remaining T2-pending-harness-ready Goals (SR6, V5, UA2). See the Classification policy block in `e2e_verification_audit.md` for the reclassification and propagation plan.

**Unique endpoints exercised**: 27 (glob v2) + 4 (legacy-only: queue/batch indirectly via UI)

---

# Section 1 — pytest E2E HTTP Tests

## tests/e2e/test_e2e_endpoint.py (7 tests)

Covers the main install/uninstall flow via `/v2/manager/queue/task` and `/v2/customnode/installed`.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestEndpointInstallUninstall::test_install_via_endpoint` | POST queue/task, POST queue/start | Install CNR pack (success) | pack dir exists + .tracking file present |
| `TestEndpointInstallUninstall::test_installed_list_shows_pack` | GET customnode/installed | Pack appears in installed list | cnr_id match in dict values |
| `TestEndpointInstallUninstall::test_uninstall_via_endpoint` | POST queue/task kind=uninstall | Uninstall success | pack dir removed from disk |
| `TestEndpointInstallUninstall::test_installed_list_after_uninstall` | GET customnode/installed | Post-uninstall state | cnr_id absent from installed list |
| `TestEndpointInstallUninstall::test_install_uninstall_cycle` | queue/task x2 | Full install→verify→uninstall cycle | All above assertions in one test |
| `TestEndpointStartup::test_comfyui_started` | GET /system_stats | Server health | 200 response |
| `TestEndpointStartup::test_startup_resolver_ran` | (log file) | UnifiedDepResolver ran at startup | log contains `[UnifiedDepResolver]` + "startup batch resolution succeeded" |

## tests/e2e/test_e2e_git_clone.py (3 tests)

Covers nightly (URL-based) install via `/v2/manager/queue/task` which triggers git_helper.py subprocess.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestNightlyInstallCycle::test_01_nightly_install` | POST queue/task selected_version=nightly | git clone via Manager API | pack dir exists + .git directory present |
| `TestNightlyInstallCycle::test_02_no_module_error` | (log file) | No ModuleNotFoundError regression | log does not contain "ModuleNotFoundError" |
| `TestNightlyInstallCycle::test_03_nightly_uninstall` | POST queue/task kind=uninstall | Uninstall nightly pack | pack dir removed |

## tests/cli/test_uv_compile.py — RELOCATED (WI-PP)

Previously tracked here as `tests/e2e/test_e2e_uv_compile.py`. Moved to
`tests/cli/` in WI-PP because every test in the suite drives cm-cli as a
subprocess; none of them exercise HTTP endpoints. The 8 tests (post
WI-MM/NN/OO consolidation) continue to cover install / reinstall (xfail-marked
for purge_node_state) / verbs-with-uv-compile (parametrized ×5) / uv-sync
no-packs-exits-zero / no-packs-emits-signal / with-packs / conflict
attribution with specs. CI runner updated in `.github/workflows/e2e.yml` to
point at the new path.

## tests/e2e/test_e2e_config_api.py (10 tests)

Covers GET/POST round-trip on configuration endpoints.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestConfigDbMode::test_read_db_mode` | GET db_mode | Read current value | text in {cache, channel, local, remote} |
| `TestConfigDbMode::test_set_and_restore_db_mode` | GET/POST db_mode | Set→read-back→restore | POST 200 + verify echo + restore verified |
| `TestConfigDbMode::test_set_db_mode_invalid_body` | POST db_mode | Malformed JSON | 400 |
| `TestConfigUpdatePolicy::test_read_update_policy` | GET policy/update | Read current policy | text in {stable, stable-comfyui, nightly, nightly-comfyui} |
| `TestConfigUpdatePolicy::test_set_and_restore_update_policy` | GET/POST policy/update | Set→read-back→restore | Round-trip verification |
| `TestConfigUpdatePolicy::test_set_policy_invalid_body` | POST policy/update | Malformed JSON | 400 |
| `TestConfigChannelUrlList::test_read_channel_url_list` | GET channel_url_list | Response shape | has `selected` (str) + `list` (array) |
| `TestConfigChannelUrlList::test_channel_list_entries_are_name_url_strings` | GET channel_url_list | Entry format | each entry is "name::url" string |
| `TestConfigChannelUrlList::test_set_and_restore_channel` | GET/POST channel_url_list | Switch channel + restore | Verify `selected` matches set value |
| `TestConfigChannelUrlList::test_set_channel_invalid_body` | POST channel_url_list | Malformed JSON | 400 |

## tests/e2e/test_e2e_customnode_info.py (11 tests)

Covers custom node info/mapping endpoints.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestCustomNodeMappings::test_getmappings_returns_dict` | GET customnode/getmappings?mode=local | Success response | 200 + dict |
| `TestCustomNodeMappings::test_getmappings_entries_have_node_lists` | GET getmappings | Entry structure | each value is `[node_list, metadata]` |
| `TestFetchUpdates::test_fetch_updates_returns_deprecated` | GET customnode/fetch_updates | Deprecated endpoint | 410 + `deprecated: true` |
| `TestInstalledPacks::test_installed_returns_dict` | GET customnode/installed | Success | 200 + dict |
| `TestInstalledPacks::test_installed_imported_mode` | GET installed?mode=imported | Startup snapshot | 200 + dict |
| `TestImportFailInfo::test_unknown_cnr_id_returns_400` | POST import_fail_info | Unknown pack | 400 |
| `TestImportFailInfo::test_missing_fields_returns_400` | POST import_fail_info | Missing cnr_id+url | 400 |
| `TestImportFailInfo::test_invalid_body_returns_error` | POST import_fail_info | Non-dict body | 400 |
| `TestImportFailInfoBulk::test_bulk_with_cnr_ids_returns_dict` | POST import_fail_info_bulk | cnr_ids list | 200 + null for unknown |
| `TestImportFailInfoBulk::test_bulk_empty_lists_returns_400` | POST import_fail_info_bulk | Empty cnr_ids+urls | 400 |
| `TestImportFailInfoBulk::test_bulk_with_urls_returns_dict` | POST import_fail_info_bulk | urls list | 200 + dict |

## tests/e2e/test_e2e_queue_lifecycle.py (9 tests)

Covers the queue management lifecycle.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestQueueLifecycle::test_reset_queue` | POST queue/reset | Empty the queue | 200 |
| `TestQueueLifecycle::test_status_after_reset` | GET queue/status | Post-reset state | all counts 0, is_processing bool |
| `TestQueueLifecycle::test_status_with_client_id_filter` | GET queue/status?client_id=X | Client filter | response echoes client_id |
| `TestQueueLifecycle::test_start_queue_already_idle` | POST queue/start | Idle worker start | status in {200, 201} |
| `TestQueueLifecycle::test_queue_task_and_history` | POST queue/task + queue/start + GET queue/status + GET queue/history | Full lifecycle | done_count>0 polled, history 200 or 400 |
| `TestQueueLifecycle::test_history_with_ui_id_filter` | GET queue/history?ui_id=X | Filter history | 200 or 400 (serialization-limit) |
| `TestQueueLifecycle::test_history_with_pagination` | GET queue/history?max_items=1&offset=0 | Pagination | 200 or 400 |
| `TestQueueLifecycle::test_history_list` | GET queue/history_list | List batch IDs | 200 + `ids` list |
| `TestQueueLifecycle::test_final_reset_and_clean_state` | POST queue/reset + GET queue/status | Cleanup | pending_count==0 |

## tests/e2e/test_e2e_snapshot_lifecycle.py (7 tests)

Covers snapshot save/list/remove cycle.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestSnapshotLifecycle::test_get_current_snapshot` | GET snapshot/get_current | Current state dict | 200 + dict |
| `TestSnapshotLifecycle::test_save_snapshot` | POST snapshot/save | Save new snapshot | 200 |
| `TestSnapshotLifecycle::test_getlist_after_save` | GET snapshot/getlist | List contains new snapshot | items.length > 0 |
| `TestSnapshotLifecycle::test_remove_snapshot` | POST snapshot/remove?target=X + GET getlist | Remove + verify | target absent + count decremented |
| `TestSnapshotLifecycle::test_remove_nonexistent_snapshot` | POST snapshot/remove | Nonexistent target | 200 (no-op) |
| `TestSnapshotLifecycle::test_remove_path_traversal_rejected` | POST snapshot/remove?target=../... | Path-traversal targets must be rejected | 400 + sentinel file outside snapshot dir preserved (SR3) |
| `TestSnapshotGetCurrentSchema::test_getlist_items_are_strings` | GET snapshot/getlist | Items shape | each item is string |

> Note: `POST /v2/snapshot/restore` intentionally NOT tested (destructive).

## tests/e2e/test_e2e_system_info.py (4 tests)

Covers system-level endpoints (version, legacy UI flag, reboot).

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestManagerVersion::test_version_returns_string` | GET manager/version | Non-empty string | 200 + len>0 |
| `TestManagerVersion::test_version_is_stable` | GET manager/version x2 | Idempotency | consecutive calls return same value |
| `TestIsLegacyManagerUI::test_returns_boolean_field` | GET is_legacy_manager_ui | Response shape | `{is_legacy_manager_ui: bool}` |
| `TestReboot::test_reboot_and_recovery` | POST manager/reboot + GET version | Restart + recovery | 200 or 403 (security); server polls healthy; version unchanged |

## tests/e2e/test_e2e_task_operations.py (16 tests)

Covers queue/task operations for kinds NOT tested in test_e2e_endpoint.py.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestDisableEnable::test_disable_pack` | POST queue/task kind=disable | Disable moves pack to .disabled/ | pack dir gone + .disabled/ entry present |
| `TestDisableEnable::test_enable_pack` | POST queue/task kind=enable | Enable restores pack | pack dir present + .disabled/ entry gone |
| `TestDisableEnable::test_disable_enable_cycle` | queue/task x2 | Full disable→enable | Both transitions verified |
| `TestUpdatePack::test_update_installed_pack` | POST queue/task kind=update | Update pack | pack still exists after update |
| `TestUpdatePack::test_update_history_recorded` | GET queue/history?ui_id=X | History has update entry | 200 or 400 (serialization-limit) |
| `TestFixPack::test_fix_installed_pack` | POST queue/task kind=fix | Fix pack | pack still exists |
| `TestFixPack::test_fix_history_recorded` | GET queue/history?ui_id=X | History has fix entry | 200 or 400 |
| `TestInstallModel::test_install_model_accepts_valid_request` | POST queue/install_model | Valid model request | 200 (reset queue after) |
| `TestInstallModel::test_install_model_missing_client_id` | POST queue/install_model | Missing client_id | 400 |
| `TestInstallModel::test_install_model_missing_ui_id` | POST queue/install_model | Missing ui_id | 400 |
| `TestInstallModel::test_install_model_invalid_body` | POST queue/install_model | Invalid metadata | 400 |
| `TestUpdateAll::test_update_all_queues_tasks` | POST queue/update_all | Queue all update tasks | 200/403 or tolerated ReadTimeout |
| `TestUpdateAll::test_update_all_missing_params` | POST queue/update_all | Missing params | 400 ValidationError |
| `TestUpdateComfyUI::test_update_comfyui_queues_task` | POST queue/update_comfyui | Queue task | 200 + total_count>=1 after |
| `TestUpdateComfyUI::test_update_comfyui_missing_params` | POST queue/update_comfyui | Missing params | 400 |
| `TestUpdateComfyUI::test_update_comfyui_with_stable_flag` | POST queue/update_comfyui?stable=true | Explicit stable flag | 200 |

## tests/e2e/test_e2e_version_mgmt.py (7 tests)

Covers comfyui_versions + comfyui_switch_version endpoints.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestComfyUIVersions::test_versions_endpoint` | GET comfyui_versions | Response shape | `{versions: list, current: str}` |
| `TestComfyUIVersions::test_versions_list_not_empty` | GET comfyui_versions | Non-empty list | len>0 |
| `TestComfyUIVersions::test_versions_items_are_strings` | GET comfyui_versions | Item type | each version is string |
| `TestComfyUIVersions::test_current_is_in_versions` | GET comfyui_versions | Current in list | current appears in versions |
| `TestSwitchVersionNegative::test_switch_version_missing_all_params` | POST comfyui_switch_version | No params | 400 or 403 |
| `TestSwitchVersionNegative::test_switch_version_missing_client_id` | POST comfyui_switch_version?ver=X | Partial params | 400 or 403 |
| `TestSwitchVersionNegative::test_switch_version_validation_error_body` | POST comfyui_switch_version | Error body shape | `error` field present (when 400 JSON) |

> Note: Actual version switching (destructive) intentionally NOT tested.

---

## tests/e2e/test_e2e_csrf.py (4 test functions / 26 parametrized invocations — post-WI-HH)

Covers the CSRF-mitigation contract from commit 99caef55 — state-changing
endpoints must reject HTTP GET so that `<img src>` / link-click /
redirect-based cross-origin triggers cannot mutate server state.

**Scope (per docstring)**: ONLY the GET-rejection contract. NOT covered
here: Origin/Referer validation (separate middleware), same-site cookies,
anti-CSRF tokens, cross-site form POST.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestStateChangingEndpointsRejectGet::test_get_is_rejected[path]` | 13 POST endpoints (queue/start, queue/reset, queue/update_all, queue/update_comfyui, queue/install_model, queue/task, snapshot/save, snapshot/remove, snapshot/restore, manager/reboot, comfyui_switch_version, import_fail_info, import_fail_info_bulk — WI-HH removed db_mode, policy/update, channel_url_list from this list since they legitimately answer GET on the read-path) | GET must reject | status_code in (400,403,404,405); explicit `not in 200-399` guard |
| `TestCsrfPostWorks::test_queue_reset_post_works` | POST queue/reset | POST counterpart works | status_code == 200 |
| `TestCsrfPostWorks::test_snapshot_save_post_works` | POST snapshot/save + cleanup via getlist+remove | POST counterpart works | status_code == 200; cleanup |
| `TestCsrfReadEndpointsStillAllowGet::test_get_read_endpoint_succeeds[path]` | 11 GET endpoints (version, db_mode, policy/update, channel_url_list, queue/status, queue/history_list, is_legacy_manager_ui, customnode/installed, snapshot/getlist, snapshot/get_current, comfyui_versions) | Negative control: read-only still works | status_code == 200 |

> Note: Three endpoints (`db_mode`, `policy/update`, `channel_url_list`) appear in BOTH reject-GET (POST path, write) and allow-GET (read path) lists — commit 99caef55 split each into a GET-read + POST-write pair; the POST path must reject GET while the GET path must continue to succeed.

---

## tests/e2e/test_e2e_csrf_legacy.py (4 test functions / 26 parametrized invocations)

Legacy-mode counterpart to `test_e2e_csrf.py`. Verifies the same CSRF
method-rejection contract but against the legacy server module loaded
via `--enable-manager-legacy-ui`. Added in WI-FF (commit following
99caef55) to close the legacy-side regression-guard gap. Audit-integrated
in WI-GG.

**Why a separate file** (per docstring L7–13): `comfyui_manager/__init__.py`
loads `glob.manager_server` XOR `legacy.manager_server` via mutex on the
`--enable-manager-legacy-ui` flag. One ComfyUI process exposes either the
glob or the legacy route table, never both — so verifying the legacy
CSRF contract requires its own module-scoped server lifecycle with the
legacy flag set (via `start_comfyui_legacy.sh`).

**Scope (per docstring L44–48)**: Same as `test_e2e_csrf.py` — ONLY the
method-reject layer. Origin/Referer, same-site cookies, anti-CSRF tokens,
and cross-site form POST are out of scope.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestLegacyStateChangingEndpointsRejectGet::test_get_is_rejected[path]` | 13 POST endpoints (queue/start, queue/reset, queue/update_all, queue/update_comfyui, queue/install_model, **queue/batch** (legacy; replaces queue/task), snapshot/save, snapshot/remove, snapshot/restore, manager/reboot, comfyui_switch_version, import_fail_info, import_fail_info_bulk) | GET must reject under legacy server | status_code in (400,403,404,405); explicit `not in 200-399` guard |
| `TestLegacyCsrfPostWorks::test_queue_reset_post_works` | POST queue/reset (legacy) | POST counterpart works under legacy server | status_code == 200 |
| `TestLegacyCsrfPostWorks::test_snapshot_save_post_works` | POST snapshot/save + cleanup via getlist+remove (legacy) | POST counterpart works + cleanup | status_code == 200; cleanup |
| `TestLegacyCsrfReadEndpointsStillAllowGet::test_get_read_endpoint_succeeds[path]` | 11 GET endpoints (version, db_mode, policy/update, channel_url_list, queue/status, queue/history_list, is_legacy_manager_ui, customnode/installed, snapshot/getlist, snapshot/get_current, comfyui_versions) | Negative control: legacy read-only still works | status_code == 200 |

> **Endpoint-list deltas vs glob** (per docstring L23–36):
> - `queue/task` → dropped (glob-only); `queue/batch` → added (legacy task-enqueue equivalent)
> - `db_mode`, `policy/update`, `channel_url_list` → dropped from reject-GET (CSRF contract applies only to the POST write-path; legacy splits these into `@routes.get` read + `@routes.post` write, identical to glob). These 3 remain in the ALLOW-GET class above. (The glob `test_e2e_csrf.py` lists them in BOTH classes; WI-HH tracks the glob-side correction.)

---

## tests/e2e/test_e2e_secgate_strict.py (1 test active + 1 skipped; WI-KK PoC, WI-LL audit-integrated)

Strict-mode security-gate PoC. Covers the middle/middle+ gate 403 contract for
Goals that require elevating `security_level=strong`. Launches via
`start_comfyui_strict.sh` (which patches `user/__manager/config.ini` to
`security_level=strong`, leaves a `.before-strict` backup, and starts the server
on the E2E port) and restores the original config in the fixture teardown.

**Scope (per docstring L3–9)**: strict-mode 403 path for the middle/middle+
gates. The default E2E config (`security_level=normal`, `is_local_mode=True`)
puts NORMAL inside the allowed set for both gates per
`comfyui_manager/glob/utils/security_utils.py` L32–38, so this harness is the
only way to exercise the 403 side. This is the first of 4 planned Goals
(SR4 ← here; SR6, V5, UA2 ← mechanical additions using the same fixture).

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestSecurityGate403_SR4::test_remove_returns_403` | POST `/v2/snapshot/remove?target=…` (under security_level=strong) | Goal SR4 — snapshot/remove below `middle` | (a) `status_code == 403`; (b) the seeded snapshot file on disk is NOT deleted (negative-check per `verification_design.md` §7.3 Security Boundary Template). |
| `TestSecurityGate403_SR4::test_post_works_at_default_after_restore` | (none — pytest.skip) | Positive counterpart of SR4 at default config | pytest.skip'd: deferred to `test_e2e_secgate_default.py` follow-up to avoid double-startup cost. Documents both halves of the gate contract. |

**Harness notes**:
- **Teardown ordering** is contract-critical: stop server FIRST, then restore config (the server holds the config-file lock; restoring before stopping causes a re-snapshot race). Documented in the fixture's `finally` block.
- Subsequent test modules continue to see `security_level=normal` because the backup restore happens deterministically in teardown.

## tests/e2e/test_e2e_secgate_default.py (1 test; WI-KK demo, WI-LL audit-integrated)

Default-mode security-gate demonstration. Covers the CV4 Goal (comfyui_switch_version
`high+` gate 403 contract) without any harness, leveraging the WI-KK research
finding that default `security_level=normal` + `is_local_mode=True` already
triggers 403 for high+ operations at the HTTP handler. This is the cleanest of
the 4 originally-classified-T2 high+ Goals to demonstrate the no-harness-needed
insight.

**Scope (per docstring L1–18)**: only the CV4 Goal. The other 3 originally-T2
high+ Goals are deferred with reclassification notes:
- **IM4** → **T2-TASKLEVEL**: non-safetensors check lives deep in the install pipeline (worker + `get_risky_level`), not at the HTTP handler. POST `/v2/manager/queue/install_model` accepts the request and queues a task; rejection only surfaces at task execution. Requires a queue-observation pattern, not a simple HTTP 403 check.
- **LGU2**, **LPP2** → **NORMAL-legacy**: registered ONLY in `legacy/manager_server.py` (L1502, L1522). Testing needs `start_comfyui_legacy.sh` fixture — follow-up `test_e2e_secgate_legacy_default.py` is the natural home.

| Test | Endpoint(s) | Scenario | Assertion semantics |
|---|---|---|---|
| `TestSecurityGate403_CV4::test_switch_version_returns_403_at_default` | POST `/v2/comfyui_manager/comfyui_switch_version` with `ver`, `client_id`, `ui_id` (at default security_level) | Goal CV4 — comfyui_switch_version below `high+` | `status_code == 403`. The `ver` query is syntactically valid so the request WOULD reach the Pydantic validation step IF the gate were broken; since the gate is the FIRST check in the handler, 403 must precede any 400-from-validation outcome. |

---

# Section 2 — Playwright UI Tests

All Playwright tests require ComfyUI running with `--enable-manager-legacy-ui` on PORT (default 8199).

## tests/playwright/legacy-ui-manager-menu.spec.ts (5 tests)

Covers the Manager Menu dialog and its settings dropdowns.

| Test | Endpoint(s) exercised | Scenario | Assertion semantics |
|---|---|---|---|
| `Manager Menu Dialog > opens via Manager button and shows 3-column layout` | (indirect: initial page + legacy UI detection) | Menu dialog opens | `#cm-manager-dialog` visible; "Custom Nodes Manager", "Model Manager", "Restart" buttons present |
| `> shows settings dropdowns (DB, Channel, Policy)` | (UI) | DB + Policy combos render | Both `<select>` elements visible |
| `> DB mode dropdown round-trips via API` | GET/POST db_mode | UI dropdown change → backend persists | selectOption → verify via GET → restore |
| `> Update Policy dropdown round-trips via API` | GET/POST policy/update | Policy change via UI | selectOption → verify GET → restore |
| `> closes and reopens without duplicating` | (UI only) | Dialog lifecycle | No duplicate dialog instances |

## tests/playwright/legacy-ui-custom-nodes.spec.ts (5 tests)

Covers the Custom Nodes Manager dialog (TurboGrid-based list).

| Test | Endpoint(s) exercised | Scenario | Assertion semantics |
|---|---|---|---|
| `Custom Nodes Manager > opens from Manager menu and renders grid` | GET customnode/getlist (legacy), customnode/getmappings | Grid render | `#cn-manager-dialog` + `.tg-body` visible |
| `> loads custom node list (non-empty)` | GET customnode/getlist | Data load | rows > 0 after polling |
| `> filter dropdown changes displayed nodes` | (client-side filter) | "Installed" filter | filtered count ≤ initial count |
| `> search input filters the grid` | (client-side filter) | Search term | filtered count ≤ initial |
| `> footer buttons are present` | (UI) | Install via Git URL / Restart buttons | At least one present |

## tests/playwright/legacy-ui-model-manager.spec.ts (4 tests)

Covers Model Manager dialog.

| Test | Endpoint(s) exercised | Scenario | Assertion semantics |
|---|---|---|---|
| `Model Manager > opens from Manager menu and renders grid` | GET externalmodel/getlist (legacy) | Grid render | `#cmm-manager-dialog` + grid visible |
| `> loads model list (non-empty)` | GET externalmodel/getlist | Data load | rows > 0 |
| `> search input filters the model grid` | (client-side filter) | Search | filtered ≤ initial |
| `> filter dropdown is present with expected options` | (UI) | Filter options | options.length > 0 |

## tests/playwright/legacy-ui-snapshot.spec.ts (3 tests)

Covers Snapshot Manager dialog.

| Test | Endpoint(s) exercised | Scenario | Assertion semantics |
|---|---|---|---|
| `Snapshot Manager > opens snapshot manager from Manager menu` | (UI) | Dialog opens | `#snapshot-manager-dialog` present |
| `> lists existing snapshots` | GET snapshot/getlist | List loads | resp.ok + `items` property |
| `> save snapshot via API and verify in list` | POST snapshot/save + GET snapshot/getlist + POST snapshot/remove | Save→verify→cleanup | items.length > 0 after save; remove cleanup |

## tests/playwright/legacy-ui-navigation.spec.ts (2 tests)

Covers dialog navigation lifecycle. Stage2 WI-F deleted two prior tests (`API health check while dialogs are open`, `system endpoints accessible from browser context`) because they exercised `page.request.*` direct API calls with no real UI interaction — coverage is now owned by `test_e2e_system_info.py::test_version_*` and related pytest suites.

| Test | Endpoint(s) exercised | Scenario | Assertion semantics |
|---|---|---|---|
| `Dialog Navigation > Manager menu → Custom Nodes → close → Manager still visible` | (UI) | Nested dialog navigation | Manager menu reopens after child close |
| `> Manager menu → Model Manager → close → reopen` | (UI) | Close and reopen Model Manager | Dialog reappears |

## tests/playwright/legacy-ui-install.spec.ts (2 tests)

Covers UI-driven install/uninstall effect verification against the test pack `ComfyUI_SigmoidOffsetScheduler`. Primary action is always a UI button click; `page.request` is used only for setup (queue/reset baseline, optional API pre-install in LB2) and effect-observation (queue/status polling, installed-list lookup) — consistent with the hybrid UI-action + backend-effect pattern in `legacy-ui-snapshot.spec.ts::SS1`.

| Test | Endpoint(s) exercised | Scenario | Assertion semantics |
|---|---|---|---|
| `UI-driven install/uninstall > LB1 Install button triggers install effect` | (UI) Custom Nodes Manager dialog → filter "Not Installed" → search pack → row Install button → version "Select" button; GET /v2/manager/queue/status (effect polling), GET /v2/customnode/installed (effect verification) | User initiates install from Custom Nodes dialog | `isPackInstalled === true` after queue drains via `waitForAllDone` |
| `UI-driven install/uninstall > LB2 Uninstall button triggers uninstall effect` | (UI) Custom Nodes Manager dialog → filter "Installed" → search pack → row Uninstall button → optional confirm dialog; GET /v2/manager/queue/status, GET /v2/customnode/installed | User initiates uninstall from Custom Nodes dialog (preconditioned by API install if pack absent) | `isPackInstalled === false` after queue drains |

## tests/playwright/debug-install-flow.spec.ts (1 test)

Debug/instrumentation test — captures the install API flow for documentation.

| Test | Endpoint(s) exercised | Scenario | Assertion semantics |
|---|---|---|---|
| `capture install button API flow` | GET customnode/getlist, POST queue/batch (legacy), GET customnode/versions/{id}, WebSocket cm-queue-status | End-to-end install UI flow capture | No assertions — logs API sequence + WebSocket frames for manual review |

---

# Section 3 — Endpoint Coverage Summary

## Glob v2 endpoints covered (27/30)

| Endpoint | Covered by |
|---|---|
| POST queue/task (install) | test_e2e_endpoint, test_e2e_git_clone, test_e2e_task_operations |
| POST queue/task (update/fix/disable/enable/uninstall) | test_e2e_endpoint, test_e2e_task_operations |
| GET queue/history_list | test_e2e_queue_lifecycle |
| GET queue/history | test_e2e_queue_lifecycle, test_e2e_task_operations |
| GET customnode/getmappings | test_e2e_customnode_info |
| GET customnode/fetch_updates | test_e2e_customnode_info (deprecated 410) |
| POST queue/update_all | test_e2e_task_operations |
| GET is_legacy_manager_ui | test_e2e_system_info, playwright legacy-ui-navigation |
| GET customnode/installed | test_e2e_endpoint, test_e2e_customnode_info |
| GET snapshot/getlist | test_e2e_snapshot_lifecycle, playwright legacy-ui-snapshot |
| POST snapshot/remove | test_e2e_snapshot_lifecycle |
| GET snapshot/get_current | test_e2e_snapshot_lifecycle |
| POST snapshot/save | test_e2e_snapshot_lifecycle, playwright legacy-ui-snapshot |
| POST customnode/import_fail_info | test_e2e_customnode_info |
| POST customnode/import_fail_info_bulk | test_e2e_customnode_info |
| POST queue/reset | test_e2e_queue_lifecycle, test_e2e_task_operations |
| GET queue/status | test_e2e_queue_lifecycle, test_e2e_task_operations |
| POST queue/start | test_e2e_endpoint, test_e2e_task_operations |
| POST queue/update_comfyui | test_e2e_task_operations |
| GET comfyui_versions | test_e2e_version_mgmt |
| POST comfyui_switch_version | test_e2e_version_mgmt (negative only) |
| POST queue/install_model | test_e2e_task_operations |
| GET/POST db_mode | test_e2e_config_api, playwright legacy-ui-manager-menu |
| GET/POST policy/update | test_e2e_config_api, playwright legacy-ui-manager-menu |
| GET/POST channel_url_list | test_e2e_config_api |
| POST manager/reboot | test_e2e_system_info |
| GET manager/version | test_e2e_system_info, playwright legacy-ui-navigation |

## CSRF Method-Reject Contract

Separate from the positive-path coverage above, the 16 state-changing POST
endpoints (glob) + 13 (legacy, with queue/batch substitution) plus 11
read-only GET endpoints per server are independently verified for their
CSRF-mitigation contract (commit 99caef55, CVSS 8.1). Coverage is split
across two files because server loading is mutex on `--enable-manager-legacy-ui`:

**Glob server** — `tests/e2e/test_e2e_csrf.py`:

| Contract | Tests | Coverage |
|---|---|---|
| 13 POST endpoints must reject HTTP GET (glob; post-WI-HH) | TestStateChangingEndpointsRejectGet (parametrized ×13) | ✓ full |
| POST counterparts must work (glob sanity) | TestCsrfPostWorks (queue/reset, snapshot/save) | ~ spot-check |
| 11 read-only GET endpoints must still allow GET (glob negative control) | TestCsrfReadEndpointsStillAllowGet (parametrized ×11) | ✓ full |

**Legacy server** (WI-FF) — `tests/e2e/test_e2e_csrf_legacy.py`:

| Contract | Tests | Coverage |
|---|---|---|
| 13 POST endpoints must reject HTTP GET (legacy; queue/task→queue/batch; dual-purpose endpoints scoped to ALLOW-GET only) | TestLegacyStateChangingEndpointsRejectGet (parametrized ×13) | ✓ full |
| POST counterparts must work (legacy sanity) | TestLegacyCsrfPostWorks (queue/reset, snapshot/save) | ~ spot-check |
| 11 read-only GET endpoints must still allow GET (legacy negative control) | TestLegacyCsrfReadEndpointsStillAllowGet (parametrized ×11) | ✓ full |

Note: this contract is NEGATIVE-assertion (must-reject) + negative-control.
Do NOT interpret CSRF-suite PASS as "CSRF fully solved" — both suites
explicitly scope themselves to the method-conversion layer only. The
legacy suite closes the gap where a reverted `@routes.post` → `@routes.get`
in `legacy/manager_server.py` would have slipped past CI.

## Glob v2 endpoints NOT covered

| Endpoint | Reason |
|---|---|
| POST snapshot/restore | Intentionally skipped (destructive — alters node state) |
| POST comfyui_switch_version (positive) | Intentionally skipped (destructive — alters ComfyUI version) |
| (none otherwise missing) | — |

## Legacy-only endpoints covered

| Endpoint | Covered by |
|---|---|
| POST queue/batch | playwright debug-install-flow (indirect — triggered via Install UI) |
| GET customnode/getlist | playwright legacy-ui-custom-nodes (indirect) |
| GET externalmodel/getlist | playwright legacy-ui-model-manager (indirect) |

## Legacy-only endpoints NOT covered

| Endpoint | Reason |
|---|---|
| GET /customnode/alternatives | Not invoked by legacy UI flows tested |
| GET customnode/versions/{node_name} | Tested indirectly via install version dialog (debug-install-flow) but no direct assertion |
| GET customnode/disabled_versions/{node_name} | No direct test |
| POST customnode/install/git_url | High+ security, destructive; not in UI flow |
| POST customnode/install/pip | High+ security, destructive |
| GET manager/notice | Removed in recent work; legacy only |

---
*End of Report B*
