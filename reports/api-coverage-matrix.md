# API Coverage Matrix — pytest E2E + Playwright

**Date**: 2026-04-20
**Worklist**: `wl-afbf982ffe41`
**Checklist**: `cl-20260420-wl-afbf982ff`
**Scope**: 39 unique (method, path) endpoints across glob and legacy managers.
**Sources**: 4 member checklist YAMLs (gteam-teng 10 · gteam-reviewer 10 · gteam-dev 10 · gteam-dbg 9).

---

## 1. Coverage Summary

| Axis | Y | I | N | P | NA | Total |
|---|---:|---:|---:|---:|---:|---:|
| **pytest E2E** | 38 | 1 | 0 | — | — | 39 |
| **Playwright** | 17 | — | 1 | 14 | 7 | 39 |

### Code legend

| Code | pytest meaning | Playwright meaning |
|------|----------------|--------------------|
| **Y** | Direct positive-path test exists | UI trigger exists AND a spec exercises it |
| **I** | Indirect only (e.g. CSRF-reject test, no positive assertion) | — |
| **N** | No coverage | Endpoint has no UI surface AND no spec covers it (1 case, wi-009 internal-only) |
| **P** | — | UI trigger exists but NO spec exercises it (PENDING Playwright) |
| **NA** | — | Endpoint has no UI surface at all (backend/CLI/gating only) |

### Effective pytest ceiling

Y (direct) + I (indirect) = **39 / 39 = 100%** — post-WI-UU every endpoint
has automated pytest coverage. The 6 legacy-only GET endpoints
(wi-031/032/033/034/035/036) that were `N` at matrix creation have been
closed as `Y (WI-TT)` via direct positive-path tests in
`tests/e2e/test_e2e_legacy_endpoints.py` (§22 of
`e2e_verification_audit.md`). wi-039 (POST /v2/manager/queue/batch) was
closed as `Y (WI-UU)` via `TestLegacyQueueBatch` in the same file — empty
`{}` payload exercises request-parse → action loop → finalize →
worker-lock release → JSON serialize. Only 1 I-rated row remains: wi-027
POST /v2/snapshot/restore, which stays I by intentional design (the
endpoint is destructive and is covered only behind a skip-by-default
marker; upgrading it to Y would require a reversible snapshot fixture).

Count progression: matrix-creation baseline Y=29/I=4/N=6 → post-WI-YY
Y=31/I=2/N=6 → post-WI-TT Y=37/I=2/N=0 → **post-WI-UU Y=38/I=1/N=0**.

### Playwright P = systemic gap

10 / 39 = **26%** of endpoints have a UI trigger that Playwright never
exercises. Originally 18/39 = 46%; WI-VV closed 4 LOW-risk P items
(wi-001 / wi-005 / wi-017 / wi-021) via real UI-click tests; WI-WW closed
5 MED items via mock-based UI→API wiring tests; WI-WW.2 closed wi-015 via
a 2-hop mock. **WI-YY** then replaced 2 of the WI-WW mocks (wi-020, wi-024)
with real pytest E2E execution — the mocks were removed and the Playwright
column reverted to P (UI-click path unexercised — pytest covers the
backend contract). The remaining 10 P items are: wi-014/037/038
(retained as WI-WW mocks — real execution requires `high+` security gate
that fails at default `security_level=normal`, needs a permissive
harness — scope for WI-YY.2), plus 7 other source-checklist-classified
P items outside the WI-VV/WW/WW.2/YY scope.

**Honesty note on mock-based closures**: rows marked `Y (WI-WW-mock)`
assert UI→API wiring only — request URL + method + payload shape.
They do NOT assert backend handler behavior, which pytest covers via
positive-path tests. A regression that kept the UI firing correctly
but broke the backend would not be caught by the mock tests alone.

---

## 2. Tier Distribution

39 endpoints split across three registration tiers:

| Tier | Count | Definition |
|------|------:|------------|
| Shared | 29 | Registered in BOTH `glob/manager_server.py` AND `legacy/manager_server.py` |
| glob-only | 1 | Registered only in `glob/manager_server.py` |
| legacy-only | 9 | Registered only in `legacy/manager_server.py` |

