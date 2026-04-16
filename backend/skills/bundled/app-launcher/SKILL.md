---
name: app-launcher
description: "Open, switch between, and manage applications. Use when: user asks to open an app, switch to an app, close an app, or manage windows. Covers Spotlight/launcher, dock, and app management."
---

## App Launcher

Efficiently open and manage applications using keyboard shortcuts and shell commands.

### Opening apps

**Preferred order** (fastest to slowest):
1. **Keyboard shortcut** — if the app has one (e.g., Cmd+Space for Spotlight)
2. **Spotlight / Launcher** — Cmd+Space (macOS), Super key (Linux/GNOME)
   - Type the first few letters of the app name
   - Press Enter when it appears
3. **Shell command** — `open -a "App Name"` (macOS) or launch command (Linux)
4. **Dock/taskbar click** — mouse to dock, click the icon (slowest)

### Switching apps

- **Cmd+Tab** (macOS) / **Alt+Tab** (Linux) — cycle through open apps
- **Cmd+`** (macOS) — cycle windows within same app
- For specific windows: Cmd+Tab to the app, then Cmd+` to the right window

### Managing windows

| Action | macOS | Linux (GNOME) |
|--------|-------|---------------|
| Minimize | Cmd+M | Super+H |
| Close window | Cmd+W | Ctrl+W or Alt+F4 |
| Quit app | Cmd+Q | Alt+F4 or Ctrl+Q |
| Fullscreen | Ctrl+Cmd+F | F11 or Super+Up |
| Show desktop | F11 or Cmd+F3 | Super+D |

### Tips

- Always prefer keyboard shortcuts over mouse navigation for speed.
- When opening an app, wait 1-2 seconds for it to launch before
  taking a screenshot.
- If an app is already open, switch to it (Cmd+Tab) instead of
  re-launching.
- For apps that take a while to start (e.g., IDEs), use a `wait` action
  after launching.
