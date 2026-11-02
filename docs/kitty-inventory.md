# Kitty inventory — build research 2026-11-02

**Status: source-researched / TESTED-ONLY; not owner-version or Fedora-membership verified.**

Upstream v0.47.1, commit `fb5255b1ae4f0249ba832d6a773348fd103449ce`.
Owner ruling: `0.47.1-1.fc44`; actual `kitten --version`: **NOT RECEIVED**.
Do not substitute this version claim for verbatim owner output. No live kitty was run.

Authority: owner 2026-11-02 sequencing-only addendum > builder v1.1 > KITTY-CLAUSE v2.
Clause SHA256: `8be8a4a94e958e1fd0323d8e687418f73e6cfd407a5a08bb6720b75769ffb6bc` (unchanged).
PR23, console cherry-pick and SC-H1 remain independent held tracks, not build prerequisites.

## Scope and trust

- Ring 1 contains all 39 upstream `kitty/rc` commands, including deprecated `new-window`.
- Ring 2 enumerates upstream bundled kittens and companion tools; Fedora package membership still needs `rpm -ql` evidence.
- Ring 3 includes the five requested configuration entries, packaging limits and Hyprland version findings.
- Every tier below is a **minimum**, not a task whitelist. Unknown verbs default K3.
- Close HER journaled IDs is K2; close HIS or mixed tabs is K3. Reversible typing in HER windows can be K2; HIS input is K3.
- Any irreversible/credential/unknown effect escalates K3. Existing T3 holds still refuse: a K3 Yes never overrides them.
- SSH options depend on the installed OpenSSH binary. The pinned fallback flags and complete kitty-specific ssh.conf/copy surface are included; installed SSH help/man reconciliation is still open.
- Defaults are the command-line defaults; an absent Python string default is None but generated Go CLI uses an empty string. `declared_default` retains explicit source metadata.
- CLI fields are not wire fields. Protocol specs and options are separately recorded. Raw source expressions are retained rather than guessed.

## Primary sources and appendix cross-check

