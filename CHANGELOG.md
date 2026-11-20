# Changelog

## Unreleased

### No deprecation warning of aiohttp with `bypass_ssl`

With `bypass_ssl = true`, the fetch of the notice and the fetch of a list
passed `verify_ssl=False` to aiohttp, which warns that the argument is
deprecated: `DeprecationWarning: verify_ssl is deprecated, use ssl=False
instead` (#2281). They now pass `ssl=False`. Without `bypass_ssl` nothing
changes: the certificate is checked as before.

### A console that is gone does not fail a prompt

A server that was started with pipes for its console goes on running when the
process that read them exits, and a write to such a pipe fails. The log hook
of the Manager passed that failure on to whatever had printed: the prompt of a
node that prints, or of a sampler at its progress bar, ended with
`BrokenPipeError: [Errno 32] Broken pipe`, on Windows with
`OSError: [Errno 22] Invalid argument` (#3223). The hook now drops what the
console does not take and does not write to that console again, and what is
written still goes to the log file. While stderr is gone, ComfyUI's own log
handler fails on each record, and Python's report of that failure is now in
the log file in full, where it broke off after its first line. This is the
hook of the log file (`file_logging`, on by default): with it off, the streams
are those of ComfyUI, and the progress bar still fails there.

### A log call that cannot be formatted does not fail its node

A log call that cannot be formatted failed its node in the log handler of the
Manager, with the exception of the format: `logging.info("value %d", "text")`
ended the node with `TypeError`. Python's logging only reports such a call
and goes on. The handler now puts a `<<logging error>>` line with the file
and the line of the call into the log file, and the node goes on.

### A snapshot restore installs a git node pack as the snapshot names it

A snapshot names a git node pack by its url. For a url that the registry
knows, the restore asked for a nightly install by the id of the registry, and
that install takes its url from the node list. When the node list had no entry
for the node pack, as after the list went over to a fork of it, nothing was
cloned and the summary said `[  FAILED   ]` with no word of why. When the node
list had another repository under the same name, that one was cloned. The
restore clones the url of the snapshot, as a nightly install of that node
pack: a version of the registry that is enabled is disabled first, and the
node pack is checked out at the commit of the snapshot. The restore no longer
reads the node list.

A node pack that was switched from its clone to a version of the registry
keeps the clone, disabled, and a snapshot saves both. The restore enabled or
cloned the clone and disabled the version that the snapshot names. Such a node
pack is restored at that version, and its git entry is left alone. When that
version cannot be installed, the clone is restored as before.

A clone of the restore that is refused says why in the log, as
`Invalid git url: ...`.

### A failed legacy backup is reported without the text of the error, and leaves no part of a backup

When the legacy directory could not be moved to its backup, the startup notice
carried the text of the error, which has paths of that directory in it. The
notice now says only that the backup failed, and the error is in the terminal.
When the move fails while it copies, the legacy directory is as it was and the
next start tries again; what was copied is removed, so that the starts do not
each leave another part of a backup.

### On an old ComfyUI, Manager only updates ComfyUI

On a ComfyUI without the System User API (before 0.3.76), Manager's data
directory is not protected, so installs are refused there and startup scripts
are not run. Other requests were still served, and other files of that
directory were still acted on. Now only the update of ComfyUI is served there:
every other request to Manager is answered with `comfyui_outdated`. A snapshot
restore scheduled in that directory is left alone at the start, and the start
says so; its `pip_auto_fix.list` and `pip_overrides.json` are not applied by
the start or by the update. Update ComfyUI to use Manager again.

After that update, the first start moves `config.ini` to the protected
directory. It moved every setting and raised only a security level below
`normal`. Now it moves the settings that are preferences and leaves behind
those that permit an install (`allow_git_url_install`, `allow_pip_install`,
`allow_flagged_nodepack_install`) or change where Manager fetches from
(`channel_url`, `http_channel_enabled`, `bypass_ssl`, `git_exe`), and any it
does not know. Those are back at their defaults, and the terminal lists the
ones that had another value; set them again if you need them. A security level
that is not a security level is set to `normal` like one below it.
### Every POST that changes something is taken only as `application/json`, and the share option is saved by POST

A page of another site can make the browser send a GET, and a POST without a
body and without a Content-Type, for which no preflight is made. The Manager
routes that take no body (`queue/start`, `queue/reset`, `queue/update_comfyui`,
`snapshot/save`, `reboot`) now answer 400 unless the request has
`Content-Type: application/json`, as the routes that read a JSON body do: a
browser does not send that header to another site without a preflight. The
share option is saved with `POST /manager/share_option` and a JSON body
`{"value": ...}`; `GET /manager/share_option` only answers with the saved
option, and a `value` given to it is ignored. The Manager's own pages send the
header. A script that calls one of these routes has to send it too, and one
that saved the share option with `?value=` has to POST.

### The file of the saved Matrix account is readable by its user only

The share dialog saves the Matrix account, with its password, in `matrix_auth`
in Manager's data directory. The file was written with the default mode of
new files, which other users of the machine can usually read. It is now written
with mode `0600`, and a file that is already there gets that mode the next
time an account is saved.

### The share option that is saved is one of the choices of the share menu

`/manager/share_option` saved any text as the share option. It now saves
`all`, `none`, `youml` or `matrix`, the choices of the menu, and answers 400
for another value.

### Restoring a snapshot needs the security level of a switch to an older version

A snapshot restore takes the node packs back to the versions that the
snapshot recorded, older ones too. `POST /snapshot/restore` needed `middle`, which the
default `security_level = normal` gives on any listener; a switch of ComfyUI to
an older version needs `high`. A restore now needs `high` as well: `normal-` or
lower on a loopback listener, `weak` otherwise. At `normal`, `Restore` in the
Snapshot Manager is refused; `cm-cli restore-snapshot` is not changed.

### Routes that read a JSON body take it only as `application/json`

A POST route that reads a JSON body parsed it whatever the Content-Type of the
request. These routes now answer 400 unless the Content-Type is
`application/json`. The Manager's own scripts send it; a script or tool that
posts JSON to the Manager without that header has to add it.

### Switching ComfyUI to an older version is held to the security level

Switching the ComfyUI version was not checked against `security_level`. A
switch to an older release, or to anything that is not a release tag, now needs
`normal-` or lower when ComfyUI listens on a loopback address, and `weak`
otherwise; at the default `normal`, `Switch ComfyUI` in the Manager menu
answers that the security level does not allow it. A switch to `nightly` or to
a newer release is an update and works at every level, as before. A ComfyUI
with commits after its release, as on `nightly`, would go back by a switch to
that release, so that counts as older; in a repository without release tags,
such as a clone without tags, every version but `nightly` does. The menu
changes the update policy to that of the chosen version only after the switch
has happened; it did so before asking for the switch.

### The server no longer returns saved sharing credentials

`GET /manager/get_matrix_auth` answered with the saved Matrix homeserver,
username and password, to any client that could reach the server. It now answers
without the password. The share dialog leaves the password field empty for the
saved account, and the server uses the saved password for the username it was
saved with; for another account a password has to be typed. An account is saved
once it has logged in; a share request no longer replaces the saved account
before that. If others could reach the server while a Matrix password was saved,
change that password.

Sharing to Matrix logs in to matrix.org, where the share room is, and to no
other homeserver. The homeserver of the share dialog can no longer be changed, a
share request that names another homeserver is refused, and an account that was
saved for another homeserver is not used: an account of matrix.org has to be
entered. Before, the server logged in to any homeserver that a request named,
with the password of the request.

The YouML API token is kept in the browser that shares, which is what sends it
to YouML; the server stored it, and `GET /manager/youml/settings` answered with
it in the same way. Both `/manager/youml/settings` routes are removed. The token
has to be entered once more in the YouML share dialog. Delete `.youml` in
Manager's data directory (`<USER_DIRECTORY>/__manager/`, or
`<USER_DIRECTORY>/default/ComfyUI-Manager/` on older ComfyUI), and if others
could reach the server while a token was saved, issue a new token.

### A setting chosen while the Manager menu is loading it is kept

The Manager menu asks the server for the database mode, the component policy,
the update policy and the share option when it is first opened. A value chosen
before the answer arrived was saved, but the menu went back to showing the old
one. The menu keeps the chosen value.

### Setting requests with an unknown value are refused

The routes that set `db_mode`, `update_policy` and `component_policy` stored
whatever value a request carried and wrote it to `config.ini`. They answer 400
for a value that is not one of those the Manager's menu offers, and for a JSON
body without a `value`, which ended with status 500.

### `git_exe` chooses the git executable

The path set as `git_exe` in `config.ini` was read but not used: git commands
kept running the `git` found on `PATH`. The Manager, cm-cli and the git helper
now run the configured executable. For the Manager it no longer has to be on
`PATH`: the Manager also starts when the only git is the one named by
`git_exe`. cm-cli still needs a git on `PATH` to start.

A value that is not a working git is reported in the log, and the default git
is used. The value is read as it is written: with a `%` in it, as in a path
of Windows, the Manager read every setting of `config.ini` as its default.
`git_exe` is used only when the configuration file is in a protected
directory, that is with a ComfyUI that has the System User API.

### The commit and the submodules of a git node pack

A snapshot recorded no commit for a git node pack whose refs were packed, as
after `git gc`. The commit is read from `packed-refs` too. A `HEAD` that is
not UTF-8, as one that names a branch in another encoding, raised an error
where the commit of a node pack is read. It is read as bytes now. On Windows
the commit of a branch whose name is not ASCII, as a Korean one, could be
unknown as well: the file of the branch is looked for under the name that Git
for Windows gives it. The commit is read while the Manager is loading, and an
error there kept the Manager from loading: also for a `.git` with a folder
where the file of the branch would be, as after
`git checkout --orphan feature` beside a branch `feature/x`, or with a file
that cannot be read. The commit of such a node pack is unknown now.

When a snapshot restore checks a git node pack out, its submodules are brought
to the commits that the commit names, also when the node pack is at the commit
of the snapshot already. A submodule that was never fetched is then fetched
too in a node pack that the Manager installed, as the Manager clones a node
pack with its submodules; in a node pack cloned without them, it is fetched
only when the node pack itself is checked out.

### A node pack whose `.git/config` cannot be read

The Manager reads the remote url of every installed node pack from its
`.git/config` while it is loading. A url with a `%`, such as one with `%20`,
a key without a value, such as `bare` alone, a key on a line that is indented
more than the one before it, a byte order mark at the start of the file, or
text that the encoding of the system cannot decode, such as the name of a
branch in another encoding, raised an error there, and the Manager did not
load. These files are read now, and for a file that cannot be read the url of
that node pack is unknown and a warning names the file once.

### An update whose git step fails is a failure, and can be done again

On Windows the pull of an update runs in a helper process, which ended with 0
when the pull failed, and its result was not read: the update went on to the
install script and ended as done. The helper ends with 1 now, and the update
fails.

When the update of its submodules failed, a node pack stayed at the new
commit: the next update found nothing to do, and the install script of the
update never ran. The pull is undone, and the submodules that were updated
before the one that failed go back with it. A node pack with a submodule
that cannot be fetched at all is not updated until it can.

### A snapshot restore reports what failed, and restores the pinned commit

The summary of a restore listed a node pack as `INSTALLED`, `DISABLED` or
`ENABLED` without looking at the result of the step: a clone that failed, for
example because the directory already existed or the url could not be reached,
was `INSTALLED`. A step that fails is now listed as `FAILED`, and the Manager
itself is no longer listed as `DISABLED`. A registry that cannot be reached
ended the restore at the first node pack to install from it, and so did a
node pack whose directory could not be moved to disable or enable it; such a
node pack is listed as `FAILED`, and the restore goes on. `cm-cli
restore-snapshot` ends with 1 when a step failed or a pip package that a
`--pip-*` option selects was not installed, and a scheduled restore then says
`Restore snapshot failed.`: it ended with 0. A url of the snapshot that cannot
be parsed ended the restore as well; the node pack is listed as `FAILED`.

A git node pack that the restore had to clone stayed at the newest commit. It
is checked out at the commit of the snapshot, and its install script runs after
that. When the commit cannot be checked out, the install script still runs, at
the commit the clone is at, and the node pack is listed as `FAILED`. An
installed git node pack that the registry does not know was checked out only
when cm-cli was run from `custom_nodes`, as a scheduled restore does; it is
checked out from any directory.

A git node pack of the registry that was already installed, or that the
restore enabled, was listed a second time as `SKIPPED`; it is listed once. An
installed one that is checked out is listed by its name, as the others are: it
was listed by its path.

A registry node pack that the restore had to install was unpacked, but its
requirements were not installed and its install script did not run. The
restore now runs them, and lists the node pack as `FAILED` when they fail.

A requirement or an install script that failed was taken as done until the
next start: the next node pack that names the requirement skipped it, and
installing or fixing the node pack again did not run the script. Both are
tried again. The install script of a git node pack was skipped in the same way
when it was cloned where another version of the node pack had been installed
since the start, as a restore does for a snapshot that has both; it runs.

### Install requests with an unusable body are answered with 400

`/customnode/install/git_url` and `/customnode/install/pip` answered 500 when
the JSON body was not an object, or when `url` or `packages` was not a string.
They answer 400, as they do for a missing field.

### What is reserved for the next start is written as UTF-8

The install script of an update, the removal of a node pack whose files are in
use and a switch of version are reserved in a file that the start-up script
reads as UTF-8, and that was written in the encoding of the system. On Windows
a path with a character outside ASCII was lost: one that the code page cannot
write, such as a Korean folder name with code page 1252, raised an error and
nothing was reserved; one that it can write was read back as another path, and
what was reserved was not carried out at the next start. The file is written
as UTF-8.

A switch of version that is carried out at the next start looked for the files
that the new version no longer has in `custom_nodes` in place of the directory
of the node pack: they stayed in the node pack, and a file of the same name in
`custom_nodes` was removed. They are removed from the node pack. A switch of
version, at the next start or at once, removes the files that the new version
no longer has before it extracts the archive of the new version: where two
names are one file, as `./a.py` and `a.py`, or names that differ in case alone
on Windows, a file of the new version was removed after it was extracted.
A name of the old list that leads out of the node pack, with `..` or as an
absolute path, removed a file outside it; nothing is removed for such a name.
A file that the old version has alone and that cannot be removed, as one that
another program has open on Windows, is left with a warning, and the switch
goes on with the files of the new version.
A folder that the files of the old version left empty, or with nothing but the
`__pycache__` of Python, stayed, and a file of the new version could not take
its place; such a folder is removed.
A node pack whose directory keeps its name is no longer moved onto itself at
the next start, which Windows refuses while a file in it is open.
When the switch moves the node pack to another directory, the install script
of the new version runs there; it was looked for in the directory that the
node pack was moved from, and did not run.

That list is written as UTF-8 and was read in the encoding of the system. On
Windows a switch of version of a node pack with a file name that the code page
of the system cannot decode ended in the middle: the files of the new version
were unpacked, its install script did not run and the files of the old version
stayed. The list is read as UTF-8. A name of the list is read as it is written:
a space at its start or its end was dropped, and the file of the other name was
the one removed.

### A scheduled snapshot restore works with `--base-directory`

With `--base-directory`, where `custom_nodes` is not inside the ComfyUI
directory, a snapshot restore scheduled for the next start failed with
`ModuleNotFoundError: No module named 'utils'`, and the request was dropped.
The restore now gets the path of ComfyUI, and the user directory and
`custom_nodes` directory the server uses.

### Console messages show paths, URLs and package names as they are

Manager printed many of its messages through rich, which reads square
brackets as markup. A package name such as `diffusers[torch]` was shown as
`diffusers`, a text such as `:100:` as an emoji, and a line longer than the
console was broken in the middle of a path or a URL. A text with a closing
tag such as `[/b]` raised `MarkupError` instead of being printed, in the
middle of the operation that reported it. These messages are now printed as
they are; numbers and quoted strings keep their colors.

### The list of ComfyUI versions answers a failure with 400 again

When the versions of ComfyUI could not be read, the request for the list ended
with status 500 and a `TypeError` in the log: the call that logs the cause was
given an argument it does not take. The cause is logged, and the answer is 400.

### A value of config.ini is plain text, and one that a setting cannot have gives its default

Manager read `%(name)s` in a value of `config.ini` as a reference to another
setting, and a `%` that is not of that form made the whole file unreadable:
every setting was then at its default, `security_level` too, and nothing said
so. A value is now read as it is written; `%%`, which was read as one `%`, is
now two. `security_level`, `network_mode`, `db_mode`, `update_policy` and
`component_policy` have their default when `config.ini` gives a value that
they cannot have, and Manager logs a warning that names it; the other settings
are read as before, and `config.ini` keeps the value. Before, a
`security_level` that is not a level refused every action that needs one; now
it is `normal`. A `config.ini` that cannot be read at all still gives the
default settings, and is still written anew from them when a setting is
saved; Manager now logs a warning when it reads one.

### After an update from an old ComfyUI, the requirements of ComfyUI are installed before the node packs are loaded

On Windows, or with `always_lazy_install`, the update of ComfyUI reserves the
install of its requirements for the next start. On a ComfyUI without the
System User API that was reserved in the legacy directory, which the updated
ComfyUI does not read. Manager installed them only at a start that found a
`config.ini` in both directories, after ComfyUI and the node packs had been
loaded. It now installs them at the start that still finds the legacy
`config.ini`, before the node packs are loaded. A ComfyUI that cannot start
without one of its new requirements does not get as far as Manager, as
before: install them with `pip install -r requirements.txt` then. The legacy
directory is moved to `.legacy-manager-backup` as before; a backup that is
already there is no longer deleted, the new one gets a numbered name, and the
start reminds of each of them.

### An old ComfyUI no longer leaves `security_level = strong` in config.ini

On a ComfyUI without the System User API, Manager refused installs by changing
the security level it had read to `strong`. A `config.ini` that Manager
created there was written with that `strong`, and installs stayed refused
after ComfyUI was updated. Now Manager does not change the security level:
the check of the security level refuses on such a ComfyUI, whatever the level
is. A `config.ini` that already has `security_level = strong` is not changed:
if you did not choose it, set it to `normal`.

### Restarting under comfy-cli no longer reports a closed log file

Restarting ComfyUI from the Manager under comfy-cli printed `ValueError: I/O
operation on closed file` on the console. The log file is closed before the
process exits, and what was logged after that was still written to it.

### Libraries are told whether the console is a terminal

With file logging on, the logger that captures the output answered every
library that asked that the console was not a terminal. After
`colorama.init()`, the colors of every `print()` were removed, and tqdm and
rich took a terminal for a pipe. The logger now answers with the state of the
real console (#3259, #3423).

### The Model Manager no longer reports an install that did not happen

After the server refused a model install request, the Model Manager kept
waiting, and the end of the next queue, such as a node pack install, was taken
for the end of that install: it asked to click Refresh and raised the notice
that all model downloads were completed, although no model had been installed.
The end of a queue that carries no model result now returns the dialog to idle
without a message when no task is left, and leaves a pending install and its
Stop button alone while tasks are left (#3437).

### A snapshot that cannot be restored or removed says why

When the server refused to restore or remove a snapshot, the Snapshot Manager
showed `Restore snapshot failed: undefined / ReferenceError: exception is not
defined`, also for a removal, and after a refused restore it still asked for a
restart of ComfyUI. An answer with another error status, such as a 502 from a
proxy, was taken as success. The message now names the snapshot and the reason:
the server's text when it gives one, and otherwise the status line, such as
`HTTP 400 Bad Request`. A restart is asked for only after a restore that was
accepted (#3436).

### The node preview shows a node's definition as text

Hovering over a node name in a pack's node list of the Custom Nodes Manager
shows a preview of the node: its name, inputs, default values, outputs and
description. They were inserted as HTML, so text between angle brackets, such
as a default of `<lora:detail:0.8>`, was missing from the preview, and markup
in a node definition was rendered. They are now shown as they are written
(#3434).

### A registry archive that cannot be extracted leaves nothing behind

When the archive of a registry node pack could not be extracted, for instance
because an entry in it cannot be written, the install ended with an error and
left the directory it had created for the pack, with the files extracted so
far, and the downloaded archive in `custom_nodes`. Installing the pack again
then stopped with `Install path already exists` until the directory was removed
by hand. The install now reports `Failed to extract archive`, and removes the
directory and the archive (#3433).

### Cache files are replaced whole, and their age is counted from the last write

The cached channel lists and the registry's node list were written in place. A
write that stopped part-way, as when the disk is full or the process is killed,
left a truncated file, which the Manager reads as an empty list. A cache is now
written beside the file and put in its place in one step, so the file holds the
previous list or the new one, and it keeps its permission bits. Where the file
cannot be replaced, as on Windows while another process has it open, the
replace is tried again for a moment; a file that stays open is left as it is,
with a warning in the log, and is updated by a later fetch.

The age of a cached list is counted from its last write. It was read from the
file's creation time, which Windows keeps when a file is rewritten, so a cache
first created more than a day ago counted as expired however recently it was
written (#3432).

### A disabled node pack that another extension asks for is enabled before the restart

When an extension asks through `cm.try-install-custom-node` for a node pack that
is disabled, the Manager asks whether to enable it and restart. On confirmation
it restarted ComfyUI without enabling the pack, which came back still disabled.
The pack is now enabled as the Enable button of the Custom Nodes Manager does,
and ComfyUI restarts only when the queue reports success; otherwise the reason
is shown.

### The clauses of a pip requirement are weighed together

A requirement for a `downgrade_blacklist` package is judged by all of its
clauses. One that allows the installed version is installed when another clause
sets a minimum above it, as in `transformers==4.*,>=4.58.0` beside an installed
`4.57.0`, or excludes it with `!=` while a newer version is allowed, as in
`transformers~=4.57.0,!=4.57.0`; without extras both were skipped, so the
upgrade did not happen. One that the installed version does not meet and that
allows no newer version, as in `transformers[torch]<=4.57.0,!=4.57.0` or
`transformers<4.58,!=4.57.*`, is skipped; it was installed, and pip replaced the
package with an older version. A pre-release counts as a newer version only when
`==`, `>=`, `<=`, `~=` or `===` names one: pip before 25.0 takes no other.

At startup, `>` is read as pip reads it: a post-release of the version, such as
`1.0.post1` for `>1.0`, does not meet it, and the requirement is installed. A
wildcard such as `==0.21.*` is met by an installed pre-release `0.21.0rc1`, and
the requirement is no longer passed to pip. A requirement that excludes the
installed version with `!=` and allows a newer one, as in `numpy>=2.2.0,!=2.2.0`
beside an installed `2.2.0`, is installed, as an immediate install does; it was
taken as installed already. pip chooses the version, and that is an older one
when no newer release exists.

An installed local build, such as the CUDA build `2.5.1+cu124`, is not replaced
on any of these grounds. For a `downgrade_blacklist` package it is also kept
when a requirement excludes it with `!=`, as in `xformers!=0.0.30` beside
`0.0.30+cu126`, unless the requirement sets a minimum above it; pip replaced the
build with whatever it found. For such a build, these changes only add
requirements that are skipped.

### pip blacklists apply however a requirement is written

`downgrade_blacklist` protects packages whose names contain a hyphen, such as
`opencv-python`; they were never protected. Names in `downgrade_blacklist`,
`pip_blacklist.list` and requirements are compared without regard to case or to
`-`, `_` and `.` (#3458).

Every version clause of a requirement is read, so `numpy>=1.24,<2` no longer
passes because its lower bound comes first. Requirements written with spaces,
parentheses, an environment marker, or as a direct reference (`name @ url`) are
read as well. A requirement with extras for a `downgrade_blacklist` package is
installed unless it would downgrade the package, so the extras' dependencies
are still installed. A `downgrade_blacklist` package is skipped when the
requirement cannot be compared with the installed version, such as a malformed
version or a direct reference, and the log says why and how to install it; the
check raised an error or let the install proceed.

Both lists also apply to requirements that carry pip options such as
`--index-url`, and to installs run through uv in embedded Python or as a
standalone tool. These installs were not checked.

At startup, an installed package is recognized however its requirement spells
the name: pending installs no longer reinstall packages whose names contain `-`
or `.`. A requirement is installed when the installed version is older than its
`~=` version or is the version that `>` excludes; an installed version that is
the `~=` version itself is no longer reinstalled.

`cm-cli` reads `downgrade_blacklist` from `config.ini`. It looked for the file
under a name that does not exist, so it protected only the built-in packages.

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

#### Outdated ComfyUI

On outdated ComfyUI versions (no system-user API) the flags do not apply:
git-URL and pip installs are refused there like every other install, whatever
the flags and the listener are, and the answer is the `comfyui_outdated`
notice. Update ComfyUI to use them.

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
