# Verification Design — Per-Goal Verification Items

**Generated**: 2026-04-18
**Source**: Derived from `endpoint_scenarios.md`, `scenario_intents.md`, `scenario_effects.md`
**Purpose**: For each scenario's achievement goal, design the concrete verification items (assertions + observables + tools) required to prove the goal is met.

**Verification item format** (used throughout):
```
Goal: <what scenario intends to achieve>
Precondition: <state required before the action>
Action: <call / UI interaction>
Observable: <what can be inspected>
Assertion: <pass/fail criterion>
Negative check: <what must NOT happen>
```

---

# Section 1 — Queue Management Verification Design

## 1.1 POST /v2/manager/queue/task (kind=install)

### Goal A1 — Install a CNR pack to loadable state
- **Precondition**: pack dir absent; `.tracking` absent
- **Action**: POST queue/task kind=install params={id, version, selected_version, mode, channel} → POST queue/start
- **Observable**: filesystem `custom_nodes/<pack>/` + `.tracking` file content; `customnode/installed` response; WebSocket `cm-queue-status all-done`
- **Assertion**: pack dir exists AND `.tracking` present AND `installed[pack_id].cnr_id == pack_id` AND version matches
- **Negative check**: no leftover `.trash_*` dirs; no ModuleNotFoundError in server log

### Goal A2 — Install a nightly (URL) pack via git clone
- **Precondition**: pack dir absent
- **Action**: POST queue/task kind=install selected_version=nightly with `repository` URL
- **Observable**: pack dir + `.git/` subdir; `.git/config` remote URL
- **Assertion**: `.git` exists AND remote URL matches request
- **Negative check**: no ModuleNotFoundError (git_helper.py subprocess ran cleanly)

### Goal A3 — Skip install when already disabled (re-enable shortcut)
- **Precondition**: pack in `.disabled/`
- **Action**: POST queue/task kind=install params.skip_post_install=true for known cnr_id
- **Observable**: pack moved back to active custom_nodes/; no fresh clone
- **Assertion**: pack active + no new download; existing `.tracking` preserved
- **Negative check**: no re-download (verify via timing or lack of network log)

### Goal A4 — Reject bad kind (validation error)
- **Precondition**: queue empty or known state
- **Action**: POST queue/task with kind="garbage"
- **Observable**: response status; `queue/status.total_count` before/after
- **Assertion**: 400 + ValidationError text; total_count unchanged
- **Negative check**: no pack changes; no task in history

### Goal A5 — Reject missing ui_id/client_id (traceability gate)
- **Action**: POST queue/task without ui_id OR without client_id
- **Assertion**: 400; no task queued (verify via status counts)

### Goal A6 — Worker auto-starts on task queue
- **Precondition**: worker idle
- **Action**: POST queue/task (any valid)
- **Observable**: `queue/status.is_processing` polling
- **Assertion**: within N seconds is_processing becomes true; eventually done_count increments

## 1.2 POST /v2/manager/queue/task (kind=uninstall)

### Goal U1 — Remove installed pack
- **Precondition**: pack present; in `installed` list
- **Action**: POST queue/task kind=uninstall params.node_name=<cnr_id>
- **Observable**: filesystem pack dir; `customnode/installed`
- **Assertion**: pack dir absent AND cnr_id absent from installed
- **Negative check**: other packs untouched; no orphan files in .disabled/

### Goal U2 — Idempotent uninstall of missing pack
- **Precondition**: pack absent
- **Action**: POST queue/task kind=uninstall for non-existent pack
- **Assertion**: task completes without raising fatal error; state unchanged

## 1.3 POST /v2/manager/queue/task (kind=update)

### Goal UP1 — Upgrade pack to newer version
- **Precondition**: pack installed at version X; version Y > X available
- **Action**: POST queue/task kind=update params.node_name, node_ver
- **Observable**: `.tracking` file content (version field); CNR API version
- **Assertion**: pack still present; new version recorded; dependencies updated
- **Negative check**: no partial state (no half-cloned dir)

### Goal UP2 — Idempotent when already up-to-date
- **Precondition**: pack at latest version
- **Action**: POST queue/task kind=update
- **Assertion**: no version downgrade; no pack removal; task completes

## 1.4 POST /v2/manager/queue/task (kind=fix)

### Goal F1 — Reinstall dependencies of existing pack
- **Precondition**: pack present; dependencies broken (simulate by removing from venv)
- **Action**: POST queue/task kind=fix params.node_name, node_ver
- **Observable**: venv site-packages for pack's requirements; import succeeds
- **Assertion**: after fix, all declared requirements importable; pack dir unchanged (same HEAD)

## 1.5 POST /v2/manager/queue/task (kind=disable)

### Goal D1 — Move pack to disabled state reversibly
- **Precondition**: pack active
- **Action**: POST queue/task kind=disable params.node_name, is_unknown
- **Observable**: `custom_nodes/.disabled/<pack>/` exists; `custom_nodes/<pack>/` absent
- **Assertion**: pack relocated to .disabled/; not in active installed list; on reload NODE_CLASS_MAPPINGS lacks its nodes
- **Negative check**: pack files preserved (not deleted)

