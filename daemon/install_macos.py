"""
install_macos.py — User-space launchd installer for Emu daemons.

Why: without OS scheduling the memory daemon only ticks while the backend is
alive, and the coworker driver daemon has to be parented by the app process.
With this installed, launchd manages both the periodic memory daemon and the
long-running emu-cua-driver daemon through one install/repair command.

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


MEMORY_LABEL = "com.emu.memory-daemon"
DRIVER_LABEL = "com.emu.emu-cua-driver"
SERVICE_LABELS = (MEMORY_LABEL, DRIVER_LABEL)

# Backwards-compatible default for older call sites that imported LABEL.
LABEL = MEMORY_LABEL

# Using platform.system() rather than sys.platform so Pylance doesn't flag
# the macOS-only branches as "unreachable" when this file is edited on
# Windows/Linux — sys.platform is a type-narrowing literal in Pyright.
_IS_MACOS = platform.system() == "Darwin"

_DAEMON_DIR = Path(__file__).resolve().parent
_REPO_DIR = _DAEMON_DIR.parent
_TEMPLATES = {
    MEMORY_LABEL: _DAEMON_DIR / "launchd" / f"{MEMORY_LABEL}.plist.template",
    DRIVER_LABEL: _DAEMON_DIR / "launchd" / f"{DRIVER_LABEL}.plist.template",
}
_PLIST_TARGETS = {
    MEMORY_LABEL: Path.home() / "Library" / "LaunchAgents" / f"{MEMORY_LABEL}.plist",
    DRIVER_LABEL: Path.home() / "Library" / "LaunchAgents" / f"{DRIVER_LABEL}.plist",
}
_PLIST_TARGET = _PLIST_TARGETS[MEMORY_LABEL]
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


def _driver_binary_path() -> Path | None:
    """Resolve the emu-cua-driver binary without touching the nested source."""
    candidates: list[Path] = []
    override = os.environ.get("EMU_CUA_DRIVER_BIN", "").strip()
    if override:
        candidates.append(Path(override).expanduser())

    candidates.extend([
        _REPO_DIR
        / "frontend"
        / "coworker-mode"
        / "emu-driver"
        / ".build"
        / "EmuCuaDriver.app"
        / "Contents"
        / "MacOS"
        / "emu-cua-driver",
        Path.home() / ".local" / "bin" / "emu-cua-driver",
        Path("/Applications/EmuCuaDriver.app/Contents/MacOS/emu-cua-driver"),
    ])

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


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


def _render(label: str = MEMORY_LABEL) -> str:
    template = _TEMPLATES[label].read_text(encoding="utf-8")
    emu_root = _emu_root()
    emu_root.mkdir(parents=True, exist_ok=True)
    (emu_root / "global" / "daemon" / "logs").mkdir(parents=True, exist_ok=True)
    rendered = (
        template
        .replace("{{REPO}}", str(_REPO_DIR))
        .replace("{{EMU_ROOT}}", str(emu_root))
        .replace("{{HOME}}", str(Path.home()))
    )
    if label == DRIVER_LABEL:
        driver_bin = _driver_binary_path()
        if driver_bin is None:
            raise FileNotFoundError(
                "emu-cua-driver binary not found. Build/install it from "
                "frontend/coworker-mode/emu-driver."
            )
        rendered = rendered.replace("{{EMU_CUA_DRIVER_BIN}}", str(driver_bin))
    return rendered


def _current_plist_text(label: str = MEMORY_LABEL) -> str:
    target = _PLIST_TARGETS[label]
    return target.read_text(encoding="utf-8") if target.exists() else ""


def _plist_is_current(label: str, rendered: str) -> bool:
    target = _PLIST_TARGETS[label]
    return target.exists() and _current_plist_text(label) == rendered


def _uid() -> int:
    return os.getuid()


def _launchctl(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _is_loaded(label: str = MEMORY_LABEL) -> bool:
    res = _launchctl("print", f"gui/{_uid()}/{label}")
    return res.returncode == 0


def _render_all() -> dict[str, str]:
    rendered_by_label: dict[str, str] = {}
    for label in SERVICE_LABELS:
        rendered = _render(label)
        plistlib.loads(rendered.encode("utf-8"))
        rendered_by_label[label] = rendered
    return rendered_by_label


def _install_service(label: str, rendered: str) -> int:
    target = _PLIST_TARGETS[label]

    if _is_loaded(label) and _plist_is_current(label, rendered):
        print(f"[install_macos] already loaded and current: {target}")
        return 0

    if _is_loaded(label):
        res = _launchctl("bootout", f"gui/{_uid()}/{label}")
        if res.returncode != 0:
            print(f"[install_macos] bootout warning for {label}: {res.stderr.strip()}", file=sys.stderr)

    target.write_text(rendered, encoding="utf-8")
    print(f"[install_macos] wrote {target}")

    res = _launchctl("bootstrap", f"gui/{_uid()}", str(target))
    if res.returncode != 0:
        print(f"[install_macos] launchctl bootstrap failed for {label}:\n{res.stderr}", file=sys.stderr)
        return res.returncode

    print(f"[install_macos] loaded as {label}")
    return 0


def _any_plist_exists() -> bool:
    return any(target.exists() for target in _PLIST_TARGETS.values())


def _all_plists_current() -> bool:
    try:
        rendered_by_label = _render_all()
    except Exception:
        return False
    return all(
        _plist_is_current(label, rendered_by_label[label])
        for label in SERVICE_LABELS
    )


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

    # Validate every rendered plist before changing launchd state, so a missing
    # driver binary cannot leave only one daemon repaired.
    try:
        rendered_by_label = _render_all()
    except Exception as exc:
        print(f"[install_macos] rendered plist is invalid: {exc}", file=sys.stderr)
        return 1

    for label in SERVICE_LABELS:
        code = _install_service(label, rendered_by_label[label])
        if code != 0:
            return code

    _marker_path().parent.mkdir(parents=True, exist_ok=True)
    _marker_path().write_text("installed\n", encoding="utf-8")
    print("[install_macos] loaded Emu launchd services")
    print(f"[install_macos] logs: {_emu_root()}/global/daemon/logs/")
    return 0


def uninstall() -> int:
    if not _IS_MACOS:
        print("[install_macos] not macOS; nothing to do")
        return 0

    for label in SERVICE_LABELS:
        if _is_loaded(label):
            res = _launchctl("bootout", f"gui/{_uid()}/{label}")
            if res.returncode != 0:
                # Non-fatal: we still want to remove the plist file.
                print(f"[install_macos] bootout warning for {label}: {res.stderr.strip()}", file=sys.stderr)

        target = _PLIST_TARGETS[label]
        if target.exists():
            target.unlink()
            print(f"[install_macos] removed {target}")

    # Leave EMU_ROOT data alone, but clear the install marker so
    # backend.sh's prompt works again.
    marker = _marker_path()
    if marker.exists():
        marker.unlink()

    print("[install_macos] uninstalled Emu launchd services")
    return 0


def status() -> int:
    if not _IS_MACOS:
        print("[install_macos] not macOS")
        return 0

    preflight_error = _install_preflight_error()

    print(f"Anchor:  {_current_anchor_path()}")
    if preflight_error:
        print(f"Stable:  no ({preflight_error})")
    else:
        print("Stable:  yes")

    for label in SERVICE_LABELS:
        target = _PLIST_TARGETS[label]
        print("")
        print(f"Label:   {label}")
        print(f"Plist:   {target}  {'(present)' if target.exists() else '(missing)'}")
        print(f"Loaded:  {_is_loaded(label)}")

        if target.exists():
            try:
                rendered = _render(label)
                print(f"Current: {_plist_is_current(label, rendered)}")
            except Exception as exc:
                print(f"Current: false ({exc})")

        if _is_loaded(label):
            res = _launchctl("print", f"gui/{_uid()}/{label}")
            # Print the whole block; it's the canonical launchd truth.
            print(f"\n--- launchctl print ({label}) ---")
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
    if not _is_loaded(MEMORY_LABEL):
        print("[install_macos] daemon not loaded; run `install` first", file=sys.stderr)
        return 1
    res = _launchctl("kickstart", "-k", f"gui/{_uid()}/{MEMORY_LABEL}")
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

    if _any_plist_exists():
        if _all_plists_current():
            return 0  # already installed and points at the current location

        bar = "─" * 60
        print(bar)
        print("  Emu Daemons")
        print(bar)
        print("  The existing daemon install is missing or points at an older location.")
        print("  Emu can repair it now so launchd manages memory and coworker driver.")
        print(bar)
        try:
            answer = input("  Repair daemon install now? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if answer in ("", "y", "yes"):
            return install()
        print("  Skipped. Background daemons may still point at the old app location.")
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
    print("  Emu Daemons")
    print(bar)
    print("  Run a small background process every 15 minutes that")
    print("  consolidates your session memory into MEMORY.md and")
    print("  daily logs, and keep the coworker driver daemon available")
    print("  through macOS launchd (no sudo required).")
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
