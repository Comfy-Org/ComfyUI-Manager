# Scenario Intent Mapping

**Generated**: 2026-04-18
**Definition of "intent"**: For each scenario — **what real use case, user need, or protection concern does this scenario represent?** Answers "why does this scenario matter, what is it there to prove?"

Intent categories used:
- **User capability** — the user wants to accomplish task X
- **Data integrity** — the system must not corrupt state
- **Security boundary** — privilege / access must be enforced
- **Input resilience** — bad input must not crash or mis-operate
- **Idempotency** — operation can be retried safely
- **Observability** — the caller needs accurate state visibility
- **Concurrency safety** — parallel calls don't interfere
- **Recovery** — system can recover from failure / bad state

---

# Section 1 — Glob v2 Endpoints

## 1.1 Queue Management

### POST /v2/manager/queue/task (install)

| Scenario | Intent |
|---|---|
| Success (CNR) | User capability: install a registered pack at a specific version for reproducibility |
| Success (nightly/URL) | User capability: install unreleased or private pack from arbitrary git URL |
| Success (skip_post_install + already disabled) | Recovery: re-enable a previously disabled pack without full reinstall (optimization path) |
| Validation error (bad kind) | Input resilience: prevent arbitrary op execution via malformed kind; ensure schema gate is the truth |
| Validation error (missing ui_id/client_id) | Observability: every queued task must be traceable back to its originator |
| Invalid JSON body | Input resilience: malformed bytes don't crash the server |
| Worker auto-start | User capability: ease of use — installer doesn't need separate "start" call (legacy path does though) |

### POST /v2/manager/queue/task (uninstall)

| Scenario | Intent |
|---|---|
| Success | User capability: remove a pack that's no longer needed or causing issues |
| Target not installed | Idempotency: uninstall of non-present pack should not fail destructively |

### POST /v2/manager/queue/task (update)

| Scenario | Intent |
|---|---|
| Success | User capability: upgrade to a newer release to get fixes/features |
| Already up-to-date | Idempotency: safe to trigger update even when nothing new exists |
| Update fails mid-way | Data integrity: don't leave pack in partially-updated state |

### POST /v2/manager/queue/task (fix)

| Scenario | Intent |
|---|---|
| Success | Recovery: when dependencies drift or break, re-install them without re-cloning source |
| Missing deps pre-fix | Recovery: fix should heal the environment |

### POST /v2/manager/queue/task (disable)

| Scenario | Intent |
|---|---|
| Success | User capability: temporarily stop using a pack without losing it (reversible) |
| Already disabled | Idempotency: re-disable is a no-op |

### POST /v2/manager/queue/task (enable)

| Scenario | Intent |
|---|---|
| Success | User capability: restore a disabled pack to active use |
| Not disabled | Idempotency: no-op when already active |

### POST /v2/manager/queue/install_model

| Scenario | Intent |
|---|---|
| Success | User capability: download models from curated whitelist for model library |
| Missing client_id/ui_id | Observability: every download is traceable |
| Invalid metadata | Input resilience: malformed model requests rejected early |
| Not in whitelist | Security boundary: prevent arbitrary URL downloads (supply-chain protection) |
| Non-safetensors + lower security | Security boundary: block executable-format model files in lower-trust env |

### POST /v2/manager/queue/update_all

| Scenario | Intent |
|---|---|
| Success | User capability: one-click update of all installed packs |
| Security denied | Security boundary: bulk ops are more risky; require middle+ trust |
| Missing params | Observability: must know who initiated bulk op |
| mode=local | User capability: work offline using cached data |
| Desktop build | Data integrity: don't self-update comfyui-manager in bundled builds |
| Empty active set | Idempotency: safe to run on fresh install with nothing to update |

### POST /v2/manager/queue/update_comfyui

| Scenario | Intent |
|---|---|
| Success | User capability: update ComfyUI core itself |
| Missing params | Observability: traceability |
| stable=true explicit | User capability: override policy for one-off stable update regardless of config |