### Goal D2 — Idempotent disable of already-disabled pack
- **Precondition**: pack in .disabled/
- **Action**: POST queue/task kind=disable
- **Assertion**: pack still in .disabled/; no duplicate; no error

## 1.6 POST /v2/manager/queue/task (kind=enable)

### Goal E1 — Restore pack from .disabled/ to active
- **Precondition**: pack in .disabled/
- **Action**: POST queue/task kind=enable params.cnr_id
- **Observable**: `custom_nodes/<pack>/` exists (may be lowercase variant); .disabled/ entry gone
- **Assertion**: pack active; appears in installed; on next reload nodes load
- **Negative check**: no duplicate entries

## 1.7 POST /v2/manager/queue/install_model

### Goal IM1 — Download model to correct subdirectory
- **Precondition**: model file absent; URL in whitelist
- **Action**: POST queue/install_model with valid ModelMetadata + client_id + ui_id
- **Observable**: `models/<type>/<filename>` file; file size > 0
- **Assertion**: file exists + non-zero size; externalmodel/getlist shows installed=True
- **Negative check**: no orphan partial downloads

### Goal IM2 — Reject missing client_id / ui_id
- **Action**: POST install_model without one of them
- **Assertion**: 400; no task queued; no download attempted

### Goal IM3 — Reject non-whitelist URL (legacy)
- **Action**: POST install_model with URL NOT in whitelist
- **Assertion**: 400; no file written

### Goal IM4 — Block non-safetensors below high+ security
- **Precondition**: security_level < high+
- **Action**: POST install_model with filename="*.ckpt"
- **Assertion**: 403; no file written

## 1.8 POST /v2/manager/queue/update_all

### Goal UA1 — Queue update tasks for all active packs
- **Precondition**: N active packs installed; queue empty
- **Action**: POST queue/update_all with ui_id, client_id, mode
- **Observable**: `queue/status.pending_count` delta
- **Assertion**: pending_count increased by N (minus manager-skip if desktop); each queued task has kind=update + correct node_name
- **Negative check**: comfyui-manager NOT in queue if __COMFYUI_DESKTOP_VERSION__ set

### Goal UA2 — Security gate (<middle+)
- **Precondition**: security_level < middle+
- **Action**: POST queue/update_all
- **Assertion**: 403; no tasks queued

### Goal UA3 — Require ui_id + client_id
- **Action**: POST queue/update_all without required params
- **Assertion**: 400 ValidationError; no queue change

## 1.9 POST /v2/manager/queue/update_comfyui

### Goal UC1 — Queue ComfyUI self-update task
- **Action**: POST queue/update_comfyui with client_id, ui_id
- **Observable**: queue/status.total_count; queued task's params
- **Assertion**: total_count += 1; queued task has kind=update-comfyui with is_stable matching config or override
- **Negative check**: actual git operation doesn't start (task queued only)

### Goal UC2 — Explicit stable flag override
- **Action**: POST queue/update_comfyui?stable=true (config says nightly)
- **Assertion**: queued task.params.is_stable == true

## 1.10 POST /v2/manager/queue/reset

### Goal R1 — Clear all queued/running/history tasks
- **Precondition**: queue has N tasks
- **Action**: POST queue/reset
- **Observable**: queue/status all counts
- **Assertion**: total_count=done_count=in_progress_count=pending_count=0; is_processing=false
- **Negative check**: history tasks also cleared

### Goal R2 — Idempotent on empty queue
- **Precondition**: queue empty
- **Action**: POST queue/reset (2 times)
- **Assertion**: 200 both times; state still empty

## 1.11 POST /v2/manager/queue/start

### Goal S1 — Start worker when idle
- **Precondition**: is_processing=false; queue has tasks
- **Action**: POST queue/start
- **Assertion**: 200; is_processing=true; tasks begin processing (done_count eventually increments)

### Goal S2 — Don't spawn duplicate worker
- **Precondition**: is_processing=true
- **Action**: POST queue/start
- **Assertion**: 201; still is_processing=true; same worker pid (observable via logs)
- **Negative check**: no duplicate task processing (each task runs once)

## 1.12 GET /v2/manager/queue/status

### Goal QS1 — Accurate overall counts
- **Precondition**: known queue state (e.g., 3 pending, 1 running, 2 done)
- **Action**: GET queue/status
- **Assertion**: counts match actual internal queue state

### Goal QS2 — Client-filtered counts
- **Precondition**: tasks from multiple client_ids
- **Action**: GET queue/status?client_id=X
- **Assertion**: response.client_id == X; counts reflect only X's tasks

## 1.13 GET /v2/manager/queue/history

### Goal QH1 — Retrieve batch history by id
- **Precondition**: batch file exists at manager_batch_history_path
- **Action**: GET queue/history?id=<batch_id>
- **Assertion**: response JSON matches file contents

