# Emu Memory Daemon

A background process that curates `.emu/` memory files (`AGENTS.md`,
`MEMORY.md`, daily logs) by running an LLM agent loop on each new session
transcript. Runs out-of-process via macOS launchd, decoupled from the
foreground Emu app.

For the architecture and security model see [DESIGN.md](DESIGN.md).

This folder is intentionally self-contained so it can be extracted to its
own repository. It has no `from backend …` imports; the Emu backend
integrates by importing `daemon.state.record_session_in_index` and by
sharing the on-disk `.emu/` tree.

## Layout

```
daemon/
├── run.py              # one-tick entry point (python -m daemon.run)
├── prompt.py           # system prompt for the agent loop
├── policy.py           # path containment rules (write allowlist)
├── tools.py            # read_file / write_file / list_dir / finish
├── llm_client.py       # provider-agnostic agent loop
├── state.py            # processed-session bookkeeping + sessions/index.json
├── cleanup.py          # log rotation, old-session pruning
├── install_macos.py    # plist install/uninstall/status (CLI)
├── install.sh          # bash wrapper around install_macos.py
├── launchd/
│   ├── com.emu.memory-daemon.plist.template
│   └── run.sh          # launchd entrypoint (sources .env, exec python)
├── .env.example        # all daemon env vars in one file
├── pyproject.toml      # standalone-installable package metadata
└── DESIGN.md
```

## Configure

Copy `.env.example` to `.env` and fill in:

```bash
cp daemon/.env.example daemon/.env
```

Minimum needed to tick:

- `EMU_DAEMON_PROVIDER` — e.g. `openrouter`, `claude`, `openai`
- `EMU_DAEMON_API_KEY` — or one of the provider-specific fallbacks
  (`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, …) — or a macOS Keychain
  entry under service name `com.emu.memory-daemon`
- `EMU_ROOT` — only when running outside the emulation-agent source tree;
  defaults to `<repo>/.emu` in-tree and `$HOME/.emu` otherwise

## Run one tick (manual)

```bash
python -m daemon.run
```

Exits 0 when there's nothing new. Honors all the path/budget guardrails
in `policy.py`.

## Install as a launchd agent (macOS)

```bash
./daemon/install.sh install     # installs/refreshes plist; idempotent
./daemon/install.sh status      # show install state
./daemon/install.sh run-now     # trigger a tick immediately
./daemon/install.sh uninstall   # remove plist + unload
```

The plist is templated at install time with the resolved `EMU_ROOT`,
`EMU_DAEMON_PROVIDER`, and the path to `daemon/launchd/run.sh`. Logs land
in `$EMU_ROOT/global/daemon/logs/`.

## Standalone install (outside emulation-agent)

```bash
pip install -e daemon/        # registers the `emu-memory-daemon` console script
export EMU_ROOT=/path/to/.emu
export EMU_DAEMON_PROVIDER=openrouter
export EMU_DAEMON_API_KEY=sk-...
emu-memory-daemon
```

## Integration contract with the Emu backend

The backend touches the daemon at exactly two points:

1. **Session index write** — when the backend creates a session it calls
   `daemon.state.record_session_in_index(session_id, date)` so the daemon
   doesn't have to rescan `sessions/`. The daemon self-heals via
   `rebuild_session_index` if this call ever fails.
2. **Shared filesystem** — both processes read/write the same `.emu/`
   tree. The daemon is the *only* writer for files in its allowlist
   (see DESIGN.md §2). The backend never writes to `MEMORY.md`,
   `AGENTS.md`, etc.

There is no IPC, no socket, no HTTP between them.
