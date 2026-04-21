"""
install_macos.py — User-space launchd installer for the Emu Memory Daemon.

Why: without OS scheduling the daemon only ticks while the backend is alive.
With this installed, macOS's launchd fires `daemon/launchd/run.sh` every
120s regardless of whether `backend.sh` is running.

Subcommands:
  install         — render plist, write to ~/Library/LaunchAgents, bootstrap it
  uninstall       — bootout + delete plist (leaves .emu/ data alone)
  status          — show launchctl state + last tick from tick.jsonl
  run-now         — kickstart one tick immediately (doesn't reset the timer)
  prompt-install  — interactive y/N/never prompt; called by backend.sh
                    on first run. Respects an install-state marker so it
                    never nags twice.

No sudo required: LaunchAgents live under the user's home and run as that
user when they're logged in.
"""

from __future__ import annotations

import os
import platform
import plistlib
import subprocess
import sys
from pathlib import Path


LABEL = "com.emu.memory-daemon"

# Using platform.system() rather than sys.platform so Pylance doesn't flag
# the macOS-only branches as "unreachable" when this file is edited on
# Windows/Linux — sys.platform is a type-narrowing literal in Pyright.
_IS_MACOS = platform.system() == "Darwin"

_DAEMON_DIR = Path(__file__).resolve().parent
_REPO_DIR = _DAEMON_DIR.parent
_TEMPLATE = _DAEMON_DIR / "launchd" / f"{LABEL}.plist.template"
_PLIST_TARGET = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
_TRANSLOCATION_MARKER = "/AppTranslocation/"


def _emu_root() -> Path:
    raw = os.environ.get("EMU_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_REPO_DIR / ".emu").resolve()


def _marker_path() -> Path:
    return _emu_root() / "global" / "daemon" / ".install_state"


def _current_anchor_path() -> Path:
    """Path the launch agent will anchor to.

    In the current dev/source layout this is the repository root. When we bundle
    the daemon inside the Electron app later, this should become the app's
    stable Resources directory instead.
    """
    return _REPO_DIR.resolve()


def _is_translocated(path: Path) -> bool:
    return _TRANSLOCATION_MARKER in str(path)


def _is_from_mounted_image(path: Path) -> bool:
    parts = path.parts
    return len(parts) >= 2 and parts[1] == "Volumes"


def _install_preflight_error() -> str | None:
    """Reject installs from transient locations that produce stale plist paths."""
    anchor = _current_anchor_path()

    if _is_translocated(anchor):
        return (
            "app is running from a translocated read-only path. Move Emu to a stable "
            "location like /Applications (packaged app) or a normal folder (source checkout), "
            "then launch it again before installing the daemon."
        )

    if _is_from_mounted_image(anchor):
        return (
            "app is running from a mounted disk image under /Volumes. Drag it to /Applications "
            "first, then launch it from there before installing the daemon."
        )

    return None


def _render() -> str:
    template = _TEMPLATE.read_text(encoding="utf-8")
    emu_root = _emu_root()
    emu_root.mkdir(parents=True, exist_ok=True)
    (emu_root / "global" / "daemon" / "logs").mkdir(parents=True, exist_ok=True)
    return (
        template
        .replace("{{REPO}}", str(_REPO_DIR))
        .replace("{{EMU_ROOT}}", str(emu_root))
        .replace("{{HOME}}", str(Path.home()))
    )


def _current_plist_text() -> str:
    return _PLIST_TARGET.read_text(encoding="utf-8") if _PLIST_TARGET.exists() else ""


def _plist_is_current(rendered: str) -> bool:
    return _PLIST_TARGET.exists() and _current_plist_text() == rendered


def _uid() -> int:
    return os.getuid()


def _launchctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _is_loaded() -> bool:
    res = _launchctl("print", f"gui/{_uid()}/{LABEL}")
    return res.returncode == 0


# ── Commands ─────────────────────────────────────────────────────────────────

def install() -> int:
    if not _IS_MACOS:
        print(f"[install_macos] this installer only supports macOS (current: {platform.system()})")
        return 2

    preflight_error = _install_preflight_error()
    if preflight_error:
        print(f"[install_macos] refusing install: {preflight_error}", file=sys.stderr)
        return 1

    # Make sure the wrapper is executable (git may preserve this; belt-and-suspenders).
    wrapper = _DAEMON_DIR / "launchd" / "run.sh"
    if wrapper.exists():
        wrapper.chmod(wrapper.stat().st_mode | 0o111)

    _PLIST_TARGET.parent.mkdir(parents=True, exist_ok=True)

    # Validate rendered plist is parseable before we hand it to launchd.
    rendered = _render()
    try:
        plistlib.loads(rendered.encode("utf-8"))
    except Exception as exc:
        print(f"[install_macos] rendered plist is invalid: {exc}", file=sys.stderr)
        return 1

    if _is_loaded() and _plist_is_current(rendered):
        _marker_path().parent.mkdir(parents=True, exist_ok=True)
        _marker_path().write_text("installed\n", encoding="utf-8")
        print(f"[install_macos] already loaded and current: {_PLIST_TARGET}")
        return 0

    # If already loaded, bootout first so we pick up any template changes.
    if _is_loaded():
        _launchctl("bootout", f"gui/{_uid()}/{LABEL}")

    _PLIST_TARGET.write_text(rendered, encoding="utf-8")
    print(f"[install_macos] wrote {_PLIST_TARGET}")

    res = _launchctl("bootstrap", f"gui/{_uid()}", str(_PLIST_TARGET))
    if res.returncode != 0:
        print(f"[install_macos] launchctl bootstrap failed:\n{res.stderr}", file=sys.stderr)
        return res.returncode

    _marker_path().parent.mkdir(parents=True, exist_ok=True)
    _marker_path().write_text("installed\n", encoding="utf-8")
    print(f"[install_macos] loaded as {LABEL} — first tick within 2 minutes")
    print(f"[install_macos] logs: {_emu_root()}/global/daemon/logs/")
    return 0


def uninstall() -> int:
    if not _IS_MACOS:
        print("[install_macos] not macOS; nothing to do")
        return 0

    if _is_loaded():
        res = _launchctl("bootout", f"gui/{_uid()}/{LABEL}")
        if res.returncode != 0:
            # Non-fatal: we still want to remove the plist file.
            print(f"[install_macos] bootout warning: {res.stderr.strip()}", file=sys.stderr)

    if _PLIST_TARGET.exists():
        _PLIST_TARGET.unlink()
        print(f"[install_macos] removed {_PLIST_TARGET}")

    # Leave EMU_ROOT data alone, but clear the install marker so
    # backend.sh's prompt works again.
    marker = _marker_path()
    if marker.exists():
        marker.unlink()

    print("[install_macos] uninstalled")
    return 0


def status() -> int:
    if not _IS_MACOS:
        print("[install_macos] not macOS")
        return 0

    preflight_error = _install_preflight_error()

    print(f"Label:   {LABEL}")
    print(f"Plist:   {_PLIST_TARGET}  {'(present)' if _PLIST_TARGET.exists() else '(missing)'}")
    print(f"Loaded:  {_is_loaded()}")
    print(f"Anchor:  {_current_anchor_path()}")
    if preflight_error:
        print(f"Stable:  no ({preflight_error})")
    else:
        print("Stable:  yes")

    if _PLIST_TARGET.exists():
        rendered = _render()
        print(f"Current: {_plist_is_current(rendered)}")

    if _is_loaded():
        res = _launchctl("print", f"gui/{_uid()}/{LABEL}")
        # Print the whole block; it's the canonical launchd truth.
        print("\n--- launchctl print ---")
        print(res.stdout)

    tick_log = _emu_root() / "global" / "daemon" / "logs" / "tick.jsonl"
    if tick_log.exists():
        print("\n--- last 3 ticks (tick.jsonl) ---")
        # Tail without shelling out.
        lines = tick_log.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-3:]:
            print(line)
    else:
        print(f"\n(no tick log yet at {tick_log})")
    return 0