### Goal QH2 — Reject path traversal
- **Action**: GET queue/history?id=../../../etc/passwd
- **Assertion**: 400 "Invalid history id"; no file read attempt

### Goal QH3 — Filter by ui_id / client_id / pagination
- **Action**: GET queue/history with respective query params
- **Assertion**: results properly filtered/paginated

## 1.14 GET /v2/manager/queue/history_list

### Goal QHL1 — List batch IDs sorted by mtime
- **Precondition**: files exist in history dir
- **Action**: GET queue/history_list
- **Assertion**: ids list == filenames (stem) sorted by mtime desc

### Goal QHL2 — Empty list when no history
- **Precondition**: empty dir
- **Assertion**: `{ids: []}`; 200

---

# Section 2 — CustomNode Info Verification Design

## 2.1 GET /v2/customnode/getmappings

### Goal CM1 — Return comprehensive node→pack mapping
- **Action**: GET getmappings?mode=local (or cache/remote)
- **Observable**: response dict; current NODE_CLASS_MAPPINGS
- **Assertion**: every currently-loaded node appears in some entry's node_list OR matches a nodename_pattern regex
- **Negative check**: no stale entries for uninstalled packs

### Goal CM2 — Nickname mode applies filter
- **Action**: GET getmappings?mode=nickname
- **Assertion**: entries include nickname field filtered by nickname_filter rules

### Goal CM3 — Require explicit mode
- **Action**: GET getmappings (no mode param)
- **Assertion**: server error (500/KeyError); no partial data

## 2.2 GET /v2/customnode/fetch_updates (deprecated)

### Goal FU1 — Signal deprecation to clients
- **Action**: GET fetch_updates?mode=local
- **Assertion**: 410 status; body `{deprecated: true, error: ..., message: ...}`
- **Negative check**: no git fetch executed (no mtime changes on .git/)

## 2.3 GET /v2/customnode/installed

### Goal IL1 — Current installed packs
- **Precondition**: known packs installed
- **Action**: GET installed
- **Assertion**: response dict keys include all installed pack identifiers; each entry has cnr_id + version + enabled

### Goal IL2 — imported mode is startup-frozen
- **Precondition**: install a new pack post-startup
- **Action**: GET installed?mode=imported
- **Assertion**: new pack absent from response (startup snapshot unchanged)
- **Negative check**: default mode DOES show new pack (proves they differ)

## 2.4 POST /v2/customnode/import_fail_info

### Goal IF1 — Return failure info for failed pack
- **Precondition**: pack exists in `cm_global.error_dict`
- **Action**: POST import_fail_info {cnr_id}
- **Assertion**: 200; response has `msg` + `traceback`; content matches error_dict entry

### Goal IF2 — Reject unknown pack
- **Action**: POST import_fail_info {cnr_id: "unknown-12345"}
- **Assertion**: 400; no response body with info

### Goal IF3 — Validate request body shape
- **Action**: POST import_fail_info with non-dict OR missing both fields OR wrong type
- **Assertion**: 400 with specific error text

## 2.5 POST /v2/customnode/import_fail_info_bulk

### Goal IFB1 — Return per-pack lookup results
- **Action**: POST import_fail_info_bulk {cnr_ids: [known, unknown]}
- **Assertion**: 200; response maps known→info dict, unknown→null

### Goal IFB2 — Reject empty lists
- **Action**: POST with {cnr_ids:[], urls:[]}
- **Assertion**: 400 "Either 'cnr_ids' or 'urls' field is required"

---

# Section 3 — Snapshot Verification Design

## 3.1 GET /v2/snapshot/get_current

### Goal SG1 — Capture current state accurately
- **Precondition**: known set of packs installed
- **Action**: GET snapshot/get_current
- **Assertion**: response has comfyui (hash/tag), git_custom_nodes (list), cnr_custom_nodes (list), pips; entries match actual installed state

## 3.2 POST /v2/snapshot/save

### Goal SS1 — Persist current state to retrievable file
- **Precondition**: snapshot dir exists
- **Action**: POST snapshot/save
- **Observable**: new file in manager_snapshot_path; snapshot/getlist response
- **Assertion**: new timestamped file created; content matches get_current() at save time; appears in getlist.items
- **Negative check**: other snapshots untouched

### Goal SS2 — Multiple saves create distinct files
- **Action**: POST save; wait 1s; POST save
- **Assertion**: 2 distinct new entries in getlist

## 3.3 GET /v2/snapshot/getlist

### Goal SL1 — List matches filesystem
- **Action**: GET snapshot/getlist
- **Assertion**: items == .json files in snapshot dir (stems), desc sorted

## 3.4 POST /v2/snapshot/remove

### Goal SR1 — Delete snapshot permanently
- **Precondition**: target snapshot exists
- **Action**: POST snapshot/remove?target=<id>
- **Assertion**: file removed from disk; absent from getlist
- **Negative check**: other snapshots untouched

### Goal SR2 — Idempotent on missing target
- **Action**: POST remove?target=nonexistent
- **Assertion**: 200 no-op

