# Scenario × Functional Effect Mapping

**Generated**: 2026-04-18
**Definition of "effect"**: The actual **functional purpose** of the feature — not just any side effect. A scenario is verified only when the intended outcome is observably achieved.

| Pattern | Effect definition |
|---|---|
| Success scenario | The feature's PURPOSE is fulfilled and observable |
| Validation/security error | The purpose is NOT fulfilled + correct rejection signal |
| State edge case | The purpose is correctly short-circuited or no-op |

Unless specified, status code alone is NOT sufficient evidence of effect.

---

# Section 1 — Glob v2 Endpoints

## 1.1 Queue Management (Install/Uninstall/Update/Fix/Disable/Enable/Model)

### POST /v2/manager/queue/task (kind=install)

Purpose: **install a custom node pack so it becomes loadable by ComfyUI**.

| Scenario | Functional effect to verify |
|---|---|
| Success (CNR pack) | (a) pack directory exists under `custom_nodes/`, (b) `.tracking` file present (CNR marker), (c) pack appears in GET `customnode/installed` with correct cnr_id + version, (d) worker `task_worker_lock` released after completion |
| Success (nightly/URL) | (a) pack directory exists, (b) `.git` subdir present (git clone), (c) repo remote matches requested URL, (d) appears in installed list |
| Success (skip_post_install + already disabled) | Pack moved from `.disabled/` back to active (enable shortcut), NOT a fresh install |
| Validation error (bad `kind` value) | Task NOT queued (queue/status unchanged), queue/history does not contain this ui_id, pack NOT installed |
| Validation error (missing ui_id/client_id) | Same: no queued task, no installation side-effect |
| Worker auto-start | After task queued, `queue/status.is_processing=true` and eventually `done_count` increments |

### POST /v2/manager/queue/task (kind=uninstall)

Purpose: **remove an installed pack so it is no longer loaded**.

| Scenario | Effect to verify |
|---|---|
| Success | Pack directory no longer exists under `custom_nodes/`, pack absent from `customnode/installed`, no import error on next ComfyUI reload |
| Target not installed | No-op or error — purpose already satisfied; no state change |
| Unknown pack | No filesystem change |

### POST /v2/manager/queue/task (kind=update)

Purpose: **update an installed pack to a newer version**.

| Scenario | Effect to verify |
|---|---|
| Success | (a) pack directory still exists, (b) version actually changed (check `.tracking` content or pyproject version), (c) dependencies refreshed, (d) still loadable by ComfyUI |
| Already up-to-date | No-op or confirmatory response; no downgrade |
| Unknown pack / Update fails | No partial state (pack not removed nor corrupted) |

### POST /v2/manager/queue/task (kind=fix)

Purpose: **re-install dependencies of an existing pack without changing source**.

| Scenario | Effect to verify |
|---|---|
| Success | (a) pack directory unchanged (same HEAD/version), (b) dependencies present in venv after fix, (c) pack import succeeds on reload |
| Missing dependencies pre-fix | After fix, imports succeed |

### POST /v2/manager/queue/task (kind=disable)

Purpose: **stop loading a pack without removing it, reversibly**.

| Scenario | Effect to verify |
|---|---|
| Success | (a) pack moved from `custom_nodes/<name>/` to `custom_nodes/.disabled/<name>/`, (b) on next ComfyUI reload, pack nodes NOT registered, (c) pack absent from `customnode/installed` (active) |
| Already disabled | No-op; still in `.disabled/` |

### POST /v2/manager/queue/task (kind=enable)

Purpose: **restore a disabled pack to active, loadable state**.

| Scenario | Effect to verify |
|---|---|
| Success | (a) pack restored from `.disabled/` to active `custom_nodes/` (may be case-normalized CNR name), (b) on reload, nodes registered again, (c) appears in `customnode/installed` |
| Not disabled (already active) | No-op; no regression |

### POST /v2/manager/queue/install_model

Purpose: **download a model file to the appropriate models/ subdirectory**.

| Scenario | Effect to verify |
|---|---|
| Success | (a) task queued (queue/status reflects), (b) eventually file downloaded to `models/<type>/<filename>`, (c) file size > 0, (d) visible via `externalmodel/getlist` with `installed=True` (legacy) |
| Missing client_id/ui_id | Task NOT queued; no download attempted |
| Invalid metadata | Task NOT queued |
| Not in whitelist (legacy check) | Download rejected; no file written |
| Non-safetensors + security<high+ | Rejected; no file written |

