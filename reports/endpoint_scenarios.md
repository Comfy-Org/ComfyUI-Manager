# Report A — Endpoint Extraction + Scenario Mapping

**Generated**: 2026-04-18
**Source files**:
- `comfyui_manager/glob/manager_server.py` (glob v2 — primary/current API)
- `comfyui_manager/legacy/manager_server.py` (legacy — `--enable-manager-legacy-ui`)

## Summary

| Category | Endpoints | Unique Scenarios |
|---|---:|---:|
| Glob v2 | 30 | 120 |
| Legacy-only (not in glob) | 9 | 34 |
| Legacy-shared (same path as glob) | 29 | — (see glob) |
| **TOTAL unique HTTP handlers** | **39** | **154** |

Security-gated endpoints:
- `middle`: reboot, snapshot/remove, _uninstall_custom_node, _update_custom_node
- `middle+`: update_all, snapshot/restore, _install_custom_node, _install_model
- `high+`: comfyui_switch_version, install/git_url, install/pip, non-safetensors model install, _fix_custom_node (raised from `high` to align the gate with the `SECURITY_MESSAGE_HIGH_P` log text — WI-#235; prior `middle` → `high` upgrade was commit `c8992e5d`)

---

# Section 1 — Glob v2 Endpoints (`comfyui_manager/glob/manager_server.py`)

## 1.1 Queue Management

### POST /v2/manager/queue/task
- **Handler**: `queue_task` (L1218)
- **Schema**: `QueueTaskItem` (Pydantic) — `{kind, ui_id, client_id, params}`
- **Scenarios**:
  1. Success — valid task (kind=install/update/fix/disable/enable/uninstall/update_comfyui/install_model) → 200
  2. Validation error — malformed kind / missing ui_id / invalid params → 400 with ValidationError text
  3. Invalid JSON body → 500
  4. State: worker auto-starts when task added

### GET /v2/manager/queue/history_list
- **Handler**: `get_history_list` (L1252)
- **Scenarios**:
  1. Success — list of batch history file IDs (basename without .json) sorted by mtime desc → 200 `{ids: [...]}`
  2. Empty history directory → 200 `{ids: []}`
  3. History path inaccessible → 400

### GET /v2/manager/queue/history
- **Handler**: `get_history` (L1281)
- **Query**: `id` (batch file) | `client_id` | `ui_id` | `max_items` | `offset`
- **Scenarios**:
  1. Success with `id=<batch_history_id>` → reads JSON file → 200
  2. Path-traversal attempt in `id` → 400 "Invalid history id"
  3. Filter by `ui_id` — returns single task history → 200 `{history: ...}`
  4. Filter by `client_id` — filters in-memory history dict → 200
  5. Pagination (`max_items`, `offset`) → 200 `{history: ...}`
  6. JSON serialization failure (in-memory TaskHistoryItem not serializable) → 400
  7. No query params — returns full current session history → 200

### POST /v2/manager/queue/reset
- **Handler**: `reset_queue` (L1718)
- **Scenarios**:
  1. Success — wipes pending + running + history → 200
  2. Idempotent — safe to call when queue already empty → 200

### GET /v2/manager/queue/status
- **Handler**: `queue_count` (L1725)
- **Query**: `client_id` (optional)
- **Scenarios**:
  1. No filter — global counts (total/done/in_progress/pending, is_processing) → 200
  2. With `client_id` — response includes `client_id` echo + per-client counts → 200
  3. Unknown client_id — returns 0 counts with echo → 200

### POST /v2/manager/queue/start
- **Handler**: `queue_start` (L1778)
- **Scenarios**:
  1. Worker not running — starts worker → 200
  2. Worker already running → 201 (already in-progress)
  3. Empty queue — worker starts then idles → 200

### POST /v2/manager/queue/update_all
- **Handler**: `update_all` (L1411)
- **Security gate**: `middle+` → 403 otherwise
- **Schema**: `UpdateAllQueryParams` — `{ui_id, client_id, mode?}`
- **Scenarios**:
  1. Success — queues update tasks for all active nodes → 200 (synchronously; slow due to reload)
  2. Missing `ui_id`/`client_id` → 400 ValidationError
  3. Security blocked (level < middle+) → 403
  4. `mode=local` — uses local channel (no network)
  5. `mode=remote/cache` — fetches cached channel data
  6. Desktop version — skips comfyui-manager pack (reads `__COMFYUI_DESKTOP_VERSION__`)
  7. Empty node set — queues 0 tasks → 200

### POST /v2/manager/queue/update_comfyui
- **Handler**: `update_comfyui` (L1791)
- **Schema**: `UpdateComfyUIQueryParams` — `{client_id, ui_id, stable?}`
- **Scenarios**:
  1. Success — queues `update-comfyui` task → 200
  2. Missing required params → 400 ValidationError
  3. `stable=true` — forces stable update regardless of config
  4. `stable=false` — forces nightly update
  5. No `stable` param — uses config policy (nightly-comfyui vs stable)

### POST /v2/manager/queue/install_model
- **Handler**: `install_model` (L1875)
- **Schema**: `ModelMetadata` (name, type, base, url, filename, save_path) + required `client_id` + `ui_id`
- **Scenarios**:
  1. Success — valid request → queues `install-model` task → 200
  2. Missing `client_id` → 400 "Missing required field: client_id"
  3. Missing `ui_id` → 400 "Missing required field: ui_id"
  4. Invalid model metadata (missing name/url/filename) → 400 ValidationError
  5. Malformed JSON → 500

## 1.2 Custom Node Info

### GET /v2/customnode/getmappings
- **Handler**: `fetch_customnode_mappings` (L1357)
- **Query**: `mode` (required: local|cache|remote|nickname)
- **Scenarios**:
  1. Success — returns `{pack_id: [node_list, metadata]}` dict → 200
  2. `mode=nickname` — applies nickname_filter → 200
  3. Missing `mode` → KeyError → 500
  4. Invalid `mode` value → may raise from get_data_by_mode → 400/500
  5. Missing nodes matched by `nodename_pattern` regex are appended

### GET /v2/customnode/fetch_updates
- **Handler**: `fetch_updates` (L1393)
- **Scenarios**:
  1. Always returns **410 Gone** with `{deprecated: true}` — deprecated endpoint
  2. Client should migrate to queue/update-based flow

### GET /v2/customnode/installed
- **Handler**: `installed_list` (L1500)
- **Query**: `mode` (default|imported)
- **Scenarios**:
  1. Default mode — current installed packs snapshot → 200 dict
  2. `mode=imported` — startup-time installed packs (frozen snapshot) → 200
  3. Empty custom_nodes dir → 200 `{}`

### POST /v2/customnode/import_fail_info
- **Handler**: `import_fail_info` (L1623)
- **Body**: `{cnr_id?, url?}` — one required
- **Scenarios**:
  1. Known failed pack via `cnr_id` — returns `{msg, traceback}` → 200
  2. Known failed pack via `url` — returns info → 200
  3. Unknown pack → 400 (no failure info available)
  4. Missing both cnr_id and url → 400 "Either 'cnr_id' or 'url' field is required"
  5. `cnr_id` not a string → 400 "'cnr_id' must be a string"
  6. Non-dict body → 400 "Request body must be a JSON object"

### POST /v2/customnode/import_fail_info_bulk
- **Handler**: `import_fail_info_bulk` (L1657)
- **Schema**: `ImportFailInfoBulkRequest` — `{cnr_ids: [], urls: []}`
- **Scenarios**:
  1. Success with `cnr_ids` list — returns `{cnr_id: {error, traceback}|null}` → 200
  2. Success with `urls` list — returns `{url: {error, traceback}|null}` → 200
  3. Both lists empty → 400 "Either 'cnr_ids' or 'urls' field is required"
  4. Validation error (wrong types) → 400
  5. Each unknown pack → `null` in results dict (not an error)

## 1.3 Snapshots

### GET /v2/snapshot/getlist
- **Handler**: `get_snapshot_list` (L1512)
- **Scenarios**:
  1. Success — list of snapshot file stems (basename minus .json), sorted desc → 200 `{items: [...]}`
  2. Empty snapshot dir → 200 `{items: []}`

### GET /v2/snapshot/get_current
- **Handler**: `get_current_snapshot_api` (L1575)
- **Scenarios**:
  1. Success — returns current system state dict → 200
  2. Internal failure → 400

### POST /v2/snapshot/save
- **Handler**: `save_snapshot` (L1585)
- **Scenarios**:
  1. Success — creates timestamped snapshot file → 200
  2. Internal failure → 400
  3. Multiple rapid saves — each creates distinct timestamped file

### POST /v2/snapshot/remove
- **Handler**: `remove_snapshot` (L1521)
- **Security gate**: `middle` → 403
- **Query**: `target` (snapshot file stem)
- **Scenarios**:
  1. Success — removes existing file → 200
  2. Nonexistent target — 200 (no-op)
  3. Path traversal (`../x`) → 400 "Invalid target"
  4. Missing `target` query → exception → 400
  5. Security blocked (level < middle) → 403

### POST /v2/snapshot/restore
- **Handler**: `restore_snapshot` (L1543)
- **Security gate**: `middle+` → 403
- **Query**: `target`
- **Scenarios**:
  1. Success — copies snapshot to startup script path (applied on next reboot) → 200
  2. Nonexistent target → 400
  3. Path traversal → 400 "Invalid target"
  4. Security blocked → 403

## 1.4 Configuration

### GET /v2/manager/db_mode
- **Handler**: `db_mode` (L1907)
- **Scenarios**: Returns plain text current value ∈ {cache, channel, local, remote} → 200

### POST /v2/manager/db_mode
- **Handler**: `set_db_mode_api` (L1912)
- **Body**: `{value: <mode>}`
- **Scenarios**:
  1. Valid value — persists to config.ini → 200
  2. Malformed JSON → 400 "Invalid request"
  3. Missing `value` key → 400 KeyError

### GET /v2/manager/policy/update
- **Handler**: `update_policy` (L1923)
- **Scenarios**: Returns plain text value ∈ {stable, stable-comfyui, nightly, nightly-comfyui} → 200

### POST /v2/manager/policy/update
- **Handler**: `set_update_policy_api` (L1928)
- **Body**: `{value: <policy>}`
- **Scenarios**:
  1. Valid value → persists config → 200
  2. Malformed JSON / missing value → 400

### GET /v2/manager/channel_url_list
- **Handler**: `channel_url_list` (L1939)
- **Scenarios**:
  1. Success — `{selected: name, list: ["name::url", ...]}` → 200
  2. Selected URL doesn't match any channel → `selected="custom"`

### POST /v2/manager/channel_url_list
- **Handler**: `set_channel_url` (L1954)
- **Body**: `{value: <channel_name>}`
- **Scenarios**:
  1. Known channel name → persists new URL → 200
  2. Unknown channel name → no-op → 200 (silent)
  3. Malformed JSON / missing value → 400

## 1.5 System

### GET /v2/manager/is_legacy_manager_ui
- **Handler**: `is_legacy_manager_ui` (L1487)
- **Scenarios**: Returns `{is_legacy_manager_ui: bool}` reflecting `--enable-manager-legacy-ui` flag → 200

### GET /v2/manager/version
- **Handler**: `get_version` (L2009)
- **Scenarios**: Returns plain text `core.version_str` → 200

### POST /v2/manager/reboot
- **Handler**: `restart` (L1968)
- **Security gate**: `middle` → 403
- **Scenarios**:
  1. Success — triggers server process restart via execv → 200 (connection may drop)
  2. `__COMFY_CLI_SESSION__` env set — writes reboot marker + exit(0) instead of execv
  3. Desktop/Windows standalone variant — removes flag before restart
  4. Security blocked → 403

## 1.6 ComfyUI Version Management

### GET /v2/comfyui_manager/comfyui_versions
- **Handler**: `comfyui_versions` (L1825)
- **Scenarios**:
  1. Success — `{versions: [...], current: "<tag or hash>"}` → 200
  2. Git access failure → 400

### POST /v2/comfyui_manager/comfyui_switch_version
- **Handler**: `comfyui_switch_version` (L1840)
- **Security gate**: `high+` → 403
- **Schema**: `ComfyUISwitchVersionParams` — `{ver, client_id, ui_id}` (JSON body; renamed in WI #261, migrated from query string in WI #258)
- **Scenarios**:
  1. Success — queues update-comfyui task with target_version → 200
  2. Missing `ver`/`client_id`/`ui_id` → 400 ValidationError (JSON with `error` field)
  3. Security blocked → 403
  4. Internal exception → 400

---

# Section 2 — Legacy-Only Endpoints (`comfyui_manager/legacy/manager_server.py`)

Endpoints in this section exist **only in the legacy server** (not registered in glob). They are served when `--enable-manager-legacy-ui` is set.

### POST /v2/manager/queue/batch
- **Handler**: `queue_batch` (L740)
- **Body**: dict with keys ∈ {update_all, reinstall, install, uninstall, update, update_comfyui, disable, install_model, fix}, each with a list of per-pack payloads
- **Scenarios**:
  1. Success with single kind (e.g. install) → appends to temp_queue_batch, finalizes, starts worker → 200 `{failed: []}`
  2. Mixed kinds in one batch — processes each sequentially
  3. Partial failure — some packs fail internally → 200 `{failed: [...ids]}`
  4. `update_all` with mode — runs legacy update_all flow inline
  5. `reinstall` — uninstall then install per pack; uninstall failure skips install
  6. `disable` — no security check inside `_disable_node`
  7. `install` with security gate fail → failed set entry
  8. Empty body `{}` → 200 `{failed: []}`

### GET /v2/customnode/getlist
- **Handler**: `fetch_customnode_list` (L1018)
- **Query**: `mode` (required), `skip_update?` (bool string)
- **Scenarios**:
  1. Success — returns `{channel, node_packs}` with installed/update state populated → 200
  2. `skip_update=true` — skips git update check (faster)
  3. Removes comfyui-manager self-entry from results
  4. Channel lookup resolves to 'default'/'custom'/known name

### GET /customnode/alternatives
- **Handler**: `fetch_customnode_alternatives` (L1072)
- **Query**: `mode` (required)
- **Scenarios**:
  1. Success — alter-list.json items keyed by id → 200

### GET /v2/externalmodel/getlist
- **Handler**: `fetch_externalmodel_list` (L1143)
- **Query**: `mode` (required)
- **Scenarios**:
  1. Success — model-list.json with `installed` flag populated per file → 200
  2. HuggingFace sentinel filename — resolves from URL basename
  3. Custom save_path — checks under models/<save_path>

### GET /v2/customnode/versions/{node_name}
- **Handler**: `get_cnr_versions` (L1262)
- **Path param**: `node_name`
- **Scenarios**:
  1. Known CNR pack — returns version list → 200
  2. Unknown pack — 400

### GET /v2/customnode/disabled_versions/{node_name}
- **Handler**: `get_disabled_versions` (L1273)
- **Scenarios**:
  1. Pack has nightly_inactive entry → version list includes "nightly"
  2. Pack has cnr_inactive entries → versions list
  3. No disabled versions → 400

### POST /v2/customnode/install/git_url
- **Handler**: `install_custom_node_git_url` (L1502)
- **Security gate**: `high+` → 403
- **Body**: plain text URL
- **Scenarios**:
  1. Success install → 200
  2. Already installed (skip action) → 200
  3. Clone failure → 400
  4. Security blocked → 403

### POST /v2/customnode/install/pip
- **Handler**: `install_custom_node_pip` (L1522)
- **Security gate**: `high+` → 403
- **Body**: plain text space-separated packages
- **Scenarios**:
  1. Success — pip install completes → 200
  2. Security blocked → 403

### GET /v2/manager/notice
- **Handler**: `get_notice` (L1747)
- **Scenarios**:
  1. Success — fetches GitHub wiki News, returns HTML → 200
  2. GitHub unreachable / non-200 → 200 "Unable to retrieve Notice" (plain text)
  3. No markdown-body div matched → 200 "Unable to retrieve Notice"
  4. Appends ComfyUI/Manager version footer
  5. Desktop variant — uses `__COMFYUI_DESKTOP_VERSION__`
  6. Non-git ComfyUI — prepends "Your ComfyUI isn't git repo" warning
  7. Outdated ComfyUI (required_commit_datetime > current) — prepends "too OUTDATED" warning

---

# Section 3 — Legacy-Shared Endpoints

These paths exist in BOTH glob and legacy files (29 endpoints). Semantics are typically equivalent but implementation may differ; see glob scenarios above. Notable differences:

- **queue/status** (L1379 legacy) — counts from `task_batch_queue[0]` (first batch only), not aggregated across batches like glob
- **queue/start** (L1465 legacy) — calls `finalize_temp_queue_batch()` first, then starts worker thread
- **update_all** (L904 legacy) — returns 401 if worker already running; auto-saves snapshot; uses temp_queue_batch instead of QueueTaskItem
- **update_comfyui** (L1572 legacy) — no params; reads config.update_policy directly; always returns 200
- **reboot** (L1796 legacy) — identical behavior to glob
- **history** (L819 legacy) — only supports `id` query (no client_id/ui_id/pagination)
- **import_fail_info** (L1289 legacy) — no basic dict validation; assumes cnr_id/url present (KeyError otherwise)

---

# Security Level Matrix

| Level | Glob endpoints | Legacy endpoints |
|---|---|---|
| **middle** | snapshot/remove, reboot | snapshot/remove, reboot, _uninstall, _update |
| **middle+** | update_all, snapshot/restore, install_model | update_all, snapshot/restore, _install_custom_node, _install_model |
| **high+** | comfyui_switch_version, _fix_custom_node | comfyui_switch_version, install/git_url, install/pip, non-safetensors model install, _fix |

> Note: `_fix` / `_fix_custom_node` security-level history: `middle` → `high` in commit `c8992e5d` (2026-04-04, which also added a previously-missing gate to the legacy handler); subsequent `high` → `high+` in WI-#235 to align the enforcement gate with the `SECURITY_MESSAGE_HIGH_P` log text (and tighten the gate for a state-mutating fix path). README 'Risky Level Table' has been updated in lockstep.

# Deprecated / Removed

- **GET /v2/customnode/fetch_updates** — glob returns 410; legacy still attempts fetch (may succeed but deprecated in concept)
- **Individual queue/{install,uninstall,update,fix,disable,reinstall,abort_current}** — removed from legacy in recent work (replaced by queue/batch aggregator)
- **GET /manager/notice** (v1, no /v2 prefix) — removed from legacy

---

# CSRF Method-Reject Contract Inventory

**Purpose**: Enumerate the 16 state-changing endpoints that must reject HTTP `GET` after commit `99caef55` (CSRF method-conversion mitigation; CVSS 8.1, reported by XlabAI / Tencent Xuanwu). This inventory supplements `verification_design.md` Section 10 (Goals CSRF-M1 / M2 / M3) and is the authoritative cross-reference for the contract enforced by `tests/e2e/test_e2e_csrf.py`.

**Data Source**: `tests/e2e/test_e2e_csrf.py::STATE_CHANGING_POST_ENDPOINTS` (L92-L109). Pre-99caef55 methods derived from `git log -S` history and the commit body of 99caef55. Security Level column cross-references the Security Level Matrix (§ above, L378-L382).

| # | Endpoint | Pre-99caef55 Method | Post-99caef55 Method | Security Level | Test Reference |
|---|----------|---------------------|----------------------|----------------|----------------|
| 1 | `/v2/manager/queue/start` | GET | POST | default | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/manager/queue/start]` |
| 2 | `/v2/manager/queue/reset` | GET | POST | default | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/manager/queue/reset]` |
| 3 | `/v2/manager/queue/update_all` | GET | POST | middle+ | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/manager/queue/update_all]` |
| 4 | `/v2/manager/queue/update_comfyui` | GET | POST | default | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/manager/queue/update_comfyui]` |
| 5 | `/v2/manager/queue/install_model` | POST | POST (pre-existing) | middle+ | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/manager/queue/install_model]` |
| 6 | `/v2/manager/queue/task` | POST | POST (pre-existing) | default | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/manager/queue/task]` |
| 7 | `/v2/snapshot/save` | GET | POST | default | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/snapshot/save]` |
| 8 | `/v2/snapshot/remove` | GET | POST | middle | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/snapshot/remove]` |
| 9 | `/v2/snapshot/restore` | GET | POST | middle+ | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/snapshot/restore]` |
| 10 | `/v2/manager/reboot` | GET | POST | middle | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/manager/reboot]` |
| 11 | `/v2/comfyui_manager/comfyui_switch_version` | GET | POST | high+ | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/comfyui_manager/comfyui_switch_version]` |
| 12 | `/v2/manager/db_mode` | GET (dual) | POST (write); GET preserved for read | default | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/manager/db_mode]` |
| 13 | `/v2/manager/policy/update` | GET (dual) | POST (write); GET preserved for read | default | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/manager/policy/update]` |
| 14 | `/v2/manager/channel_url_list` | GET (dual) | POST (write); GET preserved for read | default | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/manager/channel_url_list]` |
| 15 | `/v2/customnode/import_fail_info` | POST | POST (pre-existing) | default | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/customnode/import_fail_info]` |
| 16 | `/v2/customnode/import_fail_info_bulk` | POST | POST (pre-existing) | default | `TestStateChangingEndpointsRejectGet::test_get_is_rejected[/v2/customnode/import_fail_info_bulk]` |

**Conversion Breakdown** (reconciles commit 99caef55 body with 16-row fixture):
- **Pure GET → POST conversions**: 9 endpoints (rows 1-4, 7-11) — confirmed write-only operations formerly exposed via GET.
- **Dual-method endpoints** (GET + POST coexist after fix): 3 endpoints (rows 12-14) — the POST variant carries write semantics; GET preserved for read-only retrieval and is covered by Goal CSRF-M3.
- **Pre-existing POST endpoints** (included in the fixture for contract completeness): 4 endpoints (rows 5-6, 15-16) — these were already POST before 99caef55 but remain part of the CSRF rejection contract so any future regression to GET is caught.

**Scope Note**: This inventory narrowly documents the method-restriction layer. Complementary CSRF defenses (Origin/Referer validation, same-site cookies, anti-CSRF tokens, cross-site form POST rejection) are out of scope for this contract and tracked in `verification_design.md` § 10.2.

---
*End of Report A*