- [kitty pinned source](https://github.com/kovidgoyal/kitty/tree/v0.47.1): `kitty/rc/*.py`, `kitty/launch.py`, `kitty/simple_cli_definitions.py`, `gen/go_code.py`, `tools/cli/help.go`, `kittens/*`.
- [Protocol](https://github.com/kovidgoyal/kitty/blob/v0.47.1/docs/rc_protocol.rst): DCS JSON, X25519/SHA256/AES-256-GCM, base85, async and streaming.
- [Password enforcement](https://github.com/kovidgoyal/kitty/blob/v0.47.1/kitty/boss.py): password mode works over sockets; socket/socket-only bypass socket password checks.
- [Hyprland v0.57.0](https://github.com/hyprwm/Hyprland/tree/v0.57.0), commit `0aa6745f705f2c4b0a5004eb019ef76e5bbdb426`: Lua ConfigManager, example/hyprland.lua, Rule.cpp, WindowRuleEffectContainer.cpp and LuaBindingsConfigRules.cpp confirm the replacement rule in setup.
- [RA-15](https://github.com/jantman/robot-army/issues/125), [mcp-radar 107](https://github.com/Danyw24/mcp-radar/issues/107), [compass 88](https://github.com/tuna-os/compass/issues/88): read at build time; corroborate predictable /tmp paths, symlink and cross-UID hazards. These are reports, not owner-machine measurements.
- [dotfiles PR6](https://github.com/snaraj/dotfiles/pull/6): reviewed as third-party application/paste evidence, not transferable proof for this owner or pinned kitty.
- Clause discussion 5320 was not retrievable via the issues API (404; discussion endpoint is distinct). No claim it is absent.
- Fedora package pages, external man mirrors, forums and agent-CLI comparison pages were outside this sandbox internet allowlist. Their claims were NOT independently re-verified; pinned upstream implementation takes precedence for implementation facts.

### Build-time errata (the Drive clause is NOT rewritten)

- set-os-window-title is not a v0.47.1 RC verb; launch has --os-window-title for initial titles.
- listen_on prose omits password from allowed modes, but boss.py explicitly permits password.
- Hyprland v0.57.0 uses Lua, not the clause windowrulev2 spelling.
- Bracketed paste is application-controlled, not proof of non-execution.
- send-key declares exclude_active but its handler does not enforce it; bridge must exclude IDs itself.

## Ring 1 — every remote-control verb

| Verb | Minimum | Purpose |
|---|---|---|
| `action` | K3 | Run the specified mappable action |
| `close-tab` | K2 | Close the specified tabs |
| `close-window` | K2 | Close the specified windows |
| `create-marker` | K2 | Create a marker that highlights specified text |
| `detach-tab` | K2 | Detach the specified tabs and place them in a different/new OS window |
| `detach-window` | K2 | Detach the specified windows and place them in a different/new tab |
| `disable-ligatures` | K2 | Control ligature rendering |
| `env` | K3 | Change environment variables seen by future children |
| `focus-tab` | K2 | Focus the specified tab |
| `focus-window` | K2 | Focus the specified window |
| `get-colors` | K1 | Get terminal colors |
| `get-text` | K1 | Get text from the specified window |
| `goto-layout` | K2 | Set the window layout |
| `kitten` | K3 | Run a kitten |
| `last-used-layout` | K2 | Switch to the last used layout |
| `launch` | K2 | Run an arbitrary process in a new window/tab |
| `load-config` | K3 | (Re)load a config file |
| `ls` | K1 | List tabs/windows |
| `new-window` | K2 | Open new window |
| `remove-marker` | K2 | Remove the currently set marker, if any. |
| `resize-os-window` | K2 | Resize/show/hide/etc. the specified OS Windows |
| `resize-window` | K2 | Resize the specified windows |
| `run` | K2 | Run a program on the computer in which kitty is running and get the output |
| `scroll-window` | K1 | Scroll the specified windows |
| `select-window` | K2 | Visually select a window in the specified tab |
| `send-key` | K3 | Send arbitrary key presses to the specified windows |
| `send-text` | K3 | Send arbitrary text to specified windows |
| `set-background-image` | K3 | Set the background image |
| `set-background-opacity` | K2 | Set the background opacity |
| `set-colors` | K2 | Set terminal colors |
| `set-enabled-layouts` | K2 | Set the enabled layouts in tabs |
| `set-font-size` | K2 | Set the font size in the active top-level OS window |
| `set-spacing` | K2 | Set window paddings and margins |
| `set-tab-color` | K2 | Change the color of the specified tabs in the tab bar |
| `set-tab-title` | K2 | Set the tab title |
| `set-user-vars` | K2 | Set user variables on a window |
| `set-window-logo` | K3 | Set the window logo |
| `set-window-title` | K2 | Set the window title |
| `signal-child` | K3 | Send a signal to the foreground process in the specified windows |

### Global CLI flags (inherited by every RC command)


##### `--to`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

An address for the kitty instance to control. Corresponds to the address given
to the kitty instance via the :option:`kitty --listen-on` option or the
:opt:`listen_on` setting in :file:`kitty.conf`. If not specified, the
environment variable :envvar:`KITTY_LISTEN_ON` is checked. If that is also not
found, messages are sent to the controlling terminal for this process, i.e.
they will only work if this process is run within a kitty window.


##### `--password`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

A password to use when contacting kitty. This will cause kitty to ask the user
for permission to perform the specified action, unless the password has been
accepted before or is pre-configured in :file:`kitty.conf`. To use a blank password
specify :option:`kitten @ --use-password` as :code:`always`.


##### `--password-file`

Type: `str`; CLI default: `"rc-pass"`; explicit source default: `"rc-pass"`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

A file from which to read the password. Trailing whitespace is ignored. Relative
paths are resolved from the kitty configuration directory. Use - to read from STDIN.
Use :code:`fd:num` to read from the file descriptor :code:`num`.
Used if no :option:`kitten @ --password` is supplied. Defaults to checking for the
:file:`rc-pass` file in the kitty configuration directory.


##### `--password-env`

Type: `str`; CLI default: `"KITTY_RC_PASSWORD"`; explicit source default: `"KITTY_RC_PASSWORD"`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

The name of an environment variable to read the password from.
Used if no :option:`kitten @ --password-file` is supplied. Defaults
to checking the environment variable :envvar:`KITTY_RC_PASSWORD`.


##### `--use-password`

Type: `choices`; CLI default: `"if-available"`; explicit source default: `"if-available"`.
Choices: if-available, never, always.
Option hazards: sensitive-input-or-code.

If no password is available, kitty will usually just send the remote control command
without a password. This option can be used to force it to :code:`always` or :code:`never` use
the supplied password. If set to always and no password is provided, the blank password is used.


--help is generated by the CLI; other command-local options are extracted verbatim.


### `action` — K3

Run the specified mappable action. For a list of all available mappable actions, see :doc:`actions`. Any arguments for ACTION should follow the action. Note that parsing of arguments is action dependent so for best results specify all arguments as single string on the command line in the same format as you would use for that action in kitty.conf.

Hazards: target-default-may-be-active, effects-require-verification, arbitrary-effects, credential-access-K3.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='ACTION [ARGS FOR ACTION...]', json_field='action', minimum_count=1, completion=RemoteCommand.CompletionSpec.from_string('type:special group:complete_actions'))`.
Source: `kitty/rc/action.py`, SHA256 `d954cc954702ae7be734194f21374a5555bfa6dceb4fb5a3a074be0dd6275fcf`.

#### Wire payload (upstream declaration)

```text
action+/str: The action to perform. Of the form: action [optional args...]
    match_window/str: Window to run the action on
    self/bool: Whether to use the window this command is run in as the active window
```

#### Complete declared CLI options

##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Run the action on the window this command is run in instead of the active window.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


### `close-tab` — K2

Close an arbitrary set of tabs. The :code:`--match` option can be used to
specify complex sets of tabs to close. For example, to close all non-focused
tabs in the currently focused OS window, use::

    kitten @ close-tab --match "not state:focused and state:parent_focused"


Hazards: target-default-may-be-active, effects-require-verification, target-blind, his-window-K3, destructive-K3.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/close_tab.py`, SHA256 `c85a4a0362e2e45c6aa045dce90adf01da0e8e2426c00da13b8e77bc951389c4`.

#### Wire payload (upstream declaration)

```text
match/str: Which tab to close
    self/bool: Boolean indicating whether to close the tab of the window the command is run in
    ignore_no_match/bool: Boolean indicating whether no matches should be ignored or return an error
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Close the tab of the window this command is run in, rather than the active tab.


##### `--ignore-no-match`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Do not return an error if no tabs are matched to be closed.


### `close-window` — K2

Close the specified windows

Hazards: target-default-may-be-active, effects-require-verification, target-blind, his-window-K3, destructive-K3.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/close_window.py`, SHA256 `1f730fc9947990d7cb5b90f219d0de732c242f855ea94d9154179095f235e499`.

#### Wire payload (upstream declaration)

```text
match/str: Which window to close
    self/bool: Boolean indicating whether to close the window the command is run in
    ignore_no_match/bool: Boolean indicating whether no matches should be ignored or return an error
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Close the window this command is run in, rather than the active window.


##### `--ignore-no-match`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Do not return an error if no windows are matched to be closed.


### `create-marker` — K2

Create a marker which can highlight text in the specified window. For example: :code:`create_marker text 1 ERROR`. For full details see: :doc:`marks`

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='MARKER SPECIFICATION', json_field='marker_spec', minimum_count=2)`.
Source: `kitty/rc/create_marker.py`, SHA256 `ac844de07cd150c10ab76ca43685ef6bbe0ee7c6ea7baab67773205dd7989e90`.

#### Wire payload (upstream declaration)

```text
match/str: Which window to create the marker in
    self/bool: Boolean indicating whether to create marker in the window the command is run in
    marker_spec/list.str: A list or arguments that define the marker specification, for example: ['text', '1', 'ERROR']
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Apply marker to the window this command is run in, rather than the active window.


### `detach-tab` — K2

Detach the specified tabs and either move them into a new OS window or add them to the OS window containing the tab specified by :option:`kitten @ detach-tab --target-tab`

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/detach_tab.py`, SHA256 `d651c2f3e2fbf193aa101aa3c7651f42d19ac65f54a187880148906a9a49ed9a`.

#### Wire payload (upstream declaration)

```text
match/str: Which tab to detach
    target_tab/str: Which tab to move the detached tab to the OS window it is run in
    self/bool: Boolean indicating whether to detach the tab the command is run in
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--target-tab`, `-t`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Detach the tab this command is run in, rather than the active tab.


### `detach-window` — K2

Detach the specified windows and either move them into a new tab, a new OS window or add them to the specified tab. Use the special value :code:`new` for :option:`kitten @ detach-window --target-tab` to move to a new tab. If no target tab is specified the windows are moved to a new OS window.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/detach_window.py`, SHA256 `369bbe971ef4c6fc8c75d8b849707779f56480659b2d3d22769ad9c6738f3ed3`.

#### Wire payload (upstream declaration)

```text
match/str: Which window to detach
    target_tab/str: Which tab to move the detached window to
    self/bool: Boolean indicating whether to detach the window the command is run in
    stay_in_tab/bool: Boolean indicating focus should remain in the active tab after windows are moved
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--target-tab`, `-t`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.
Use the special value :code:`new` to move to a new tab.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Detach the window this command is run in, rather than the active window.


##### `--stay-in-tab`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Keep the focus on a window in the currently focused tab after moving the specified windows.


### `disable-ligatures` — K2

Control ligature rendering for the specified windows/tabs (defaults to active window). The :italic:`STRATEGY` can be one of: :code:`never`, :code:`always`, :code:`cursor`.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='STRATEGY', count=1, json_field='strategy')`.
Source: `kitty/rc/disable_ligatures.py`, SHA256 `bc3b0629be6d69ad2b29fc8638e34aa6856f97eb27758b1340b3b163d1d29f7e`.

#### Wire payload (upstream declaration)

```text
strategy+/choices.never.always.cursor: One of :code:`never`, :code:`always` or :code:`cursor`
    match_window/str: Window to change opacity in
    match_tab/str: Tab to change opacity in
    all/bool: Boolean indicating operate on all windows
```

#### Complete declared CLI options

##### `--all`, `-a`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

By default, ligatures are only affected in the active window. This option will
cause ligatures to be changed in all windows.


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--match-tab`, `-t`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


### `env` — K3

Change the environment variables that will be seen in newly launched windows. Similar to the :opt:`env` option in :file:`kitty.conf`, but affects running kitty instances. If no = is present, the variable is removed from the environment.

Hazards: target-default-may-be-active, effects-require-verification, arbitrary-effects, credential-access-K3.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='env_var1=val env_var2=val ...', minimum_count=1, json_field='env')`.
Source: `kitty/rc/env.py`, SHA256 `96b5cf7d970d4410f9de45f0853c8e67576cb72b061e0a528f9e209e6ac142ed`.

#### Wire payload (upstream declaration)

```text
env+/dict.str: Dictionary of environment variables to values. When a env var ends with = it is removed from the environment.
```

#### Complete declared CLI options
No command-local flags declared (framework help still applies).

### `focus-tab` — K2

The active window in the specified tab will be focused.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/focus_tab.py`, SHA256 `8e97da1379070b45165251ecc58dfeac5e90dc37ef18762870a87bc9d9f91540`.

#### Wire payload (upstream declaration)

```text
match/str: The tab to focus
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.


### `focus-window` — K2

Focus the specified window, if no window is specified, focus the window this command is run inside.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/focus_window.py`, SHA256 `5cc42825c7629cdac44c8ad67a3c41bcead8832f341208acfaf021ef40a8ed23`.

#### Wire payload (upstream declaration)

```text
match/str: The window to focus
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response from kitty. This means that even if no matching window is found,
the command will exit with a success code.


### `get-colors` — K1

Get the terminal colors for the specified window (defaults to active window). Colors will be output to STDOUT in the same syntax as used for :file:`kitty.conf`.

To get a single color use:
  get-colors | grep "^background " | tr -s | cut -d" " -f2

Change background above to whatever color you are interested in.

Hazards: target-default-may-be-active, effects-require-verification, screen-or-environment-may-contain-secrets.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/get_colors.py`, SHA256 `f7d31ba8b72c5f4e900dd9372c6f3df814d7d6535cb46940e01b32fbc54375ca`.

#### Wire payload (upstream declaration)

```text
match/str: The window to get the colors for
    configured/bool: Boolean indicating whether to get configured or current colors
```

#### Complete declared CLI options

##### `--configured`, `-c`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

Instead of outputting the colors for the specified window, output the currently
configured colors.


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


### `get-text` — K1

Get text from the specified window

Hazards: target-default-may-be-active, effects-require-verification, screen-or-environment-may-contain-secrets.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/get_text.py`, SHA256 `53049f84a8d48bc8845bf0e57501766b9caa89a21de5a5ff966d9ae8f0291833`.

#### Wire payload (upstream declaration)

```text
match/str: The window to get text from
    extent/choices.screen.first_cmd_output_on_screen.last_cmd_output.last_visited_cmd_output.all.selection:         One of :code:`screen`, :code:`first_cmd_output_on_screen`, :code:`last_cmd_output`,         :code:`last_visited_cmd_output`, :code:`all`, or :code:`selection`
    ansi/bool: Boolean, if True send ANSI formatting codes
    cursor/bool: Boolean, if True send cursor position/style as ANSI codes
    wrap_markers/bool: Boolean, if True add wrap markers to output
    clear_selection/bool: Boolean, if True clear the selection in the matched window
    self/bool: Boolean, if True use window the command was run in
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--extent`

Type: `choices`; CLI default: `"screen"`; explicit source default: `"screen"`.
Choices: screen,  all,  selection,  first_cmd_output_on_screen,  last_cmd_output,  last_visited_cmd_output,  last_non_empty_output.
Option hazards: inherits act hazards.

What text to get. The default of :code:`screen` means all text currently on the screen.
:code:`all` means all the screen+scrollback and :code:`selection` means the
currently selected text. :code:`first_cmd_output_on_screen` means the output of the first
command that was run in the window on screen. :code:`last_cmd_output` means
the output of the last command that was run in the window. :code:`last_visited_cmd_output` means
the first command output below the last scrolled position via scroll_to_prompt.
:code:`last_non_empty_output` is the output from the last command run in the window that had
some non empty output. The last four require :ref:`shell_integration` to be enabled.


##### `--ansi`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

By default, only plain text is returned. With this flag, the text will
include the ANSI formatting escape codes for colors, bold, italic, etc.


##### `--add-cursor`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Add ANSI escape codes specifying the cursor position and style to the end of the text.


##### `--add-wrap-markers`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Add carriage returns at every line wrap location (where long lines are wrapped at
screen edges).


##### `--clear-selection`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Clear the selection in the matched window, if any.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Get text from the window this command is run in, rather than the active window.


### `goto-layout` — K2

Set the window layout in the specified tabs (or the active tab if not specified). You can use special match value :code:`all` to set the layout in all tabs. In case there are multiple layouts with the same name but different options, specify the full layout definition or a unique prefix of the full definition.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='LAYOUT_NAME', count=1, json_field='layout', completion=RemoteCommand.CompletionSpec.from_string('type:keyword group:"Layout" kwds:' + ','.join(layout_names())))`.
Source: `kitty/rc/goto_layout.py`, SHA256 `f27f69b9dcb6b0530fe65762543eb196480005ac54b01ac95808818e8c5347c0`.

#### Wire payload (upstream declaration)

```text
layout+/str: The new layout name
    match/str: Which tab to change the layout of
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


### `kitten` — K3

Run a kitten over the specified windows (active window by default). The :italic:`kitten_name` can be either the name of a builtin kitten or the path to a Python file containing a custom kitten. If a relative path is used it is searched for in the :ref:`kitty config directory <confloc>`. If the kitten is a :italic:`no_ui` kitten and its handle response method returns a string or boolean, this is printed out to stdout.

Hazards: target-default-may-be-active, effects-require-verification, arbitrary-effects, credential-access-K3.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='kitten_name', json_field='kitten', minimum_count=1, first_rest=('kitten', 'args'))`.
Source: `kitty/rc/kitten.py`, SHA256 `f8954ae9ce9646edd6b96dcc81ad5425e2561c80b57383295fcf107ca2e4ba10`.

#### Wire payload (upstream declaration)

```text
kitten+/str: The name of the kitten to run
    args/list.str: Arguments to pass to the kitten as a list
    match/str: The window to run the kitten over
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


### `last-used-layout` — K2

Switch to the last used window layout in the specified tabs (or the active tab if not specified).

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/last_used_layout.py`, SHA256 `102ec028c5778b86e7a911ae8b0b21a0ba87d78c259443cff155302c3c8df89c`.

#### Wire payload (upstream declaration)

```text
match/str: Which tab to change the layout of
    all/bool: Boolean to match all tabs
```

#### Complete declared CLI options

##### `--all`, `-a`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Change the layout in all tabs.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response from kitty. This means that even if no matching tab is found,
the command will exit with a success code.


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


### `launch` — K2

Prints out the id of the newly opened window. Any command line arguments are assumed to be the command line used to run in the new window, if none are provided, the default shell is run. For example::

    kitten @ launch --title=Email mutt

Hazards: target-default-may-be-active, effects-require-verification, arbitrary-process, focus-steal, never-grant-rc, stamp-required.
Async: True; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='[CMD ...]', json_field='args', completion=RemoteCommand.CompletionSpec.from_string('type:special group:cli.CompleteExecutableFirstArg'))`.
Source: `kitty/rc/launch.py`, SHA256 `5c5485031fdbaf3403ff50935a236564bdf5db0553fb044246b70070ffdc522e`.

#### Wire payload (upstream declaration)

```text
args+/list.str: The command line to run in the new window, as a list, use an empty list to run the default shell
    match/str: The tab to open the new window in
    next_to/str: The window next to which to create the new window or empty string to use active window
    source_window/str: The window to use as source for data or empty string to use active window
    window_title/str: Title for the new window
    cwd/str: Working directory for the new window
    add_to_session/str: Session name to add created window/tab to
    env/list.str: List of environment variables of the form NAME=VALUE
    var/list.str: List of user variables of the form NAME=VALUE
    os_panel/list.str: List of panel settings
    tab_title/str: Title for the new tab
    type/choices.window.tab.os-window.os-panel.overlay.overlay-main.background.clipboard.primary: The type of window to open
    keep_focus/bool: Boolean indicating whether the current window should retain focus or not
    copy_colors/bool: Boolean indicating whether to copy the colors from the current window
    copy_cmdline/bool: Boolean indicating whether to copy the cmdline from the current window
    copy_env/list.str=copy_local_env: List of strings representing the local env vars
    hold/bool: Boolean indicating whether to keep window open after cmd exits
    location/choices.first.after.before.neighbor.last.vsplit.hsplit.split.default: Where in the tab to open the new window
    allow_remote_control/bool: Boolean indicating whether to allow remote control from the new window
    remote_control_password/list.str: A list of remote control passwords
    stdin_source/choices.none.@selection.@screen.@screen_scrollback.@alternate.@alternate_scrollback.        @first_cmd_output_on_screen.@last_cmd_output.@last_visited_cmd_output: Where to get stdin for the process from
    stdin_add_formatting/bool: Boolean indicating whether to add formatting codes to stdin
    stdin_add_line_wrap_markers/bool: Boolean indicating whether to add line wrap markers to stdin
    spacing/list.str: A list of spacing specifications, see the docs for the set-spacing command
    marker/str: Specification for marker for new window, for example: "text 1 ERROR"
    logo/str: Path to window logo
    logo_position/str: Window logo position as string or empty string to use default
    logo_alpha/float: Window logo alpha or -1 to use default
    self/bool: Boolean, if True use tab the command was run in
    os_window_title/str: Title for OS Window
    os_window_name/str: WM_NAME for OS Window
    os_window_class/str: WM_CLASS for OS Window
    os_window_state/choices.normal.fullscreen.maximized.minimized: The initial state for OS Window
    os_window_position/str: The position for OS Window
    color/list.str: list of color specifications such as foreground=red
    watcher/list.str: list of paths to watcher files
    bias/float: The bias with which to create the new window in the current layout
    wait_for_child_to_exit/bool: Boolean indicating whether to wait and return child exit code
    hold_after_ssh/bool: Boolean indicating whether to run a local shell after exiting the ssh session cloned via cwd=current or similar
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--wait-for-child-to-exit`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Wait until the launched program exits and print out its exit code. The exit code is
printed out instead of the window id. If the program exited normally its exit code is printed, which
is always greater than or equal to zero. If the program was killed by a signal, the symbolic name
of the SIGNAL is printed, if available, otherwise the signal number with a leading minus sign is printed.


##### `--response-timeout`

Type: `float`; CLI default: `86400.0`; explicit source default: `"86400"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

The time in seconds to wait for the started process to exit, when using the :option:`--wait-for-child-to-exit`
option. Defaults to one day.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Do not print out the id of the newly created window.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

If specified the tab containing the window this command is run in is used
instead of the active tab


##### `--source-window`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

A match expression to select the window from which data such as title, colors, env vars,
screen contents, etc. are copied. When not specified the currently active window is used.
See :ref:`search_syntax` for the syntax used for specifying windows.


##### `--window-title`, `--title`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The title to set for the new window. By default, title is controlled by the
child process. The special value :code:`current` will copy the title from the
:option:`source window <launch --source-window>`.


##### `--tab-title`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The title for the new tab if launching in a new tab. By default, the title
of the active window in the tab is used as the tab title. The special value
:code:`current` will copy the title from the tab containing the
:option:`source window <launch --source-window>`.


##### `--type`

Type: `choices`; CLI default: `"window"`; explicit source default: `"window"`.
Choices: window, tab, os-window, os-panel, overlay, overlay-main, background, clipboard, primary.
Option hazards: inherits act hazards.

Where to launch the child process:

:code:`window`
    A new :term:`kitty window <window>` in the current tab

:code:`tab`
    A new :term:`tab` in the current OS window. Not available when the
    :doc:`launch <launch>` command is used in :ref:`startup sessions <sessions>`.

:code:`os-window`
    A new :term:`operating system window <os_window>`.  Not available when the
    :doc:`launch <launch>` command is used in :ref:`startup sessions <sessions>`.

:code:`overlay`
    An :term:`overlay window <overlay>` covering the current active kitty window

:code:`overlay-main`
    An :term:`overlay window <overlay>` covering the current active kitty window.
    Unlike a plain overlay window, this window is considered as a :italic:`main`
    window which means it is used as the active window for getting the current working
    directory, the input text for kittens, launch commands, etc. Useful if this overlay is
    intended to run for a long time as a primary window.

:code:`background`
    The process will be run in the :italic:`background`, without a kitty
    window. Note that if :option:`kitten @ launch --allow-remote-control` is
    specified the :envvar:`KITTY_LISTEN_ON` environment variable will be set to
    a dedicated socket pair file descriptor that the process can use for remote
    control.

:code:`clipboard`, :code:`primary`
    These two are meant to work with :option:`--stdin-source <launch --stdin-source>` to copy
    data to the :italic:`system clipboard` or :italic:`primary selection`.

:code:`os-panel`
    Similar to :code:`os-window`, except that it creates the new OS Window as a desktop panel.
    Only works on platforms that support this, such as Wayand compositors that support the layer
    shell protocol. Use the :option:`kitten @ launch --os-panel` option to configure the panel.

#placeholder_for_formatting#


##### `--keep-focus`, `--dont-take-focus`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Keep the focus on the currently active window instead of switching to the newly
opened window.


##### `--cwd`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

The working directory for the newly launched child. Use the special value
:code:`current` to use the working directory of the :option:`source window <launch --source-window>`.
The special value :code:`last_reported` uses the last working directory reported
by the shell (needs :ref:`shell_integration` to work). The special value
:code:`oldest` works like :code:`current` but uses the working directory of the
oldest foreground process associated with the currently active window rather
than the newest foreground process. Finally, the special value :code:`root`
refers to the process that was originally started when the window was created.

When opening in the same working directory as the current window causes the new
window to connect to a remote host, you can use the :option:`--hold-after-ssh`
flag to prevent the new window from closing when the connection is terminated.


##### `--add-to-session`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Add the newly created window/tab to the specified session. Use :code:`.` to add
to the session of the :option:`source window <launch --source-window>`, if any. See :ref:`sessions`
for what a session is and how to use one. By default, the window is added to the
session of the :option:`source window <launch --source-window>` when :option:`kitten @ launch --cwd`
is set to use the the working directory from that window, otherwise the newly created window
does not belong to any session. To force adding to no session, use the value :code:`!`.
Adding a newly created window to a session is purely temporary, it does not change the actual
session file, for that you have to resave the session. Note that using this flag in a launch
command within a session file has no effect as the window is always added to the
session belonging to that file.


##### `--env`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

Environment variables to set in the child process. Can be specified multiple
times to set different environment variables. Syntax: :code:`name=value`. Using
:code:`name=` will set to empty string and just :code:`name` will remove the
environment variable.


##### `--var`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

User variables to set in the created window. Can be specified multiple
times to set different user variables. Syntax: :code:`name=value`. Using
:code:`name=` will set to empty string.


##### `--hold`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Keep the window open even after the command being executed exits, at a shell prompt.
The shell will be run after the launched command exits.


##### `--copy-colors`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Set the colors of the newly created window to be the same as the colors in the
:option:`source window <launch --source-window>`.


##### `--copy-cmdline`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Ignore any specified command line and instead use the command line from the
:option:`source window <launch --source-window>`.


##### `--copy-env`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

Copy the environment variables from the :option:`source window <launch --source-window>` into the newly
launched child process. Note that this only copies the environment when the
window was first created, as it is not possible to get updated environment variables
from arbitrary processes. In particular, this means, if you are running a shell in the
window and the shell has set env vars in its rc files, these will **not** be copied.
To copy that environment, use either the :ref:`clone-in-kitty <clone_shell>` feature
or the kitty remote control feature with :option:`kitten @ launch --copy-env`.


##### `--location`

Type: `choices`; CLI default: `"default"`; explicit source default: `"default"`.
Choices: first, after, before, neighbor, last, vsplit, hsplit, split, default.
Option hazards: inherits act hazards.

Where to place the newly created window when it is added to a tab which already
has existing windows in it. :code:`after` and :code:`before` place the new
window before or after the active window. :code:`neighbor` is a synonym for
:code:`after`. Also applies to creating a new tab, where the value of
:code:`after` will cause the new tab to be placed next to the current tab
instead of at the end. The values of :code:`vsplit`, :code:`hsplit` and
:code:`split` are only used by the :code:`splits` layout and control if the new
window is placed in a vertical, horizontal or automatic split with the currently
active window. The default is to place the window in a layout dependent manner,
typically, after the currently active window. See :option:`--next-to <launch --next-to>`
to use a window other than the currently active window.


##### `--next-to`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

A match expression to select the window next to which the new window is created.
See :ref:`search_syntax` for the syntax for specifying windows. If not specified
defaults to the active window. When used via remote control
this option is ignored unless the matched window is in the target tab (default active tab).
When using :option:`--type <launch --type>` of :code:`tab`, the tab will be created
in the OS Window containing the matched window.


##### `--bias`

Type: `float`; CLI default: `0.0`; explicit source default: `"0"`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The bias used to alter the size of the window.
It controls what fraction of available space the window takes. The exact meaning
of bias depends on the current layout.

* Splits layout: The bias is interpreted as a percentage between 0 and 100.
When splitting a window into two, the new window will take up the specified fraction
of the space allotted to the original window and the original window will take up
the remainder of the space.

* Vertical/horizontal layout: The bias is interpreted as adding/subtracting from the
normal size of the window. It should be a number between -90 and 90. This number is
the percentage of the OS Window size that should be added to the window size.
So for example, if a window would normally have been size 50 in the layout inside an
OS Window that is size 80 high and --bias -10 is used it will become *approximately*
size 42 high. Note that sizes are approximations, you cannot use this method to
create windows of fixed sizes.

* Tall layout: If the window being created is the *first* window in a column, then
the bias is interpreted as a percentage, as for the splits layout, splitting the OS
Window width between columns. If the window is a second or subsequent window in a column
the bias is interpreted as adding/subtracting from the window size as for the vertical
layout above.

* Fat layout: Same as tall layout except it goes by rows instead of columns.

* Grid layout: The bias is interpreted the same way as for the Vertical and Horizontal
layouts, as something to be added/subtracted to the normal size. However, the
since in a grid layout there are rows *and* columns, the bias on the first window in a column
operates on the columns. Any later windows in that column operate on the row.
So, for example, if you bias the first window in a grid layout it will change the width
of the first column, the second window, the width of the second column, the third window,
the height of the second row and so on.

The bias option was introduced in kitty version 0.36.0.


##### `--allow-remote-control`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: never-grant-rc, target-expansion.

Programs running in this window can control kitty (even if remote control is not
enabled in :file:`kitty.conf`). Note that any program with the right level of
permissions can still write to the pipes of any other program on the same
computer and therefore can control kitty. It can, however, be useful to block
programs running on other computers (for example, over SSH) or as other users.
See :option:`--remote-control-password` for ways to restrict actions allowed by
remote control.


##### `--remote-control-password`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: never-grant-rc, sensitive-input-or-code.

Restrict the actions remote control is allowed to take. This works like
:opt:`remote_control_password`. You can specify a password and list of actions
just as for :opt:`remote_control_password`. For example::

    --remote-control-password '"my passphrase" get-* set-colors'

This password will be in effect for this window only.
Note that any passwords you have defined for :opt:`remote_control_password`
in :file:`kitty.conf` are also in effect. You can override them by using the same password here.
You can also disable all :opt:`remote_control_password` global passwords for this window, by using::

    --remote-control-password '!'

This option only takes effect if :option:`--allow-remote-control`
is also specified. Can be specified multiple times to create multiple passwords.
This option was added to kitty in version 0.26.0


##### `--stdin-source`

Type: `choices`; CLI default: `"none"`; explicit source default: `"none"`.
Choices: none, @selection, @screen, @screen_scrollback, @alternate, @alternate_scrollback, @first_cmd_output_on_screen, @last_cmd_output, @last_visited_cmd_output.
Option hazards: sensitive-input-or-code.

Pass the screen contents as :file:`STDIN` to the child process.

:code:`@selection`
    is the currently selected text in the :option:`source window <launch --source-window>`.

:code:`@screen`
    is the contents of the :option:`source window <launch --source-window>`.

:code:`@screen_scrollback`
    is the same as :code:`@screen`, but includes the scrollback buffer as well.

:code:`@alternate`
    is the secondary screen of the :option:`source window <launch --source-window>`. For example if you run
    a full screen terminal application, the secondary screen will
    be the screen you return to when quitting the application.

:code:`@first_cmd_output_on_screen`
    is the output from the first command run in the shell on screen.

:code:`@last_cmd_output`
    is the output from the last command run in the shell.

:code:`@last_visited_cmd_output`
    is the first output below the last scrolled position via :ac:`scroll_to_prompt`,
    this needs :ref:`shell integration <shell_integration>` to work.

#placeholder_for_formatting#


##### `--stdin-add-formatting`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

When using :option:`--stdin-source <launch --stdin-source>` add formatting
escape codes, without this only plain text will be sent.


##### `--stdin-add-line-wrap-markers`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

When using :option:`--stdin-source <launch --stdin-source>` add a carriage
return at every line wrap location (where long lines are wrapped at screen
edges). This is useful if you want to pipe to program that wants to duplicate
the screen layout of the screen.


##### `--marker`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Create a marker that highlights text in the newly created window. The syntax is
the same as for the :ac:`toggle_marker` action (see :doc:`/marks`).


##### `--os-window-class`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Set the :italic:`WM_CLASS` property on X11 and the application id property on
Wayland for the newly created OS window when using :option:`--type=os-window
<launch --type>`. Defaults to whatever is used by the parent kitty process,
which in turn defaults to :code:`kitty`.


##### `--os-window-name`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Set the :italic:`WM_NAME` property on X11 for the newly created OS Window when
using :option:`--type=os-window <launch --type>`. Defaults to
:option:`--os-window-class <launch --os-window-class>`.


##### `--os-window-title`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Set the title for the newly created OS window. This title will override any
titles set by programs running in kitty. The special value :code:`current` will
copy the title from the OS Window containing the
:option:`source window <launch --source-window>`.


##### `--os-window-state`

Type: `choices`; CLI default: `"normal"`; explicit source default: `"normal"`.
Choices: normal, fullscreen, maximized, minimized.
Option hazards: inherits act hazards.

The initial state for the newly created OS Window.


##### `--os-window-position`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The position, for example :code:`10x20`, on screen at which to place the newly
created OS Window. This may or may not work depending on the policies of the
desktop environment/window manager. It never works on Wayland.


##### `--logo`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Path to a PNG image to use as the logo for the newly created window. See
:opt:`window_logo_path`. Relative paths are resolved from the kitty configuration directory.


##### `--logo-position`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The position for the window logo. Only takes effect if :option:`--logo` is
specified. See :opt:`window_logo_position`.


##### `--logo-alpha`

Type: `float`; CLI default: `-1.0`; explicit source default: `"-1"`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The amount the window logo should be faded into the background. Only takes
effect if :option:`--logo` is specified. See :opt:`window_logo_alpha`.


##### `--color`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Change colors in the newly launched window. You can either specify a path to a
:file:`.conf` file with the same syntax as :file:`kitty.conf` to read the colors
from, or specify them individually, for example::

    --color background=white --color foreground=red


##### `--spacing`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Set the margin and padding for the newly created window.
For example: :code:`margin=20` or :code:`padding-left=10` or :code:`margin-h=30`. The shorthand form sets
all values, the :code:`*-h` and :code:`*-v` variants set horizontal and vertical values.
Can be specified multiple times. Note that this is ignored for overlay windows as these use the settings
from the base window.


##### `--watcher`, `-w`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

Path to a Python file. Appropriately named functions in this file will be called
for various events, such as when the window is resized, focused or closed. See
the section on watchers in the launch command documentation: :ref:`watchers`.
Relative paths are resolved relative to the :ref:`kitty config directory
<confloc>`. Global watchers for all windows can be specified with
:opt:`watcher` in :file:`kitty.conf`.


##### `--os-panel`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Options to control the creation of desktop panels. Takes the same settings
as the :doc:`panel kitten </kittens/panel>`, except for :option:`--override <kitty +kitten panel --override>`
and :option:`--config <kitty +kitten panel --config>`. Can be specified multiple times.
For example, to create a desktop panel at the bottom of the screen two lines high::

    launch --type os-panel --os-panel lines=2 --os-panel edge=bottom sh -c "echo; echo; echo hello; sleep 5s"


##### `--hold-after-ssh`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

When using :option:`--cwd`:code:`=current` or similar from a window that is running the ssh kitten,
the new window will run a local shell after disconnecting from the remote host, when this option
is specified.


### `load-config` — K3

(Re)load the specified kitty.conf config files(s). If no files are specified the previously specified config file is reloaded. Note that the specified paths must exist and be readable by the kitty process on the computer that process is running on. Relative paths are resolved with respect to the kitty config directory on the computer running kitty.

Hazards: target-default-may-be-active, effects-require-verification, arbitrary-effects, credential-access-K3.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='CONF_FILE ...', json_field='paths', completion=RemoteCommand.CompletionSpec.from_string('type:file group:"CONF files", ext:conf'))`.
Source: `kitty/rc/load_config.py`, SHA256 `045ac005a1c0665b015df60d1aa9f03f0183c716582482317a0d3e1981b1fbc5`.

#### Wire payload (upstream declaration)

```text
paths/list.str: List of config file paths to load
    override/list.str: List of individual config overrides
    ignore_overrides/bool: Whether to apply previous overrides
```

#### Complete declared CLI options

##### `--ignore-overrides`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

By default, any config overrides previously specified at the kitty invocation command line
or a previous load-config-file command are respected. Use this option to have them ignored instead.


##### `--override`, `-o`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Override individual configuration options, can be specified multiple times.
Syntax: :italic:`name=value`. For example: :option:`kitty -o` font_size=20


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.


### `ls` — K1

List windows. The list is returned as JSON tree. The top-level is a list of operating system kitty windows. Each OS window has an :italic:`id` and a list of :italic:`tabs`. Each tab has its own :italic:`id`, a :italic:`title` and a list of :italic:`windows`. Each window has an :italic:`id`, :italic:`title`, :italic:`current working directory`, :italic:`process id (PID)`, :italic:`command-line` and :italic:`environment` of the process running in the window. Additionally, when running the command inside a kitty window, that window can be identified by the :italic:`is_self` parameter.

You can use these criteria to select windows/tabs for the other commands.

You can limit the windows/tabs in the output by using the :option:`--match` and :option:`--match-tab` options.

Hazards: target-default-may-be-active, effects-require-verification, screen-or-environment-may-contain-secrets.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/ls.py`, SHA256 `2d1e74a116fa7caf3ceaa534846ceecc92fadf915798e8772d97c4aeb0695f58`.

#### Wire payload (upstream declaration)

```text
all_env_vars/bool: Whether to send all environment variables for every window rather than just differing ones
    match/str: Window to change colors in
    match_tab/str: Tab to change colors in
    self/bool: Boolean indicating whether to list only the window the command is run in
    output_format/str: Output in json or session format
```

#### Complete declared CLI options

##### `--all-env-vars`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code, target-expansion.

Show all environment variables in output, not just differing ones.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Only list the window this command is run in.


##### `--output-format`

Type: `choices`; CLI default: `"json"`; explicit source default: `"json"`.
Choices: json, session.
Option hazards: inherits act hazards.

Output in JSON or kitty session format


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--match-tab`, `-t`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


### `new-window` — K2

DEPRECATED: Use the :ref:`launch <at-launch>` command instead.

Open a new window in the specified tab. If you use the :option:`kitten @ new-window --match` option the first matching tab is used. Otherwise the currently active tab is used. Prints out the id of the newly opened window (unless :option:`--no-response` is used). Any command line arguments are assumed to be the command line used to run in the new window, if none are provided, the default shell is run. For example::

    kitten @ new-window --title Email mutt

Hazards: target-default-may-be-active, effects-require-verification, arbitrary-process, focus-steal, never-grant-rc, stamp-required.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='[CMD ...]', json_field='args')`.
Source: `kitty/rc/new_window.py`, SHA256 `1cd4411d6021a0475bd19d959864533e4513459cfdd35c0c2ebe20674f6f5725`.

#### Wire payload (upstream declaration)

```text
args+/list.str: The command line to run in the new window, as a list, use an empty list to run the default shell
    match/str: The tab to open the new window in
    title/str: Title for the new window
    cwd/str: Working directory for the new window
    keep_focus/bool: Boolean indicating whether the current window should retain focus or not
    window_type/choices.kitty.os: One of :code:`kitty` or :code:`os`
    new_tab/bool: Boolean indicating whether to open a new tab
    tab_title/str: Title for the new tab
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--title`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The title for the new window. By default it will use the title set by the
program running in it.


##### `--cwd`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

The initial working directory for the new window. Defaults to whatever
the working directory for the kitty process you are talking to is.


##### `--keep-focus`, `--dont-take-focus`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Keep the current window focused instead of switching to the newly opened window.


##### `--window-type`

Type: `choices`; CLI default: `"kitty"`; explicit source default: `"kitty"`.
Choices: kitty, os.
Option hazards: inherits act hazards.

What kind of window to open. A kitty window or a top-level OS window.


##### `--new-tab`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Open a new tab.


##### `--tab-title`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Set the title of the tab, when open a new tab.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response giving the id of the newly opened window. Note that
using this option means that you will not be notified of failures and that
the id of the new window will not be printed out.


### `remove-marker` — K2

Remove the currently set marker, if any.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/remove_marker.py`, SHA256 `58a1d6bd50e0b8cb81c9c1a2b0ff7722df603cc258ec116c438e52561f645c97`.

#### Wire payload (upstream declaration)

```text
match/str: Which window to remove the marker from
    self/bool: Boolean indicating whether to detach the window the command is run in
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Apply marker to the window this command is run in, rather than the active window.


### `resize-os-window` — K2

Resize (or other operations) on the specified OS Windows. Note that some window managers/environments do not allow applications to resize their windows, for example, tiling window managers.

To modify OS Panels created with the panel kitten, use :option:`--action`=:code:`os-panel`. Specify the modifications in the same syntax as used by the panel kitten, without the leading dashes. Use the :option:`--incremental` option to only change the specified panel settings. For example, move the panel to bottom edge and make it two lines tall: :code:`--action=os-panel --incremental lines=2 edge=bottom`

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='[OS Panel settings ...]', json_field='os_panel', special_parse='escape_list_of_strings(args), nil')`.
Source: `kitty/rc/resize_os_window.py`, SHA256 `f2790bdc62043fcbc5f82ddd9cf54ef3ff3d7cdadabc6a6f8f382f25af611e82`.

#### Wire payload (upstream declaration)

```text
match/str: Which window to resize
    self/bool: Boolean indicating whether to close the window the command is run in
    incremental/bool: Boolean indicating whether to adjust the size incrementally
    action/choices.resize.toggle-fullscreen.toggle-maximized.toggle-visibility.hide.show.os-panel: The action to perform
    unit/choices.cells.pixels: One of :code:`cells` or :code:`pixels`
    width/int: Integer indicating desired window width
    height/int: Integer indicating desired window height
    os_panel/list.str: Settings for modifying the OS Panel
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--action`

Type: `choices`; CLI default: `"resize"`; explicit source default: `"resize"`.
Choices: resize, toggle-fullscreen, toggle-maximized, toggle-visibility, hide, show, os-panel.
Option hazards: inherits act hazards.

The action to perform.


##### `--unit`

Type: `choices`; CLI default: `"cells"`; explicit source default: `"cells"`.
Choices: cells, pixels.
Option hazards: inherits act hazards.

The unit in which to interpret specified sizes.


##### `--width`

Type: `int`; CLI default: `0`; explicit source default: `"0"`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Change the width of the window. Zero leaves the width unchanged.


##### `--height`

Type: `int`; CLI default: `0`; explicit source default: `"0"`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Change the height of the window. Zero leaves the height unchanged.


##### `--incremental`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Treat the specified sizes as increments on the existing window size
instead of absolute sizes. When using :option:`--action`=:code:`os-panel`,
only the specified settings are changed, otherwise non-specified settings
keep their current value.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Resize the window this command is run in, rather than the active window.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.


### `resize-window` — K2

Resize the specified windows in the current layout. Note that not all layouts can resize all windows in all directions.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/resize_window.py`, SHA256 `8ab51e30ed16bc8bcb1208b4f58a6be38b4f6fd9fb2ba9b07e473a643eaf185f`.

#### Wire payload (upstream declaration)

```text
match/str: Which window to resize
    self/bool: Boolean indicating whether to resize the window the command is run in
    increment/int: Integer specifying the resize increment
    axis/choices.horizontal.vertical.reset: One of :code:`horizontal, vertical` or :code:`reset`
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--increment`, `-i`

Type: `int`; CLI default: `2`; explicit source default: `"2"`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The number of cells to change the size by, can be negative to decrease the size.


##### `--axis`, `-a`

Type: `choices`; CLI default: `"horizontal"`; explicit source default: `"horizontal"`.
Choices: horizontal, vertical, reset.
Option hazards: inherits act hazards.

The axis along which to resize. If :code:`horizontal`,
it will make the window wider or narrower by the specified increment.
If :code:`vertical`, it will make the window taller or shorter by the specified increment.
The special value :code:`reset` will reset the layout to its default configuration.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Resize the window this command is run in, rather than the active window.


### `run` — K2

Run the specified program on the computer in which kitty is running. When STDIN is not a TTY it is forwarded to the program as its STDIN. STDOUT and STDERR from the the program are forwarded here. The exit status of this invocation will be the exit status of the executed program. If you wish to just run a program without waiting for a response,  use @ launch --type=background instead.

Hazards: target-default-may-be-active, effects-require-verification, silent, arbitrary-process, irreversible-effects-K3.
Async: True; streaming: True; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='CMD ...', json_field='data', special_parse='+cmdline:!read_run_data(io_data, args, &payload)', minimum_count=1, completion=RemoteCommand.CompletionSpec.from_string('type:special group:cli.CompleteExecutableFirstArg'))`.
Source: `kitty/rc/run.py`, SHA256 `ea3373d05799167637b8fca4b87a4da768ac0105d6d800e0269835c952bdac3f`.

#### Wire payload (upstream declaration)

```text
data+/str: Chunk of STDIN data, base64 encoded no more than 4096 bytes. Must send an empty chunk to indicate end of data.
    cmdline+/list.str: The command line to run
    env/list.str: List of environment variables of the form NAME=VALUE
    allow_remote_control/bool: A boolean indicating whether to allow remote control
    remote_control_password/list.str: A list of remote control passwords
```

#### Complete declared CLI options

##### `--env`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

Environment variables to set in the child process. Can be specified multiple
times to set different environment variables. Syntax: :code:`name=value`. Using
:code:`name=` will set to empty string and just :code:`name` will remove the
environment variable.


##### `--allow-remote-control`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: never-grant-rc, target-expansion.

The executed program will have privileges to run remote control commands in kitty.


##### `--remote-control-password`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: never-grant-rc, sensitive-input-or-code.

Restrict the actions remote control is allowed to take. This works like
:opt:`remote_control_password`. You can specify a password and list of actions
just as for :opt:`remote_control_password`. For example::

    --remote-control-password '"my passphrase" get-* set-colors'

This password will be in effect for this window only.
Note that any passwords you have defined for :opt:`remote_control_password`
in :file:`kitty.conf` are also in effect. You can override them by using the same password here.
You can also disable all :opt:`remote_control_password` global passwords for this window, by using::

    --remote-control-password '!'

This option only takes effect if :option:`--allow-remote-control`
is also specified. Can be specified multiple times to create multiple passwords.
This option was added to kitty in version 0.26.0


### `scroll-window` — K1

Scroll the specified windows, if no window is specified, scroll the window this command is run inside. :italic:`SCROLL_AMOUNT` can be either the keywords :code:`start` or :code:`end` or an argument of the form :italic:`<number>[unit][+-]`. :code:`unit` can be :code:`l` for lines, :code:`p` for pages, :code:`u` for unscroll and :code:`r` for scroll to prompt. If unspecified, :code:`l` is the default. For example, :code:`30.5` will scroll down 30 and a half lines, :code:`2p-` will scroll up 2 pages and :code:`0.5p` will scroll down half page. :code:`3u` will *unscroll* by 3 lines, which means that 3 lines will move from the scrollback buffer onto the top of the screen. :code:`1r-` will scroll to the previous prompt and :code:`1r` to the next prompt. See :ac:`scroll_to_prompt` for details on how scrolling to prompt works.

Hazards: target-default-may-be-active, effects-require-verification, screen-or-environment-may-contain-secrets.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='SCROLL_AMOUNT', count=1, special_parse='parse_scroll_amount(args[0])', json_field='amount')`.
Source: `kitty/rc/scroll_window.py`, SHA256 `ebd6010c3ef6b7bee87d9703df35a91c0943afcd6d3d1b21422bd424d5bd1f6d`.

#### Wire payload (upstream declaration)

```text
amount+/list.scroll_amount: The amount to scroll, a two item list with the first item being              either a number or the keywords, start and end.              And the second item being either 'p' for pages or 'l' for lines or 'u'
             for unscrolling by lines, or 'r' for scrolling to prompt.
    match/str: The window to scroll
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.