### Goal SR3 — Reject path traversal
- **Action**: POST remove?target=../../etc/passwd
- **Assertion**: 400 "Invalid target"; no file ops outside snapshot dir

### Goal SR4 — Security gate (<middle)
- **Precondition**: security_level < middle
- **Action**: POST remove
- **Assertion**: 403; target file untouched
- **Test reference**: `tests/e2e/test_e2e_secgate_strict.py::TestSecurityGate403_SR4::test_remove_returns_403` (WI-KK PoC, audit-integrated by WI-LL — uses `start_comfyui_strict.sh` strict-mode fixture)

## 3.5 POST /v2/snapshot/restore

### Goal SR5 — Schedule snapshot restore for next reboot
- **Precondition**: target snapshot exists
- **Action**: POST restore?target=<id>
- **Observable**: manager_startup_script_path for `restore-snapshot.json`
- **Assertion**: restore-snapshot.json exists; content == target snapshot; (downstream: reboot → state reverts)

### Goal SR6 — Security gate (<middle+)
- **Assertion**: 403; no marker file

---

# Section 4 — Config Verification Design

## 4.1 GET /v2/manager/db_mode

### Goal C1 — Return current config value
- **Action**: GET db_mode
- **Assertion**: text response ∈ {cache, channel, local, remote}; matches config.ini[db_mode]

## 4.2 POST /v2/manager/db_mode

### Goal C2 — Persist new value to config.ini
- **Precondition**: original value X
- **Action**: POST db_mode {value: Y} where Y ≠ X
- **Observable**: GET db_mode after POST; config.ini file content; GET after process restart
- **Assertion**: GET returns Y; config.ini updated; survives restart (restart + re-GET returns Y)
- **Cleanup**: restore X

### Goal C3 — Reject malformed JSON / missing value
- **Action**: POST with non-JSON body OR {foo: bar}
- **Assertion**: 400; config.ini unchanged

## 4.3-4.4 GET/POST /v2/manager/policy/update

Same verification pattern as db_mode, with policy values ∈ {stable, stable-comfyui, nightly, nightly-comfyui}.

## 4.5 GET /v2/manager/channel_url_list

### Goal C4 — Return selected + available channels
- **Action**: GET channel_url_list
- **Assertion**: response has selected (str) + list (array of "name::url" strings); selected == name whose URL matches config.channel_url else "custom"

## 4.6 POST /v2/manager/channel_url_list

### Goal C5 — Switch channel by name
- **Precondition**: original channel X
- **Action**: POST {value: Y} where Y is a known channel name
- **Observable**: GET after POST
- **Assertion**: selected == Y; config.channel_url == channels[Y]
- **Cleanup**: restore X

### Goal C6 — Silent no-op on unknown name
- **Action**: POST {value: "nonexistent-channel-xyz"}
- **Assertion**: 200; selected UNCHANGED (verify via GET)

---

# Section 5 — System + ComfyUI Version Verification Design

## 5.1 GET /v2/manager/version

### Goal V1 — Consistent version string
- **Action**: GET version × 2 consecutive calls
- **Assertion**: both return same non-empty string == core.version_str

## 5.2 GET /v2/manager/is_legacy_manager_ui

### Goal V2 — Reflect CLI flag
- **Precondition**: server started with/without --enable-manager-legacy-ui
- **Action**: GET is_legacy_manager_ui
- **Assertion**: response.is_legacy_manager_ui matches the actual CLI flag

## 5.3 POST /v2/manager/reboot

### Goal V3 — Process restart + recovery
- **Precondition**: server running; pre_version captured
- **Action**: POST reboot
- **Observable**: connection behavior; health endpoint polling; post-reboot version
- **Assertion**: connection drops or 200; within N seconds server responds again; post_version == pre_version (verifies core state preserved)
- **Negative check**: config unchanged across reboot

### Goal V4 — COMFY_CLI_SESSION mode
- **Precondition**: __COMFY_CLI_SESSION__ env set
- **Action**: POST reboot
- **Assertion**: `.reboot` marker file created; process exits with code 0 (external manager restarts)

### Goal V5 — Security gate (<middle)
- **Action**: POST reboot at low security
- **Assertion**: 403; server continues (no restart occurs)

## 5.4 GET /v2/comfyui_manager/comfyui_versions

### Goal CV1 — Enumerate versions + current
- **Action**: GET comfyui_versions
- **Assertion**: response `{versions, current}`; versions list non-empty; each item is string; current ∈ versions; matches actual `.git` tags/commits

### Goal CV2 — Fail cleanly on non-git
- **Precondition**: ComfyUI dir not a git repo (simulate)
- **Action**: GET
- **Assertion**: 400; no partial response

## 5.5 POST /v2/comfyui_manager/comfyui_switch_version

### Goal CV3 — Queue update-comfyui task with target_version
- **Precondition**: security_level ≥ high+
- **Action**: POST switch_version?ver=X&client_id=Y&ui_id=Z
- **Observable**: queue/status; queued task params
- **Assertion**: task queued with params.target_version=X
- **Note**: actual switch (destructive) NOT verified in E2E