### POST /v2/manager/queue/update_all

Purpose: **queue update tasks for ALL currently active packs**.

| Scenario | Effect to verify |
|---|---|
| Success | queue/status.pending_count == N where N = (active_nodes + unknown_active_nodes - manager-skip). Each queued task has correct `kind=update` + correct `node_name` |
| Security denied (<middle+) | 403; NO tasks queued; queue/status unchanged |
| Missing params | 400; NO tasks queued |
| mode=local | No remote fetch; uses local channel data |
| Desktop build | `comfyui-manager` pack NOT in queued tasks |

### POST /v2/manager/queue/update_comfyui

Purpose: **queue a self-update task for ComfyUI core**.

| Scenario | Effect to verify |
|---|---|
| Success | (a) queue/status.total_count increased by 1, (b) the queued task has `kind=update-comfyui` with `params.is_stable` matching request/config |
| Missing params | 400; no task queued |
| stable=true overrides config | Task params.is_stable==True regardless of config policy |

### POST /v2/manager/queue/reset

Purpose: **clear all queued/running/history tasks**.

| Scenario | Effect to verify |
|---|---|
| Success | queue/status: total_count=0, done_count=0, pending_count=0, in_progress_count=0, is_processing=false |
| Already empty | Same; idempotent |

### POST /v2/manager/queue/start

Purpose: **start the worker thread to process queued tasks**.

| Scenario | Effect to verify |
|---|---|
| Worker not running | queue/status.is_processing becomes true (may be momentary if queue empty); tasks transition pending → running → done |
| Already running | 201; is_processing remains true; no duplicate worker spawned |
| Empty queue | Worker starts and idles; no errors |

### GET /v2/manager/queue/status

Purpose: **accurately reflect the current queue state**.

| Scenario | Effect to verify |
|---|---|
| No filter | Counts match actual internal queue state (cross-check via known queued tasks) |
| With client_id filter | client_id echo + filtered counts correspond to only that client's tasks |
| Fields shape | total/done/in_progress/pending/is_processing all present + correct types |

### GET /v2/manager/queue/history

Purpose: **retrieve completed task records for introspection**.