### `select-window` — K2

Prints out the id of the selected window. Other commands can then be chained to make use of it.

Hazards: target-default-may-be-active, effects-require-verification.
Async: True; streaming: False; no-response declaration: False.
Argument declaration: ``.
Source: `kitty/rc/select_window.py`, SHA256 `d32a5a12daa8a540d4dc65a619084946f07e1e581734cfdf98cf9d5dce57d1fb`.

#### Wire payload (upstream declaration)

```text
match/str: The tab to open the new window in
    self/bool: Boolean, if True use tab the command was run in
    title/str: A title for this selection
    exclude_active/bool: Exclude the currently active window from the list to pick
    reactivate_prev_tab/bool: Reactivate the previously activated tab when finished
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--response-timeout`

Type: `float`; CLI default: `60.0`; explicit source default: `"60"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

The time in seconds to wait for the user to select a window.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Select window from the tab containing the window this command is run in,
instead of the active tab.


##### `--title`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

A title that will be displayed to the user to describe what this selection is for.


##### `--exclude-active`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Exclude the currently active window from the list of windows to pick.


##### `--reactivate-prev-tab`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

When the selection is finished, the tab in the same OS window that was activated
before the selection will be reactivated. The last activated OS window will also
be refocused.


### `send-key` — K3

Send arbitrary key presses to specified windows. All specified keys are sent first as press events then as release events in reverse order. Keys are sent to the programs running in the windows. They are sent only if the current keyboard mode for the program supports the particular key. For example: send-key ctrl+a ctrl+b. Note that errors are not reported, for technical reasons, so send-key always succeeds, even if no key was sent to any window.

Hazards: target-default-may-be-active, effects-require-verification, silent-success, arbitrary-input, broadcast, his-window-K3.
Async: False; streaming: False; no-response declaration: True.
Argument declaration: `RemoteCommand.Args(spec='[KEYS TO SEND ...]', json_field='keys')`.
Source: `kitty/rc/send_key.py`, SHA256 `a66921c25f138aac9ff87aebd603881aa08cfee3b83f822d1796599418c66e0b`.

#### Wire payload (upstream declaration)

```text
keys+/list.str: The keys to send
    match/str: A string indicating the window to send text to
    match_tab/str: A string indicating the tab to send text to
    all/bool: A boolean indicating all windows should be matched.
    exclude_active/bool: A boolean that prevents sending text to the active window
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--match-tab`, `-t`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--all`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Match all windows.


