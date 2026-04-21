# Emu Memory Daemon — Design Document

> Status: implemented and running in production code. This document remains
> design-oriented, but the core system is now live: a launchd-driven background
> daemon that runs `python -m daemon.run` at fixed intervals (currently 120s in
> the launchd template) and curates `.emu/` memory files using strict path
> policy constraints.
>
> **Distribution model.** The daemon ships **bundled inside the Emu macOS
> app** (`.dmg`). The user never runs an install script; the first time the
> app launches it resolves the user-specific `.emu/` path, writes a plist
> templated with that path into `~/Library/LaunchAgents/`, and loads it with
> `launchctl`. Uninstall happens via the app's preferences pane, or by
> deleting the app (which triggers a bundled uninstall helper).

---

## 1. Purpose

Run the **Emu Memory Daemon** unattended on the user's Mac. Every 2 minutes it
wakes, scans `.emu/sessions/`, and curates the workspace memory files
(`AGENTS.md`, `MEMORY.md`, daily logs, etc.) per the rules in
`backend/prompts/daemon.md`.

It is the only process that writes to those files. Its blast radius MUST be
restricted to the `.emu/` directory tree. Everything in this design is built
around that single security invariant.

---

## 2. Threat Model & Security Invariants

The daemon hosts an LLM that is given tool calls. The LLM is *adversarial* for
the purpose of design — it could be steered by prompt injection inside a
session transcript (which itself contains arbitrary user/agent text, and
could contain attacker-controlled content if the user ever pasted hostile
data).

We therefore enforce **defense in depth**:

| Layer | Mechanism | Stops |
|---|---|---|
| L1: Tool surface | Only `read_file`, `write_file`, `list_dir`, `finish` exposed. **No shell, no exec, no network tool.** | Arbitrary code execution by the LLM |
| L2: Path policy | Every path argument is resolved with `os.path.realpath` and must start with the runtime-resolved `EMU_ROOT`. Symlinks pointing outside `.emu/` are rejected. Denylist for `SOUL.md` and dotfiles. | Path traversal, symlink escape, writes to forbidden files |
| L3: Process hygiene | Single-instance via `flock`, bounded turns / tokens per tick, consecutive-failure gate, logs to `.emu/global/daemon/logs/`. | Runaway loops, concurrent runs corrupting files |

### Non-goals
- We do **not** sandbox against the user themselves — they own the machine.
- We do **not** try to defend against a compromised Python interpreter.
- We do **not** expose the daemon to remote callers — no HTTP, no IPC socket.

### Hard rules
- **No shell tool.** Ever. The LLM cannot spawn processes.
- **No network tool.** The only network egress is the model provider's API,
  made by the daemon itself, not by the model.
- **No write to `SOUL.md`.** Hardcoded in tool layer (L2).
- **No write outside `.emu/workspace/` + `.emu/global/daemon/`.** All other
  writes rejected.
- **Read scope ⊇ write scope.** Read allowed anywhere in `.emu/`, write only
  in the allowlist below.

### Write allowlist (L2, paths relative to `EMU_ROOT`)
```
workspace/AGENTS.md
workspace/MEMORY.md
workspace/USER.md
workspace/IDENTITY.md
workspace/memory/YYYY-MM-DD.md            # date-format validated
global/daemon/state.json                  # processed-session bookkeeping
global/daemon/logs/*                      # rotating logs
```

Any write outside this list returns a structured error to the model and is
recorded in the audit log. We do **not** silently allow.

---

## 3. Runtime Topology

The daemon runs out-of-process via macOS launchd. It is intentionally decoupled
from FastAPI backend uptime so memory curation can continue while backend is
offline.