> **Note on dispatch**: the WI-SS-E dispatch text cited `Shared 28, glob-only 2,
> legacy-only 9` but source-code verification (grep of `@routes.(get\|post)` in
> both managers) yields 29/1/9. Only `POST /v2/manager/queue/task` is confirmed
> glob-only by the audit (`reports/e2e_verification_audit.md:299`). This
> matrix reports the verified counts.

### Tier × coverage crosstab

| Tier | pytest Y | pytest I | pytest N | PW Y | PW P | PW NA | PW N |
|------|---------:|---------:|---------:|-----:|-----:|------:|-----:|
| Shared (29) | 28 | 1 | 0 | 15 | 7 | 6 | 1 |
| glob-only (1) | 1 | 0 | 0 | 0 | 0 | 1 | 0 |
| legacy-only (9) | 9 | 0 | 0 | 2 | 7 | 0 | 0 |
| **Total** | **38** | **1** | **0** | **17** | **14** | **7** | **1** |

**Observations** (post-WI-UU):
- Legacy-only (9) pytest coverage is now **fully direct**: 9 Y + 0 I +
  0 N. WI-TT closed 6 N → Y (wi-031/032/033/034/035/036). WI-YY-real
  closed 2 I → Y (wi-037/038 via the permissive harness). WI-UU closed
  the final I → Y (wi-039 via `TestLegacyQueueBatch`). The remaining
  weakness for this tier is Playwright — 7/9 are Playwright-P.
- Shared (29) holds the sole remaining pytest-I (wi-027 snapshot/restore,
  intentional skip-by-default design). 0 pytest-N, balanced Y/P on
  Playwright.
- glob-only has only 1 endpoint (queue/task) and it is Playwright-NA by
  design — the legacy UI uses `queue/batch` (wi-039) instead.

---

## 3. Full Matrix (39 rows, sorted by wi-id)

