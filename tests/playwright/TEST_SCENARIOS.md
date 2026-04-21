# Legacy UI Playwright E2E — Test Scenarios

Scenario list based on the actual API call flow of the Legacy UI (runtime-verified).

## URL Convention

ComfyUI's `api.fetchApi()` automatically prepends the `/api` prefix to every path.
- JS call: `fetchApi('/v2/manager/db_mode')` → actual request: `GET /api/v2/manager/db_mode`
- When intercepted by Playwright `route`, the URL is captured in the `/api/v2/...` form.

## Install Flow (Runtime-verified)

```
[Install button click]
  → GET /api/v2/customnode/versions/{id}     ← list available versions
  → Version-selection dialog (<select multiple> + "Select"/"Cancel")
  → "Select" click
  → POST /api/v2/manager/queue/batch         ← actual install request
       body: {"install":[{...nodeData, selected_version:"latest"}], "batch_id":"uuid"}
  → WebSocket push: cm-queue-status
       {status:"in_progress", done_count, total_count}
       {status:"batch-done", nodepack_result:{"hash":"success"}}
       {status:"all-done"}
```

---

## 1. API calls at Manager Menu initialization

**File**: `legacy-ui-manager-menu.spec.ts` (existing + enhanced)

5 API calls made concurrently when the Manager Menu opens (runtime-verified):

| # | Scenario | Assertion | Endpoint |
|---|---------|------|----------|
| 1-1 | DB mode loading | Dropdown value shown | `GET /api/v2/manager/db_mode` |
| 1-2 | Channel list loading | Dropdown options shown | `GET /api/v2/manager/channel_url_list` |
| 1-3 | Update policy loading | Dropdown value shown | `GET /api/v2/manager/policy/update` |
| 1-4 | Notice loading | Right panel text is non-empty | `GET /api/v2/manager/notice` |
| 1-5 | DB mode change round-trip | POST → GET verification | `POST /api/v2/manager/db_mode` |
| 1-6 | Policy change round-trip | POST → GET verification | `POST /api/v2/manager/policy/update` |
| 1-7 | Channel change round-trip | POST → GET verification | `POST /api/v2/manager/channel_url_list` |

## 2. Custom Nodes Manager — list retrieval

**File**: `legacy-ui-custom-nodes.spec.ts` (existing + enhanced)

2 API calls made when the Custom Nodes Manager opens (runtime-verified):

| # | Scenario | UI action | Assertion | Endpoint |
|---|---------|---------|------|----------|
| 2-1 | List loading (cache) | Open Custom Nodes Manager | Grid rows > 0 | `GET /api/v2/customnode/getlist?mode=cache&skip_update=true` |
| 2-2 | Mapping loading | (concurrent with list) | Request observed | `GET /api/v2/customnode/getmappings?mode=cache` |
| 2-3 | Installed filter | Filter → "Installed" | rows ≤ All | Client-side filter |
| 2-4 | Not Installed filter | Filter → "Not Installed" | rows > 0 | Client-side filter |
| 2-5 | Import Failed filter | Filter → "Import Failed" | Filter works | Client-side filter |
| 2-6 | Check Update | "Check Update" button | Filter flips to "Update", API re-called | `GET /api/v2/customnode/getlist?mode=cache` (no `skip_update`) |
| 2-7 | Check Missing | "Check Missing" button | Filter flips to "Missing" | `GET /api/v2/customnode/getmappings?mode=cache` |
| 2-8 | Alternatives filter | Filter → "Alternatives of A1111" | Data loads | `GET /api/customnode/alternatives?mode=cache` |

## 3. Full node install lifecycle

**File**: `legacy-ui-node-lifecycle.spec.ts` (new)

Install flow: Install button → versions API → version-selection dialog → Select → queue/batch → WebSocket status push