| Scenario | Effect to verify |
|---|---|
| id=<batch_id> query | Returns JSON content of that batch file (not another's) |
| Path traversal | file read DOES NOT occur; returns 400 |
| ui_id filter | Returns the matching single task record |
| client_id filter | Returns only that client's history |
| Pagination | Result size ≤ max_items |
| Serialization limitation | If 400 returned, server didn't crash; no corrupted state |

### GET /v2/manager/queue/history_list

Purpose: **list available batch history file IDs**.

| Scenario | Effect to verify |
|---|---|
| Success | Returned `ids` ⊆ files in `manager_batch_history_path` (mtime-desc sorted) |
| Empty | ids=[] reflects empty dir |

## 1.2 Custom Node Info

### GET /v2/customnode/getmappings

Purpose: **provide node→pack mapping for the UI to resolve missing nodes**.

| Scenario | Effect to verify |
|---|---|
| Success mode=local/cache/remote | Returned dict: values are `[node_list, metadata]`, all currently-loaded `NODE_CLASS_MAPPINGS` either present in a node_list OR matched by `nodename_pattern` regex |
| mode=nickname | Nicknames filter applied (each entry has nickname field) |
| Missing mode query | 500/KeyError; no partial data returned |

### GET /v2/customnode/fetch_updates (deprecated)

Purpose: **(deprecated) was previously used to fetch git updates**.

| Scenario | Effect to verify |
|---|---|
| Always | 410 + `{deprecated: true}`. No git fetch performed (no disk I/O on .git dirs) |

### GET /v2/customnode/installed

Purpose: **list currently-installed packs with metadata for the UI**.

| Scenario | Effect to verify |
|---|---|
| mode=default | Dict reflects real filesystem scan of `custom_nodes/`: every dir with proper marker appears |
| mode=imported | Returns snapshot frozen at startup (unchanged after runtime installs) — proves stability |
| Newly installed pack | After install, default mode reflects it; imported mode does NOT |

### POST /v2/customnode/import_fail_info

Purpose: **return detailed traceback/message for a pack that failed to import at startup**.

| Scenario | Effect to verify |
|---|---|
| Known failed pack via cnr_id | 200 + body has `msg` + `traceback` matching `cm_global.error_dict[module]` |
| Known failed via url | Same |
| Unknown pack | 400 (no info); `error_dict` NOT mutated |
| Missing fields / non-dict | 400 with appropriate text |

### POST /v2/customnode/import_fail_info_bulk

Purpose: **same as above but for multiple packs in one call**.

| Scenario | Effect to verify |
|---|---|
| cnr_ids list | Each key maps to either {error, traceback} (if failed) or null (if no failure). Unknown cnr_ids → null |
| urls list | Same semantics |
| Empty lists | 400 |
| Mixed types inside list | 400 or skip with per-item error |

## 1.3 Snapshots

### GET /v2/snapshot/get_current

Purpose: **capture and return the current system state (not persist it)**.

| Scenario | Effect to verify |
|---|---|
| Success | Returned dict contains `comfyui` (hash/tag), `git_custom_nodes` (list), `cnr_custom_nodes` (list), `pips`. Consistent with actual installed state |

### POST /v2/snapshot/save

Purpose: **persist current system state so it can be restored later**.

| Scenario | Effect to verify |
|---|---|
| Success | (a) new file created in `manager_snapshot_path` with timestamped name, (b) file content == get_current() at save time, (c) appears in `snapshot/getlist.items` |

### GET /v2/snapshot/getlist

Purpose: **list saved snapshots for UI selection**.

| Scenario | Effect to verify |
|---|---|
| Success | items list matches .json files in snapshot dir (without extension), sorted desc |
| After save | New snapshot name appears at top |
| After remove | Removed name absent |

### POST /v2/snapshot/remove

Purpose: **delete a saved snapshot permanently**.

| Scenario | Effect to verify |
|---|---|
| Success | File removed from disk; absent from getlist |
| Nonexistent target | No change; 200 (no-op) |
| Path traversal | File NOT removed; 400; any other files untouched |
| Security denied | File NOT removed; 403 |

### POST /v2/snapshot/restore

Purpose: **schedule a snapshot to be applied on next server restart** (the actual restore happens at startup).

| Scenario | Effect to verify |
|---|---|
| Success | `restore-snapshot.json` copied to `manager_startup_script_path`. Next reboot → actual state reverts to snapshot (verifiable by reboot + get_current comparison) |
| Nonexistent target | No marker file created; 400 |
| Path traversal | No file operations; 400 |
| Security denied | No marker file; 403 |

## 1.4 Configuration

### GET /v2/manager/db_mode

Purpose: **return current DB source mode config**.

| Scenario | Effect to verify |
|---|---|
| Success | Returned text == `core.get_config()["db_mode"]` value in `config.ini` |

### POST /v2/manager/db_mode

Purpose: **persist new DB mode to config.ini**.

| Scenario | Effect to verify |
|---|---|
| Valid value | (a) config.ini written to disk with new value, (b) GET returns new value, (c) survives process restart |
| Malformed JSON / missing value | 400; config.ini UNCHANGED |

### GET/POST /v2/manager/policy/update

Purpose: **read/persist update policy (stable vs nightly)**.

Same verification pattern as db_mode but for `update_policy` key.

### GET /v2/manager/channel_url_list

Purpose: **return available channels + currently selected**.

| Scenario | Effect to verify |
|---|---|
| Success | `selected` matches channel whose URL == config.channel_url (else "custom"); `list` is all known channels as "name::url" |

### POST /v2/manager/channel_url_list

Purpose: **switch active channel by name**.

| Scenario | Effect to verify |
|---|---|
| Known name | config.channel_url written with new URL; GET.selected matches new name |
| Unknown name | Silent no-op; 200; channel_url UNCHANGED (verify) |
| Malformed | 400; channel_url UNCHANGED |

## 1.5 System

### GET /v2/manager/is_legacy_manager_ui

Purpose: **let UI know which Manager UI (legacy vs current) to load**.

| Scenario | Effect to verify |
|---|---|
| Success | `is_legacy_manager_ui` matches the CLI flag `--enable-manager-legacy-ui` that was passed |

### GET /v2/manager/version

Purpose: **report the Manager package version**.

| Scenario | Effect to verify |
|---|---|
| Success | Text == core.version_str (non-empty, semver-ish) |
| Idempotent | Consecutive calls return identical value |

### POST /v2/manager/reboot

Purpose: **restart the server process**.

| Scenario | Effect to verify |
|---|---|
| Success | (a) server process actually exits, (b) new process binds same port, (c) new process serves requests, (d) pre-reboot state preserved (version, config) |
| CLI session mode | `.reboot` marker file created before exit(0); process-manager restarts |
| Security denied | 403; process continues (no restart) |

### GET /v2/comfyui_manager/comfyui_versions

Purpose: **enumerate available ComfyUI versions + current**.

| Scenario | Effect to verify |
|---|---|
| Success | `current` is a git tag/hash present in `.git` log; `versions` array non-empty; current ∈ versions |
| Git failure | 400; no partial response |

### POST /v2/comfyui_manager/comfyui_switch_version

Purpose: **queue a task to switch ComfyUI to a target version (actual switch happens via worker)**.

| Scenario | Effect to verify |
|---|---|
| Success | (a) task queued with `params.target_version=<ver>`, (b) queue/status reflects, (c) eventually `.git` HEAD points at target commit/tag after worker runs |
| Missing params | 400; no task queued |
| Security denied (<high+) | 403; no task queued |

---

# Section 2 — Legacy-only Endpoints (UI → effect)

For these, the functional purpose is triggered by UI interaction. The effect MUST be observable both through the UI (state transitions, renders) AND/OR through the backend (filesystem, queue state).

### POST /v2/manager/queue/batch (legacy)

Purpose: **accept one aggregated request to enqueue multiple operations, then start the worker**.

| Scenario | Effect to verify |
|---|---|
| install item(s) | Each pack installed (filesystem effect); `failed` list only contains actually-failed ids |
| uninstall item(s) | Each pack removed |
| update item(s) | Packs updated (version change verifiable) |
| reinstall item(s) | Pack removed then re-installed (dir exists, .tracking present) |
| disable | Pack in `.disabled/` |
| install_model | Model file downloaded |
| fix | Dependencies re-resolved |
| update_comfyui | ComfyUI update task queued |
| update_all | All active pack updates queued |
| Mixed kinds | Each kind's effect achieved; `failed` contains only real failures |

### GET /v2/customnode/getlist (legacy)

Purpose: **feed the Custom Nodes Manager dialog with the list of available + installed packs**.

| Scenario | Effect to verify |
|---|---|
| Success | Response has `channel` + `node_packs`; each pack includes install state (installed/disabled), stars (github-stats), update availability (if skip_update=false) |
| skip_update=true | No git fetch performed (check timing / no remote calls) |
| Channel resolution | Maps URL back to name (default/custom/etc.) |

### GET /customnode/alternatives (legacy)

Purpose: **show alternative pack recommendations for a given pack**.

| Scenario | Effect to verify |
|---|---|
| Success | Response dict keyed by unified pack id; values from `alter-list.json` with markdown processed |

### GET /v2/externalmodel/getlist (legacy)

Purpose: **list available external models with install state for Model Manager dialog**.

| Scenario | Effect to verify |
|---|---|
| Success | Each model entry has `installed` ∈ {'True','False'}; True ⟺ file actually exists under appropriate models subdir |
| HuggingFace sentinel | Filename resolved from URL basename; installed flag correct |
| Custom save_path | Path resolved correctly |

### GET /v2/customnode/versions/{node_name} (legacy)

Purpose: **list all versions of a CNR pack for the user to pick**.

| Scenario | Effect to verify |
|---|---|
| Known CNR pack | Response array lists all available versions (latest first, typically) matches CNR registry |
| Unknown pack | 400; no partial data |

### GET /v2/customnode/disabled_versions/{node_name} (legacy)

Purpose: **list versions of a pack currently in the disabled state for possible re-enable**.

| Scenario | Effect to verify |
|---|---|
| Has disabled versions | Response array matches actual `cnr_inactive_nodes[node]` keys + "nightly" if in `nightly_inactive_nodes` |
| None disabled | 400 |

### POST /v2/customnode/install/git_url (legacy)

Purpose: **clone a pack from arbitrary git URL (dangerous; requires high+)**.

| Scenario | Effect to verify |
|---|---|
| Success | Repo cloned into `custom_nodes/`, `.git` dir present, repo remote matches URL |
| Already installed | 200 skip; no duplicate; no overwrite |
| Clone failure | 400; no partial dir left behind |
| Security denied (<high+) | 403; no filesystem change |

### POST /v2/customnode/install/pip (legacy)

Purpose: **run `pip install <packages>` in the venv**.

| Scenario | Effect to verify |
|---|---|
| Success | Packages are importable from the venv Python afterwards (or `pip list` shows them) |
| Security denied (<high+) | 403; no pip invocation |

### GET /v2/manager/notice (legacy)

Purpose: **fetch the News wiki content and augment with version footer**.

| Scenario | Effect to verify |
|---|---|
| GitHub reachable | HTML returned; contains markdown-body content + ComfyUI/Manager version footer appended |
| GitHub unreachable | "Unable to retrieve Notice"; no crash |
| Non-git ComfyUI | Response starts with "Your ComfyUI isn't git repo" warning |
| Outdated ComfyUI | Response starts with "too OUTDATED!!!" warning |
| Desktop variant | Footer uses `__COMFYUI_DESKTOP_VERSION__` instead of commit hash |

---

# Section 3 — UI→effect Mapping (Legacy)

For Playwright tests, the "UI→effect" contract requires:

| UI action | Target endpoint | Effect to verify |
|---|---|---|
| Click Manager menu button | (none — UI only) | `#cm-manager-dialog` visible |
| Click "Custom Nodes Manager" menu item | GET customnode/getlist + getmappings | `#cn-manager-dialog` + grid populated (rows > 0) |
| Click "Model Manager" menu item | GET externalmodel/getlist | `#cmm-manager-dialog` + grid populated |
| Click "Snapshot Manager" menu item | GET snapshot/getlist | `#snapshot-manager-dialog` + list populated |
| Click "Install" on a pack row | GET customnode/versions/{id} → POST queue/batch (install) → WebSocket cm-queue-status | Pack dir exists on disk + row shows "Installed" state in UI + WebSocket `all-done` received |
| Click "Uninstall" on installed row | POST queue/batch (uninstall) | Pack dir removed + row state updates to "Not Installed" |
| Click "Disable" on row | POST queue/batch (disable) | Pack in `.disabled/` + row state "Disabled" |
| Click "Update" on outdated row | POST queue/batch (update) | Pack version changes + row state update |
| Click "Fix" on row | POST queue/batch (fix) | Dependencies restored |
| Click "Try alternatives" | GET /customnode/alternatives | Alternatives list rendered |
| Open "Versions" dropdown on row | GET customnode/versions/{id} | Version list rendered in UI |
| Open "Disabled Versions" on row | GET customnode/disabled_versions/{id} | Disabled versions rendered |
| Click "Install via Git URL" button + enter URL + confirm | POST customnode/install/git_url | Pack cloned; dir visible in UI |
| Click "Install via pip" | POST customnode/install/pip | Package installed; no UI crash |
| Click "Install" on Model Manager row | POST queue/install_model | Model file downloaded; row state "Installed" |
| Change DB mode dropdown | POST db_mode | Config persisted; dropdown value persists after dialog reopen |
| Change Update Policy dropdown | POST policy/update | Same |
| Change Channel dropdown | POST channel_url_list | Same |
| Click "Update All" button | POST queue/update_all | Multiple tasks queued; progress indicator shows count |
| Click "Update ComfyUI" button | POST queue/update_comfyui | Task queued; status indicator |
| Click "Save Snapshot" in Snapshot Manager | POST snapshot/save | New row in dialog list with timestamp |
| Click "Remove" on snapshot row | POST snapshot/remove?target=X | Row disappears from list |
| Click "Restore" on snapshot row | POST snapshot/restore?target=X | Marker file created; next reboot applies |
| Click "Restart" button | POST manager/reboot | Server restarts; UI reconnects |
| Open Manager menu with pending News | GET manager/notice | News panel visible with HTML content |
| Filter/search in grid | (client-side) | Row count ≤ initial count |
| Close dialog (X button / Esc) | (none) | Dialog hidden; no leaked DOM |

---

# Section 4 — Effects Not Easily Observable

Some purposes can only be proven via side-channel observation:

| Endpoint | Purpose | Why hard to verify |
|---|---|---|
| POST snapshot/restore | Apply snapshot at next reboot | Must actually reboot + compare post-state; destructive |
| POST switch_version (positive) | Change ComfyUI version | Destructive; needs rollback |
| POST manager/reboot | Restart process | Hard to assert "new process" vs "same process" cleanly; proxy: pid change or connection drop+rebind |
| POST queue/start → worker runs | Tasks execute | Timing-dependent; must poll done_count |
| GET manager/notice | Content from GitHub | External dependency; flaky |
| POST install (network) | Actually installs | Depends on CNR/GitHub availability |
| POST install_model (download) | File downloaded | Slow; large files; fake whitelist URL returns quick 404 |

For these, tests either (a) accept destructive as out-of-scope, (b) use timing/polling, or (c) mock at minimum granularity.

---
*End of Scenario × Effect Mapping*
