# Install Emu

This file is context for a setup agent such as Claude Code, Codex, or another local coding agent. Keep the install simple, local-first, and privacy-focused. Prefer the repo scripts over hand-written commands because they already encode the expected setup flow.

## Goal

Install and run Emu on a user's laptop from this repository checkout.

Emu has two main processes:

- Backend: FastAPI server on `127.0.0.1:8000`.
- Frontend: Electron desktop app.

On macOS, Emu can also install a per-user memory daemon with launchd and use the bundled coworker driver for background app control.

## Safety Rules For Setup Agents

Follow these rules before running commands:

- Do not use `sudo` unless the user explicitly approves it.
- Do not run destructive commands such as `rm -rf`, `git reset --hard`, `git clean -fdx`, or broad permission changes.
- Do not print, upload, or summarize API keys. Keep secrets in `backend/.env` or the user's shell environment.
- Bind services to loopback only. The backend should run on `127.0.0.1`, not `0.0.0.0`.
- Ask before installing system tools with Homebrew or before running any `curl | sh` installer.
- Ask before granting macOS Accessibility or Screen Recording permissions. These are user-controlled System Settings permissions.
- Prefer the safe project scripts: `./backend.sh`, `./frontend.sh`, and `python3 -m daemon.install_macos ...`.

## Privacy Notes

Emu is designed to run locally by default:

- Backend traffic is served on `127.0.0.1:8000`.
- Session artifacts, memory, and auth tokens are stored under `.emu/` in the repo/user workspace.
- Provider API keys stay in `backend/.env` or environment variables.
- The memory daemon is a per-user LaunchAgent. It does not require sudo, Full Disk Access, Accessibility, or Screen Recording.
- The desktop app needs Accessibility and Screen Recording on macOS to inspect and control windows.
- Coworker mode uses `emu-cua-driver` to interact with target windows. It should use discovery-first workflows and avoid disrupting the user's foreground work.

## Prerequisites

Required for local development:

- macOS is recommended for full app behavior, coworker mode, permissions, and daemon install.
- Node.js 18+ with npm.
- Python 3.12+.
- `uv` Python package manager.
- Xcode Command Line Tools or Swift toolchain for building the coworker driver.

macOS helper dependency for remote desktop actions:

```bash
brew install cliclick
```

Install `uv` only after user approval if it is missing:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install Xcode Command Line Tools if Swift/build tools are missing:

```bash
xcode-select --install
```

## Step 1: Enter The Repo

Run commands from the repository root:

```bash
cd /path/to/emulation-agent
```

If this checkout uses submodules, initialize them:

```bash
git submodule update --init --recursive
```

## Step 2: Configure Provider Secrets

Create `backend/.env` if it does not exist. Add one provider key or an OpenAI-compatible endpoint.

Examples:

```bash
# Claude
ANTHROPIC_API_KEY=...

# OpenAI
OPENAI_API_KEY=...

# OpenRouter
OPENROUTER_API_KEY=...

# Gemini
GOOGLE_API_KEY=...

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_API_KEY=...

# OpenAI-compatible endpoint
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=none
```

Optional values:

```bash
EMU_PROVIDER=claude
EMU_DEV=1
USE_OMNI_PARSER=0
EMU_DAEMON_AUTO_INSTALL=1
```

Use `EMU_DAEMON_AUTO_INSTALL=0` if the user wants to opt in manually to daemon install.

## Step 3: Start Backend

Use the project script:

```bash
chmod +x backend.sh
./backend.sh
```

What this script does:

- Loads `backend/.env` if present.
- Creates `backend/.venv` with `uv venv` when needed.
- Runs `uv sync`.
- Detects the model provider from environment variables.
- Deploys Modal/OmniParser only when configured.
- Installs or refreshes the macOS memory daemon by default on macOS.
- Starts FastAPI at `http://127.0.0.1:8000`.

Manual backend fallback:

```bash
cd backend
uv venv
uv sync
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

## Step 4: Start Frontend

Open a second terminal at the repo root:

```bash
chmod +x frontend.sh
./frontend.sh
```

What this script does:

- Runs `npm install` if `node_modules` is missing.
- Starts Electron with `npm start`.

Manual frontend fallback:

```bash
npm install
npm start
```

## Step 5: macOS Permissions

For the desktop app to interact with the screen, the user may need to grant:

- Accessibility.
- Screen Recording.

Use the in-app permission card when available. Otherwise open macOS System Settings and grant permissions to Emu, Terminal, or the packaged app being used.

After changing permissions, restart the app.

## Step 6: Memory Daemon

The daemon is optional but recommended on macOS. It runs as the current user through launchd and does not need sudo.

Install or refresh:

```bash
python3 -m daemon.install_macos install
```

Check status:

```bash
python3 -m daemon.install_macos status
```

Run one tick now:

```bash
python3 -m daemon.install_macos run-now
```

Uninstall:

```bash
python3 -m daemon.install_macos uninstall
```

Daemon files and logs are under `.emu/global/daemon/`. The daemon should only read and write inside `.emu/`.

## Step 7: Coworker Driver And Packaging

For full coworker mode validation or packaged app builds, build the driver:

```bash
npm run build:driver
```

Package a local app directory:

```bash
npm run pack
```

Build release artifacts:

```bash
npm run dist
```

The packaged app expects the driver at:

```text
Emu.app/Contents/Resources/emu-cua-driver/emu-cua-driver
```

## Quick Verification

Backend is healthy when logs show the server listening on:

```text
http://127.0.0.1:8000
```

Frontend is healthy when the Electron app opens and can send a request without `401` errors.

Daemon is healthy when:

```bash
python3 -m daemon.install_macos status
```

reports an installed LaunchAgent.

Coworker driver is healthy when the app can list windows or capture a target window after permissions are granted.

## Common Fixes

If `uv` is missing, install it after user approval and restart the terminal.

If backend calls return `401`, restart both backend and frontend so they share the current `.emu/.auth_token`.

If frontend cannot connect, confirm the backend is running on `127.0.0.1:8000` and no stale backend process is active.

If macOS actions fail, grant Accessibility and Screen Recording, then restart Emu.

If the daemon refuses to install, make sure the app/repo is in a stable path and not running from a mounted DMG or app translocation path.

If Modal is selected and setup fails, run:

```bash
cd backend
uv run modal setup
```

then start the backend again.

## Minimal Agent Runbook

For a normal macOS setup agent session:

```bash
cd /path/to/emulation-agent
git submodule update --init --recursive
# create backend/.env with one provider key, without printing the key
chmod +x backend.sh frontend.sh
./backend.sh
```

Then in a second terminal:

```bash
cd /path/to/emulation-agent
./frontend.sh
```

Only run daemon, permission, driver build, or packaging commands when they are needed for the user's goal.