### Goal CV4 — Security gate (<high+)
- **Action**: POST switch_version at lower security
- **Assertion**: 403; no task queued
- **Test reference**: `tests/e2e/test_e2e_secgate_default.py::TestSecurityGate403_CV4::test_switch_version_returns_403_at_default` (WI-KK demo, audit-integrated by WI-LL — runs at default `security_level=normal`; WI-KK research showed `is_local_mode=True + normal` is already outside the `[WEAK, NORMAL_]` allowed set for high+, so no harness is needed)

### Goal CV5 — Validate params
- **Action**: POST without ver OR without client_id/ui_id
- **Assertion**: 400 with error details; no task queued

---

# Section 6 — Legacy-only Verification Design (UI → effect)

All verification here assumes Playwright UI interaction as the Action. Effect is observed through both UI state and backend filesystem/state.

## 6.1 POST /v2/manager/queue/batch

### Goal LB1 — Install via UI row "Install" button
- **Precondition**: pack not installed; Custom Nodes Manager dialog open
- **Action (UI)**: filter to Not Installed → click Install on target row → click "Select" on version dialog
- **Observable**: backend: custom_nodes/<pack>/ + `.tracking`; UI: row badge changes to "Installed"; WebSocket: cm-queue-status all-done
- **Assertion**: backend install effect + UI state updates

### Goal LB2 — Uninstall via UI
- **Precondition**: pack installed
- **Action (UI)**: click "Uninstall" button on row
- **Observable**: backend: pack dir removed; UI: row shows "Not Installed"
- **Assertion**: both states consistent

### Goal LB3 — Disable via UI
- **Action (UI)**: click "Disable" button on row
- **Assertion**: pack in .disabled/; UI row shows "Disabled"

### Goal LB4 — Update all via menu
- **Action (UI)**: Manager menu → "Update All"
- **Observable**: queue/status; progress indicator in UI
- **Assertion**: N tasks queued; UI progress reflects N; eventual completion

### Goal LB5 — Batch partial failure reporting
- **Action (UI)**: batch with one guaranteed-fail pack
- **Observable**: response.failed array; UI notification
- **Assertion**: failed list contains only failed pack id; others succeeded

## 6.2 GET /v2/customnode/getlist

### Goal LG1 — Populate Custom Nodes Manager dialog
- **Action (UI)**: click "Custom Nodes Manager" from Manager menu
- **Observable**: UI grid rows
- **Assertion**: rows > 0; each row has Title + Installed/Not-Installed state + Install/Uninstall button

### Goal LG2 — skip_update=true optimizes loading
- **Action (UI)**: open dialog with flag set (URL param or setting)
- **Observable**: loading time; network log
- **Assertion**: no git fetch calls; load time < N seconds

## 6.3 GET /customnode/alternatives

### Goal LA1 — Show alternatives on dedicated UI flow
- **Action (UI)**: trigger alternatives display (specific button or context)
- **Observable**: alternatives panel/dialog
- **Assertion**: populated with alter-list.json entries (at least one if data exists)

## 6.4 GET /v2/externalmodel/getlist

### Goal LM1 — Populate Model Manager dialog
- **Action (UI)**: open Model Manager
- **Observable**: UI grid
- **Assertion**: rows > 0; each row has `installed` flag accurately reflecting filesystem

### Goal LM2 — Install flag correctness
- **Precondition**: pre-existing model file at known path
- **Action (UI)**: open Model Manager
- **Assertion**: that model row shows "Installed"

## 6.5 GET /v2/customnode/versions/{node_name}

### Goal LV1 — Version dropdown on Install click
- **Action (UI)**: click Install on a CNR pack row
- **Observable**: version selector (select multiple) in modal
- **Assertion**: dropdown options match CNR registry versions for that pack; "latest" option present

### Goal LV2 — Unknown pack → 400 (UI should handle)
- **Action**: direct API call with bogus node_name
- **Assertion**: 400; UI shows error or skips

## 6.6 GET /v2/customnode/disabled_versions/{node_name}

### Goal LDV1 — Show disabled versions for re-enable
- **Precondition**: pack has disabled versions
- **Action (UI)**: open pack's "Disabled Versions" dropdown
- **Observable**: dropdown options
- **Assertion**: options match backend disabled_versions response

## 6.7 POST /v2/customnode/install/git_url

### Goal LGU1 — Install via "Install via Git URL" button
- **Precondition**: security_level ≥ high+; pack absent
- **Action (UI)**: click button → enter URL → confirm
- **Observable**: custom_nodes/<pack>/ + .git/
- **Assertion**: pack cloned; UI reflects

### Goal LGU2 — Security gate
- **Precondition**: security_level < high+
- **Assertion**: 403 from API; UI shows error; no clone occurs

## 6.8 POST /v2/customnode/install/pip

### Goal LPP1 — Install pip packages via UI
- **Action (UI)**: trigger pip install flow with known package
- **Observable**: venv site-packages
- **Assertion**: package importable after install

