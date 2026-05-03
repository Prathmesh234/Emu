# Emu coworker driver docs

This folder is the operator/developer knowledge base for Emu's coworker mode.
The integrated runtime uses the Emu-branded `emu-cua-driver` fork in
`frontend/coworker-mode/emu-driver/` to drive native macOS apps in the
background without stealing the user's foreground app, moving the real cursor,
or switching Spaces.

## What the skill covers

- The snapshot-before-AND-after invariant that keeps the agent honest
  about whether an action actually landed.
- The backgrounded-click recipe (yabai focus-without-raise + stamped
  SLEventPostToPid) that lets synthetic clicks land on Chrome web
  content without raising the window or pulling the user across Spaces.
- Web-app quirks (`WEB_APPS.md`) — Chromium/WebKit/Electron/Tauri,
  including the minimized-Chrome keyboard-commit caveat and the
  `set_value` workaround.
- Trajectory recording (`RECORDING.md`) — optional per-session
  recording + replay for demos and regressions.
- Canvas/viewport apps (Blender, Unity, GHOST, Qt, wxWidgets) —
  HID-tap fallback when AX is empty.

See `SKILL.md` for the main skill body and `../coworker-mode/PLAN.md` for the
current integration status.

## Prerequisites

1. **macOS 14 or newer** — the driver depends on SkyLight private SPIs
   that were stabilized in Sonoma.
2. **`emu-cua-driver` CLI + `EmuCuaDriver.app`** — build from this repo:
   ```bash
   npm run build:driver
   ```
   Or from the nested driver directly:
   ```bash
   cd frontend/coworker-mode/emu-driver
   scripts/build-app.sh debug
   ```
   The driver runs as an `.app` bundle because macOS TCC grants are
   tied to a stable bundle id (`com.emu.cuadriver`). Electron starts
   `emu-cua-driver serve --no-relaunch` and the backend/renderer call
   through that long-lived daemon path.
3. **TCC grants** — **Accessibility** and **Screen Recording** in
   System Settings → Privacy & Security. Emu shows a permission card
   with direct `Allow` links when either grant is missing.
   Verify with:
   ```bash
   frontend/coworker-mode/emu-driver/.build/EmuCuaDriver.app/Contents/MacOS/emu-cua-driver call check_permissions '{"prompt":false}'
   ```
   Both fields must be granted before real background interaction works.

## Install

The skill is two drop-in directories.

**Personal scope** (all Claude Code sessions on your machine):

```bash
mkdir -p ~/.claude/skills
cp -R frontend/coworker-mode/emu-driver/Skills/cua-driver ~/.claude/skills/emu-cua-driver
```

Or symlink if you want edits-in-place:

```bash
ln -s "$PWD/frontend/coworker-mode/emu-driver/Skills/cua-driver" ~/.claude/skills/emu-cua-driver
```

**Project scope** (committed alongside a specific repo):

```bash
mkdir -p .claude/skills
cp -R frontend/coworker-mode/emu-driver/Skills/cua-driver .claude/skills/emu-cua-driver
```

## Invoking the skill

Claude Code auto-invokes the skill when you ask for macOS GUI
automation — e.g. "open the Downloads folder in Finder", "click the
Save button in Numbers", "navigate to trycua.com in Chrome". You can
also invoke it explicitly:

```
/emu-cua-driver
```

## Files

- `SKILL.md` — the main skill body (~500 lines). Loaded on first
  invocation; stays in context for the session.
- `WEB_APPS.md` — browsers, Electron, Tauri (Chromium + WebKit). Loaded
  on demand when SKILL.md's pointer is followed.
- `RECORDING.md` — trajectory recording / replay. Loaded on demand.
- `TESTS.md` — manual test scripts for end-to-end skill verification.

## Troubleshooting

- `emu-cua-driver: command not found` → run `npm run build:driver`; packaged
  builds copy the binary to `Emu.app/Contents/Resources/emu-cua-driver/`.
- `No cached AX state for pid X window_id W` → element_index was
  reused across turns, or across different windows of the same app.
  Call `get_window_state({pid, window_id})` first in the same turn,
  with the same window_id you're about to act against.
- Empty `tree_markdown` → `capture_mode` is set to `vision`, which
  skips the AX walk by design. Flip back to the default `som`
  (`emu-cua-driver config set capture_mode som`) to get the tree.
  Tiny screenshot → likely a stale window capture. See "Behavior
  matrix" in SKILL.md for the full mode table.
- System-alert beep when pressing Return on a minimized Chrome
  omnibox → the keyboard-commit-on-minimized limitation. Use
  `set_value` on the field instead, or AX-click a Go/Submit button.
  See `WEB_APPS.md`.

## Updates

The skill evolves alongside the driver. To update an external Claude Code copy:

```bash
cd frontend/coworker-mode/emu-driver
cp -R Skills/cua-driver ~/.claude/skills/emu-cua-driver
```

## License

MIT. Same license as the parent `trycua/cua` repo.
