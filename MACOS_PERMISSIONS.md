# macOS Permissions for Emu

This is the permission flow for the packaged `.dmg` app. Users should drag Emu into `/Applications`, launch it from there, and grant the macOS permissions below when prompted.

## Required Permissions

### Screen Recording

Emu needs Screen Recording so the Electron app can capture the current display and send screenshots to the local agent backend.

Grant it in:

```text
System Settings -> Privacy & Security -> Screen Recording -> Emu
```

After enabling it, quit and reopen Emu. macOS usually requires a restart of the app before screen capture works.

### Accessibility

Emu needs Accessibility so it can move the mouse, click, scroll, type, and send keyboard shortcuts on behalf of the user.

Grant it in:

```text
System Settings -> Privacy & Security -> Accessibility -> Emu
```

If actions fail silently, remove Emu from the list, add it again, then quit and reopen Emu.

## Memory Daemon

The memory daemon is installed as a per-user LaunchAgent. It does not require sudo, Full Disk Access, Screen Recording, or Accessibility.

What it does:

- Runs in the background on a fixed launchd interval.
- Reads and writes only inside Emu's `.emu/` data directory.
- Consolidates session history into memory files and daily logs.
- Trims old daemon logs and prunes stale session folders.

Where macOS installs it:

```text
~/Library/LaunchAgents/com.emu.memory-daemon.plist
```

Useful commands:

```bash
python3 -m daemon.install_macos status
python3 -m daemon.install_macos run-now
python3 -m daemon.install_macos uninstall
```

## First Launch Checklist

1. Drag Emu from the `.dmg` into `/Applications`.
2. Launch Emu from `/Applications`, not directly from the mounted disk image.
3. Grant Screen Recording when prompted.
4. Grant Accessibility when prompted or when the first action fails.
5. Quit and reopen Emu after changing either permission.
6. Confirm the backend is healthy and the daemon is installed from Emu settings or with the status command above.

## Notes for Packaging

- The daemon LaunchAgent must point at a stable app location. Do not install it while Emu is running from `/Volumes` or an App Translocation path.
- The packaged app should install or repair the LaunchAgent after the app is already in `/Applications`.
- The daemon only needs file access to `.emu/`; desktop control permissions belong to the Electron app, not the daemon.
- Packaged daemon auto-install is feature-flagged with `PACKAGED_MODE`. The default is `PACKAGED_MODE=0`, so packaged builds skip auto-install until the frozen daemon runtime is included. Set `PACKAGED_MODE=1` to enable packaged LaunchAgent install/repair from the app Resources directory.