```
┌───────────────────────────────────────────────────────────────────────┐
│ launchd (user LaunchAgent)                                            │
│   StartInterval=120                                                    │
│   ProgramArguments -> daemon/launchd/run.sh                            │
└─────────────────────────────┬─────────────────────────────────────────┘
                              │ exec
                              ▼
┌───────────────────────────────────────────────────────────────────────┐
│ daemon.run.main()   (one tick — no persistent process)                │
│   1. resolve EMU_ROOT (env var, else <repo>/.emu)                     │
│   2. acquire flock($EMU_ROOT/global/daemon/.tick.lock)                │
│   3. load processed-session state                                     │
│   4. inventory $EMU_ROOT/sessions/, filter UNPROCESSED only           │
│      (incremental always — no backfill)                               │
│   5. if nothing new → return 0                                        │
│   6. build prompt = DAEMON_PROMPT + INPUT manifest                    │
│   7. agent loop (≤ MAX_TURNS, ≤ MAX_TOKENS)                           │
│        ├─ tool: read_file(path)   [L2 enforced]                       │
│        ├─ tool: write_file(path, content)   [L2 + size cap enforced]  │
│        ├─ tool: list_dir(path)                                        │
│        └─ tool: finish(summary)                                       │
│   8. post-pass: re-validate every target path before writing          │
│   9. mark processed sessions in state.json                            │
│  10. release lock, return                                             │
└───────────────────────────────────────────────────────────────────────┘
```

Two independent path enforcement points: the tool dispatcher (L2) and a final
post-pass before the daemon commits to disk.

Lifecycle note: launchd controls daemon invocation cadence independently.

---

## 4. File Layout

```
daemon/
├── DESIGN.md       ← this document
├── __init__.py
├── run.py          ← entrypoint (main() = one tick; called by backend lifespan)
├── prompt.py       ← DAEMON_PROMPT string (embedded)
├── tools.py        ← read_file / write_file / list_dir
├── policy.py       ← path resolution + allowlist checks
├── state.py        ← processed-session tracker
└── llm_client.py   ← thin wrapper over backend/providers
```

At app **first launch**, the app does:
1. Resolve `EMU_ROOT` from user preferences (default `$HOME/.emu`).
2. Template the plist and sandbox profile, substituting the real paths.
3. Write templated plist to `~/Library/LaunchAgents/com.emu.memory-daemon.plist`.
4. `launchctl load` it.

This avoids the hardcoded `/Users/prathmeshbhatt/...` paths from the earlier
draft — the app knows each user's path at runtime.

---

## 5. The launchd plist (template)

`daemon/launchd/com.emu.memory-daemon.plist.template`

Placeholders `{{HOME}}`, `{{EMU_ROOT}}`, `{{APP_BUNDLE}}` are substituted by
the Emu app at install time.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.emu.memory-daemon</string>

    <!-- Every 2 minutes. launchd coalesces missed ticks across sleep. -->
    <key>StartInterval</key>
    <integer>120</integer>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/sandbox-exec</string>
        <string>-f</string>
        <string>{{APP_BUNDLE}}/Contents/Resources/daemon/sandbox/emu-daemon.sb</string>
        <string>{{APP_BUNDLE}}/Contents/Resources/daemon/python</string>
        <string>-m</string>
        <string>daemon.run</string>
    </array>

    <!-- Pass the user's resolved paths + provider choice into the child env.
         The API key is read from the user's keychain by the daemon itself;
         never embed it here. -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>EMU_ROOT</key>                 <string>{{EMU_ROOT}}</string>
        <key>EMU_DAEMON_PROVIDER</key>      <string>{{PROVIDER}}</string>
        <key>HOME</key>                     <string>{{HOME}}</string>
    </dict>

    <key>WorkingDirectory</key>
    <string>{{APP_BUNDLE}}/Contents/Resources/daemon</string>

    <!-- Never run as root. -->
    <key>Nice</key>                  <integer>5</integer>
    <key>LowPriorityIO</key>         <true/>
    <key>ProcessType</key>           <string>Background</string>

    <!-- Do not auto-restart; every 5 min is restart enough. -->
    <key>KeepAlive</key>             <false/>
    <key>RunAtLoad</key>             <false/>
    <key>AbandonProcessGroup</key>   <false/>

    <key>StandardOutPath</key>       <string>{{EMU_ROOT}}/global/daemon/logs/stdout.log</string>
    <key>StandardErrorPath</key>     <string>{{EMU_ROOT}}/global/daemon/logs/stderr.log</string>

    <key>HardResourceLimits</key>
    <dict>
        <key>CPU</key>               <integer>180</integer>
    </dict>