| # | Scenario | UI action | Assertion | Endpoint |
|---|---------|---------|------|----------|
| 3-1 | Install — version query | "Not Installed" → "Install" click | Version-list dialog appears | `GET /api/v2/customnode/versions/{id}` |
| 3-2 | Install — select version + send batch | Pick version in `<select>` → "Select" click | `queue/batch` called with `install` key in body | `POST /api/v2/manager/queue/batch` |
| 3-3 | Install — WebSocket status | Install runs | `cm-queue-status` messages: in_progress → batch-done → all-done | WebSocket |
| 3-4 | Uninstall | "Installed" → "Uninstall" click → confirm dialog "OK" | `uninstall` key in batch body | `POST /api/v2/manager/queue/batch` |
| 3-5 | Disable | "Installed" → "Disable" click | `disable` key in batch body | `POST /api/v2/manager/queue/batch` |
| 3-6 | Enable | "Disabled" → "Enable" click → pick version | `install` key + `skip_post_install:true` in batch body | `GET disabled_versions/{id}` → `POST queue/batch` |
| 3-7 | Update | "Installed" → "Try update" click | `update` key in batch body | `POST /api/v2/manager/queue/batch` |
| 3-8 | Fix | import-fail node → "Try fix" click | `fix` key in batch body (skip if none) | `POST /api/v2/manager/queue/batch` |

## 4. Version management

**File**: `legacy-ui-node-versions.spec.ts` (new)

| # | Scenario | UI action | Assertion | Endpoint |
|---|---------|---------|------|----------|
| 4-1 | Installed node version list | "Installed" → "Switch Ver" click | Version list shown in `<select multiple>` dialog | `GET /api/v2/customnode/versions/{id}` |
| 4-2 | Disabled node version list | "Disabled" → "Enable" click | `disabled_versions` call observed | `GET /api/v2/customnode/disabled_versions/{id}` |

## 5. Batch operations + stop

**File**: `legacy-ui-batch-operations.spec.ts` (new)

| # | Scenario | UI action | Assertion | Endpoint |
|---|---------|---------|------|----------|
| 5-1 | Update All | Manager Menu → "Update All" click | `update_all` key in batch body | `POST /api/v2/manager/queue/batch` |
| 5-2 | Update ComfyUI | Manager Menu → "Update ComfyUI" click | `update_comfyui` key in batch body | `POST /api/v2/manager/queue/batch` |
| 5-3 | Stop (Manager Menu) | "Restart" toggle → "Stop" click | `queue/reset` invoked | `POST /api/v2/manager/queue/reset` |
| 5-4 | Stop (Custom Nodes Manager) | "Stop" button click | `queue/reset` invoked | `POST /api/v2/manager/queue/reset` |

Note: `queue/abort_current` is not called directly from JS (server-only). Stop uses `queue/reset`.

## 6. Git URL / PIP install

**File**: `legacy-ui-install-methods.spec.ts` (new)

| # | Scenario | UI action | Assertion | Endpoint |
|---|---------|---------|------|----------|
| 6-1 | Git URL install | "Install via Git URL" → enter URL → confirm | 200 or 403 | `POST /api/v2/customnode/install/git_url` |
| 6-2 | Git URL cancel | "Install via Git URL" → cancel | No API call | — |
| 6-3 | PIP package install | "Install PIP packages" → enter package name | 200 or 403 | `POST /api/v2/customnode/install/pip` |

## 7. Import failure details

**File**: `legacy-ui-custom-nodes.spec.ts` (enhanced)

| # | Scenario | UI action | Assertion | Endpoint |
|---|---------|---------|------|----------|
| 7-1 | Import failure details | "Import Failed" filter → "IMPORT FAILED ↗" click | Error dialog appears | `POST /api/v2/customnode/import_fail_info` |

Note: skipped when no import-failed nodes are present.

## 8. Model management

**File**: `legacy-ui-model-manager.spec.ts` (existing + enhanced)

| # | Scenario | UI action | Assertion | Endpoint |
|---|---------|---------|------|----------|
| 8-1 | Model list loading | Open Model Manager | Grid rows > 0 | `GET /api/v2/externalmodel/getlist?mode=cache` |
| 8-2 | Model search | Enter query | Grid filtered | Client-side filter |
| 8-3 | Model install | Row's "Install" click | `install_model` key in batch body | `POST /api/v2/manager/queue/batch` |

## 9. Full snapshot lifecycle

**File**: `legacy-ui-snapshot.spec.ts` (existing + enhanced)

