# Legacy UI — Channel Combo DOM Mapping Note

**Date**: 2026-04-20
**Context**: WI-OO Item 3 follow-up — bloat sweep `dev:ci-022` B8 "Channel dropdown"
test was title-mismatched (filter `/Cache|Local|Channel/` matched DB combo's
option text, not the Channel combo itself). This record documents the correct
DOM locators for any future reactivation.
**Scope**: Record only. No test code added; no audit impact.

---

## 1. Source Locations

| Artifact | Path | Lines | Role |
|----------|------|-------|------|
| Channel combo creation + registration | `comfyui_manager/js/comfyui-manager.js` | 960-986 | Creates the `<select>`, installs title attr, fetches options from API, mounts into the settings panel via `createSettingsCombo` |
| Settings row wrapper | `comfyui_manager/js/comfyui-gui-builder.js` | 15-27 | Exports `createSettingsCombo(label, content)` that wraps the combo in the label/input row |

## 2. DOM Structure

| Field | Value |
|-------|-------|
| Tag | `<select>` |
| Classes | `cm-menu-combo p-select p-component p-inputwrapper p-inputwrapper-filled` |
| `title` attribute | `"Configure the channel for retrieving data from the Custom Node list (including missing nodes) or the Model list."` (set at L961) |
| Options source | `/v2/manager/channel_url_list` — populated asynchronously at L963-984 |
| Option texts | Channel URL names (e.g. `default`, `recent`, custom URLs); NOT the word "Channel" |
| Label wrapper | `div.setting-item > div.flex.flex-row.items-center.gap-2 > div.form-label.flex.grow.items-center > span.text-muted` with `textContent: "Channel"` (from `createSettingsCombo`) |
| Render timing | Select element itself: **sync** at menu build time. Options: **async** after `channel_url_list` fetch resolves |

## 3. Why the Original `hasText: /Cache|Local|Channel/` Filter Failed

The removed test used `hasText` to find the Channel dropdown, but that matcher
searches the element's rendered text (its `<option>` children's text in the case
of a `<select>`). The Channel combo's options are channel URL names — they do
not contain the words `Cache`, `Local`, or `Channel`.

In contrast, the DB (datasrc) combo located a few lines above
(comfyui-manager.js:957, built from `this.datasrc_combo` which seeds options
`Cache` / `Local` / `Remote`) did contain those literals, so the filter
silently resolved to the wrong `<select>`. The test asserted visibility, which
passed against the DB combo, masking the mismatch until WI-OO's audit exposed
it as B8 title-mismatch bloat.

## 4. Stable Selector Candidates

Ordered by robustness (most stable first):

1. **Title attribute (recommended)** — unique per L961
   ```ts
   select[title^="Configure the channel"]
   ```
   The leading prefix `Configure the channel` appears nowhere else in the
   managed panel. Safe against minor title copy edits as long as the opening
   phrase is preserved.

2. **Label-based scope** — DOM-structure dependent
   ```ts
   .setting-item:has(span.text-muted:text-is("Channel")) select
   ```
   Works as long as `createSettingsCombo` keeps its current wrapper shape and
   the exact label text `"Channel"`.

3. **Class-only** — NOT unique
   Classes `cm-menu-combo p-select ...` are shared with the DB, Update-Policy,
   and Share combos. Using classes alone will match multiple elements and is
   brittle.

## 5. Async-Population Note

Options for the Channel combo are populated via an async `fetchApi` call to
`/v2/manager/channel_url_list` at L963. Two testing consequences:

- A visibility assertion on the `<select>` resolves immediately — the element
  is appended synchronously at L960 and mounted at L986.
- An assertion about option count or specific option values MUST wait for the
  fetch to resolve. Use `expect.poll` (or equivalent) with a reasonable
  timeout (≥5s) rather than an immediate `toHaveCount` check.

## 6. Proposed Test Skeleton (Reference Only)

Not added to any spec — kept here for future activation.

```ts
test('shows Channel dropdown (async-populated)', async ({ page }) => {
  await openManagerMenu(page);
  const dialog = page.locator('#cm-manager-dialog').first();
  const channelCombo = dialog.locator('select[title^="Configure the channel"]');
  await expect(channelCombo).toBeVisible();
  await expect.poll(
    async () => await channelCombo.locator('option').count(),
    { timeout: 5000 }
  ).toBeGreaterThan(0);
});
```

## 7. Decision

Test **not** added. This aligns with the post-bloat-sweep net-removal
direction established by WI-OO: re-introducing a Channel-dropdown visibility
test would re-expand the surface the sweep explicitly trimmed. The record is
preserved here so that, if future coverage expansion prioritizes the settings
panel, reactivation needs only copy the skeleton above and choose selector
option 1 from §4.