</dict>
</plist>
```

Notes:
- `StartInterval=120` handles sleep/wake more gracefully than calendar intervals.
- `RunAtLoad=false` — fire on the next 5-min tick, not on install.
- `KeepAlive=false` — don't respawn a crash loop tightly.
- `EnvironmentVariables` carries `EMU_ROOT` and `EMU_DAEMON_PROVIDER`. The
  **API key is not in the plist**; the daemon fetches it from Keychain (see §8).

---

## 6. The sandbox-exec profile (template)

`daemon/sandbox/emu-daemon.sb.template` — `{{EMU_ROOT}}`, `{{APP_BUNDLE}}`, `{{HOME}}`
substituted at install time.

```scheme
(version 1)
(deny default)

;; --- Required for python to start at all ---
(allow process-fork)
(allow process-exec
    (subpath "/usr/bin")
    (subpath "/bin")
    (subpath "/usr/local/bin")
    (subpath "/opt/homebrew")
    (subpath "{{APP_BUNDLE}}/Contents/Resources/daemon"))

(allow file-read*
    (subpath "/usr/lib")
    (subpath "/usr/share")
    (subpath "/System")
    (subpath "/Library/Frameworks")
    (subpath "/private/etc")
    (subpath "/opt/homebrew")
    (subpath "{{APP_BUNDLE}}")
    (subpath "{{HOME}}/Library/Caches"))

;; --- The ONLY writable region: the user's .emu directory ---
(allow file-write*
    (subpath "{{EMU_ROOT}}"))
(allow file-read*
    (subpath "{{EMU_ROOT}}"))

;; --- Network: outbound HTTPS for any provider ---
;; Provider endpoints span many hosts (Anthropic, OpenAI, Gemini, Bedrock,
;; OpenRouter, Fireworks, Together, Baseten, Modal, h_company, Azure). We
;; cannot enumerate them statically without breaking when endpoints move,
;; so we allow all outbound 443 and trust the daemon layer to only talk to
;; the configured provider host. DNS + TLS require the supporting syscalls.
(allow network-outbound
    (remote tcp "*:443")
    (remote udp "*:53"))      ;; DNS
(allow network-bind (local ip "localhost:*"))
(allow system-socket)
(allow mach-lookup)
(allow sysctl-read)
(allow iokit-open)
```

Key property: even if the LLM somehow induced the tool layer to misbehave and
called `os.system("rm -rf ~/Documents")`, the sandbox would deny
`process-exec` outside whitelisted paths and deny `file-write*` outside
`.emu/`. Two independent failures must occur for damage to escape `.emu/`.

We deliberately do **not** allow writes to `~/Library/LaunchAgents/`, so the
daemon cannot rewrite its own plist.

---

## 7. Tool surface exposed to the LLM

Only four tools. No "shell" or "python" tool.

```python
# daemon/tools.py — sketch

