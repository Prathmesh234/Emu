<<<<<<< HEAD
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
=======
---
name: app-launcher
description: "Open, switch between, and manage applications. Use when: user asks to open an app, switch to an app, close an app, or manage windows. Covers Windows Search/Start menu, taskbar, and app management."
---

## App Launcher

Efficiently open and manage applications using keyboard shortcuts and shell commands.

### Opening apps

**Preferred order** (fastest to slowest):
1. **Keyboard shortcut** — if the app has one (e.g., Win key for Start/Windows Search)
2. **Windows Search / Start menu** — Win key (Windows), Super key (Linux/GNOME)
   - Type the first few letters of the app name
   - Press Enter when it appears
3. **Shell command** — `Start-Process "AppName"` (Windows/PowerShell) or launch command (Linux)
4. **Taskbar click** — mouse to taskbar, click the icon (slowest)

### Switching apps

- **Alt+Tab** (Windows) / **Alt+Tab** (Linux) — cycle through open apps
- **Alt+`** (Windows) — cycle windows within same app (if supported)
- For specific windows: Alt+Tab to the app, then Alt+` to the right window

### Managing windows

| Action | Windows | Linux (GNOME) |
|--------|---------|---------------|
| Minimize | Win+Down arrow | Super+H |
| Close window | Ctrl+W | Ctrl+W or Alt+F4 |
| Quit app | Alt+F4 | Alt+F4 or Ctrl+Q |
| Fullscreen | F11 | F11 or Super+Up |
| Show desktop | Win+D | Super+D |

### Tips

- Always prefer keyboard shortcuts over mouse navigation for speed.
- When opening an app, wait 1-2 seconds for it to launch before
  taking a screenshot.
- If an app is already open, switch to it (Alt+Tab) instead of
  re-launching.
- For apps that take a while to start (e.g., IDEs), use a `wait` action
  after launching.
>>>>>>> origin/main