### POST /v2/manager/queue/reset

| Scenario | Intent |
|---|---|
| Success | Recovery: abort an in-progress batch; clear failed state |
| Already empty | Idempotency: safe to call repeatedly as cleanup |

### POST /v2/manager/queue/start

| Scenario | Intent |
|---|---|
| Worker not running | User capability: explicit trigger for the async worker |
| Already running | Concurrency safety: don't spawn duplicate workers (data corruption risk) |
| Empty queue | Idempotency: no error on empty queue |

### GET /v2/manager/queue/status

| Scenario | Intent |
|---|---|
| No filter | Observability: dashboard view of overall progress |
| client_id filter | Observability: per-client progress for multi-user UI |
| Unknown client_id | Input resilience: unknown id returns 0s, not error |

### GET /v2/manager/queue/history

| Scenario | Intent |
|---|---|
| id=<batch_id> | Observability: inspect an old batch for audit/debug |
| Path traversal | Security boundary: prevent arbitrary file reads via history endpoint |
| ui_id filter | Observability: detailed view for one task |
| client_id filter | Observability: per-client history |
| Pagination | Performance: avoid huge payload on long histories |
| Serialization failure | Input resilience: fail cleanly (400) rather than crash |

### GET /v2/manager/queue/history_list

| Scenario | Intent |
|---|---|
| Success | Observability: enumerate past batches |
| Empty | Idempotency: no crash on empty history dir |
| Path inaccessible | Input resilience: fail cleanly |

## 1.2 Custom Node Info

### GET /v2/customnode/getmappings

| Scenario | Intent |
|---|---|
| Success (mode=local/cache/remote) | User capability: UI resolves "missing nodes in workflow" to recommend packs |
| mode=nickname | User capability: shorter display names for UI |
| Missing mode | Input resilience: require explicit mode choice |

### GET /v2/customnode/fetch_updates (deprecated)

| Scenario | Intent |
|---|---|
| Always 410 | API contract: signal clients to migrate to queue-based flow; don't silently break |

### GET /v2/customnode/installed

| Scenario | Intent |
|---|---|
| mode=default | Observability: current state for UI |
| mode=imported | Observability: startup-time state for diff ("what changed since boot") |
| Empty | Idempotency: no crash on empty install |

### POST /v2/customnode/import_fail_info

| Scenario | Intent |
|---|---|
| Known failed pack | Recovery: show user exact traceback so they can decide fix vs report vs uninstall |
| Unknown pack | Input resilience: 400 rather than empty success (distinguishable) |
| Missing fields / non-dict | Input resilience: reject early |

### POST /v2/customnode/import_fail_info_bulk

| Scenario | Intent |
|---|---|
| cnr_ids list | Performance: batch lookup for dialog that shows multiple failed packs at once |
| urls list | Same, for git-URL-installed packs |
| Empty lists | Input resilience: require at least one query |
| Null for unknown | Observability: distinguish "no failure info" from "lookup failed" |

## 1.3 Snapshots

### GET /v2/snapshot/get_current

| Scenario | Intent |
|---|---|
| Success | Observability: inspect system state before taking a snapshot |
| Failure | Input resilience: fail cleanly |

### POST /v2/snapshot/save

| Scenario | Intent |
|---|---|
| Success | User capability: persist current state for later rollback |
| Multiple saves | Observability: each save is independently retrievable |

### GET /v2/snapshot/getlist

| Scenario | Intent |
|---|---|
| Success | User capability: choose which snapshot to restore/delete |
| Empty | Idempotency: no crash on empty snapshot dir |

### POST /v2/snapshot/remove

| Scenario | Intent |
|---|---|
| Success | User capability: housekeeping (remove old snapshots) |
| Nonexistent target | Idempotency: re-delete should not error |
| Path traversal | Security boundary: prevent deleting files outside snapshot dir |
| Missing target | Input resilience |
| Security denied | Security boundary: middle security required |

