# Changelog

All notable changes to **ComfyUI-Manager** are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- A search in the legacy Custom Nodes Manager lists the best matches first.
  It only filtered the list, so the rows stayed in the listed order and for
  `face` a nodepack with `Interface` in its title could stand above one with
  the word `Face` (#1191). The rows of a search are now ordered by a score.
  A whole word counts more than a part of a word, in whichever searched column
  matches best, and a match in more columns and more stars raise the score.
  Rows with the same score stay in the listed order. A search replaces a column
  sort that was made before it. Clicking a column header during a search sorts
  by that column, and typing in the search box again goes back to the best
  matches. Clearing the search box brings back the listed order, or keeps the
  column sort that was made during the search. The list is filtered 300 ms
  after the last key. The first click on the Nodes, ★ and Last Update headers
  sorts from the highest value down.

### Fixed

- Check Update in the legacy Custom Nodes Manager no longer stops the server,
  and shows how far it is. It fetched every git nodepack inside the request
  for the node list. Until the last fetch had ended the server answered
  nothing else, and with many git nodepacks the page gave up after a minute
  with `Failed to get custom node list.` (#3574). The check now runs in the
  background. The page shows `Checking updates (n/total) ...` while the
  repositories are fetched, the server goes on answering, and the nodepacks
  that have an update are listed when the check has ended. A task on
  nodepacks that is started during a check, such as Update All, runs when the
  check has ended, as before. A model download and an update of ComfyUI do
  not wait for it. When the connection to the server is lost and comes back
  during a check, as when the server restarts, the page asks for the check
  again.

  A git nodepack that the registry does not know was left out of the check,
  unless the node list gave it an `id` that is its repository name. Every
  enabled git nodepack of the list is fetched now, so a check can take longer
  than before.

  On Windows, a check that found an update for a git nodepack put the
  install script of that nodepack down to run at the next start, though
  nothing had been updated. A check no longer does that.

  `GET /v2/customnode/getlist` no longer fetches, with or without
  `skip_update`, and `GET /v2/customnode/fetch_updates` of the legacy server
  answers 410, as that of the new one does. A check is asked for with
  `POST /v2/customnode/check_update` of the legacy server and reports by the
  `cm-check-update` event.

- A reserved install does not install a URL requirement again. A requirement
  that is a URL, as `git+https://github.com/owner/repo` or the URL of a wheel,
  was installed again by every reserved install of its nodepack, and for a
  repository that is a clone and a build at the start of the server (#3575). On
  Windows, or with `always_lazy_install`, every install, update and fix that
  the server is asked for is reserved. The requirement is now skipped when a
  package installed from that URL is there. It is then left as it is, as a name
  without a version is: new commits of the repository are not followed.
- A fix installs a URL requirement again by force. A fix of a nodepack
  (**Try fix**, `cm-cli fix`) is the way to have a package from a URL
  installed again. It installs what the package needs now, and then the
  package itself from its URL, by force and without the cache of pip or uv.
  When the repository cannot be reached, what is installed is kept, and uv
  installs the installed commit once more from its cache when it has it. A fix
  also installs the requirements that an install, an update or an earlier fix
  of the same session has installed.
- A fix that failed is reported as failed. A fix of a nodepack that the
  server is asked for (**Try fix** of the legacy page, a `fix` task of the
  queue) was reported as a success also when a requirement could not be
  installed or `install.py` failed: only the log said `install script failed`.
  Such a fix is now reported as failed. A fix that is reserved for the next
  start, as on Windows or with `always_lazy_install`, is reported as soon as it
  is reserved, as before. With `use_unified_resolver` the requirements of a
  nodepack wait for the next start as well, and the fix answers for
  `install.py` alone; the legacy core runs them at the fix.
- No deprecation warning of aiohttp with `bypass_ssl`. With
  `bypass_ssl = true`, the fetch of the legacy notice and the fetch of a list
  passed `verify_ssl=False` to aiohttp, which warns that the argument is
  deprecated: `DeprecationWarning: verify_ssl is deprecated, use ssl=False
  instead` (#2281). They now pass `ssl=False`. Without `bypass_ssl` nothing
  changes: the certificate is checked as before.
- A console that is gone does not fail a prompt. A server that was started
  with pipes for its console goes on running when the process that read them
  exits, and a write to such a pipe fails. The log hook passed that failure
  on to whatever had printed: the prompt of a node that prints, or of a
  sampler at its progress bar, ended with
  `BrokenPipeError: [Errno 32] Broken pipe`, on Windows with
  `OSError: [Errno 22] Invalid argument` (#3223). The hook now drops what the
  console does not take and does not write to that console again, and what
  is written still goes to the log file. A log record that cannot be
  formatted is no longer written to the console by the Manager, where it
  could fail the node the same way: for a record that the console shows,
  Python's logging reports it there already. The line that the Manager puts
  into the log file for such a record names the file and the line of the
  call; it named the record itself, which failed the node when the message
  of the call could not be turned into text. While stderr is gone, ComfyUI's
  own log handler fails on each record, and Python's report of that failure
  is now in the log file in full, where it broke off after its first line.
  This is the hook of the log file (`file_logging`, on by default): with it
  off, the streams are those of ComfyUI, and the progress bar still fails
  there.
- A snapshot restore clones a git node pack from the url of the snapshot.
  For a url that the registry knows, it asked for a nightly install by the id
  of the registry, which takes its url from the node list first: when the
  node list had another repository under the same name, that one was cloned.
  The restore no longer reads the node list.
- A snapshot restore leaves a node pack at the version of the registry that
  the snapshot names. A node pack that was switched from its clone to a
  version keeps the clone, disabled, and a snapshot saves both: the restore
  enabled or cloned the clone and disabled that version. When that version
  cannot be installed, the clone is restored as before.
- A clone of a snapshot restore that is refused says why in the log, as
  `Invalid git url: ...`. The summary said `[  FAILED   ]` with no word of
  why.
- A folder in `custom_nodes` with neither `.git` nor `.tracking`, left by an
  install that broke midway or by a download unpacked by hand, was taken for a
  git nodepack: Update All logged
  `ERROR: An error occurred while updating ...` for it, and its nodepack
  showed as not installed (#3330). It is now an invalid installation. Update
  All and `cm-cli update all` leave it alone, `/v2/customnode/installed`
  lists it with `invalid_installation: true`, the legacy node list marks its row
  `INVALID INSTALLATION ↗` and offers Reinstall, and the startup notice names
  it. `kind: "reinstall"` in `/v2/manager/queue/task` installs the nodepack
  again in its place. By its folder name it is enabled, disabled and
  uninstalled as before.
- A reinstall, of any nodepack, keeps the folders it replaces until the new
  installation is in place, and puts them back when the install fails. It
  deleted them first, so a failed download lost the nodepack.
  `cm-cli reinstall` makes the same reinstall and prints `[REINSTALLED]`.
- What is in the way of a reinstall, such as a clone of a fork at the install
  path or under the name of the nodepack, is moved to
  `custom_nodes/.disabled/.archived/` and the log says where it is. It is not
  deleted and no longer loaded, and it goes back when the install fails. The
  legacy server failed there with `Install path already exists`, and
  `cm-cli reinstall` deleted it.
- The console line of a failed update says why the update failed.

## [4.4.2] - 2026-11-19

### Security

- Keep the saved Matrix password on the server.
  `GET /v2/manager/get_matrix_auth` answered with the saved homeserver, username
  and password, to any client that could reach the server. It now answers
  without the password. With the legacy UI, the share dialog leaves the password
  field empty for the saved account, and the server uses the saved password for
  the username it was saved with; for another account a password has to be
  typed. An account is saved once it has logged in; a share request no longer
  replaces the saved account before that. If others could reach the server while
  a Matrix password was saved, change that password.
- Share to Matrix through matrix.org only, where the share room is. The server
  logged in to any homeserver that a share request named, with the password of
  the request. The homeserver of the legacy UI's share dialog can no longer be
  changed, a share request that names another homeserver is refused, and an
  account that was saved for another homeserver is not used: an account of
  matrix.org has to be entered.
- Keep the YouML API token in the browser that shares, which is what sends it to
  YouML. The server stored it, and `GET /v2/manager/youml/settings` answered
  with it to any client that could reach the server. Both
  `/v2/manager/youml/settings` routes are removed. With the legacy UI, the token
  has to be entered once more in the YouML share dialog. Delete `.youml` in
  `<USER_DIRECTORY>/__manager/`, and if others could reach the server while a
  token was saved, issue a new token.
- Hold a switch of ComfyUI to an older version to the security level when it is
  asked for through `POST /v2/manager/queue/task`. The switch route has needed
  `normal-` or lower on a loopback listener, or `weak` in `personal_cloud` mode,
  since 4.2.1; an `update-comfyui` task with a version was not checked. Such a
  task now needs the same when the version is an older release or is not a
  release tag. A task for `nightly` or for a newer release is an update and runs
  at every level, as before. A ComfyUI with commits after its release, as on
  `nightly`, would go back by a switch to that release, so that counts as older;
  in a repository without release tags, such as a clone without tags, every
  version but `nightly` does. `Switch ComfyUI` in the legacy UI's menu changed
  the update policy before it asked for the switch, so a switch that was refused
  still changed it; it now changes it after the switch is accepted, and says so
  when the security level does not allow the switch.
- Hold an enable that puts a nightly in the place of a registry version to the
  security level of a nightly install (`middle+`). An `enable` names a node pack
  and no version; with a registry version of the pack enabled and its nightly
  disabled, it enabled the nightly instead, at any security level through
  `queue/task` and at `middle` through the legacy UI's install route.
- Hold a snapshot restore to the security level of the switch route (`high+`).
  A restore takes the node packs back to the versions that the
  snapshot recorded. `POST /v2/snapshot/restore` needed `middle+`, which the
  default `security_level = normal` gives on a loopback listener. It now needs
  `normal-` or lower on a loopback listener, or `weak` in `personal_cloud`
  mode, and is refused otherwise. `cm-cli restore-snapshot` is not changed.
- Read a value of `config.ini` as plain text, and use the default of a setting
  for a value that it cannot have. Manager read `%(name)s` in a value as a
  reference to another setting, and a `%` that is not of that form made the
  whole file unreadable: every setting was then at its default,
  `security_level` too, and nothing said so. A value is now read as it is
  written; `%%`, which was read as one `%`, is now two. `security_level`,
  `network_mode`, `db_mode` and `update_policy` have their default when
  `config.ini` gives a value that they cannot have, and Manager logs a warning
  that names it; the other settings are read as before, and `config.ini` keeps
  the value. Before, a `security_level` that is not a level refused every
  action that needs one; now it is `normal`. A `config.ini` that cannot be read
  at all still gives the default settings, and is still written anew from them
  when a setting is saved; Manager now logs a warning when it reads one.
- Take a JSON body only as `application/json`. A POST route that reads a JSON
  body parsed it whatever the Content-Type of the request. These routes, among
  them `POST /v2/manager/queue/task` and `POST /v2/manager/queue/batch`, now
  answer 400 unless the Content-Type is `application/json`. The legacy routes
  `POST /v2/customnode/install/git_url` and `POST /v2/customnode/install/pip`
  now take `{"url": ...}` and `{"packages": ...}` as JSON in place of plain
  text. A script or tool that posts to these routes without
  `Content-Type: application/json` has to add it.
- Save only a choice of the share menu as the share option.
  `/v2/manager/share_option` saved any text as the share option. It now saves
  `all`, `none`, `youml` or `matrix`, the choices of the menu, and answers 400
  for another value.
- Write the saved Matrix account as a file of its user only. The share dialog
  saves the account, with its password, in `matrix_auth` in Manager's data
  directory. The file was written with the default mode of new files, which
  other users of the machine can usually read. It is now written with mode
  `0600`, and a file that is already there gets that mode the next time an
  account is saved.
- Take every POST that changes something only as `application/json`, and save
  the share option by POST. A page of another site can make the browser send a
  GET, and a POST without a body and without a Content-Type, for which no
  preflight is made. The routes that take no body
  (`/v2/manager/queue/start`, `/v2/manager/queue/reset`,
  `/v2/manager/queue/update_all`, `/v2/manager/queue/update_comfyui`,
  `/v2/snapshot/save`, `/v2/snapshot/remove`, `/v2/snapshot/restore`,
  `/v2/manager/reboot`) now answer 400 unless the request has
  `Content-Type: application/json`, as the routes that read a JSON body do: a
  browser does not send that header to another site without a preflight. The
  share option is saved with `POST /v2/manager/share_option` and a JSON body
  `{"value": ...}`; `GET /v2/manager/share_option` only answers with the saved
  option, and a `value` given to it is ignored. The legacy UI sends the header.
  A script that calls one of these routes has to send it too, and one that
  saved the share option with `?value=` has to POST.

## [4.4.1] - 2026-11-19

### Fixed

- Restarting ComfyUI from the Manager under comfy-cli no longer prints
  `ValueError: I/O operation on closed file` on the console. The log file is
  closed before the process exits, and what was logged after that was still
  written to it.
- In the legacy UI, Update ComfyUI and Update All with ComfyUI no longer end
  with status 500 and nothing queued. The batch route called the handler of
  the update route without a request.
- With `update_policy = nightly`, the legacy server updates ComfyUI to the
  nightly version. Only `nightly-comfyui` was taken as nightly, and `nightly`
  as stable.
- The legacy server answers 400 again when the list of ComfyUI versions cannot
  be read or a switch to another version fails. The call that logs the cause
  was given an argument it does not take, so the answer was 500 with a
  `TypeError` in the log.

- Update ComfyUI to the latest stable version again when Manager runs git
  through GitPython, which it does whenever the `git` command is available.
  The update ended with `Failed to checkout 'master' branch` and ComfyUI
  stayed at its version: the branch to check out was passed to git as an
  object instead of by its name. An update to the nightly version failed the
  same way when the checkout was detached and the remote's default branch was
  not known locally.

- On the default server, `POST /v2/manager/queue/update_comfyui` follows
  `update_policy` when the request names no version line. Its `stable`
  parameter defaulted to true, so the policy was never read and such a request
  updated ComfyUI to the stable version also under `nightly-comfyui`.
  `nightly` is taken as nightly too.
- On the default server, the same route reads `is_stable`, the name the
  ComfyUI frontend sends, when `stable` is not given. It was ignored.
- `openapi.yaml` lists the values the two setting routes accept: `cache` for
  `db_mode` and `stable-comfyui` for the update policy were missing.

- Print console messages with paths, URLs and package names as they are.
  Manager printed many of its messages through rich, which reads square
  brackets as markup: a package name such as `diffusers[torch]` was shown as
  `diffusers`, a text such as `:100:` as an emoji, and a line longer than the
  console was broken in the middle of a path or a URL. A text with a closing
  tag such as `[/b]` raised `MarkupError` instead of being printed, in the
  middle of the operation that reported it. Numbers and quoted strings keep
  their colors.

- Start with a node pack whose `.git/config` Manager could not read. A url
  with a `%`, such as one with `%20`, a key without a value, such as `bare`
  alone, a key on a line that is indented more than the one before it, a byte
  order mark at the start of the file, or on Windows text that
  the code page of the system cannot decode, such as a Korean user name
  written in UTF-8, raised an error while Manager was loading: ComfyUI did not
  start, or with `--enable-manager-legacy-ui` started without Manager. These
  files are read now, and for a file that cannot be read the url of that pack
  is unknown and a warning names the file once.

- Run the git executable set as `git_exe` in `config.ini`. The path was read
  but not used: with the GitPython backend, git commands kept running the
  `git` found on `PATH`, and without a `git` on `PATH` the pygit2 backend was
  selected, or with the legacy UI Manager did not load. Both servers, the git
  helper and `cm-cli` now run the configured executable. For the servers and
  what they start it no longer has to be on `PATH`; `cm-cli` run by hand still
  needs a git on `PATH`. A value that is not a working git is reported, and
  the default git is used. The value is read as it is written: with a `%` in
  it, as in a path of Windows, Manager read every setting of `config.ini` as
  its default. The configured executable is also run when pygit2
  is asked for with `CM_USE_PYGIT2=1` but is not installed.
- Start without a git. With neither a `git` on `PATH` nor pygit2, ComfyUI did
  not start, or with the legacy UI started without Manager; Manager now loads
  and reports that git is missing, and what needs git fails when it is used.
  With pygit2 and no `git`, the legacy UI started without Manager; it now
  loads on the pygit2 backend, but what the legacy server does with GitPython
  itself still needs a git.

- Update the submodules of a submodule with the pygit2 backend, and fail when
  the submodules could not be updated. pygit2 updated the submodules of the
  nodepack and not those below them, which git does. When it could not update
  them and there was no `git` to do it in its place, or that `git` did not
  answer in time, a message was printed and the install or the update went on
  as if they were updated.
- Fetch the submodules of a nodepack through the proxy with the pygit2
  backend. The nodepack was cloned through the `http.proxy` of the global git
  configuration and its submodules were not, so behind a proxy they could not
  be fetched. As for the nodepack, the proxy is used for an `https` url.
- Fetch a submodule with an ssh url over https with the pygit2 backend, as the
  nodepack itself is. It was asked for credentials, which pygit2 does not
  have, and with a public repository does not need.
- Fetch a submodule again with the pygit2 backend after its clone failed, and
  check one out again after its checkout was removed, as by an update that
  was undone. What was left of it in `.git/modules` kept every later update
  from it.
- Update a nodepack whose submodule is at another commit than the nodepack
  names, with the pygit2 backend. The update ended before the pull, at a
  stash with nothing to stash, as it did after a submodule could not be
  fetched once.
- Do not end a clone or a fetch of the pygit2 backend at a progress message
  of the server. pygit2 decodes each piece of such a message as UTF-8, and a
  piece can end in the middle of a character: with a server that writes its
  messages in a language other than English, a clone, a fetch or the update
  of a submodule failed now and then with `UnicodeDecodeError`.
- Bring the submodules of a git nodepack to the commits that its commit names
  when a snapshot restore checks it out, and also when it is at the commit of
  the snapshot already. A submodule that was never fetched is then fetched
  too in a nodepack that Manager installed, as Manager clones a nodepack with
  its submodules; with the pygit2 backend, or in a nodepack cloned without
  them, it is fetched only when the nodepack itself is checked out.
- Record the commit of a git nodepack whose refs are packed, as after
  `git gc`, in a snapshot. It was recorded as `unknown`. A `HEAD` that is not
  UTF-8, as one that names a branch in another encoding, raised an error where
  the commit of a nodepack is read. It is read as bytes now. On Windows the
  commit of a branch whose name is not ASCII, as a Korean one, could be
  unknown as well: the file of the branch is looked for under the name that
  Git for Windows gives it.
- Start with a git nodepack whose commit cannot be read. The commit is read
  while Manager is loading, and an error there kept ComfyUI from starting, or
  with `--enable-manager-legacy-ui` Manager from loading: for a `.git` with a
  folder where the file of the branch would be, as after
  `git checkout --orphan feature` beside a branch `feature/x`, or with a file
  that cannot be read. The commit of such a nodepack is unknown now.
- Fail an update whose pull failed in the git helper. On Windows the pull runs
  in a helper process, which ended with 0 when the pull failed, and its result
  was not read: the update went on to the install script and ended as done.
  The helper ends with 1 now.
- Undo the pull of an update when the update of its submodules fails. The
  nodepack stayed at the new commit: the next update found nothing to do, and
  the install script of the update never ran. The submodules that were updated
  before the one that failed go back with it. A nodepack with a submodule
  that cannot be fetched at all is not updated until it can.

- Carry out a scheduled snapshot restore in the directories of the server.
  With `--base-directory`, the restore that runs at the next start worked on
  the Manager's files and the `custom_nodes` directory inside the ComfyUI
  directory instead of those of the base directory: it did not see the node
  packs of the server.

- Report the steps of a snapshot restore that failed. The summary listed a
  nodepack as `INSTALLED`, `DISABLED` or `ENABLED` without looking at the
  result of the step: a clone that failed, for example because the directory
  already existed or the url could not be reached, was `INSTALLED`. A step that
  fails is listed as `FAILED`, and Manager itself is no longer listed as
  `DISABLED`. A Registry that cannot be reached ended the restore at the first
  nodepack to install from it, and so did a nodepack whose directory could not
  be moved to disable or enable it; such a nodepack is listed as `FAILED`, and
  the restore goes on. `cm-cli restore-snapshot` ends with 1 when a step failed
  or a pip package that a `--pip-*` option selects was not installed, and a
  scheduled restore then says `Restore snapshot failed.`: it ended with 0. A
  url of the snapshot that cannot be parsed ended the restore as well; the
  nodepack is listed as `FAILED`. A git nodepack of the Registry that was
  already installed, or that the restore enabled, was listed a second time as
  `SKIPPED`; it is listed once. An installed one that is checked out is listed
  by its name, as the others are: it was listed by its path.
- Restore the commit of the snapshot for every git nodepack. A git nodepack
  that the restore had to clone stayed at the newest commit; it is checked out
  at the commit of the snapshot, and its install script runs after that. When
  the commit cannot be checked out, the install script still runs, at the
  commit the clone is at, and the nodepack is listed as `FAILED`. An installed
  git nodepack that the Registry does not know was checked out only when
  `cm-cli` was run from `custom_nodes`, as a scheduled restore does; it is
  checked out from any directory.
- Install the requirements and run the install script of a Registry nodepack
  that a snapshot restore installs. The nodepack was unpacked and nothing
  more. It is listed as `FAILED` when they fail.
- Try a requirement or an install script that failed again. It was taken as
  done until the next start: the next nodepack that names the requirement
  skipped it, and installing or fixing the nodepack again did not run the
  script. The install script of a git nodepack was skipped in the same way
  when it was cloned where another version of the nodepack had been installed
  since the start, as a restore does for a snapshot that has both; it runs.
- Write what is reserved for the next start as UTF-8, which is how the
  start-up script reads it. The install script of an update, the removal of a
  nodepack whose files are in use and a switch of version are reserved in a
  file that was written in the encoding of the system. On Windows a path with
  a character outside ASCII was lost: one that the code page cannot write,
  such as a Korean folder name with code page 1252, raised an error and
  nothing was reserved; one that it can write was read back as another path,
  and what was reserved was not carried out at the next start.
- Remove the files of the old version from the nodepack when a switch of
  version is carried out at the next start. The files that the new version no
  longer has were looked for in `custom_nodes` in place of the directory of the
  nodepack: they stayed in the nodepack, and a file of the same name in
  `custom_nodes` was removed. A switch of version, at the next start or at
  once, removes the files that the new version no longer has before it extracts
  the archive of the new version: where two names are one file, as `./a.py` and
  `a.py`, or names that differ in case alone on Windows, a file of the new
  version was removed after it was extracted. A name of the old list that leads
  out of the nodepack, with `..` or as an absolute path, removed a file outside
  it; nothing is removed for such a name. A file that the old version has alone
  and that cannot be removed, as one that another program has open on Windows,
  is left with a warning, and the switch goes on with the files of the new
  version. A nodepack whose directory keeps its name is no longer moved onto
  itself at the next start, which Windows refuses while a file in it is open.
  When the switch moves the nodepack to another directory, the install script
  of the new version runs there; it was looked for in the directory that the
  nodepack was moved from, and did not run.
  A folder that the files of the old version left empty, or with nothing but
  the `__pycache__` of Python, stayed, and a file of the new version could not
  take its place; such a folder is removed.
- Read the list of the files of a Registry nodepack as UTF-8, which is how it
  is written. It was read in the encoding of the system: on Windows a switch of
  version of a nodepack with a file name that the code page of the system
  cannot decode ended in the middle, with the files of the new version
  unpacked, its install script not run and the files of the old version left. A
  name of the list is read as it is written: a space at its start or its end
  was dropped, and the file of the other name was the one removed.

- Refuse a `db_mode` or an `update_policy` that Manager does not know in the
  legacy server. With `--enable-manager-legacy-ui`, the two setting routes
  stored whatever value a request carried and wrote it to `config.ini`. They
  answer 400 for a value that is not one of the known ones, as the default
  server does.
- Answer 400 from the two setting routes of both servers for a JSON body that
  is not an object. It ended with status 500.
- Name the security level `normal-` and the database mode `channel` as the
  servers do in `common/enums.py`, which had `normal-minus` and no `channel`.
  Nothing read these two members.

- Keep a database mode, update policy or share option that is chosen in the
  legacy Manager menu while the menu is still loading the stored value. The
  value was saved, but the menu went back to showing the old one when it
  arrived.

- Draw the dialogs of the legacy UI with styles of Manager's own. The Manager
  menu, the Custom Nodes Manager, the Model Manager and the Snapshot Manager
  were built with the classes of PrimeVue dialogs and buttons, and a ComfyUI
  frontend that no longer ships those styles drew them without a background:
  the buttons lay over the canvas and the nodes behind them. `main` has had
  this change since #3392.

## [4.4] - 2026-11-16

### Changed

- Require Python 3.10 or newer to match ComfyUI's minimum supported version.
  Python 3.9 is no longer supported.

### Removed

- Remove four share destinations of the legacy UI that no longer take workflows
  from Manager: ComfyWorkflows (its domain registration has expired), Copus (its
  API answers that publishing from ComfyUI is no longer supported), OpenArt (its
  workflow API and pages are gone), and eSheep (its site no longer resolves).
  Sharing to YouML and to the Matrix server is unchanged. A saved `Share`
  setting that names a removed site now acts as `All`, and the Workflow Gallery
  button no longer opens a removed site that was visited last. The files saved
  for the removed sites are no longer read; `comfyworkflows_sharekey`,
  `.openart_key`, and `esheep_share_message.json` under
  `<USER_DIRECTORY>/__manager/` can be deleted.

### Security

- Allow administrators to exempt selected Registry IDs from the flagged CNR
  install restriction using `nodepack-whitelist.list` beside Manager's `config.ini`.
  Entries are case-insensitive, apply to all versions, and take effect without a
  restart. Server startup creates a commented template with no default exceptions;
  other installation security checks still apply.
- Verify the TLS certificate when the legacy UI fetches its notice from GitHub;
  verification was off for every user. A response whose certificate is not
  trusted is discarded and the notice area shows `Unable to retrieve Notice`. It
  shows the same when the connection fails, where it used to show a server
  error. Behind a proxy that re-signs TLS traffic, point the `SSL_CERT_FILE`
  environment variable at a CA bundle that includes the proxy's CA, or set
  `bypass_ssl = True` in `config.ini`, which turns verification off for this
  fetch too (#3302).
- Check every model install against the model list, including the download URL:
  the folder, base, file name, and URL must match an entry. With the legacy UI,
  a request with a listed name and another URL was accepted. Without it, the
  list was not checked, and neither was the rule that a model in a format other
  than `.safetensors` must be in the default channel's list unless the security
  level is `normal-` or lower on a loopback listener, or `weak` in
  `personal_cloud` mode (#3428).
- Share to the Matrix server only a file inside ComfyUI's output or temp
  directory. The file name and subfolder of the output to share come from the
  request and were not checked, so a request could have any file that ComfyUI
  can read uploaded to the Matrix homeserver named in the same request. Only
  installations with `matrix-nio`, which Manager does not install, were
  affected (#3427).

### Fixed

- Apply `downgrade_blacklist` to packages whose names contain a hyphen, such as
  `opencv-python`; they were never protected. Names in `downgrade_blacklist`,
  `pip_blacklist.list`, and requirements are now compared without regard to case
  or to `-`, `_`, and `.` (#3458).
- Read every version clause of a requirement, so `numpy>=1.24,<2` no longer
  passes because its lower bound comes first, and read requirements written with
  spaces, parentheses, an environment marker, or as a direct reference
  (`name @ url`). Versions with a local label such as `0.0.30+cu126` or a fourth
  component such as `5.0.0.93` are compared correctly.
- Install a requirement with extras for a `downgrade_blacklist` package unless it
  would downgrade the package, so the extras' dependencies are still installed.
- Skip a `downgrade_blacklist` package when the requirement cannot be compared
  with the installed version, such as a malformed version or a direct reference,
  and log the reason with how to install it. The list check previously raised an
  error or let the install proceed.
- Apply `downgrade_blacklist` and `pip_blacklist.list` to requirements that carry
  pip options such as `--index-url`, and to installs run through uv in embedded
  Python or as a standalone tool. These installs were not checked.
- At startup, recognize an installed package however its requirement spells the
  name. Pending installs no longer downgrade or reinstall packages whose names
  contain `-` or `.`, and a requirement older than its `~=` version is upgraded.
- Restore the OpenCV repair that runs at startup and after installs. When
  `opencv-python`, `opencv-python-headless`, `opencv-contrib-python`, and
  `opencv-contrib-python-headless` are installed at different versions, the older
  ones are reinstalled at the newest installed version, without their
  dependencies, so numpy is left as it is. A headless package is installed
  after one with the GUI, so `cv2` stays importable on a Linux without the
  graphics libraries; within each kind, the package with the contrib modules is
  installed last. OpenCV packages listed in `pip_auto_fix.list` are left to
  that list. The repair found no installed OpenCV package and did nothing; it
  now also compares four-part versions such as `4.11.0.100` numerically.
- In the legacy core, except on Windows, give the backup branch the next free
  name when an update cannot fast-forward and a backup branch of the same second
  already exists. The existing name was reused, so creating the branch failed
  and the update was not applied.
- On Windows, keep command-line arguments intact when ComfyUI restarts, from the
  Restart button or after an install that runs at startup. An argument with a
  space, such as `--output-directory "D:\My Outputs"`, was split in two, so
  ComfyUI failed to start with `unrecognized arguments`; quotation marks and
  empty arguments were lost as well. A ComfyUI started as a module (`python -m`)
  from a Python path with a space now restarts too (#3339).
- In the legacy UI, make `Fix node (recreate)` work on a node with a connected
  input on frontends whose node ids are strings. It stopped with
  `findInputSlot is not a function` and left two copies of the node on the
  canvas: the original, still wired, and an unwired replacement (#3126).
- In the legacy UI, make `Fix node (recreate)` work on a node inside a
  subgraph. It read the node's links from the root graph, so it stopped with an
  error and left the same two copies of the node. Links to the inputs and
  outputs of the subgraph are kept as well.
- Read the version of a node pack installed from the registry when it has a
  pre-release, such as `1.8.0-beta.1` or `0.7.2-b2`; such a pack was not
  recognized as a registry pack. A version with a fourth part, such as
  `0.1.3.post1`, stopped the scan of installed node packs with
  `invalid literal for int()`, in the server and in `cm-cli` (#3431).
- Compare the versions in `pip_auto_fix.list` as pip does. An entry for a
  package installed with a local label or as a pre-release, such as
  `torch==2.5.1` beside an installed `2.5.1+cu124`, was skipped with
  `Failed to restore`. Such an entry is now applied: that installed version
  meets it, and one that does not, such as `2.6.0+cu124`, is replaced with
  `pip install`. `~=` is a compatible-release clause: it was taken as met by
  any other version, and as not met by the same version.
- Keep the custom node list and the model list loading when the channel answers
  with something other than JSON, such as a block page or `404: Not Found`. The
  startup cache update stored an empty result in the cache, in place of a list
  cached earlier, and the lists then failed to load from it until a later start
  got the lists from the channel; with the legacy UI the Model Manager showed
  `Failed to get external model list.`. Such a response is now handled like a
  failed connection: the cache is left as it is, and without a cached list the
  one bundled with the Manager is used. An empty result that an earlier version
  cached is replaced at the next start that reaches the channel, or goes away
  when the files in `<USER_DIRECTORY>/__manager/cache` are deleted (#3480).
- Judge a requirement for a `downgrade_blacklist` package by all of its clauses.
  One that allows the installed version is installed when another clause sets a
  minimum above it, as in `transformers==4.*,>=4.58.0` beside an installed
  `4.57.0`, or excludes it with `!=` while a newer version is allowed, as in
  `transformers~=4.57.0,!=4.57.0`; without extras both were skipped, so the
  upgrade did not happen. One that the installed version does not meet and
  that allows no newer version, as in `transformers[torch]<=4.57.0,!=4.57.0` or
  `transformers<4.58,!=4.57.*`, is skipped; it was installed, and pip replaced
  the package with an older version. A pre-release counts as a newer version
  only when `==`, `>=`, `<=`, `~=` or `===` names one: pip before 25.0 takes no
  other.
- At startup, read `>` as pip reads it: a post-release of the version, such as
  `1.0.post1` for `>1.0`, does not meet it, and the requirement is installed. A
  wildcard such as `==0.21.*` is met by an installed pre-release `0.21.0rc1`,
  and the requirement is no longer passed to pip.
- At startup, install a requirement that excludes the installed version with
  `!=` and allows a newer one, as in `numpy>=2.2.0,!=2.2.0` beside an installed
  `2.2.0`, as an immediate install does; it was taken as installed already. pip
  chooses the version, and that is an older one when no newer release exists.
- Leave an installed local build, such as the CUDA build `2.5.1+cu124`, alone
  on all of these grounds. For a `downgrade_blacklist` package, keep it as well
  when a requirement excludes it with `!=`, as in `xformers!=0.0.30` beside
  `0.0.30+cu126`, unless the requirement sets a minimum above it; pip replaced
  the build with whatever it found. For such a build, these changes only add
  requirements that are skipped.
- In the legacy UI, enable a disabled node pack that another extension
  requires before restarting. After the user agreed to enable it and restart,
  ComfyUI restarted with the pack still disabled, because the request went to
  a route that no longer exists. The pack is now enabled through the queue, as
  the Custom Nodes Manager does, and ComfyUI restarts only when that
  succeeded; otherwise the reason is shown. While other tasks are queued
  behind the pack, ComfyUI is not restarted, and the user is asked to restart
  after them. `Rebooting...` is shown as well: the restart request is never
  answered, which ended the handler before it.
- In the legacy UI, say so when that restart is refused at the current
  security level. Nothing was shown; the browser console had
  `show_message is not defined`.
- With `cm-cli restore-snapshot` and its `--pip-non-url`, `--pip-non-local-url`
  or `--pip-local-url` options, report a pip package as failed only when pip
  fails for it. Every package was listed under `Installation failed for pip
  packages`, and pip was run a second time for each package named by version
  (#3425).
- When restoring a snapshot, check a git node pack out at the commit the
  snapshot names when the snapshot was saved while that pack's HEAD was
  detached. The hash was saved with the newline that follows it in `.git/HEAD`,
  so the checkout failed and the pack was reported as skipped at the commit it
  had. New snapshots hold the bare hash, and the newline in an existing
  snapshot is ignored. A registry node pack already at the snapshot's version
  is left alone without asking the registry; when the registry could not be
  reached, that lookup stopped the restore (#3426).
- Replace a cache file in one step when it is updated, so a write that stops
  part-way leaves the previous list. It left a truncated file, which Manager
  reads as an empty list. The age of a cached list is counted from its last
  write; it was read from the file's creation time, which Windows keeps when a
  file is rewritten (#3432).
- When the archive of a registry node pack cannot be extracted, report the
  failure and remove the directory created for the pack and the downloaded
  archive. Both were left behind, and installing the pack again stopped with
  `Install path already exists` until the directory was removed by hand (#3433).
- In the legacy UI, show a node's name, inputs, default values, outputs and
  description as text in the preview that appears over a node name in a pack's
  node list. They were inserted as HTML, so a default such as
  `<lora:name:0.8>` was missing from the preview and markup in a node
  definition was rendered (#3434).
- In the legacy UI, keep the Model Manager waiting for its downloads when
  another batch finishes, such as a node pack install queued before them or a
  model install started earlier. It showed the downloads as done while they
  were still running, hid the Stop button, and ignored their real completion.
  After Stop, the dialog returns to idle; it stayed waiting, with its Stop
  button. A failed download is no longer followed by the request to click
  Refresh (#3303, #3437).
- In the legacy UI, say why restoring or removing a snapshot failed. For a
  request the server refused, the message was `Restore snapshot failed:
  undefined / ReferenceError: exception is not defined`, also for a removal,
  and a refused restore still asked for a restart. An answer with another
  error status was taken as success (#3436).
- With file logging on, tell libraries that ask whether the console is a
  terminal the state of the real console. The logger that captures the output
  always answered that it was not one, so after `colorama.init()` the colors of
  every `print()` were removed, and tqdm and rich took a terminal for a pipe
  (#3259, #3423).

## [4.3] - 2026-09-19

### Security

- Prevent HTML and URL injection in the legacy Manager UI while preserving
  supported formatting and links.
- Require loopback-only listeners or `allow_flagged_nodepack_install = true`
  to install Flagged CNR versions through either Manager API. This requirement
  is additional to the existing installation security checks.

### Fixed

- Preserve administrator settings when saving configuration from the Manager UI.
- Clear legacy install progress state when batch submission fails.
- Attribute multiline uv dependency conflicts to the affected nodepacks while
  filtering unrelated stderr output.

## [4.2.2] - 2026-06-15

### Security

- **Dedicated install flags decouple git-URL / pip installs from `security_level`**:
  `POST /v2/customnode/install/git_url` and `POST /v2/customnode/install/pip`
  (and the batch install path for git URLs not in the custom-node DB) are now
  gated by two new `config.ini` `[default]` flags — `allow_git_url_install`
  and `allow_pip_install` — instead of `security_level`. Both default to
  `false` (secure by default), and a non-loopback listener stays denied unless
  `network_mode = personal_cloud` (the existing network-position invariant is
  retained — the flags never widen exposure beyond what was possible before).
  `security_level` no longer has any effect on these two endpoints, in either
  direction. The unknown-pip-package block in batch installs remains
  unconditional. Activation requires a restart (no hot reload).

### Migration notes

- **Users running `security_level = weak` or `normal-`**: these environments
  could previously use the git-URL / pip install endpoints; after upgrading
  they are denied (HTTP 403) until you explicitly opt in by setting
  `allow_git_url_install = true` and/or `allow_pip_install = true` in the
  `[default]` section of `config.ini`. The flags are NOT auto-seeded from
  your `security_level` — explicit opt-in is intentional.

### Fixed

- **pygit2 fallback hardening (Desktop 2.0)**: under `CM_USE_PYGIT2=1` the
  pygit2 backend ran `clone_repository` / `remote.fetch` honoring the user's
  global git config, so an `insteadOf` rewrite (https→ssh) or credential
  helper forced authentication and failed with *"authentication required but
  no callback set"*. The system/global/XDG config search path is now blanked
  at import time (hermetic libgit2 operations) and SSH-form GitHub URLs are
  normalized to anonymous HTTPS on clone and when opening a repo. System
  `git` is preferred when available.
- **pygit2 fallback follow-ups**: `list_remotes()` fetches now route through
  `_fetch_remote` so the proxy and SSH→HTTPS rewrite apply to every fetch
  entry point, with `pull` provided on the proxies via a shared
  `_pull_remote` helper. `_to_https_url` now handles `ssh://git@host:port/...`
  URLs (drops the custom SSH port instead of mangling it) and collapses
  leading slashes; non-scp-form and port-only/IPv6 `ssh://` URLs are returned
  unchanged. `clone_repo` omits the `proxy=` kwarg when no proxy is
  configured (proxy-less installs keep working on pygit2 < 1.18), and pygit2
  is now pinned to `>= 1.18`.

## [4.2.1] - 2026-04-22

Security-hardening release. Contains breaking-ish API changes for
state-mutating endpoints. See **Migration notes** below before upgrading
programmatic clients.

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

- **Server-push feature flag `extension.manager.supports_csrf_post`** registered
  at startup, allowing ComfyUI-frontend (and other clients) to detect
  CSRF-POST backend support as a semantic capability contract, without
  relying on version string parsing. Manager versions prior to 4.2.1 do not
  set the flag — clients should treat its absence as 'incompatible with
  POST-only state-mutation endpoints'.
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

[4.4.2]: https://github.com/Comfy-Org/ComfyUI-Manager/compare/v4.4.1...v4.4.2
[4.4.1]: https://github.com/Comfy-Org/ComfyUI-Manager/compare/v4.4...v4.4.1
[4.4]: https://github.com/Comfy-Org/ComfyUI-Manager/compare/v4.3...v4.4
[4.3]: https://github.com/Comfy-Org/ComfyUI-Manager/compare/v4.2.2...v4.3
[4.2.2]: https://github.com/Comfy-Org/ComfyUI-Manager/compare/v4.2.1...v4.2.2
[4.2.1]: https://github.com/Comfy-Org/ComfyUI-Manager/compare/v4.1b6...v4.2.1