##### `--exclude-active`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Do not send text to the active window, even if it is one of the matched windows.


### `send-text` — K3

Send arbitrary text to specified windows. The text follows Python escaping rules. So you can use :link:`escapes <https://www.gnu.org/software/bash/manual/html_node/ANSI_002dC-Quoting.html>` like :code:`'\\e'` to send control codes and :code:`'\\u21fa'` to send Unicode characters. Remember to use single-quotes otherwise the backslash is interpreted as a shell escape character. If you use the :option:`kitten @ send-text --match` option the text will be sent to all matched windows. By default, text is sent to only the currently active window. Note that errors are not reported, for technical reasons, so send-text always succeeds, even if no text was sent to any window.

Hazards: target-default-may-be-active, effects-require-verification, silent-success, arbitrary-input, broadcast, his-window-K3, python-escape-cli, newline-execution, bracketed-paste-not-a-guarantee.
Async: False; streaming: False; no-response declaration: True.
Argument declaration: `RemoteCommand.Args(spec='[TEXT TO SEND]', json_field='data', special_parse='+session_id:parse_send_text(io_data, args)')`.
Source: `kitty/rc/send_text.py`, SHA256 `598d90e13628126d764250408436d2f0fce8ee5828182f41568ee6834d573f0b`.

#### Wire payload (upstream declaration)

