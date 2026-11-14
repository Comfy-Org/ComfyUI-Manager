# Changelog

## Unreleased

### Lists load after a channel response that is not JSON

When the channel answered with something other than JSON, such as a block page
or `404: Not Found`, the Manager stored an empty result in its cache. The custom
node list and the model list (`Failed to get external model list.`) then failed
to load from that cache, for up to a day, even after the channel answered
properly again. Such a response is now handled like a failed connection: nothing
is cached and the list bundled with the Manager is used. An empty result that an
earlier version already cached is replaced at the next start while the channel
answers; for a channel other than the default one that covers only the node
list, unless `default_cache_as_channel_url` is on. Otherwise it goes away when
it is a day old or when the files in `user/__manager/cache` are deleted (#3480).

### Versions with a suffix are read for node packs and pip packages

A node pack installed from the registry is recognized when its version has a
pre-release, such as `1.8.0-beta.1` or `0.7.2-b2`; such a pack was not taken as
a registry pack. A version with a fourth part, such as `0.1.3.post1`, stopped
the scan of installed node packs with `invalid literal for int()`, in the server
and in `cm-cli`.

Installed pip versions are ordered as pip orders them. A package installed with
a local label or as a pre-release, such as `2.5.1+cu124` or `4.41.0rc1`, raised
the same error where a requirement is compared with the installed version. At
the next start, the rest of that node pack's requirements and its `install.py`
were then skipped; an immediate install stopped at a package protected from
downgrade; an entry of `pip_auto_fix.list` was skipped with `Failed to restore`.
Such an entry is now applied: `torch==2.5.1` is met by an installed
`2.5.1+cu124`, and replaces an installed `2.6.0+cu124` with `pip install`. In
`pip_auto_fix.list`, `~=` is now a compatible-release clause: it was taken as
met by any other version, and as not met by the same version (#3431).

### Sharing to Matrix uploads only a file in the output or temp directory

Sharing to the Matrix server uploads only a file inside ComfyUI's output or temp
directory. The file name and subfolder of the output to share come from the
request and were not checked, so a request could have any file that ComfyUI can
read uploaded to the Matrix homeserver named in the same request (#3427).

### Fix node (recreate) works inside a subgraph

`Fix node (recreate)` on a node inside a subgraph stopped with an error and left
two copies of the node: the original, still wired, and an unwired replacement.
It read the node's links from the root graph; it now reads them from the graph
the node is in, and keeps the links to the inputs and outputs of the subgraph as
well.

### Notice retrieval verifies the TLS certificate

The notice in the Manager menu is fetched from GitHub with certificate
verification on; it was off for every user. A response whose certificate is not
trusted is discarded and the notice area shows `Unable to retrieve Notice`. It
shows the same when the connection fails, where it used to show a server error.
Behind a proxy that re-signs TLS traffic, point the `SSL_CERT_FILE` environment
variable at a CA bundle that includes the proxy's CA, or set `bypass_ssl = True`
in `config.ini`, which turns verification off for this fetch too (#3302).

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

### Removed share destinations

Four share destinations no longer take workflows from Manager and are removed:
ComfyWorkflows (its domain registration has expired), Copus (its API answers
that publishing from ComfyUI is no longer supported), OpenArt (its workflow API
and pages are gone), and eSheep (its site no longer resolves). Sharing to YouML
and to the Matrix server is unchanged. A saved `Share` setting that names a
removed site now acts as `All`, and the Workflow Gallery button no longer opens
a removed site that was visited last. The files saved for the removed sites are
no longer read; `comfyworkflows_sharekey`, `.openart_key`, and
`esheep_share_message.json` in Manager's data directory
(`<USER_DIRECTORY>/__manager/`, or `<USER_DIRECTORY>/default/ComfyUI-Manager/`
on older ComfyUI) can be deleted.