| # | Scenario | UI action | Assertion | Endpoint |
|---|---------|---------|------|----------|
| 9-1 | Snapshot list | Open Snapshot Manager | Table rows shown | `GET /api/v2/snapshot/getlist` |
| 9-2 | Snapshot save | "Save snapshot" click | "Current snapshot saved" message | `POST /api/v2/snapshot/save` |
| 9-3 | Snapshot restore | "Restore" click | 200 or 403, RESTART button shown | `POST /api/v2/snapshot/restore?target=X` |
| 9-4 | Snapshot remove | "Remove" click | Row removed from list | `POST /api/v2/snapshot/remove?target=X` |

## 10. Dialog navigation

**File**: `legacy-ui-navigation.spec.ts` (existing)

| # | Scenario | Assertion |
|---|---------|------|
| 10-1 | Manager → Custom Nodes → close → re-open Manager | Dialog transitions cleanly |
| 10-2 | Manager → Model Manager → close → re-open | Dialog transitions cleanly |
| 10-3 | API call while dialog is open | Server responds normally |
| 10-4 | Legacy UI enabled check | `is_legacy_manager_ui: true` |

---

## File composition summary

| File | New/Enhanced | Scenarios | Target Endpoints |
|------|----------|:-------:|---------------|
| `legacy-ui-manager-menu.spec.ts` | enhanced | 7 | db_mode, channel_url_list, policy/update, notice |
| `legacy-ui-custom-nodes.spec.ts` | enhanced | 9 | getlist, getmappings, alternatives, import_fail_info |
| `legacy-ui-node-lifecycle.spec.ts` | **new** | 8 | versions/{id}, disabled_versions/{id}, queue/batch (install/uninstall/update/fix/disable/enable) |
| `legacy-ui-node-versions.spec.ts` | **new** | 2 | versions/{id}, disabled_versions/{id} |
| `legacy-ui-batch-operations.spec.ts` | **new** | 4 | queue/batch (update_all, update_comfyui), queue/reset |
| `legacy-ui-install-methods.spec.ts` | **new** | 3 | install/git_url, install/pip |
| `legacy-ui-model-manager.spec.ts` | enhanced | 3 | externalmodel/getlist, queue/batch (install_model) |
| `legacy-ui-snapshot.spec.ts` | enhanced | 4 | snapshot/getlist, save, restore, remove |
| `legacy-ui-navigation.spec.ts` | existing | 4 | is_legacy_manager_ui, version |

**Total: 44 scenarios**

## Legacy-only endpoint coverage

| Endpoint | Scenarios |
|----------|---------|
| `GET /api/v2/customnode/getlist` | 2-1, 2-6 |
| `GET /api/v2/customnode/getmappings` | 2-2, 2-7 |
| `GET /api/customnode/alternatives` | 2-8 |
| `GET /api/v2/customnode/versions/{id}` | 3-1, 4-1 |
| `GET /api/v2/customnode/disabled_versions/{id}` | 3-6, 4-2 |
| `POST /api/v2/customnode/import_fail_info` | 7-1 |
| `POST /api/v2/customnode/install/git_url` | 6-1 |
| `POST /api/v2/customnode/install/pip` | 6-3 |
| `GET /api/v2/externalmodel/getlist` | 8-1 |
| `POST /api/v2/manager/queue/batch` | 3-2, 3-4~3-8, 5-1, 5-2, 8-3 |
| `POST /api/v2/manager/queue/reset` | 5-3, 5-4 |
| `GET /api/v2/manager/notice` | 1-4 |
| `GET /api/v2/snapshot/getlist` | 9-1 |
| `POST /api/v2/snapshot/save` | 9-2 |
| `POST /api/v2/snapshot/restore` | 9-3 |
| `POST /api/v2/snapshot/remove` | 9-4 |

## Exclusions

- `share_option` — per user instruction
- **External-service auth/integration** (9 endpoints) — external services are unreachable from E2E
- **Individual queue endpoints** (6) — unused by JS; delegated internally through `queue/batch`
- `queue/abort_current` — unused by JS (Stop uses `queue/reset`)
- `/manager/notice` (v1) — superseded by v2

## API call verification method

Capture the actual API call sequence via Playwright `page.route('**/*')` interception.
Verify job progress/completion via the `cm-queue-status` WebSocket event.