### POST /v2/snapshot/restore

| Scenario | Intent |
|---|---|
| Success | Recovery: rollback to a known-good state after bad update |
| Nonexistent | Input resilience |
| Path traversal | Security boundary |
| Security denied | Security boundary: middle+ required (restore is destructive) |

## 1.4 Configuration

### GET /v2/manager/db_mode

| Scenario | Intent |
|---|---|
| Success | Observability: UI shows current mode setting |

### POST /v2/manager/db_mode

| Scenario | Intent |
|---|---|
| Valid | User capability: switch between online/local DB for different network conditions |
| Malformed | Input resilience |
| Missing value | Input resilience: don't silently set unknown/empty |

### GET/POST /v2/manager/policy/update

Same as db_mode: observability of current policy + user choice to change update strategy (stable vs nightly) + input resilience.

### GET /v2/manager/channel_url_list

| Scenario | Intent |
|---|---|
| Success | Observability: show available channels in UI dropdown |
| "custom" selected | Input resilience: URL not in known list doesn't break display |

### POST /v2/manager/channel_url_list

| Scenario | Intent |
|---|---|
| Known name | User capability: switch between upstream vs fork vs private channel |
| Unknown name | Input resilience: silent no-op (don't crash on typo) |
| Malformed | Input resilience |

## 1.5 System

### GET /v2/manager/is_legacy_manager_ui

| Scenario | Intent |
|---|---|
| Success | User capability: frontend picks which UI variant to mount at page load |

### GET /v2/manager/version

| Scenario | Intent |
|---|---|
| Success | Observability: display version in UI (troubleshooting / support) |
| Idempotent | Data integrity: version doesn't change at runtime |

### POST /v2/manager/reboot

| Scenario | Intent |
|---|---|
| Success | User capability: apply changes that require restart (snapshot restore, ComfyUI version switch) |
| CLI session mode | Integration: cooperates with external process manager for clean restart |
| Security denied | Security boundary: middle required (restart affects all users) |

### GET /v2/comfyui_manager/comfyui_versions

| Scenario | Intent |
|---|---|
| Success | User capability: enumerate ComfyUI versions to pick one for rollback/upgrade |
| Git failure | Input resilience: fail cleanly if ComfyUI isn't a git repo |

### POST /v2/comfyui_manager/comfyui_switch_version

| Scenario | Intent |
|---|---|
| Success | User capability: switch ComfyUI to specific version (pin for reproducibility) |
| Missing params | Observability |
| Security denied | Security boundary: high+ required (massive blast radius — affects core behavior) |

---

# Section 2 — Legacy-only Endpoints

### POST /v2/manager/queue/batch

| Scenario | Intent |
|---|---|
| Single-kind batch | User capability: execute multiple operations of same type in one round-trip |
| Mixed-kind batch | User capability: apply a workflow (uninstall-then-install = reinstall) atomically |
| Partial failure (`failed` list) | Observability: distinguish which packs in the batch failed from ones that succeeded |
| Empty body | Idempotency: no-op if nothing to do |
| update_all sub-key | User capability: trigger bulk update as part of batch |

### GET /v2/customnode/getlist

| Scenario | Intent |
|---|---|
| Success | User capability: populate Custom Nodes Manager dialog with full available pack catalog |
| skip_update=true | Performance: fast load when user doesn't need remote fetch |
| Channel resolution | Observability: user sees which channel data came from |

### GET /customnode/alternatives

| Scenario | Intent |
|---|---|
| Success | User capability: recommend alternative packs when one is discontinued/unavailable |

### GET /v2/externalmodel/getlist

| Scenario | Intent |
|---|---|
| Success | User capability: browse curated model catalog |
| `installed` flag per model | Observability: which models already present |
| HuggingFace sentinel | User capability: HF-hosted models via standard URL |
| Custom save_path | User capability: custom model placement |

### GET /v2/customnode/versions/{node_name}

| Scenario | Intent |
|---|---|
| Known CNR | User capability: pick a specific version to install (stability over latest) |
| Unknown pack | Input resilience |

### GET /v2/customnode/disabled_versions/{node_name}

| Scenario | Intent |
|---|---|
| Has disabled | User capability: see what versions are available to re-enable without fresh install |
| None | Input resilience |

### POST /v2/customnode/install/git_url

| Scenario | Intent |
|---|---|
| Success | User capability: install arbitrary git pack (for advanced users / private packs) |
| Already installed | Idempotency |
| Clone failure | Input resilience: bad URL returns error; no corrupt state |
| Security denied | Security boundary: high+ required (arbitrary code execution risk) |

### POST /v2/customnode/install/pip

| Scenario | Intent |
|---|---|
| Success | User capability: install pip packages needed by a pack |
| Security denied | Security boundary: high+ required (arbitrary package execution risk) |

### GET /v2/manager/notice

| Scenario | Intent |
|---|---|
| GitHub reachable | User capability: see latest Manager news/changelog inline |
| GitHub unreachable | Input resilience: don't block UI on external service failure |
| Non-git ComfyUI | Observability: warn user that their install is non-standard |
| Outdated ComfyUI | Observability: warn user they're too old to be safe |
| Desktop variant | User capability: correct footer for desktop distribution |

---

# Section 3 — Cross-cutting Scenarios

Some scenarios recur across many endpoints with consistent intent:

| Scenario pattern | Applies to | Unified intent |
|---|---|---|
| Malformed JSON body | all POST endpoints accepting JSON | Input resilience — protect against corrupted bytes / wrong content-type |
| Missing required field | all POST endpoints with schemas | Input resilience + Observability (traceability fields mandatory) |
| Path traversal in target/id | snapshot/remove, snapshot/restore, queue/history | Security boundary — prevent arbitrary filesystem access |
| Security level denial (middle/middle+/high+) | destructive endpoints | Security boundary — tier privileged ops per deployment risk profile |
| Idempotent re-call on empty state | queue/reset, history_list, snapshot/getlist, installed | Idempotency — safe to poll or retry |
| Repeated read returns same value | version, db_mode, policy/update | Data integrity — config/runtime state is stable |
| Empty collection returned cleanly | history, getlist, installed, alternatives | Input resilience — empty is valid, not an error |

---

# Section 4 — Intent Coverage Summary

| Intent category | # scenarios | Notes |
|---|---:|---|
| User capability (positive user need) | 62 | The "happy paths" |
| Input resilience | 32 | Mostly 400s for bad input |
| Security boundary | 15 | Security levels + path traversal |
| Idempotency | 14 | No-op / retry safety |
| Observability | 16 | State visibility + traceability |
| Data integrity | 8 | Config/state stability |
| Recovery | 5 | Fix, restore, reset |
| Concurrency safety | 2 | Worker dedup |

Total unique scenarios mapped: ~154 (matches Report A).

---

# Section 5 — Why This Mapping Matters

For each scenario, the **intent** drives the TEST design:
- **User capability** scenarios need end-to-end effect verification (feature works as promised)
- **Input resilience** scenarios need negative tests (bad inputs rejected cleanly)
- **Security boundary** scenarios need permission gate tests (403 proven per security level)
- **Idempotency** scenarios need repeat-call tests (no state drift)
- **Observability** scenarios need response-correctness tests (UI can trust the data)
- **Data integrity** scenarios need consistency tests (no runtime mutation of constants)
- **Recovery** scenarios need fault-injection tests (broken state → fix heals it)
- **Concurrency safety** scenarios need parallel-call tests (no duplicate workers/tasks)

Gaps in current E2E suite are best understood by intent: missing tests are typically for **security boundary** (403 gates), **input resilience edge cases** (path traversal, missing value keys), and **recovery** (fix/restore). These are the hardest to reach in simple E2E but matter most for production safety.

---
*End of Scenario Intent Mapping*