```text
data+/str: The data being sent. Can be either: text: followed by text or base64: followed by standard base64 encoded bytes
    match/str: A string indicating the window to send text to
    match_tab/str: A string indicating the tab to send text to
    all/bool: A boolean indicating all windows should be matched.
    exclude_active/bool: A boolean that prevents sending text to the active window
    session_id/str: A string that identifies a "broadcast session"
    bracketed_paste/choices.disable.auto.enable: Whether to wrap the text in bracketed paste escape codes
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--match-tab`, `-t`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--all`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Match all windows.


##### `--exclude-active`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Do not send text to the active window, even if it is one of the matched windows.


##### `--stdin`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

Read the text to be sent from :italic:`stdin`. Note that in this case the text is sent as is,
not interpreted for escapes. If stdin is a terminal, you can press :kbd:`Ctrl+D` to end reading.


##### `--from-file`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Path to a file whose contents you wish to send. Note that in this case the file contents
are sent as is, not interpreted for escapes.


##### `--bracketed-paste`

Type: `choices`; CLI default: `"disable"`; explicit source default: `"disable"`.
Choices: disable, auto, enable.
Option hazards: inherits act hazards.

When sending text to a window, wrap the text in bracketed paste escape codes. The default is to not do this.
A value of :code:`auto` means, bracketed paste will be used only if the program running in the window has turned
on bracketed paste mode.


### `set-background-image` — K3

Set the background image for the specified OS windows. You must specify the path to an image that will be used as the background. If you specify the special value :code:`none` then any existing image will be removed. Supported image formats are: PNG, JPEG, WEBP, GIF, BMP, TIFF

You can also specify an index to change the background image to one of the pre-configured set of background images. The index is either a number, or a number preceeded by the plus or minus sign which acts as an increment. If the index falls outside the range of configured images, the first configured image is used. For example: set-background -- -1 or set-background 3

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: True; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='PATH_TO_IMAGE_OR_INDEX', count=1, json_field='data', special_parse='!read_background_image(io_data, args[0])', completion=ImageCompletion)`.
Source: `kitty/rc/set_background_image.py`, SHA256 `f9b4932494c9128f0686f9d881dfed78e683f91133bf7ad773665d59375b9ddb`.

#### Wire payload (upstream declaration)

```text
data+/str: Chunk of at most 512 bytes of PNG data, base64 encoded. Must send an empty chunk to indicate end of image.     Or the special value - to indicate image must be removed. Or the value index:idx to change image.
    match/str: Window to change opacity in
    layout/choices.{layout_choices.replace(",", ".")}: The image layout
    all/bool: Boolean indicating operate on all windows
    configured/bool: Boolean indicating if the configured value should be changed
```

#### Complete declared CLI options

##### `--all`, `-a`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

By default, background image is only changed for the currently active OS window. This option will
cause the image to be changed in all windows.


##### `--configured`, `-c`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

Change the configured background image which is used for new OS windows. Note that an index with this option
is not supported. Specifying :code:`none` will erase *all* configured background images.


##### `--layout`

Type: `choices`; CLI default: `"configured"`; explicit source default: `"configured"`.
Choices: tiled, scaled, mirror-tiled, clamped, centered, cscaled, configured.
Option hazards: inherits act hazards.

How the image should be displayed. A value of :code:`configured` will use the configured value.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response from kitty. This means that even if setting the background image
failed, the command will exit with a success code.


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


### `set-background-opacity` — K2

Set the background opacity for the specified windows. This will only work if you have turned on :opt:`dynamic_background_opacity` in :file:`kitty.conf`. The background opacity affects all kitty windows in a single OS window. For example::

    kitten @ set-background-opacity 0.5

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='OPACITY', count=1, json_field='opacity', special_parse='parse_opacity(args[0])')`.
Source: `kitty/rc/set_background_opacity.py`, SHA256 `7f642c61e19c60b7ca6e5fa321d068ced900e6cf0f9c8ce1dd80df697aaa8855`.

#### Wire payload (upstream declaration)

```text
opacity+/float: A number between 0 and 1
    match_window/str: Window to change opacity in
    match_tab/str: Tab to change opacity in
    all/bool: Boolean indicating operate on all windows
    toggle/bool: Boolean indicating if opacity should be toggled between the default and the specified value
```

#### Complete declared CLI options

##### `--all`, `-a`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

By default, background opacity are only changed for the currently active OS window. This option will
cause background opacity to be changed in all windows.


##### `--toggle`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

When specified, the background opacity for the matching OS windows will be reset to default if it is currently
equal to the specified value, otherwise it will be set to the specified value.


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--match-tab`, `-t`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


### `set-colors` — K2

Set the terminal colors for the specified windows/tabs (defaults to active window). You can either specify the path to a conf file (in the same format as :file:`kitty.conf`) to read the colors from or you can specify individual colors, for example::

    kitten @ set-colors foreground=red background=white

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='COLOR_OR_FILE ...', json_field='colors', special_parse='parse_colors_and_files(args)', completion=RemoteCommand.CompletionSpec.from_string('type:file group:"CONF files", ext:conf'))`.
Source: `kitty/rc/set_colors.py`, SHA256 `d21eaa5d12a54b779dfcc56e0c1d48a3ade2807b381f4334b0ea2c068d2a2f22`.

#### Wire payload (upstream declaration)

```text
colors+/dict.colors: An object mapping names to colors as 24-bit RGB integers or null for nullable colors. Or a string for transparent_background_colors.
    match_window/str: Window to change colors in
    match_tab/str: Tab to change colors in
    all/bool: Boolean indicating change colors everywhere or not
    configured/bool: Boolean indicating whether to change the configured colors. Must be True if reset is True
    reset/bool: Boolean indicating colors should be reset to startup values