### Goal LPP2 — Security gate
- **Assertion**: 403 at lower security; no pip invocation

## 6.9 GET /v2/manager/notice

### Goal LN1 — Fetch and display News
- **Precondition**: GitHub reachable
- **Action**: GET manager/notice (triggered on Manager menu open)
- **Assertion**: HTML response; contains expected markdown-body content; footer has ComfyUI + Manager version

### Goal LN2 — Graceful on GitHub unreachable
- **Precondition**: network blocked
- **Assertion**: "Unable to retrieve Notice" returned; no server crash; UI shows message

### Goal LN3 — Non-git ComfyUI warning
- **Precondition**: ComfyUI dir not a git repo
- **Assertion**: response starts with "isn't git repo" warning paragraph

### Goal LN4 — Outdated ComfyUI warning
- **Precondition**: comfy_ui_commit_datetime.date() < required_commit_datetime.date()
- **Assertion**: response starts with "too OUTDATED!!!" paragraph

---

# Section 7 — Cross-cutting Intent Pattern Templates

Reusable verification templates organized by intent category. Apply the template to any scenario of that type.

## 7.1 User Capability Template

**Goal**: User accomplishes task X.

**Verification structure**:
1. **Precondition check**: state is F0 (function not yet performed)
2. **Invoke action**: endpoint call or UI interaction
3. **Wait for completion**: poll status endpoint OR WebSocket event OR filesystem observer
4. **Observable assertions** (in order):
   - Response status 2xx
   - Response body schema correct
   - Side-effect state is F1 (function performed)
   - Secondary state changes (counters, history, lists) reflect the change
5. **Negative checks**:
   - No orphan state (partial writes, stale locks)
   - Other unrelated state unchanged (blast radius contained)
6. **Cleanup**: restore F0 where possible (for idempotent tests)

**Examples in this report**: A1, A2, U1, UP1, D1, E1, IM1, UA1, R1, S1, SS1, SR1, C2, C5, V3, CV3, LB1-LB5, LGU1, LPP1

## 7.2 Input Resilience Template

**Goal**: Bad input must be rejected without side effects.

**Verification structure**:
1. **Precondition**: system in known-good state S0
2. **Action**: send malformed/invalid input (craft variants per endpoint):
   - Malformed JSON (raw text, wrong Content-Type)
   - Missing required field
   - Wrong type for field
   - Out-of-range value
   - Extraneous unexpected field (should be ignored)
3. **Observable assertions**:
   - Response 4xx (400 typical; 500 only if server constraint like KeyError)
   - Error message identifies the problem (if surfaced)
4. **Negative checks** (the critical part):
   - State S1 == S0 (no mutation)
   - Queue/history not populated
   - Filesystem unchanged
   - No downstream side effects (no email, no download, no process start)

**Examples**: A4, A5, U1 (missing target), IM2, UA3, UC2 edges, QH2, IF2, IF3, IFB2, C3, LV2

## 7.3 Security Boundary Template

**Goal**: Operations requiring privilege X must fail at lower privilege.

**Verification structure**:
1. **Precondition**: server running at specific `security_level` below the gate
2. **Action**: invoke the privileged endpoint
3. **Observable assertions**:
   - Response 403
   - Server log contains security-denied message
4. **Critical negative checks**:
   - NO task queued
   - NO filesystem change
   - NO network operation initiated
   - NO config change
   - NO process change (no restart, no exit)
5. **Positive counterpart**: at or above required level, operation succeeds