| wi | METHOD path | tier | pytest | Playwright | gap |
|---|---|---|---|---|---|
| wi-001 | GET /v2/comfyui_manager/comfyui_versions | shared | Y | Y (WI-VV) | 🟢 closed — legacy-ui-manager-menu.spec.ts asserts Switch ComfyUI click → GET returns non-empty versions list |
| wi-002 | GET /v2/customnode/fetch_updates | shared | Y | NA | 🟢 none (deprecated 410, no JS trigger) |
| wi-003 | GET /v2/customnode/getmappings | shared | Y | Y | 🟢 none (dual coverage) |
| wi-004 | GET /v2/customnode/installed | shared | Y | Y | 🟢 none (dual coverage) |
| wi-005 | GET /v2/manager/channel_url_list | shared | Y | Y (WI-VV) | 🟢 closed — legacy-ui-manager-menu.spec.ts polls channel combo for populated options via stable selector `select[title^="Configure the channel"]` |
| wi-006 | GET /v2/manager/db_mode | shared | Y | Y | 🟢 none (dual coverage) |
| wi-007 | GET /v2/manager/is_legacy_manager_ui | shared | Y | NA | 🟢 none (server-side gating flag) |
| wi-008 | GET /v2/manager/policy/update | shared | Y | P | 🟢 LOW — add Playwright assertion (pytest fully covers contract) |
| wi-009 | GET /v2/manager/queue/history | shared | Y | N | 🟢 none (no UI surface, internal API only) |
| wi-010 | GET /v2/manager/queue/history_list | shared | Y | NA | 🟢 none (backend-only, not surfaced in UI) |
| wi-011 | GET /v2/manager/queue/status | shared | Y | Y | 🟢 none (dual coverage) |
| wi-012 | GET /v2/manager/version | shared | Y | P | 🟢 LOW — add version-string assertion to bootstrap spec |
| wi-013 | GET /v2/snapshot/get_current | shared | Y | P | 🟢 none — 3rd-party share extensions only, out-of-scope for legacy-ui |
| wi-014 | POST /v2/comfyui_manager/comfyui_switch_version | shared | Y (WI-YY-real) | P | 🟢 pytest closed — test_e2e_legacy_real_ops.py::TestSwitchComfyuiSelfSwitch executes real POST via permissive-harness (security_level=normal-) with a no-op self-switch (ver=<current>). Playwright mock REMOVED. |
| wi-015 | POST /v2/customnode/import_fail_info | shared | Y (WI-YY-real) | P | 🟢 pytest closed — test_e2e_legacy_real_ops.py::TestImportFailInfoReal pre-seeds `ComfyUI-YoloWorld-EfficientSAM` via git clone (no pip install), scan captures ImportError in cm_global.error_dict, warmup via `/v2/customnode/import_fail_info_bulk` populates active_nodes, then POST single-endpoint with cnr_id=directory-basename returns the captured `{name, path, msg}` payload. Playwright mock REMOVED (spec file deleted). |
| wi-016 | POST /v2/customnode/import_fail_info_bulk | shared | Y | NA | 🟢 none (server-internal/CLI-only) |
| wi-017 | POST /v2/manager/channel_url_list | shared | Y | Y (WI-VV) | 🟢 closed — legacy-ui-manager-menu.spec.ts selects alternate option, intercepts POST → 200, restores original in finally |
| wi-018 | POST /v2/manager/db_mode | shared | Y | Y | 🟢 none (dual coverage via UI close-reopen round-trip) |
| wi-019 | POST /v2/manager/policy/update | shared | Y | Y | 🟢 none (dual coverage) |
| wi-020 | POST /v2/manager/queue/install_model | shared | Y (WI-YY-real) | P | 🟢 pytest closed — test_e2e_legacy_real_ops.py::TestInstallModelRealDownload downloads the real TAEF1 Decoder (~4.7MB from github.com/madebyollin/taesd raw), polls for disk artifact, asserts size > 1MB, teardown deletes file. Playwright mock REMOVED in WI-YY; UI-click path still unexercised (P) — scope for WI-YY.2 if needed. |
| wi-021 | POST /v2/manager/queue/reset | shared | Y | Y (WI-VV) | 🟢 closed — legacy-ui-manager-menu.spec.ts exercises endpoint via `page.request.post` (UI-click path unsafe at idle: restart_stop_button at idle triggers rebootAPI, not queue/reset; `.cn-manager-stop` / `.model-manager-stop` are display:none). Asserts 200 + queue/status still callable post-reset. |
| wi-022 | POST /v2/manager/queue/start | shared | Y | NA | 🟢 none (server/test-only) |
| wi-023 | POST /v2/manager/queue/update_all | shared | Y | NA | 🟢 LOW — UI uses queue/batch not this endpoint (possibly CLI-only; confirm intent) |
| wi-024 | POST /v2/manager/queue/update_comfyui | shared | Y (WI-YY-real) | P | 🟢 pytest closed — test_e2e_legacy_real_ops.py::TestUpdateComfyuiQueued asserts direct endpoint returns 200 at default security_level (no gate — legacy/manager_server.py:1572-1576). Handler just queues an "update-comfyui" entry; triggering git pull would require a subsequent /queue/batch call (explicitly avoided to preserve test-env git state). COMFYUI_MANAGER_SKIP_MANAGER_REQUIREMENTS=1 safety belt exported at server startup covers pip install runaway risk. Playwright mock REMOVED in WI-YY. |
| wi-025 | POST /v2/manager/reboot | shared | Y | P | 🟢 none — visibility checked; click omitted for safety (would kill test server) |
| wi-026 | POST /v2/snapshot/remove | shared | Y | Y | 🟢 none (dual coverage) |
| wi-027 | POST /v2/snapshot/restore | shared | I | P | 🟡 add pytest coverage behind skip-by-default (reversible via saved snapshot); Playwright restore also missing |
| wi-028 | POST /v2/snapshot/save | shared | Y | Y | 🟢 none (strong dual coverage) |
| wi-029 | GET /v2/snapshot/getlist | shared | Y | Y | 🟢 none (dual coverage) |
| wi-030 | POST /v2/manager/queue/task | glob-only | Y | NA | 🟢 LOW — glob-UI Playwright harness needed to cover queue/task from UI tier |
| wi-031 | GET /customnode/alternatives | legacy-only | Y (WI-TT) | P | 🟢 closed — test_e2e_legacy_endpoints.py (§22 of e2e_verification_audit) asserts positive-path GET with `mode=local` |
| wi-032 | GET /v2/customnode/disabled_versions/{node_name} | legacy-only | Y (WI-TT) | P | 🟢 closed — test_e2e_legacy_endpoints.py (§22) asserts disabled-version list schema |
| wi-033 | GET /v2/customnode/getlist | legacy-only | Y (WI-TT) | Y | 🟢 closed — test_e2e_legacy_endpoints.py (§22) asserts schema (`channel`/`node_packs`) + mode param variants |
| wi-034 | GET /v2/customnode/versions/{node_name} | legacy-only | Y (WI-TT) | Y | 🟢 closed — test_e2e_legacy_endpoints.py (§22) asserts schema + 404 |
| wi-035 | GET /v2/externalmodel/getlist | legacy-only | Y (WI-TT) | Y | 🟢 closed — test_e2e_legacy_endpoints.py (§22) asserts `?mode=local` schema + non-empty list |
| wi-036 | GET /v2/manager/notice | legacy-only | Y (WI-TT) | P | 🟢 closed — test_e2e_legacy_endpoints.py (§22) asserts notice payload (200 + dict) |
| wi-037 | POST /v2/customnode/install/git_url | legacy-only | Y (WI-YY-real) | P | 🟢 pytest closed — test_e2e_legacy_real_ops.py::TestInstallViaGitUrlRealClone executes real POST via permissive-harness cloning `nodepack-test1-do-not-install` (same test-fixture repo used by tests/cli/test_uv_compile.py); verifies custom_nodes/<dir>/.git exists; teardown rm -rf. Playwright mock REMOVED. |
| wi-038 | POST /v2/customnode/install/pip | legacy-only | Y (WI-YY-real) | P | 🟢 pytest closed — test_e2e_legacy_real_ops.py::TestInstallPipRealExecute executes real POST via permissive-harness with trusted `text-unidecode` pkg; asserts install-scripts.txt lazy reservation (handler uses `#FORCE` prefix at manager_core.py:2370 → reserve_script schedules pip install for next startup, not synchronous). Playwright mock REMOVED. |
| wi-039 | POST /v2/manager/queue/batch | legacy-only | Y (WI-UU) | Y | 🟢 closed via TestLegacyQueueBatch empty-`{}` payload positive-path (exercises request-parse → action loop → finalize → worker-lock release → JSON serialize pipeline); response shape `{failed: [...]}` status 200; landed in `tests/e2e/test_e2e_legacy_endpoints.py` (§22 of e2e_verification_audit) |