```

#### Complete declared CLI options

##### `--all`, `-a`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

By default, colors are only changed for the currently active window. This option will
cause colors to be changed in all windows.


##### `--configured`, `-c`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

Also change the configured colors (i.e. the colors kitty will use for new
windows or after a reset).


##### `--reset`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Restore all colors to the values they had at kitty startup. Note that if you specify
this option, any color arguments are ignored and :option:`kitten @ set-colors --configured` and :option:`kitten @ set-colors --all` are implied.


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--match-tab`, `-t`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


### `set-enabled-layouts` — K2

Set the enabled layouts in the specified tabs (or the active tab if not specified). You can use special match value :code:`all` to set the enabled layouts in all tabs. If the current layout of the tab is not included in the enabled layouts, its layout is changed to the first enabled layout.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='LAYOUT ...', minimum_count=1, json_field='layouts', completion=RemoteCommand.CompletionSpec.from_string('type:keyword group:"Layout" kwds:' + ','.join(layout_names())), args_choices=layout_names)`.
Source: `kitty/rc/set_enabled_layouts.py`, SHA256 `f7ee68148d3458ff27132036e9f509ecca44f57ddc01c7fab07b7513d8758eb5`.

#### Wire payload (upstream declaration)

```text
layouts+/list.str: The list of layout names
    match/str: Which tab to change the layout of
    configured/bool: Boolean indicating whether to change the configured value
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--configured`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

Change the default enabled layout value so that the new value takes effect for all newly created tabs
as well.


### `set-font-size` — K2

Sets the font size to the specified size, in pts. Note that in kitty all sub-windows in the same OS window must have the same font size. A value of zero resets the font size to default. Prefixing the value with a :code:`+`, :code:`-`, :code:`*` or :code:`/` changes the font size by the specified amount. Use -- before using - to have it not mistaken for a option. For example: kitten @ set-font-size -- -2

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='FONT_SIZE', count=1, special_parse='+increment_op:parse_set_font_size(args[0], &payload)', json_field='size')`.
Source: `kitty/rc/set_font_size.py`, SHA256 `b6ce983b69413be06ed93c7c0a294442fca781d920486374a311bf5ac865a536`.

#### Wire payload (upstream declaration)

```text
size+/float: The new font size in pts (a positive number). If absent is assumed to be zero which means reset to default.
    all/bool: Boolean whether to change font size in the current window or all windows
    increment_op/choices.+.-.*./: The string ``+``, ``-``, ``*`` or ``/`` to interpret size as an increment
```

#### Complete declared CLI options

##### `--all`, `-a`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

By default, the font size is only changed in the active OS window,
this option will cause it to be changed in all OS windows. It also changes
the font size for any newly created OS Windows in the future.


### `set-spacing` — K2

Set the paddings and margins for the specified windows (defaults to active window). For example: :code:`margin=20` or :code:`padding-left=10` or :code:`margin-h=30`. The shorthand form sets all values, the :code:`*-h` and :code:`*-v` variants set horizontal and vertical values. The special value :code:`default` resets to using the default value. If you specify a tab rather than a window, all windows in that tab are affected.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='MARGIN_OR_PADDING ...', minimum_count=1, json_field='settings', special_parse='parse_set_spacing(args)')`.
Source: `kitty/rc/set_spacing.py`, SHA256 `5007540b061aafbafe34726ec39bbe6839142975aa9b9f7a6fa561718cdaa18c`.

#### Wire payload (upstream declaration)

```text
settings+/dict.spacing: An object mapping margins/paddings using canonical form {'margin-top': 50, 'padding-left': null} etc
    match_window/str: Window to change paddings and margins in
    match_tab/str: Tab to change paddings and margins in
    all/bool: Boolean indicating change paddings and margins everywhere or not
    configured/bool: Boolean indicating whether to change the configured paddings and margins. Must be True if reset is True
```

#### Complete declared CLI options

##### `--all`, `-a`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

By default, settings are only changed for the currently active window. This option will
cause paddings and margins to be changed in all windows.


##### `--configured`, `-c`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: sensitive-input-or-code.

Also change the configured paddings and margins (i.e. the settings kitty will use for new
windows).


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--match-tab`, `-t`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


### `set-tab-color` — K2


Change the color of the specified tabs in the tab bar

The foreground and background colors when active and inactive can be overridden using this command. The syntax for specifying colors is: active_fg=color active_bg=color inactive_fg=color inactive_bg=color. Where color can be either a color name or a value of the form #rrggbb or the keyword NONE to revert to using the default colors.


Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='COLORS', json_field='colors', minimum_count=1, special_parse='parse_tab_colors(args)')`.
Source: `kitty/rc/set_tab_color.py`, SHA256 `920449b0f33478ba5a62b29b1666ceea3f466a35c5e692c1db55ab10fff05cbb`.

#### Wire payload (upstream declaration)

```text
colors+/dict.colors: An object mapping names to colors as 24-bit RGB integers. A color value of null indicates it should be unset.
    match/str: Which tab to change the color of
    self/bool: Boolean indicating whether to use the tab of the window the command is run in
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Close the tab this command is run in, rather than the active tab.


### `set-tab-title` — K2

Set the title for the specified tabs. If you use the :option:`kitten @ set-tab-title --match` option the title will be set for all matched tabs. By default, only the tab in which the command is run is affected. If you do not specify a title, the title of the currently active window in the tab is used.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='TITLE ...', json_field='title', special_parse='expand_ansi_c_escapes_in_args(args...)')`.
Source: `kitty/rc/set_tab_title.py`, SHA256 `482850d51e60de11bfc6d5b05643ee4a08fe76bc0243c224c2f2af1913c80601`.

#### Wire payload (upstream declaration)

```text
title+/str: The new title
    match/str: Which tab to change the title of
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The tab to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`index`, :code:`title`, :code:`window_id`, :code:`window_title`,
:code:`pid`, :code:`cwd`, :code:`cmdline` :code:`env`, :code:`var`, :code:`state`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all tabs.

For numeric fields: :code:`id`, :code:`index`, :code:`window_id`, :code:`pid` and :code:`recent`, the
expression is interpreted as a number, not a regular expression. Negative values for :code:`id`/:code:`window_id` match
from the highest id number down, in particular, -1 is the most recently created tab/window.

When using :code:`title` or :code:`id`, first a matching tab is looked for, and if not found a matching window is looked
for, and the tab for that window is used.

You can also use :code:`window_id` and :code:`window_title` to match the tab that contains the window with the specified
id or title.

The :code:`index` number is used to match the nth tab in the currently active OS window.
The :code:`recent` number matches recently active tabs in the currently active OS window, with zero being the currently
active tab, one the previously active tab and so on.

The field :code:`session` matches tabs that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`. Tabs containing any window with the specified environment
variables are matched. Similarly, :code:`var` matches tabs containing any window with the specified user variable.

The field :code:`state` matches on the state of the tab. Supported states are:
:code:`active`, :code:`focused`, :code:`needs_attention`, :code:`parent_active`, :code:`parent_focused`
and :code:`focused_os_window`.
Active tabs are the tabs that are active in their parent OS window. There is only one focused tab
and it is the tab to which keyboard events are delivered. If no tab is focused, the last focused tab is matched.
The value :code:`focused_os_window` matches all tabs in the currently focused OS window.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of tabs.


### `set-user-vars` — K2

Set user variables for the specified windows. If you use the :option:`kitten @ set-user-vars --match` option the variables will be set for all matched windows. By default, only the window in which the command is run is affected. If you do not specify any variables, the current variables are printed out, one per line. To unset a variable specify just its name.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(json_field='var', spec='[NAME=VALUE ...]')`.
Source: `kitty/rc/set_user_vars.py`, SHA256 `85c2ed11abc995483a924875848ba275875350bd4cf7919842e33647ef938293`.

#### Wire payload (upstream declaration)

```text
var/list.str: List of user variables of the form NAME=VALUE
    match/str: Which windows to change the title in
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


### `set-window-logo` — K3

Set the logo image for the specified windows. You must specify the path to an image that will be used as the logo. If you specify the special value :code:`none` then any existing logo will be removed. Supported image formats are: PNG, JPEG, WEBP, GIF, BMP, TIFF

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: True; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(spec='PATH_TO_PNG_IMAGE', count=1, json_field='data', special_parse='!read_window_logo(io_data, args[0])', completion=ImageCompletion)`.
Source: `kitty/rc/set_window_logo.py`, SHA256 `4e30d35625f1054b126fe44af6cda2c62e20718784d2f300007353d0ff4287f0`.

#### Wire payload (upstream declaration)

```text
data+/str: Chunk of PNG data, base64 encoded no more than 2048 bytes. Must send an empty chunk to indicate end of image.     Or the special value :code:`-` to indicate image must be removed.
    position/str: The logo position as a string, empty string means default
    alpha/float: The logo alpha between :code:`0` and :code:`1`. :code:`-1` means use default
    match/str: Which window to change the logo in
    self/bool: Boolean indicating whether to act on the window the command is run in
```

#### Complete declared CLI options

##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


##### `--self`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

Act on the window this command is run in, rather than the active window.


##### `--position`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The position for the window logo. See :opt:`window_logo_position`.


##### `--alpha`

Type: `float`; CLI default: `-1.0`; explicit source default: `"-1"`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The amount the window logo should be faded into the background.
See :opt:`window_logo_position`.


##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response from kitty. This means that even if setting the image
failed, the command will exit with a success code.


### `set-window-title` — K2

Set the title for the specified windows. If you use the :option:`kitten @ set-window-title --match` option the title will be set for all matched windows. By default, only the window in which the command is run is affected. If you do not specify a title, the last title set by the child process running in the window will be used.

Hazards: target-default-may-be-active, effects-require-verification.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(json_field='title', spec='[TITLE ...]', special_parse='expand_ansi_c_escapes_in_args(args...)')`.
Source: `kitty/rc/set_window_title.py`, SHA256 `83fc98224d66d1b4a2a223b8822d8c01850c89e36efabcc1211370b7479e7ba6`.

#### Wire payload (upstream declaration)

```text
title/str: The new title
    match/str: Which windows to change the title in
    temporary/bool: Boolean indicating if the change is temporary or permanent
```

#### Complete declared CLI options

##### `--temporary`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

By default, the title will be permanently changed and programs running in the window will not be able to change it
again. If you want to allow other programs to change it afterwards, use this option.


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


### `signal-child` — K3

Send one or more signals to the foreground process in the specified windows. If you use the :option:`kitten @ signal-child --match` option the signal will be sent for all matched windows. By default, only the active window is affected. If you do not specify any signals, :code:`SIGINT` is sent by default. You can also map :ac:`signal_child` to a shortcut in :file:`kitty.conf`, for example::

    map f1 signal_child SIGTERM

Hazards: target-default-may-be-active, effects-require-verification, target-blind, his-window-K3, destructive-K3.
Async: False; streaming: False; no-response declaration: False.
Argument declaration: `RemoteCommand.Args(json_field='signals', spec='[SIGNAL_NAME ...]', value_if_unspecified=('SIGINT',))`.
Source: `kitty/rc/signal_child.py`, SHA256 `86971025e2d1501962cb1ea260c8682e024580dc39777c80c34d140ddfd9ce82`.

#### Wire payload (upstream declaration)

```text
signals+/list.str: The signals, a list of names, such as :code:`SIGTERM`, :code:`SIGKILL`, :code:`SIGUSR1`, etc.
    match/str: Which windows to send the signals to
