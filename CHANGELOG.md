# Changelog

## Unreleased

### Security policy: dedicated install flags (`allow_git_url_install` / `allow_pip_install`)

Two new boolean keys in `config.ini` (`[default]` section), both defaulting to
`false`, now govern the arbitrary-install surfaces:

| Flag | Governs |
|------|---------|
| `allow_git_url_install` | `POST /customnode/install/git_url` and the unknown-git-URL arm of `POST /manager/queue/install` (incl. reinstall delegation) — the entire install transaction, transitive dependency pip installs included. On the batch queue path the flag applies **in addition to** the queue's `security_level` entry gate (see below) |
| `allow_pip_install` | `POST /customnode/install/pip` only |

These surfaces additionally require a **loopback listener** (`--listen` on a
loopback IP such as `127.0.0.1` or `::1` — not a general LAN/private address);
the flags never open a non-loopback deployment. On the two
**direct** endpoints (`POST /customnode/install/git_url` and
`POST /customnode/install/pip`), the flags fully **decouple** the surface
from `security_level`: it no longer has any effect in either direction — a
strict level cannot deny them when the flag is `true`, and a weak level
cannot allow them when the flag is `false`. On the **batch queue path**
(`POST /manager/queue/install`), the flag is **necessary but not
sufficient**: it gates the unknown-git-URL arm at the risky position, while
the queue's normal `security_level` entry gate (`middle`) remains in force —
at `security_level = strong`, batch unknown-URL installs stay denied even
with the flag set to `true`. `security_level` continues to govern every
other gated endpoint unchanged. Only the case-insensitive string `true`
enables a flag; a missing or malformed key reads as `false`.

#### Migration note (no auto-seed)

There is **no automatic migration** from `security_level`. Users who
previously relied on `security_level = weak` (or `normal-`) to use
install-via-git-URL / install-pip must now **opt in explicitly** by adding to
`config.ini`:

```ini
[default]
allow_git_url_install = true
allow_pip_install = true
```

Changes take effect after a **restart** (no hot reload).

#### Residual-risk note — outdated ComfyUI behavior change

On outdated ComfyUI versions (no system-user API), the manager previously
forced `security_level = strong`, which unconditionally denied the
git-URL/pip install surfaces. After this change those surfaces are governed
by the new flags instead: an operator who explicitly sets a flag to `true`
on a **loopback** listener can now perform installs on outdated ComfyUI
where the forced-strong policy previously denied them. This is an accepted,
deliberate trade-off: it requires explicit operator opt-in, remains bounded
to loopback listeners, and the flag-deny path on outdated ComfyUI still
surfaces the `comfyui_outdated` notice. If you operate an outdated ComfyUI
deployment, leave both flags at their default `false` and update ComfyUI.