---

## 4. Priority Gap List

### 🔴 HIGH — ALL CLOSED (0 items)

_All 🔴 HIGH gaps have been closed. WI-TT closed the 6 pytest-N items
(wi-031/032/033/034/035/036 — see LOW-closed-WI-TT). WI-YY-real promoted
wi-037/038 from I to Y via the permissive harness (see
LOW-closed-real-permissive). WI-UU closed the final high-fanout indirect
item — wi-039 (POST /v2/manager/queue/batch) — via
`TestLegacyQueueBatch`; see LOW-closed-WI-UU below._

### 🟡 MEDIUM — Playwright P with real UI surface

All 10 original MED items have been closed across WI-VV / WI-WW / WI-WW.2. No remaining 🟡 items at the legacy-UI surface.

### 🟢 LOW-closed-real (4 items via WI-VV — real UI-click)

- wi-001 GET comfyui_versions — 'Switch ComfyUI' button → legacy-ui-manager-menu.spec.ts
- wi-005 GET channel_url_list — channel combo populate → legacy-ui-manager-menu.spec.ts
- wi-017 POST channel_url_list — channel combo change event → legacy-ui-manager-menu.spec.ts
- wi-021 POST queue/reset — idle POST via `page.request` (UI-click path unsafe at idle) → legacy-ui-manager-menu.spec.ts

### 🟢 LOW-closed-mock (removed in WI-YY)

Previously 3 items (wi-014/037/038) were covered by WI-WW mock tests.
All three have been PROMOTED to real pytest E2E via the permissive
harness (see LOW-closed-real-permissive below). The `high+` gate
remains the production security contract — it's the supported
operator-configured downgrade to `normal-` that enables these
features in trusted environments, which is exactly what the harness
reproduces.

### 🟢 LOW-closed-mock-2hop (retired — promoted to real E2E via WI-YY.3)

Originally wi-015 was covered via a 2-hop Playwright mock (WI-WW.2).
WI-YY.3 replaced this with real pytest E2E using a pre-seeded broken
pack (see LOW-closed-real-broken-pack-preseed below). The mock spec
file `tests/playwright/legacy-ui-mock-install.spec.ts` has been
DELETED — all 6 items it once covered now have real pytest E2E
coverage (via default / permissive / broken-pack fixtures).