```

#### Complete declared CLI options

##### `--no-response`

Type: `bool-set`; CLI default: `false`; explicit source default: `"false"`.
Choices: not enumerated.
Option hazards: response-is-not-effect-proof.

Don't wait for a response indicating the success of the action. Note that
using this option means that you will not be notified of failures.


##### `--match`, `-m`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: target-expansion.

The window to match. Match specifications are of the form: :italic:`field:query`.
Where :italic:`field` can be one of: :code:`id`, :code:`title`, :code:`pid`, :code:`cwd`, :code:`cmdline`, :code:`num`,
:code:`env`, :code:`var`, :code:`state`, :code:`neighbor`, :code:`session` and :code:`recent`.
:italic:`query` is the expression to match. Expressions can be either a number or a regular expression, and can be
:ref:`combined using Boolean operators <search_syntax>`.

The special value :code:`all` matches all windows.

For numeric fields: :code:`id`, :code:`pid`, :code:`num` and :code:`recent`, the expression is interpreted as
a number, not a regular expression. Negative values for :code:`id` match from the highest id number down, in particular,
-1 is the most recently created window.

The field :code:`num` refers to the window position in the current tab, starting from zero and counting clockwise (this
is the same as the order in which the windows are reported by the :ref:`kitten @ ls <at-ls>` command).

The window id of the current window is available as the :envvar:`KITTY_WINDOW_ID` environment variable.

The field :code:`recent` refers to recently active windows in the currently active tab, with zero being the currently
active window, one being the previously active window and so on.

The field :code:`neighbor` refers to a neighbor of the active window in the specified direction, which can be:
:code:`left`, :code:`right`, :code:`top` or :code:`bottom`.

The field :code:`session` matches windows that were created in the specified session.
Use the expression :code:`^$` to match windows that were not created in a session and
:code:`.` to match the currently active session and :code:`~` to match either the currently
active session or the last active session when no session is active.

When using the :code:`env` field to match on environment variables, you can specify only the environment variable name
or a name and value, for example, :code:`env:MY_ENV_VAR=2`.

Similarly, the :code:`var` field matches on user variables set on the window. You can specify name or name and value
as with the :code:`env` field.

The field :code:`state` matches on the state of the window. Supported states
are: :code:`active`, :code:`focused`, :code:`needs_attention`,
:code:`parent_active`, :code:`parent_focused`, :code:`focused_os_window`,
:code:`self`, :code:`overlay_parent`.  Active windows are the windows that are
active in their parent tab. There is only one focused window and it is the
window to which keyboard events are delivered. If no window is focused, the
last focused window is matched. The value :code:`focused_os_window` matches
all windows in the currently focused OS window. The value :code:`self` matches
the window in which the remote control command is run. The value
:code:`overlay_parent` matches the window that is under the :code:`self`
window, when the self window is an overlay.

Note that you can use the :ref:`kitten @ ls <at-ls>` command to get a list of windows.


## Ring 2 — bundled kittens and companion tools

Upstream membership only. `tools/cmd/tool/main.go` provides compiled entry points; Python-only kittens use `kitty +kitten NAME`.

| Name | Purpose | Source |
|---|---|---|
| `ask` | Interactive questions and dialogs | `kittens/ask/main.py` |
| `broadcast` | Type into multiple windows | `kittens/broadcast/main.py` |
| `choose_files` | Graphical file chooser | `kittens/choose_files/main.py` |
| `choose_fonts` | Choose and preview fonts | `kittens/choose_fonts/main.py` |
| `clipboard` | Read or write the system clipboard | `kittens/clipboard/main.py` |
| `command_palette` | Search kitty actions | `kittens/command_palette/main.py` |
| `desktop_ui` | Desktop integration user interfaces | `kittens/desktop_ui/main.py` |
| `diff` | Side-by-side file/directory diff | `kittens/diff/main.py` |
| `dnd` | Drag and drop terminal files | `kittens/dnd/main.py` |
| `hints` | Keyboard selection of text, URLs and paths | `kittens/hints/main.py` |
| `hyperlinked_grep` | Run ripgrep and hyperlink paths | `kittens/hyperlinked_grep/main.py` |
| `icat` | Display images in a terminal | `kittens/icat/main.py` |
| `notify` | Desktop notifications | `kittens/notify/main.py` |
| `pager` | Terminal pager | `kittens/pager/main.py` |
| `panel` | Desktop panel | `kittens/panel/main.py` |
| `query_terminal` | Query terminal capabilities | `kittens/query_terminal/main.py` |
| `quick_access_terminal` | Drop-down terminal | `kittens/quick_access_terminal/main.py` |
| `remote_file` | Download/open/edit remote SSH files; edit saves upload changes | `kittens/remote_file/main.py` |
| `resize_window` | Interactively resize kitty windows | `kittens/resize_window/main.py` |
| `show_key` | Inspect keyboard events | `kittens/show_key/main.py` |
| `ssh` | OpenSSH wrapper with remote terminfo, bootstrap and shell integration | `kittens/ssh/main.py` |
| `themes` | Preview/apply color themes | `kittens/themes/main.py` |
| `transfer` | TTY file transfer; recursive and incremental | `kittens/transfer/main.py` |
| `unicode_input` | Choose Unicode characters | `kittens/unicode_input/main.py` |
| `mouse-demo` | Demonstrate terminal mouse reporting | `tools/cmd/tool/main.go` |
| `edit-in-kitty` | Open files in kitty editor windows | `tools/cmd/tool/main.go` |
| `run-shell` | Run a shell with integration (legacy T3 hold still applies) | `tools/cmd/tool/main.go` |
| `update-self` | Update standalone kitten (not a substitute for Fedora dnf) | `tools/cmd/tool/main.go` |

### ssh

OpenSSH wrapper with remote terminfo, bootstrap and shell integration

These are ssh.conf copy-directive options, NOT top-level SSH flags.


##### `--glob`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Interpret file arguments as glob patterns. Globbing is based on
standard wildcards with the addition that ``/**/`` matches any number of directories.
See the :link:`detailed syntax <https://github.com/bmatcuk/doublestar#patterns>`.


##### `--dest`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The destination on the remote host to copy to. Relative paths are resolved
relative to HOME on the remote host. When this option is not specified, the
local file path is used as the remote destination (with the HOME directory
getting automatically replaced by the remote HOME). Note that environment
variables and ~ are not expanded.


##### `--exclude`

Type: `list`; CLI default: `[]`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

A glob pattern. Files with names matching this pattern are excluded from being
transferred. Only used when copying directories. Can
be specified multiple times, if any of the patterns match the file will be
excluded. If the pattern includes a :code:`/` then it will match against the full
path, not just the filename. In such patterns you can use :code:`/**/` to match zero
or more directories. For example, to exclude a directory and everything under it use
:code:`**/directory_name`.
See the :link:`detailed syntax <https://github.com/bmatcuk/doublestar#patterns>` for
how wildcards match.


##### `--symlink-strategy`

Type: `choices`; CLI default: `"preserve"`; explicit source default: `"preserve"`.
Choices: preserve, resolve, keep-path.
Option hazards: inherits act hazards.

Control what happens if the specified path is a symlink. The default is to preserve
the symlink, re-creating it on the remote machine. Setting this to :code:`resolve`
will cause the symlink to be followed and its target used as the file/directory to copy.
The value of :code:`keep-path` is the same as :code:`resolve` except that the remote
file path is derived from the symlink's path instead of the path of the symlink's target.
Note that this option does not apply to symlinks encountered while recursively copying directories,
those are always preserved.


Invocation is identical to installed OpenSSH. Kitty discovers its flags from ssh usage; this pinned fallback is NOT proof of the owner OpenSSH option set or defaults. --kitten option=value overrides ssh.conf; all config keys and copy options are included. Collect ssh -V and the installed ssh(1)/ssh_config(5) at the owner gate.

| OpenSSH fallback flag | Argument |
|---|---|
| `-4` | `` |
| `-6` | `` |
| `-A` | `` |
| `-a` | `` |
| `-C` | `` |
| `-f` | `` |
| `-G` | `` |
| `-g` | `` |
| `-K` | `` |
| `-k` | `` |
| `-M` | `` |
| `-N` | `` |
| `-n` | `` |
| `-q` | `` |
| `-s` | `` |
| `-T` | `` |
| `-t` | `` |
| `-V` | `` |
| `-v` | `` |
| `-X` | `` |
| `-x` | `` |
| `-Y` | `` |
| `-y` | `` |
| `-B` | `bind_interface` |
| `-b` | `bind_address` |
| `-c` | `cipher_spec` |
| `-D` | `[bind_address:]port` |
| `-E` | `log_file` |
| `-e` | `escape_char` |
| `-F` | `configfile` |
| `-I` | `pkcs11` |
| `-i` | `identity_file` |
| `-J` | `[user@]host[:port]` |
| `-L` | `address` |
| `-l` | `login_name` |
| `-m` | `mac_spec` |
| `-O` | `ctl_cmd` |
| `-o` | `option` |
| `-p` | `port` |
| `-Q` | `query_option` |
| `-R` | `address` |
| `-S` | `ctl_path` |
| `-W` | `host:port` |
| `-w` | `local_tun[:remote_tun]` |

#### Kitty SSH configuration (`--kitten option=value` / ssh.conf)

##### hostname

Default: `"*"`.


The hostname that the following options apply to. A glob pattern to match
multiple hosts can be used. Multiple hostnames can also be specified, separated
by spaces. The hostname can include an optional username in the form
:code:`user@host`. When not specified options apply to all hosts, until the
first hostname specification is found. Note that matching of hostname is done
against the name you specify on the command line to connect to the remote host.
If you wish to include the same basic configuration for many different hosts,
you can do so with the :ref:`include <include>` directive. In version 0.28.0
the behavior of this option was changed slightly, now, when a hostname is encountered
all its config values are set to defaults instead of being inherited from a previous
matching hostname block. In particular it means hostnames dont inherit configurations,
thereby avoiding hard to understand action-at-a-distance.


##### interpreter

Default: `"sh"`.


The interpreter to use on the remote host. Must be either a POSIX complaint
shell or a :program:`python` executable. If the default :program:`sh` is not
available or broken, using an alternate interpreter can be useful.


##### remote_dir

Default: `".local/share/kitty-ssh-kitten"`.


The location on the remote host where the files needed for this kitten are
installed. Relative paths are resolved with respect to :code:`$HOME`. Absolute
paths have their leading / removed and so are also resolved with respect to $HOME.


##### copy

Default: `""`.


Copy files and directories from local to remote hosts. The specified files are
assumed to be relative to the HOME directory and copied to the HOME on the
remote. Directories are copied recursively. If absolute paths are used, they are
copied as is. For example::

    copy .vimrc .zshrc .config/some-dir

Use :code:`--dest` to copy a file to some other destination on the remote host::

    copy --dest some-other-name some-file