def run_now() -> int:
    if not _is_loaded():
        print("[install_macos] daemon not loaded; run `install` first", file=sys.stderr)
        return 1
    res = _launchctl("kickstart", "-k", f"gui/{_uid()}/{LABEL}")
    if res.returncode != 0:
        print(f"[install_macos] kickstart failed:\n{res.stderr}", file=sys.stderr)
        return res.returncode
    print("[install_macos] kicked off one tick")
    return 0


def prompt_install() -> int:
    """Interactive first-run flow called by backend.sh. Exits quietly in non-TTY."""
    if not _IS_MACOS:
        return 0

    # Non-interactive shells (CI, nohup) shouldn't block on input.
    if not sys.stdin.isatty():
        return 0

    if _PLIST_TARGET.exists():
        rendered = _render()
        if _plist_is_current(rendered):
            return 0  # already installed and points at the current location

        bar = "─" * 60
        print(bar)
        print("  Emu Memory Daemon")
        print(bar)
        print("  The existing daemon install points at an older location.")
        print("  Emu can repair it now so background ticks follow the current app.")
        print(bar)
        try:
            answer = input("  Repair daemon install now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if answer in ("", "y", "yes"):
            return install()
        print("  Skipped. Background daemon may still point at the old app location.")
        return 0

    preflight_error = _install_preflight_error()
    if preflight_error:
        print(f"[install_macos] skipping prompt: {preflight_error}")
        return 0

    marker = _marker_path()
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == "declined":
        return 0  # user said never

    bar = "─" * 60
    print(bar)
    print("  Emu Memory Daemon")
    print(bar)
    print("  Run a small background process every 2 minutes that")
    print("  consolidates your session memory into MEMORY.md and")
    print("  daily logs. It keeps running even when the backend is")
    print("  shut down (via macOS launchd, no sudo required).")
    print()
    print("  Scope: reads/writes only inside .emu/")
    print("  Logs:  .emu/global/daemon/logs/tick.jsonl")
    print(bar)
    try:
        answer = input("  Install now? [y/N/never] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0

    if answer in ("y", "yes"):
        return install()
    if answer == "never":
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("declined\n", encoding="utf-8")
        print("  OK — won't ask again. `python -m daemon.install_macos install` to opt in later.")
        return 0

    print("  Skipped. Will ask again next ./backend.sh run.")
    return 0


# ── Dispatch ─────────────────────────────────────────────────────────────────

_COMMANDS = {
    "install":        install,
    "uninstall":      uninstall,
    "status":         status,
    "run-now":        run_now,
    "prompt-install": prompt_install,
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in _COMMANDS:
        print("usage: python -m daemon.install_macos {install|uninstall|status|run-now|prompt-install}")
        return 2
    return _COMMANDS[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