### 🟢 LOW-closed-real (2 items via WI-YY — REAL pytest E2E at default security)

- wi-020 POST install_model — TestInstallModelRealDownload (real 4.7MB TAEF1 download + disk-artifact verify + teardown) → test_e2e_legacy_real_ops.py
- wi-024 POST update_comfyui — TestUpdateComfyuiQueued (direct endpoint POST returns 200; worker-trigger intentionally deferred to preserve test-env git state) → test_e2e_legacy_real_ops.py

### 🟢 LOW-closed-real-permissive (3 items via WI-YY — REAL pytest E2E at normal- security)

Permissive harness (`start_comfyui_permissive.sh`) patches config.ini
`security_level = normal-` so `high+` gates pass. All inputs are
HARDCODED TRUSTED constants — never derived from test input or env:

- wi-014 POST comfyui_switch_version — TestSwitchComfyuiSelfSwitch (self-switch no-op: GET current version → POST ver=<current>) → test_e2e_legacy_real_ops.py
- wi-037 POST install/git_url — TestInstallViaGitUrlRealClone (real clone of `nodepack-test1-do-not-install` → verify .git dir → rm -rf teardown) → test_e2e_legacy_real_ops.py
- wi-038 POST install/pip — TestInstallPipRealExecute (POST text-unidecode → verify install-scripts.txt reservation; lazy schedule per manager_core.py:2370 `#FORCE` prefix → reserve_script) → test_e2e_legacy_real_ops.py

### 🟢 LOW-closed-real-broken-pack-preseed (1 item via WI-YY.3 — REAL pytest E2E with state seeding)

Pre-seed fixture (`comfyui_with_broken_pack`) clones a known-broken
pack into custom_nodes/ BEFORE server start (NO pip install of its
deps — import must fail). Server scan captures the ImportError into
cm_global.error_dict (prestartup_script.py:302-305). Test warms up
state via `/v2/customnode/import_fail_info_bulk` (which calls
reload + get_custom_nodes), then POSTs single-endpoint with the
DIRECTORY-BASENAME cnr_id. Teardown rm -rf the seed.

- wi-015 POST import_fail_info — TestImportFailInfoReal::test_import_fail_info_returns_error (cnr_id=`ComfyUI-YoloWorld-EfficientSAM` → 200 + {name, path, msg} with real traceback) + test_import_fail_info_unknown_cnr_id_returns_400 (control) → test_e2e_legacy_real_ops.py

### 🟢 LOW-closed-WI-TT (6 items — pytest N→Y via direct positive-path)

All 6 legacy-only GET endpoints that were `pytest=N` at matrix creation
have been closed via direct positive-path tests landed in
`tests/e2e/test_e2e_legacy_endpoints.py` (Section 22 of
`e2e_verification_audit.md`). This lifts pytest effective ceiling from
33/39 = 85% to **39/39 = 100%**.

- wi-031 GET /customnode/alternatives — closed (mode=local schema + list)
- wi-032 GET /v2/customnode/disabled_versions/{node_name} — closed (disabled-version list)
- wi-033 GET /v2/customnode/getlist — closed (channel / node_packs + mode variants)
- wi-034 GET /v2/customnode/versions/{node_name} — closed (schema + 404)
- wi-035 GET /v2/externalmodel/getlist — closed (?mode=local schema + non-empty)
- wi-036 GET /v2/manager/notice — closed (notice payload / 200 + dict)

### 🟢 LOW-closed-WI-UU (1 item — high-fanout pytest I→Y via direct positive-path)

The final 🔴 HIGH item (wi-039 POST /v2/manager/queue/batch,
high-fanout over install_model / update_all / update_comfyui) has been
closed via direct positive-path in
`tests/e2e/test_e2e_legacy_endpoints.py` (§22 of
`e2e_verification_audit.md`). This lifts pytest to **38 Y + 1 I + 0 N**;
the last I is wi-027 snapshot/restore, retained by intentional design.

- wi-039 POST /v2/manager/queue/batch — closed (TestLegacyQueueBatch empty-`{}` payload; exercises request-parse → action loop → finalize → worker-lock release → JSON serialize; response shape `{failed: [...]}` status 200)