TOOLS = [
    {
        "name": "list_dir",
        "description": "List files in a directory under .emu/ (read-only).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file under .emu/.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write a UTF-8 text file. Allowed targets: workspace/AGENTS.md, "
            "workspace/MEMORY.md, workspace/USER.md, workspace/IDENTITY.md, "
            "workspace/memory/YYYY-MM-DD.md. SOUL.md is forbidden."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "finish",
        "description": "Signal that the curation pass is complete.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]
```

### Size control (soft, not schema-level)

We removed the hard `maxLength: 200_000` from the `content` property — the
LLM should not be bounded by a rigid JSON-schema limit. Instead we enforce a
**total write budget per tick**, checked in the dispatcher:

```python
# daemon/tools.py — sketch

MAX_PER_FILE_BYTES   = 512 * 1024        # single write cap — sanity
MAX_TOTAL_BYTES_TICK = 2 * 1024 * 1024   # sum of all writes in one tick
```

If a single write exceeds `MAX_PER_FILE_BYTES` or the cumulative total for
the tick exceeds `MAX_TOTAL_BYTES_TICK`, the tool returns a structured error
to the model (which may then choose to trim) and the event is logged.
These numbers are generous for the use case (MEMORY.md is ~3k chars by spec)
while still preventing unbounded writes from runaway generations.

### Path enforcement (policy.py)

`EMU_ROOT` is **runtime-resolved**, never hardcoded:

```python
# daemon/policy.py — sketch

import os, re
from pathlib import Path

def _resolve_emu_root() -> Path:
    raw = os.environ.get("EMU_ROOT") or str(Path.home() / ".emu")
    root = Path(raw).expanduser().resolve(strict=True)
    return root

EMU_ROOT = _resolve_emu_root()

WRITE_ALLOWLIST_FILES = {
    "workspace/AGENTS.md",
    "workspace/MEMORY.md",
    "workspace/USER.md",
    "workspace/IDENTITY.md",
}
WRITE_ALLOWLIST_PREFIXES = (
    "workspace/memory/",
    "global/daemon/",
)
DAILY_LOG_RE = re.compile(r"^workspace/memory/\d{4}-\d{2}-\d{2}\.md$")
FORBIDDEN_FILES = {"workspace/SOUL.md"}

class PolicyError(Exception): pass

def _resolve_inside_emu(raw: str) -> Path:
    if "\x00" in raw:
        raise PolicyError("null byte in path")
    candidate = (EMU_ROOT / raw.lstrip("/")).resolve(strict=False)
    try:
        candidate.relative_to(EMU_ROOT)
    except ValueError:
        raise PolicyError(f"path escapes .emu/: {raw}")
    return candidate

def check_read(raw: str) -> Path:
    return _resolve_inside_emu(raw)

def check_write(raw: str) -> Path:
    resolved = _resolve_inside_emu(raw)
    rel = str(resolved.relative_to(EMU_ROOT))
    if rel in FORBIDDEN_FILES:
        raise PolicyError("write to SOUL.md is forbidden")
    if rel in WRITE_ALLOWLIST_FILES:
        return resolved
    if any(rel.startswith(p) for p in WRITE_ALLOWLIST_PREFIXES):
        if rel.startswith("workspace/memory/") and not DAILY_LOG_RE.match(rel):
            raise PolicyError(f"invalid daily-log filename: {rel}")
        return resolved
    raise PolicyError(f"write target not in allowlist: {rel}")
```

`check_write` is called both inside the `write_file` tool **and** in the
post-pass after the agent finishes.

---

## 8. The agent loop

`daemon/run.py` — sketch:

```python
# NOTE: For now the daemon runs the single fixed DAEMON_PROMPT. In the future
# we may support attached "skills" per Hermes's model (extra prompt fragments
# injected into the session). The agent loop is structured so that plugging
# in skills later is an additive change — see `build_system_prompt()` below.

import fcntl, os, sys
from pathlib import Path
from daemon import tools, policy, state, llm_client
from daemon.prompt import DAEMON_PROMPT      # inline string, embedded at build

MAX_TURNS  = 24
MAX_TOKENS = 120_000

def build_system_prompt() -> str:
    # Hook: if/when skills land, concatenate their bodies here.
    return DAEMON_PROMPT

def main() -> int:
    lock_path = policy.EMU_ROOT / "global" / "daemon" / ".tick.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("[daemon] previous tick still running; skipping")
            return 0

        unprocessed = state.list_unprocessed_sessions()   # incremental only
        if not unprocessed:
            print("[daemon] no new sessions; idle")
            return 0

        result = llm_client.run_agent_loop(
            system=build_system_prompt(),
            user=state.build_input_manifest(unprocessed),
            tools=tools.TOOLS,
            tool_dispatcher=tools.dispatch,       # enforces L2 + size caps
            max_turns=MAX_TURNS,
            max_total_tokens=MAX_TOKENS,
        )

        for written_path in result.written_paths:
            policy.check_write(str(written_path.relative_to(policy.EMU_ROOT)))

        state.mark_processed(unprocessed, run_id=result.run_id)
        return 0

if __name__ == "__main__":
    sys.exit(main())
```

Limits:
- **MAX_TURNS = 24** — prompt is a 6-step procedure; 24 is plenty, bounds runaway loops.
- **MAX_TOKENS = 120k** — caps API spend per tick.
- **flock** ensures one tick at a time even if launchd misfires.

### Provider + API key

The daemon uses the existing `backend/providers/` registry. Two env vars
control which provider and key are used; both are set from the app's UI and
written into the user's `.env` (and documented in `.env.example`):

| Variable              | Purpose                                          |
|-----------------------|--------------------------------------------------|
| `EMU_DAEMON_PROVIDER` | Name of a provider in `backend/providers/` (e.g. `claude`, `openai`, `openrouter`, `gemini`, `bedrock`, `fireworks`, `together_ai`, `baseten`, `modal`, `h_company`, `azure_openai`). |
| `EMU_DAEMON_API_KEY`  | API key for that provider. Stored in macOS Keychain when possible; env var is the fallback path that the `.env` sets. |

`llm_client.py` reads `EMU_DAEMON_PROVIDER`, looks the provider up in the
existing registry, and constructs the client — no per-provider daemon code.

### Where the API key lives (preference order)
1. macOS Keychain (`security find-generic-password -s com.emu.memory-daemon`).
2. Env var `EMU_DAEMON_API_KEY` (set by the app via `.env`).
3. Refuse to start if neither present — log to stderr and exit 0.

The key is never written to disk by the daemon and never logged.

### `.env.example` additions

```dotenv
# Memory daemon (required for the .emu/ background curator to run)
EMU_DAEMON_PROVIDER=claude
EMU_DAEMON_API_KEY=
```

---

## 9. Idempotency & state

`$EMU_ROOT/global/daemon/state.json` — owned exclusively by the daemon:

```json
{
  "version": 1,
  "processed_sessions": {
    "7a6ecd05-1ec7-44ad-af8a-f2c079f6b443": {
      "processed_at": "2026-04-17T10:25:00Z",
      "run_id": "tick-2026-04-17T10-25-00Z"
    }
  },
  "last_tick_at": "2026-04-17T10:25:00Z",
  "consecutive_failures": 0
}
```

Behavior:
- A session is "unprocessed" if its folder exists in `$EMU_ROOT/sessions/`
  and its ID is not in `processed_sessions`.
- **Incremental only.** No backfill pass, even on first tick after install —
  the daemon will only ever process sessions created after it is running.
- After a successful tick, all sessions seen this run are marked processed.
- We **do not** delete session folders — that's the user's job.
- If `consecutive_failures >= 5`, the daemon writes one line to `stderr.log`
  and exits 0 (do not nag the user; they can inspect logs).

---

## 10. Observability

Every tick writes one structured log line to
`$EMU_ROOT/global/daemon/logs/tick.jsonl`:

```json
{"ts":"2026-04-17T10:25:00Z","run_id":"...","sessions_seen":3,"sessions_new":1,
 "turns":7,"tokens_in":4210,"tokens_out":812,"files_written":["workspace/MEMORY.md"],
 "policy_violations":0,"status":"ok"}
```

`policy_violations` must be **0** on healthy runs. Any non-zero indicates the
model attempted something blocked — worth investigating.

The daemon also prints `[daemon]` status lines to stderr (the backend's
terminal) when a tick processes sessions or raises an exception.

---

## 11. Install / Uninstall (app-driven, no user scripts)

The daemon is **packaged inside the Emu `.dmg`**. Users do not run install
shell scripts. Instead:

### On first app launch
The Electron/main process of the Emu app performs the following, after the
user signs in and picks their `.emu` location:

```js
// main.js — sketch (pseudocode)
async function installMemoryDaemon({ emuRoot, provider }) {
  const home = os.homedir();
  const appBundle = path.dirname(path.dirname(app.getAppPath()));   // .app/

  const plistTemplate = await fs.readFile(
    path.join(appBundle, 'Contents/Resources/daemon/launchd/com.emu.memory-daemon.plist.template'),
    'utf8');
  const sbTemplate = await fs.readFile(
    path.join(appBundle, 'Contents/Resources/daemon/sandbox/emu-daemon.sb.template'),
    'utf8');

  const subst = s => s
    .replaceAll('{{HOME}}',        home)
    .replaceAll('{{EMU_ROOT}}',    emuRoot)
    .replaceAll('{{APP_BUNDLE}}',  appBundle)
    .replaceAll('{{PROVIDER}}',    provider);

  await fs.mkdir(path.join(emuRoot, 'global/daemon/logs'), { recursive: true });

  const rendered = path.join(appBundle, 'Contents/Resources/daemon/sandbox/emu-daemon.sb');
  await fs.writeFile(rendered, subst(sbTemplate));

  const plistDst = path.join(home, 'Library/LaunchAgents/com.emu.memory-daemon.plist');
  await fs.writeFile(plistDst, subst(plistTemplate), { mode: 0o644 });

  await execFile('launchctl', ['unload', plistDst]).catch(() => {});
  await execFile('launchctl', ['load',   plistDst]);
}
```

### On uninstall / disable (preferences pane)
```js
async function uninstallMemoryDaemon() {
  const plistDst = path.join(os.homedir(), 'Library/LaunchAgents/com.emu.memory-daemon.plist');
  await execFile('launchctl', ['unload', plistDst]).catch(() => {});
  await fs.rm(plistDst, { force: true });
}
```

### On app update
The app re-runs `installMemoryDaemon` to refresh the plist (paths inside the
`.app` bundle may change across versions). The plist label stays the same, so
`launchctl unload && load` cleanly hot-swaps.

The user sees a single checkbox in preferences: **"Run memory daemon in
background every 2 minutes."** That toggle calls install/uninstall above.

---

## 12. Open questions / confirmed decisions

| # | Item | Decision |
|---|---|---|
| 1 | Provider | All providers in `backend/providers/` available; user picks via `EMU_DAEMON_PROVIDER` env var. |
| 2 | API key location | `EMU_DAEMON_API_KEY` in `.env`/`.env.example`; Keychain optional upgrade path. |
| 3 | Daily-log timezone | Local time, logged explicitly next to each write. |
| 4 | First-tick backfill | **None.** Incremental only from install forward. |
| 5 | Skill-style injection | Not now. `build_system_prompt()` left as the hook point (see note atop `run.py`). |
| 6 | CPU ceiling | Keep `HardResourceLimits.CPU = 180` seconds. |

---

## 13. Implementation order (when we're ready to build)

1. `policy.py` + unit tests (path traversal, symlink escape, allowlist).
2. `tools.py` + dispatcher with policy + size-cap enforcement.
3. `state.py` + idempotency tests (incremental-only semantics).
4. `prompt.py` (embedded `DAEMON_PROMPT` string).
5. `llm_client.py` thin wrapper reading `EMU_DAEMON_PROVIDER` from env.
6. `run.py` glue.
7. Sandbox profile template; test manually under `sandbox-exec` first.
8. Plist template + Electron install/uninstall helpers in `main.js`.
9. Preferences-pane toggle in the frontend.
10. Run for a week in-app; review `tick.jsonl` for `policy_violations > 0`.

Until step 10 reports clean for a week, do not consider this production.
