# Playwright E2E Tests — Legacy Manager UI

Browser-based E2E tests for the ComfyUI-Manager legacy UI.

## Prerequisites

1. **E2E environment** built via `python tests/e2e/scripts/setup_e2e_env.py`
2. **Playwright installed**: `npx playwright install chromium`
3. **ComfyUI running** with legacy UI enabled:

```bash
E2E_ROOT=/tmp/e2e_full_test
PORT=8199
$E2E_ROOT/venv/bin/python $E2E_ROOT/comfyui/main.py \
  --listen 127.0.0.1 --port $PORT \
  --enable-manager-legacy-ui \
  --cpu
```

## Running Tests

```bash
# With server already running:
PORT=8199 npx playwright test

# Single file:
PORT=8199 npx playwright test tests/playwright/legacy-ui-manager-menu.spec.ts

# Headed (visible browser):
PORT=8199 npx playwright test --headed

# Debug mode:
PORT=8199 npx playwright test --debug
```

## Test Files

| File | Scenarios |
|------|-----------|
| `legacy-ui-manager-menu.spec.ts` | Menu dialog rendering, settings dropdowns, API round-trip |
| `legacy-ui-custom-nodes.spec.ts` | Node list grid, filter, search, footer buttons |
| `legacy-ui-model-manager.spec.ts` | Model list grid, filter, search |
| `legacy-ui-snapshot.spec.ts` | Snapshot list, save, remove |
| `legacy-ui-navigation.spec.ts` | Dialog open/close, nested navigation, no duplicates |