Glob patterns can be specified to copy multiple files, with :code:`--glob`::

    copy --glob images/*.png

Files can be excluded when copying with :code:`--exclude`::

    copy --glob --exclude *.jpg --exclude *.bmp images/*

Files whose remote name matches the exclude pattern will not be copied.
For more details, see :ref:`ssh_copy_command`.


##### shell_integration

Default: `"inherited"`.


Control the shell integration on the remote host. See :ref:`shell_integration`
for details on how this setting works. The special value :code:`inherited` means
use the setting from :file:`kitty.conf`. This setting is useful for overriding
integration on a per-host basis.


##### login_shell

Default: `""`.


The login shell to execute on the remote host. By default, the remote user
account's login shell is used.


##### env

Default: `""`.


Specify the environment variables to be set on the remote host. Using the
name with an equal sign (e.g. :code:`env VAR=`) will set it to the empty string.
Specifying only the name (e.g. :code:`env VAR`) will remove the variable from
the remote shell environment. The special value :code:`_kitty_copy_env_var_`
will cause the value of the variable to be copied from the local environment.
The definitions are processed alphabetically. Note that environment variables
are expanded recursively, for example::

    env VAR1=a
    env VAR2=${HOME}/${VAR1}/b

The value of :code:`VAR2` will be :code:`<path to home directory>/a/b`.


##### cwd

Default: `""`.


The working directory on the remote host to change to. Environment variables in
this value are expanded. The default is empty so no changing is done, which
usually means the HOME directory is used.


##### color_scheme

Default: `""`.


Specify a color scheme to use when connecting to the remote host. If this option
ends with :code:`.conf`, it is assumed to be the name of a config file to load
from the kitty config directory, otherwise it is assumed to be the name of a
color theme to load via the :doc:`themes kitten </kittens/themes>`. Note that
only colors applying to the text/background are changed, other config settings
in the .conf files/themes are ignored.


##### remote_kitty

Default: `"if-needed"`.


Make :program:`kitten` available on the remote host. Useful to run kittens such
as the :doc:`icat kitten </kittens/icat>` to display images or the
:doc:`transfer file kitten </kittens/transfer>` to transfer files. Only works if
the remote host has an architecture for which :link:`pre-compiled kitten binaries
<https://github.com/kovidgoyal/kitty/releases>` are available. Note that kitten
is not actually copied to the remote host, instead a small bootstrap script is
copied which will download and run kitten when kitten is first executed on the
remote host. A value of :code:`if-needed` means kitten is installed only if not
already present in the system-wide PATH. A value of :code:`yes` means that kitten
is installed even if already present, and the installed kitten takes precedence.
Finally, :code:`no` means no kitten is installed on the remote host. The
installed kitten can be updated by running: :code:`kitten update-self` on the
remote host.


##### share_connections

Default: `"yes"`.


Within a single kitty instance, all connections to a particular server can be
shared. This reduces startup latency for subsequent connections and means that
you have to enter the password only once. Under the hood, it uses SSH
ControlMasters and these are automatically cleaned up by kitty when it quits.
You can map a shortcut to :ac:`close_shared_ssh_connections` to disconnect all
active shared connections.


##### askpass

Default: `"unless-set"`.


Control the program SSH uses to ask for passwords or confirmation of host keys
etc. The default is to use kitty's native :program:`askpass`, unless the
:envvar:`SSH_ASKPASS` environment variable is set. Set this option to
:code:`ssh` to not interfere with the normal ssh askpass mechanism at all, which
typically means that ssh will prompt at the terminal. Set it to :code:`native`
to always use kitty's native, built-in askpass implementation. Note that not
using the kitty askpass implementation means that SSH might need to use the
terminal before the connection is established, so the kitten cannot use the
terminal to send data without an extra roundtrip, adding to initial connection
latency.


##### delegate

Default: `""`.


Do not use the SSH kitten for this host. Instead run the command specified as the delegate.
For example using :code:`delegate ssh` will run the ssh command with all arguments passed
to the kitten, except kitten specific ones. This is useful if some hosts are not capable
of supporting the ssh kitten.


##### forward_remote_control

Default: `"no"`.


Forward the kitty remote control socket to the remote host. This allows using the kitty
remote control facilities from the remote host. WARNING: This allows any software
on the remote host full access to the local computer, so only do it for trusted remote hosts.
Note that this does not work with abstract UNIX sockets such as :file:`@mykitty` because of SSH limitations.
This option uses SSH socket forwarding to forward the socket pointed to by the :envvar:`KITTY_LISTEN_ON`
environment variable.


##### password

Default: `""`.


Specify a password to use when SSH prompts for a password. The value format is
"backend:secret". Currently, only the "text" backend is supported, which stores
the secret in plain text in the config file. For example:

    password text:my_password

If the backend prefix is omitted, it is treated as "text:" for backward
compatibility. Beware that storing passwords in plain text is insecure.


##### totp_secret

Default: `""`.


Specify a TOTP shared secret to auto-fill one-time codes when SSH asks for them.
The value format is "backend:secret". Currently, only the "text" backend is
supported. For example:

    totp_secret text:JBSWY3DPEHPK3PXP

If the backend prefix is omitted, it is treated as "text:" for backward
compatibility.


##### totp_digits

Default: `"6"`.


Number of digits for the generated TOTP codes. Default is 6.


##### totp_period

Default: `"30"`.


Time period in seconds for the TOTP code validity. Default is 30.



### transfer

TTY file transfer; recursive and incremental




##### `--direction`, `-d`

Type: `choices`; CLI default: `"download"`; explicit source default: `"download"`.
Choices: upload, download, send, receive.
Option hazards: inherits act hazards.

Whether to send or receive files. :code:`send` or :code:`download` copy files from the computer
on which the kitten is running (usually the remote computer) to the local computer. :code:`receive`
or :code:`upload` copy files from the local computer to the remote computer.


##### `--mode`, `-m`

Type: `choices`; CLI default: `"normal"`; explicit source default: `"normal"`.
Choices: normal, mirror.
Option hazards: inherits act hazards.

How to interpret command line arguments. In :code:`mirror` mode all arguments
are assumed to be files/dirs on the sending computer and they are mirrored onto the
receiving computer. Files under the HOME directory are copied to the HOME directory
on the receiving computer even if the HOME directory is different.
In :code:`normal` mode the last argument is assumed to be a destination path on the
receiving computer. The last argument must be an existing directory unless copying a
single file. When it is a directory it should end with a trailing slash.


##### `--compress`

Type: `choices`; CLI default: `"auto"`; explicit source default: `"auto"`.
Choices: auto, never, always.
Option hazards: inherits act hazards.

Whether to compress data being sent. By default compression is enabled based on the
type of file being sent. For files recognized as being already compressed, compression
is turned off as it just wastes CPU cycles.


##### `--permissions-bypass`, `-p`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The password to use to skip the transfer confirmation popup in kitty. Must match
the password set for the :opt:`file_transfer_confirmation_bypass` option in
:file:`kitty.conf`. Note that leading and trailing whitespace is removed from
the password. A password starting with :code:`.`, :code:`/` or :code:`~`
characters is assumed to be a file name to read the password from. A value of
:code:`-` means read the password from STDIN. A password that is purely a number
less than 256 is assumed to be the number of a file descriptor from which to
read the actual password.


##### `--confirm-paths`, `-c`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Before actually transferring files, show a mapping of local file names to remote
file names and ask for confirmation.


##### `--transmit-deltas`, `-x`

Type: `bool-set`; CLI default: `false`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

If a file on the receiving side already exists, use the rsync algorithm to
update it to match the file on the sending side, potentially saving lots of
bandwidth and also automatically resuming partial transfers. Note that this will
actually degrade performance on fast links or with small files, so use with care.


### remote_file

Download/open/edit remote SSH files; edit saves upload changes




##### `--mode`, `-m`

Type: `choices`; CLI default: `"ask"`; explicit source default: `"ask"`.
Choices: ask, edit.
Option hazards: inherits act hazards.

Which mode to operate in.


##### `--path`, `-p`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Path to the remote file.


##### `--hostname`, `-h`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

Hostname of the remote host.


##### `--ssh-connection-data`

Type: `str`; CLI default: `""`; explicit source default: `null`.
Choices: not enumerated.
Option hazards: inherits act hazards.

The data used to connect over ssh.


## Ring 3 — kitty.conf / Fedora / Hyprland

### paste_actions

Upstream default: `"quote-urls-at-prompt,confirm"`.


A comma separated list of actions to take when pasting or dropping text into the terminal.
The supported paste actions are:

:code:`quote-urls-at-prompt`:
    If the text being pasted is a URL and the cursor is at a shell prompt,
    automatically quote the URL (needs :opt:`shell_integration`).
:code:`replace-dangerous-control-codes`
    Replace dangerous control codes from pasted text, without confirmation.
:code:`replace-newline`
    Replace the newline character from pasted text, without confirmation.
:code:`confirm`:
    Confirm the paste if the text to be pasted contains any terminal control codes
    as this can be dangerous, leading to code execution if the shell/program running
    in the terminal does not properly handle these.
:code:`confirm-if-large`
    Confirm the paste if it is very large (larger than 16KB) as pasting
    large amounts of text into shells can be very slow.
:code:`filter`:
    Run the filter_paste() function from the file :file:`paste-actions.py` in
    the kitty config directory on the pasted text. The text returned by the
    function will be actually pasted.
:code:`no-op`:
    Has no effect.


### enabled_layouts

Upstream default: `"*"`.


The enabled window layouts. A comma separated list of layout names. The special
value :code:`all` means all layouts. The first listed layout will be used as the
startup layout. Default configuration is all layouts in alphabetical order. For
a list of available layouts, see the :ref:`layouts`.


### remote_control_password

Upstream default: `""`.


Allow other programs to control kitty using passwords. This option can be
specified multiple times to add multiple passwords. If no passwords are present
kitty will ask the user for permission if a program tries to use remote control
with a password. A password can also *optionally* be associated with a set of
allowed remote control actions. For example::

    remote_control_password "my passphrase" get-colors set-colors focus-window focus-tab

Only the specified actions will be allowed when using this password.
Glob patterns can be used too, for example::

    remote_control_password "my passphrase" set-tab-* resize-*

To get a list of available actions, run::

    kitten @ --help

A set of actions to be allowed when no password is sent can be specified by
using an empty password. For example::

    remote_control_password "" *-colors

Finally, the path to a python module can be specified that provides a function
:code:`is_cmd_allowed` that is used to check every remote control command.
For example::

    remote_control_password "my passphrase" my_rc_command_checker.py

Relative paths are resolved from the kitty configuration directory.
See :ref:`rc_custom_auth` for details.


### allow_remote_control

Upstream default: `"no"`.


Allow other programs to control kitty. If you turn this on, other programs can
control all aspects of kitty, including sending text to kitty windows, opening
new windows, closing windows, reading the content of windows, etc. Note that
this even works over SSH connections. The default setting of :code:`no`
prevents any form of remote control. The meaning of the various values are:

:code:`password`
    Remote control requests received over both the TTY device and the socket
    are confirmed based on passwords, see :opt:`remote_control_password`.

:code:`socket-only`
    Remote control requests received over a socket are accepted
    unconditionally. Requests received over the TTY are denied.
    See :opt:`listen_on`.

:code:`socket`
    Remote control requests received over a socket are accepted
    unconditionally. Requests received over the TTY are confirmed based on
    password.

:code:`no`
    Remote control is completely disabled.

:code:`yes`
    Remote control requests are always accepted.


### listen_on

Upstream default: `"none"`.


Listen to the specified socket for remote control connections. Note that this
will apply to all kitty instances. It can be overridden by the :option:`kitty
--listen-on` command line option. For UNIX sockets, such as
:code:`unix:${TEMP}/mykitty` or :code:`unix:@mykitty` (on Linux). Environment
variables are expanded and relative paths are resolved with respect to the
temporary directory. If :code:`{kitty_pid}` is present, then it is replaced by
the PID of the kitty process, otherwise the PID of the kitty process is
appended to the value, with a hyphen. For TCP sockets such as
:code:`tcp:localhost:0` a random port is always used even if a non-zero port
number is specified.  See the help for :option:`kitty --listen-on` for more
details. Note that this will be ignored unless :opt:`allow_remote_control` is
set to either: :code:`yes`, :code:`socket` or :code:`socket-only`.
Changing this option by reloading the config is not supported.


### Packaging and upgrade gate

The owner design record identifies Fedora 44 updates `0.47.1-1.fc44`, base `0.43.1`, and packages `kitty`, `kitty-kitten`, `kitty-shell-integration`, `kitty-terminfo`. These are **ruling-supplied facts**, not installed-package measurements here.
Owner collects `rpm -q kitty kitty-kitten kitty-shell-integration kitty-terminfo`, package file lists, `kitten --version`, and `ssh -V`. Never use `kitten update-self` to bypass RPM-managed upgrades.
Run `tools/kitty/drift.py` after **every dnf kitty upgrade**, then manually reconcile command/options/defaults, semantic changes, Fedora membership and OpenSSH delegation before calling this lane done.

### Hyprland focus interop

See `docs/kitty-setup.md`: v0.57.0 uses `hl.window_rule`, `initial_title`, `no_initial_focus`. The legacy windowrulev2 spelling is historical, not the install instruction for 0.57. `stay_focused` pins an existing surface and is not interchangeable with no-initial-focus. Audit broad stay-focused rules; do not install one on HER windows.

### License and reproduction

Upstream option/protocol/config prose is GPL-3.0, copyright Kovid Goyal and contributors. `src/assistant/hands/kitty/data/COPYING.kitty` accompanies the extracted text.
Build scripts parse Python AST and literal option declarations only; they do not import or execute upstream kitty. Download v0.47.1 source, run `tools/kitty/build_inventory.py SOURCE src/assistant/hands/kitty/data/inventory.json`, then `tools/kitty/render_inventory.py`.