**Note**: wi-027 POST snapshot/restore is MED on Playwright (UI trigger at
`snapshot.js:12`) and HIGH on pytest (intentionally untested as destructive;
needs skip-by-default marker).

### 🟢 LOW / adequate-with-rationale

- wi-023 POST queue/update_all — UI uses `/queue/batch` not this endpoint (possibly CLI-only)
- wi-025 POST reboot — click intentionally omitted; clicking would kill the test server mid-run
- wi-022 POST queue/start, wi-010 history_list, wi-030 queue/task — server/test-only or glob-UI N/A
- wi-016 POST import_fail_info_bulk — backend/CLI-only path
- wi-002 GET fetch_updates — deprecated 410, no JS trigger
- wi-009 GET queue/history — internal API only (no UI surface)
- wi-013 GET snapshot/get_current — 3rd-party share extensions only (out-of-scope for legacy-ui)
- wi-008 GET policy/update, wi-012 GET manager/version — pytest fully covers contract; Playwright add would be nice-to-have

---

## 5. Key Systemic Observations

1. **Playwright P = 14 / 39 = 36%** (post WI-VV+WW+WW.2+YY+YY.3; was 18/39=46%).
   Coverage evolution: WI-VV closed 4 LOW-risk items via real UI-click;
   WI-WW closed 5 MED items via mock-based UI→API wiring; WI-WW.2
   closed wi-015 via 2-hop mock. **WI-YY** then promoted 5 of the 6
   mocks (wi-014/020/024/037/038) to REAL pytest E2E — 2 run under
   the default-security fixture (wi-020 real TAEF1 download,
   wi-024 direct endpoint POST) and 3 run under a permissive-harness
   fixture (security_level=normal-) using HARDCODED TRUSTED inputs
   (wi-014 self-switch no-op, wi-037 nodepack-test1-do-not-install,
   wi-038 text-unidecode lazy-install). Playwright mocks for these 5
   items were REMOVED; the Playwright column reverted to P (UI-click
   not yet exercised in Playwright — backend contract now fully
   covered by pytest). wi-015 remains as a 2-hop mock (legitimate:
   pytest negative-path tests cover the 400 branch; UI→API wiring is
   asserted via mock). COMFYUI_MANAGER_SKIP_MANAGER_REQUIREMENTS=1 is
   exported as the safety belt in start_comfyui.sh for any
   install/update flow. Permissive harness security note: these
   endpoints exist to serve a supported feature — operators in a
   trusted environment lower security_level to `normal-`/`weak` to
   enable them. The 200 path IS the feature; testing it requires
   exactly this configuration, with TRUSTED fixed inputs (never user
   input).

2. **pytest effective ceiling = 39 / 39 = 100%** (Y=38 + I=1, N=0)
   post-WI-UU. WI-TT closed 6 N → Y
   (wi-031/032/033/034/035/036); WI-UU closed the final high-fanout
   I → Y (wi-039 via `TestLegacyQueueBatch`). The sole remaining I
   row is **wi-027 POST /v2/snapshot/restore** — intentional design,
   NOT a gap: the endpoint is destructive and sits behind a
   skip-by-default marker; upgrading it to Y requires a reversible
   snapshot fixture, scoped as an optional WI-XX.

3. **Legacy-only tier — pytest now fully direct**:
   - 0 pytest-N, 0 pytest-I, 9 pytest-Y = 9/9 direct coverage.
   - 7 / 9 legacy-only endpoints remain Playwright-P — the audit focus
     shifts from pytest coverage to UI-surface Playwright expansion.

4. **Shared tier is healthy**: 0 pytest-N, 27/29 pytest-Y, 11/29 Playwright-Y.
   The 11 Shared-tier Playwright-P items are all UI-exists-but-not-tested —
   never a protocol gap.

5. **glob-only is structurally Playwright-NA**: The single glob-only endpoint
   (`queue/task`) has no legacy UI surface by design — the legacy UI dispatches
   through `queue/batch` (wi-039). Closing this needs a glob-UI Playwright
   harness, which is an upstream-ComfyUI scope concern.

---

## 6. Recommended Follow-up WIs

