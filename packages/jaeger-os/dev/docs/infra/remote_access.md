# Remote access for a Jaeger device

Two directions, two different stories. Read this whole doc before deploying a
Jaeger unit you intend to manage remotely.

```
        ┌─────────────────────────────────────────────────────┐
        │                  Jaeger unit (host)                 │
        │                                                     │
operator ──SSH──►  sshd  ──►  tmux  ──►  jaeger TUI ──┐       │
                                                       │       │
                                                       ▼       │
                                              ssh_exec / remote_terminal
                                                       │       │
                                                       └──SSH──┼──► other hosts
                                                               │
        └─────────────────────────────────────────────────────┘
            (inbound: OS-level; no JROS code)   (outbound: JROS tool)
```

## Inbound — operating the device from elsewhere

This is **not a JROS feature**. It's the host OS doing what host OSes do:
``sshd`` listens; the operator connects; they run ``jaeger`` in a shell;
the TUI works over the SSH stream because ``prompt_toolkit`` reads
terminal size + colour from the controlling tty, both of which SSH
forwards.

### One-time host setup

1. **Enable SSH on the device.** macOS: *System Settings → General →
   Sharing → Remote Login*. Linux: ``sudo systemctl enable --now sshd``.
2. **Key-only auth** — turn off password auth in ``/etc/ssh/sshd_config``:
   ```
   PasswordAuthentication no
   PubkeyAuthentication yes
   ```
   Reload with ``sudo systemctl reload ssh`` (Linux) or ``sudo launchctl
   kickstart -k system/com.openssh.sshd`` (macOS).
3. **Put your operator key in** ``~jaeger/.ssh/authorized_keys`` (one
   key per line; modes ``600`` on the file, ``700`` on the dir).
4. **Optional but recommended** — set ``AllowUsers jaeger`` so other
   accounts on the box can't be reached over SSH.

### Persistent sessions (tmux)

Without tmux, **closing the SSH connection kills the TUI process**
(and therefore the agent — see [Agent persistence](#agent-persistence)).
Wrap the TUI in tmux so disconnect ≠ kill:

```sh
ssh jaeger@<unit>
tmux new -s jaeger      # first time
# … run `jaeger` inside the tmux session …
# Ctrl-b, d   to detach (TUI keeps running)
tmux attach -t jaeger   # next time
```

### Agent persistence

Important caveat: **the agent lives inside the TUI process.** If tmux
keeps the TUI alive, the agent stays alive too. If something kills the
TUI, the agent dies — model unloads, conversation history of the
current session is gone, the instance lock is released. Things that
*do* survive the agent dying: the kanban board, ``remember()`` facts,
the episodic log, and any subprocess started via the
``start_background`` tool (those are session leaders that outlive the
parent).

A future architecture decision will split the agent into a daemon that
TUI/web clients attach to over a socket; until then, treat the TUI
process as the agent.

## Outbound — the agent operating other hosts

This **is** a JROS feature: the ``ssh_exec`` tool (agent-facing name:
``remote_terminal``). It's a thin wrapper around the local ``ssh``
binary — the agent gets one verb:

```
remote_terminal(host, command, timeout_s=60)
  → {ok, host, command, exit_code, stdout, stderr, elapsed_s, timed_out, interrupted}
```

### Why subprocess and not paramiko

``ssh(1)`` already reads ``~/.ssh/config``, walks the user's keychain,
honours ``known_hosts``, forwards the agent, and respects
``ControlMaster``. A pure-Python client would reimplement all of that
and never quite match. The cost — one fork+exec per call — is fine for
the use case (the agent is not running ten thousand SSH calls per
second).

### What's pinned

The tool overrides three ssh options so the contract doesn't silently
shift with the user's ``ssh_config``:

  - ``BatchMode=yes`` — never prompt for a password. A missing key fails
    fast instead of hanging on a prompt the agent can't answer.
  - ``ConnectTimeout=10`` — dead hosts fail in ~10 seconds instead of
    the OS default ~75.
  - ``StrictHostKeyChecking=accept-new`` — first-time hosts get added to
    ``known_hosts`` automatically, but a **changed** key still aborts.
    Protects against the basic key-swap MITM without making every new
    host an interactive moment.

The remote command is passed as one argv element after ``--``, so the
**local** shell does not parse it. The **remote** side still runs it
through the remote shell — same as ``ssh host '<command>'`` from a
terminal.

### Safety stack — same as run_shell

Three layers:

1. **Hardline guard** (``hardline_guard("command")``) — refuses
   catastrophic commands (``rm -rf /``, ``mkfs``, fork bombs, raw-disk
   writes) regardless of tier or confirmation. Runs *outside* the tier
   check, so it can't be bypassed by an over-eager confirmation
   provider.
2. **Tier-4 PRIVILEGED gate** (``@requires_tier(PermissionTier.PRIVILEGED)``)
   — every call routes through the confirmation flow. The human sees and
   approves the exact ``host`` + ``command`` before the subprocess runs.
3. **Pre-flight audit** — every call writes a row to
   ``<instance>/logs/audit.jsonl`` *before* the subprocess starts, so a
   hung or never-returning call still leaves a record.

Host-string validation happens **first** so a host like ``-oProxyCommand=...``
or ``foo;rm -rf /`` is rejected before any of the above runs. We strip
the input, reject leading dashes, and reject anything carrying shell
metacharacters.

### Out of scope (deliberate)

  - **File transfer** — no ``scp``/``rsync`` tool. If you need to move a
    file, ``cat`` it through the command (small) or do it over an
    explicit ``run_shell`` call (large, intentional).
  - **Streaming output** — long-running ``tail -f`` style commands
    aren't supported. The tool returns one buffered result. For
    persistent watching, launch via ``start_background``.
  - **Hostname allowlist** — the device can SSH to any destination the
    local ``ssh_config`` knows about. If you need to fence a Jaeger unit
    to a specific set of hosts, do it at the OS level (firewall,
    ``Match Host`` blocks in ``ssh_config``, or a wrapper script the
    agent's ``ssh`` binary actually points at).

These can be added later when a concrete use case justifies them; each
has its own security shape and shouldn't be folded into ``ssh_exec`` on
spec.