**Security tiers to cover**:
- `middle` — reboot, snapshot/remove, _uninstall, _update
- `middle+` — update_all, snapshot/restore, _install_custom_node, _install_model
- `high+` — comfyui_switch_version, install/git_url, install/pip, non-safetensors model, _fix (`middle` → `high` in commit `c8992e5d`; subsequent `high` → `high+` in WI-#235 to align the gate with the `SECURITY_MESSAGE_HIGH_P` log text)

**Path-traversal sub-template** (within security boundary):
1. Action: request with `../`, absolute path, encoded traversal
2. Assertion: 400 "Invalid target" or similar
3. Negative check: target file unchanged; no files outside the endpoint's scope accessed

**Examples**: IM4, UA2, SR3, SR4, SR6, V5, CV4, LGU2, LPP2, QH2

## 7.4 Observability Template

**Goal**: Caller can trust the response to reflect actual system state.

**Verification structure**:
1. **Establish known state**: inject a known delta (queue a task, install a pack, save a snapshot)
2. **Read endpoint**: GET the observability endpoint
3. **Assertion**: response reflects the known delta
4. **Consistency check**: read again immediately; result identical (no race/jitter)
5. **Schema check**: all expected fields present with correct types

**Required-identity fields** (traceability sub-pattern):
- client_id + ui_id must be present in inputs for all state-mutating endpoints
- Verify that history/status queries can locate tasks by these IDs

**Examples**: QS1, QS2, QH1, QH3, IL1, IL2, SL1, C1, V1, V2, CV1, LG1, LM1, LM2, LV1, LDV1

## 7.5 Idempotency Template

**Goal**: Re-invoking an operation on an already-satisfied state is safe.

**Verification structure**:
1. **Invoke operation** to reach state F1
2. **Invoke same operation again** (no intermediate state change)
3. **Assertions**:
   - Response 2xx (same or semantically equivalent status, e.g., 200/201)
   - State remains F1 (no regression, no duplicate)
   - No error raised
4. **Stress variant**: invoke N times in rapid succession; ensure no race condition

**Examples**: U2, UP2, D2, E2, R2, S2, SS2 (distinct but both succeed), SR2, C6

## 7.6 Data Integrity Template

**Goal**: Config / runtime constants remain stable and consistent.

**Verification structure**:
1. **Read constant twice** (consecutive or across operations)
2. **Assertion**: identical values
3. **Persistence across restart**: set value → reboot → re-read
4. **Assertion**: value persisted

**Examples**: V1 (version idempotent), C2 (db_mode survives restart), CV1 (versions list stable)

## 7.7 Recovery Template

**Goal**: System can recover from failure or drifted state.

**Verification structure**:
1. **Induce failure state**: delete dependency, corrupt a file, disable a pack
2. **Invoke recovery operation**: fix, restore, re-enable
3. **Assertion**: state is healthy again; pack/module loads
4. **Negative check**: no data loss; original files preserved where applicable

**Examples**: F1 (fix dependency), E1 (enable disabled), SR5 (restore snapshot)

## 7.8 Concurrency Safety Template

**Goal**: Parallel or duplicated operations don't corrupt state.

**Verification structure**:
1. **Setup parallel trigger**: fire multiple start/reset/task commands in rapid succession
2. **Assertions**:
   - No duplicate worker thread (single pid in logs)
   - No task processed twice (idempotent task-id check)
   - No race-condition data corruption (e.g., half-written config)
3. **Stress test variant**: N parallel requests, assert linearized outcome

**Examples**: S2 (duplicate start), R1 (reset during processing)

---

# Section 8 — Verification Matrix Summary

| Intent category | Template | Scenarios using | Test type needed |
|---|---|---:|---|
| User capability | 7.1 | 62 | E2E effect verification (real install/remove/save etc.) |
| Input resilience | 7.2 | 32 | Negative tests with negative-check assertions |
| Security boundary | 7.3 | 15 | Permission tests at each security level |
| Observability | 7.4 | 16 | GET correctness + traceability tests |
| Idempotency | 7.5 | 14 | Repeat-call tests |
| Data integrity | 7.6 | 8 | Cross-restart persistence tests |
| Recovery | 7.7 | 5 | Fault-injection tests |
| Concurrency safety | 7.8 | 2 | Parallel-call stress tests |

---

# Section 9 — Practical Implementation Priority

Based on security impact + existing coverage gaps:

## 🔴 Must-add (security + integrity)
1. **Path traversal tests** for snapshot/remove, snapshot/restore, queue/history (Section 7.3 path sub-template)
2. **Security gate 403 tests** for each tier — requires running with restricted security_level in separate test run
3. **Config persistence across restart** — set db_mode → reboot → verify (Section 7.6)

## 🟡 Should-add (coverage quality)
4. **UI-driven install/uninstall flow** (LB1-LB3) — convert debug-install-flow.spec.ts to assertion test
5. **install_model effect** — current test only checks 200; add queue/status verification (Goal IM1)
6. **Fix recovery test** — induce broken dependency, verify fix heals (Goal F1)

## 🟢 Nice-to-have
7. Concurrency tests (duplicate queue/start; parallel task queueing)
8. get_current snapshot content fidelity — compare to actual installed state
9. Update version bump verification — test install v1.0.0 → update → expect v1.0.1 marker

---

# Section 10 — Security Mitigation Contracts

Layer: CSRF method-rejection (GET→POST conversion, commit `99caef55`). This section formalizes the contract exercised by TWO test files — one per server variant (mutex loading via `--enable-manager-legacy-ui`):

- `tests/e2e/test_e2e_csrf.py` — glob server (4 functions / 26 parametrized invocations — post-WI-HH; was 29 before the 3 dual-purpose endpoints were removed from the reject-GET fixture)
- `tests/e2e/test_e2e_csrf_legacy.py` — legacy server (4 functions / 26 parametrized invocations; WI-FF added, WI-GG audit-integrated)

Scope is deliberately narrow — see each test file's SCOPE docstring: only the method-reject layer, not Origin/Referer/same-site/anti-token defenses (those are handled by `origin_only_middleware` at the aiohttp layer and are out of scope here). The full 16-endpoint inventory is recorded in `reports/endpoint_scenarios.md` under "CSRF Method-Reject Contract Inventory"; the legacy file substitutes `/v2/manager/queue/batch` for `/v2/manager/queue/task` (glob-only) and scopes the 3 dual-purpose endpoints (`db_mode`, `policy/update`, `channel_url_list`) to the ALLOW-GET class only.

## 10.1 CSRF Method-Reject Contract

### Goal CSRF-M1 — State-changing endpoints reject HTTP GET (13 endpoints, post-WI-HH)
- **Precondition**: ComfyUI running; the 13 state-changing endpoints from `STATE_CHANGING_POST_ENDPOINTS` declared as `@routes.post(...)` in `comfyui_manager/glob/manager_server.py` (mirror in `comfyui_manager/legacy/manager_server.py`) — post-WI-HH count; excludes the 3 dual-purpose endpoints (`db_mode`, `policy/update`, `channel_url_list`) whose GET path legitimately reads the current value
- **Action**: HTTP GET to each endpoint path (no body, `allow_redirects=False`, module-scoped ComfyUI fixture)
- **Observable**: HTTP status code; response body (first 200 chars on failure)
- **Assertion**: `status_code not in range(200, 400)` AND `status_code in (400, 403, 404, 405)` for every path in the 13-endpoint fixture (post-WI-HH; the legacy counterpart also iterates 13 paths after substituting `queue/batch` for `queue/task`)
- **Negative check**: no 2xx success and no 3xx redirect on any state-changing path (blocks `<img src=...>`, link-click, and redirect-based cross-origin triggers — CVSS 8.1 vector from XlabAI/Tencent Xuanwu report)
- **Test reference** (glob): `tests/e2e/test_e2e_csrf.py::TestStateChangingEndpointsRejectGet::test_get_is_rejected` (1 function × 13 parametrized invocations — post-WI-HH)
- **Test reference** (legacy): `tests/e2e/test_e2e_csrf_legacy.py::TestLegacyStateChangingEndpointsRejectGet::test_get_is_rejected` (1 function × 13 parametrized invocations — `queue/batch` replaces `queue/task`; the 3 dual-purpose endpoints are covered via the read-path under CSRF-M3)

### Goal CSRF-M2 — POST counterparts still succeed (positive control)
- **Precondition**: ComfyUI running; clean snapshot state
- **Action**: POST `/v2/manager/queue/reset` (no-op reset), then POST `/v2/snapshot/save` (creates a snapshot, cleaned up via `/v2/snapshot/remove`)
- **Observable**: HTTP 200 response on both POSTs; on save, the new entry is observable via `/v2/snapshot/getlist`
- **Assertion**: `status_code == 200` for both POSTs; cleanup removes the just-created snapshot
- **Negative check**: the CSRF fix must NOT break the legitimate POST path (regression guard — functional equivalence of the converted endpoints must hold)
- **Test reference** (glob): `tests/e2e/test_e2e_csrf.py::TestCsrfPostWorks` (2 functions: `test_queue_reset_post_works`, `test_snapshot_save_post_works`)
- **Test reference** (legacy): `tests/e2e/test_e2e_csrf_legacy.py::TestLegacyCsrfPostWorks` (2 functions — same endpoints, legacy server fixture)

### Goal CSRF-M3 — Read-only endpoints still allow GET (negative control, 11 endpoints)
- **Precondition**: ComfyUI running
- **Action**: HTTP GET to 11 read-only endpoints: `/v2/manager/version`, `/v2/manager/db_mode`, `/v2/manager/policy/update`, `/v2/manager/channel_url_list`, `/v2/manager/queue/status`, `/v2/manager/queue/history_list`, `/v2/manager/is_legacy_manager_ui`, `/v2/customnode/installed`, `/v2/snapshot/getlist`, `/v2/snapshot/get_current`, `/v2/comfyui_manager/comfyui_versions`
- **Observable**: HTTP status code
- **Assertion**: `status_code == 200` for every read-only path
- **Negative check**: the CSRF fix must NOT over-correct by making pure-read endpoints POST-only (would break UI flows that `<img>`-safe-read via GET). Note: the 3 dual-purpose endpoints (`db_mode`, `policy/update`, `channel_url_list`) appear in BOTH CSRF-M1 (write path requires POST; plain GET is rejected) AND CSRF-M3 (read path still answers GET 200); this dual appearance is intentional — they were split into GET (read) + POST (write) by 99caef55.
- **Test reference** (glob): `tests/e2e/test_e2e_csrf.py::TestCsrfReadEndpointsStillAllowGet::test_get_read_endpoint_succeeds` (1 function × 11 parametrized invocations)
- **Test reference** (legacy): `tests/e2e/test_e2e_csrf_legacy.py::TestLegacyCsrfReadEndpointsStillAllowGet::test_get_read_endpoint_succeeds` (1 function × 11 parametrized invocations — same endpoint list)

## 10.2 Out-of-Scope CSRF Layers (tracked for future verification)
- **Origin/Referer validation** — `origin_only_middleware` (aiohttp layer); not exercised by `test_e2e_csrf.py`
- **Same-site cookie enforcement** — browser-layer concern; not server-testable in isolation
- **Anti-CSRF token verification** — not implemented in current codebase
- **Cross-site form POST defense** — subsumed by Origin validation above

These remain Goals for future work; do not infer coverage from Goals CSRF-M1/M2/M3.

---
*End of Verification Design Report*