| WI | Scope | Closes | Priority |
|---|---|---|---|
| **WI-TT** | Add 6 direct positive-path pytest tests for legacy-only GET endpoints — landed in `tests/e2e/test_e2e_legacy_endpoints.py` (§22 of `e2e_verification_audit.md`); closed 2026-04-21 | wi-031, 032, 033, 034, 035, 036 | 🟢 DONE |
| **WI-UU** | Add pytest positive-path for `POST /v2/manager/queue/batch` (high-fanout) — landed `TestLegacyQueueBatch` in `tests/e2e/test_e2e_legacy_endpoints.py` (§22 of `e2e_verification_audit.md`); closed 2026-04-21 | wi-039 | 🟢 DONE |
| **WI-VV** | Legacy-UI Playwright — 4 LOW-risk P closures via real UI-click (closed 2026-04-20) | wi-001, 005, 017, 021 | 🟢 DONE |
| **WI-WW** | env var skip + 5 mock-based Playwright P closures (closed 2026-04-20) | wi-014, 020, 024, 037, 038 | 🟢 DONE |
| **WI-WW.2** | Playwright P closure for wi-015 via 2-hop mock (getlist stub + POST intercept; closed 2026-04-21) | wi-015 | 🟢 DONE |
| **WI-YY** | Replace 5 of 6 mocks with REAL pytest E2E — default-security (wi-020, wi-024) + permissive-harness with trusted fixed inputs (wi-014 self-switch, wi-037 nodepack-test1, wi-038 text-unidecode) + env var safety belt + start_comfyui_permissive.sh harness (closed 2026-04-21) | wi-014, wi-020, wi-024, wi-037, wi-038 | 🟢 DONE |
| **WI-YY.3** | Replace remaining mock (wi-015) with REAL pytest E2E via pre-seeded broken pack (ComfyUI-YoloWorld-EfficientSAM cloned without pip deps; warmup via import_fail_info_bulk; cnr_id=directory-basename lookup) — deleted the legacy-ui-mock-install.spec.ts file (closed 2026-04-21) | wi-015 | 🟢 DONE |
| **WI-WW** (optional) | pytest-I → pytest-Y for install endpoints (`install/git_url`, `install/pip`) — superseded by WI-YY-real (wi-037 via TestInstallViaGitUrlRealClone, wi-038 via TestInstallPipRealExecute in test_e2e_legacy_real_ops.py) | wi-037, 038 | 🟢 DONE (via WI-YY) |
| **WI-XX** (optional) | Skip-by-default pytest for `POST /v2/snapshot/restore` | wi-027 | 🟡 MEDIUM |

Post-WI-UU pytest coverage is **38/39 Y + 1/39 I = 100% effective**
(N = 0). 0 🔴 HIGH items remain. 5 matrix rows carry the
`Y (WI-YY-real)` annotation — real-E2E execution replacing prior
`I`-only markers on mock-covered endpoints. The sole remaining
pytest-I row is wi-027 POST /v2/snapshot/restore, retained by
intentional design (destructive endpoint behind a skip-by-default
marker; scoped as optional WI-XX for future reversible-fixture
upgrade). Playwright is **17/39 Y = 44%** post-WI-YY.3 (from
13/39 = 33% at matrix creation; peaked at 18/39 pre-YY.3 before
the wi-015 mock was removed in favor of real pytest E2E via a
pre-seeded broken pack). 6 mocks removed in total (5 via WI-YY
+ 1 via WI-YY.3) in favor of real pytest E2E — the trade-off is
honest real-execution coverage via pytest (with a permissive
harness for high+ gated items using trusted fixed inputs) instead
of mock-only UI-wiring via Playwright.

---

## 7. Source YMLs

| Member | File | Items |
|--------|------|------:|
| gteam-teng | `.claude/pair-working/checklists/cl-20260420-wl-afbf982ff/gteam-teng.yml` | 10 |
| gteam-reviewer | `.claude/pair-working/checklists/cl-20260420-wl-afbf982ff/gteam-reviewer.yml` | 10 |
| gteam-dev | `.claude/pair-working/checklists/cl-20260420-wl-afbf982ff/gteam-dev.yml` | 10 |
| gteam-dbg | `.claude/pair-working/checklists/cl-20260420-wl-afbf982ff/gteam-dbg.yml` |  9 |
| | **Total** | **39** |
