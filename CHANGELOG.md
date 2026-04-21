# Changelog

All notable changes to **ComfyUI-Manager** are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Security-hardening release on branch `fix/csrf-post-conversion`. Contains
breaking-ish API changes for state-mutating endpoints. See **Migration notes**
below before upgrading programmatic clients.

### Security

- **CSRF Content-Type gate**: 18 state-mutation POST handlers (9 in `glob`, 9 in
  `legacy`) now reject the three CORS "simple request" Content-Types
  (`application/x-www-form-urlencoded`, `multipart/form-data`, `text/plain`).
  This closes the residual `<form method="POST">` bypass route that remained
  after the GET→POST transition. Legitimate clients using `application/json`
  (or no body) are unaffected.
- **`do_fix` security level raised from `high` to `high+`**: aligns the
  enforcement gate (`is_allowed_security_level`) with the log text emitted by
  `SECURITY_MESSAGE_HIGH_P`. Both `glob/manager_server.py` and
  `legacy/manager_server.py` updated in lockstep. Environments running at
  `security_level = high` can no longer fix a nodepack — use
  `security_level = normal` or lower.
- **Config setters now gated at `middle` security level**:
  `POST /v2/manager/db_mode`, `POST /v2/manager/policy/update`, and
  `POST /v2/manager/channel_url_list` now check
  `is_allowed_security_level('middle')` before mutating configuration (both
  `glob` and `legacy`). Closes a pre-existing gap where the write path was
  reachable at any security level. Reads (`GET`) remain unrestricted.

### Changed

- **State-changing endpoints converted from `GET` to `POST`** (CSRF hardening):
  `/v2/manager/queue/{update_all, reset, start, update_comfyui}`,
  `/v2/snapshot/{remove, restore, save}`,
  `/v2/comfyui_manager/comfyui_switch_version`,
  `/v2/manager/reboot`.
  Query-string parameters are preserved where they existed; only the HTTP
  method changes.
- **`POST /v2/comfyui_manager/comfyui_switch_version` parameters moved from
  query string to JSON body** (REST idiom + body-reading CSRF posture):
  The handler now consumes `application/json` with the body shape
  `{"ver": "...", "client_id": "...", "ui_id": "..."}` instead of reading
  `?ver=...&client_id=...&ui_id=...` from the URL. Because body-reading
  handlers are already covered by the CORS-preflight mechanism for
  cross-origin protection, the Content-Type rejection gate introduced for
  the other state-mutation endpoints is intentionally NOT applied here
  (see `comfyui_manager/common/manager_security.py` module docstring).
  The first-party JS client in `comfyui_manager/js/comfyui-manager.js`
  was updated in the same change; third-party callers must migrate.
- **Config endpoints split into `GET` (read) + `POST` (write)**:
  `/v2/manager/{db_mode, policy/update, channel_url_list}`. `GET` returns the
  current value; `POST` accepts a JSON body `{"value": "..."}`. The prior
  single-method form that accepted a `?value=...` query parameter on either
  verb is retired.
- **`openapi.yaml` fully resynchronized** with the server: HTTP methods, the
  dual-method splits above, request-body schemas for the new POST setters,
  and the `TaskHistoryItem.params` field now match `manager_server.py`.
- **Legacy `restart(self)` → `restart(request)`**: parameter name corrected.
  No behavioral change.

### Added

- **E2E test harness variants** for security-level and legacy-mode scenarios:
  `tests/e2e/scripts/start_comfyui_legacy.sh`,
  `tests/e2e/scripts/start_comfyui_permissive.sh`,
  `tests/e2e/scripts/start_comfyui_strict.sh`. See
  `docs/guide/GUIDE_E2E_TEST.md` for usage.
- **`COMFYUI_MANAGER_SKIP_MANAGER_REQUIREMENTS` environment variable**: when
  set, skips the `manager_requirements.txt` reinstall path. Intended for E2E
  environments where those dependencies are provisioned separately.
- **`TaskHistoryItem.params` field** (Pydantic + `openapi.yaml`): mirrors
  `QueueTaskItem.params` so that task history retains the original request
  payload (nullable when unavailable).
- **Automated endpoint coverage** — pytest E2E + Playwright specs covering all
  39 unique `(method, path)` endpoints across `glob` and `legacy`. Coverage is
  tracked in `reports/api-coverage-matrix.md` and
  `reports/e2e_test_coverage.md`.

### Removed

- **Legacy per-operation POST routes consolidated into `POST /v2/manager/queue/batch`**:
  `/v2/manager/queue/{install, uninstall, update, fix, disable, reinstall, abort_current}`.
  The first-party JS client already uses `queue/batch`; only third-party
  scripts that call the per-operation routes directly are affected.
- **`GET /manager/notice`** (v1, pip-install redirect banner).
  `GET /v2/manager/notice` remains available.

### Migration notes

- Third-party clients calling `POST /v2/manager/queue/install` (and the other
  per-operation queue routes) must switch to
  `POST /v2/manager/queue/batch` with a body such as
  `{"install": [{id, ver, ...}], "batch_id": "..."}`. See
  `reports/endpoint_scenarios.md` for the full payload shape.
- Programmatic clients that posted to the CSRF-hardened endpoints with
  `application/x-www-form-urlencoded`, `multipart/form-data`, or `text/plain`
  must switch to `application/json` (or omit the body entirely when the
  endpoint takes its parameters from the query string).
- Clients that called any of the methods listed under **Changed → State-changing
  endpoints** with `GET` must switch to `POST`. Query parameters remain valid.
- Clients that wrote configuration via
  `GET /v2/manager/{db_mode, policy/update, channel_url_list}?value=...`
  must switch to `POST` with JSON body `{"value": "..."}`.
- Third-party scripts calling
  `POST /v2/comfyui_manager/comfyui_switch_version?ver=...&client_id=...&ui_id=...`
  must switch to `POST` with `Content-Type: application/json` and body
  `{"ver": "...", "client_id": "...", "ui_id": "..."}`. The query-string
  form no longer works.
- Environments running at `security_level = high` can no longer run
  `do_fix`. Either lower the security level (`normal`, `normal-`, or `weak`
  as appropriate) or skip the fix operation.
- Environments running at `security_level = high` can no longer mutate
  `db_mode`, `policy/update`, or `channel_url_list` via POST (returns `403`).
  Lower the security level to `normal` or below to change configuration, or
  perform the change from a trusted entry point. Read access via `GET` is
  unaffected.

[Unreleased]: https://github.com/Comfy-Org/ComfyUI-Manager/compare/v4.1b6...HEAD
