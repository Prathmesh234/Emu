"""
backend/tools/coworker_tools.py

Coworker-mode tool surface — published to the LLM ONLY when
``agent_mode == "coworker"``. Two pieces:

  1. ``COWORKER_DRIVER_TOOLS_OPENAI`` — OpenAI-format function specs for
     every ``cua_*`` driver tool (plus the control-plane
     ``list_running_apps``). These are merged into the agent tool
     catalogue alongside the always-on tools in
     ``providers/agent_tools.py:AGENT_TOOLS_OPENAI``.

  2. ``call_driver_tool(name, args)`` — shells out to ``emu-cua-driver
     call <name> '<json>'`` (the v1 transport per PLAN §4.5/§5.4) and
     parses the result. The Swift CLI exposes one subcommand per MCP
     tool, so this is a 1:1 forward.

The binary is resolved with this precedence:

    $EMU_CUA_DRIVER_BIN
    ~/.local/bin/emu-cua-driver
    /Applications/EmuCuaDriver.app/Contents/MacOS/emu-cua-driver

If none exist the helper returns a structured ``tool_error`` payload so
the model can recover via the dispatcher's normal error-surfacing path
rather than crashing the request.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# Tool specs — OpenAI function-calling format
# ═══════════════════════════════════════════════════════════════════════════

# Reused parameter fragments. Driver-authoritative shapes are taken
# verbatim from frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/*.swift.
_PID = {"type": "integer", "description": "Target process ID."}
_WID_OPTIONAL = {
    "type": "integer",
    "description": (
        "CGWindowID for the window whose cua_get_window_state produced "
        "the element_index. REQUIRED when element_index is used; ignored "
        "in the pixel (x/y) path."
    ),
}
_WID_REQUIRED = {
    "type": "integer",
    "description": (
        "CGWindowID for the target window. Must belong to `pid`; it can "
        "come from cua_launch_app or cua_list_windows."
    ),
}
_ELEMENT_INDEX = {
    "type": "integer",
    "description": (
        "AX element index from the most recent cua_get_window_state "
        "snapshot for this (pid, window_id). Mutually exclusive with "
        "x/y pixel coordinates. Reusing an index across snapshots is "
        "undefined."
    ),
}
_X_WINDOW = {
    "type": "number",
    "description": (
        "X in window-local screenshot pixels — same space as the PNG "
        "cua_get_window_state returns. Top-left origin of the target's "
        "window. Must be provided together with y. Pixel path only; omit "
        "when using element_index."
    ),
}
_Y_WINDOW = {
    "type": "number",
    "description": (
        "Y in window-local screenshot pixels — same space as the PNG "
        "cua_get_window_state returns. Top-left origin of the target's "
        "window. Must be provided together with x. Pixel path only; omit "
        "when using element_index."
    ),
}
_MODIFIER_ARRAY = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Modifier keys: cmd / shift / option / ctrl. Pixel path only.",
}


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


COWORKER_DRIVER_TOOLS_OPENAI: list[dict] = [
    # ── Control-plane (coworker-only) ─────────────────────────────────────
    _fn(
        "list_running_apps",
        (
            "Enumerate running regular macOS apps. Returns name, pid, "
            "bundle_id, and front_window_id for each. Use this to discover "
            "the pid/window_id of an app the user names that may already "
            "be running, BEFORE calling element-indexed cua_* tools. "
            "Internally routed to the driver's list_apps."
        ),
        {},
    ),

    # ── Discovery ─────────────────────────────────────────────────────────
    _fn(
        "cua_list_apps",
        "Same as list_running_apps but the driver-namespaced form. Returns running regular apps with pid, name, bundle_id, front_window_id. No params.",
        {},
    ),
    _fn(
        "cua_list_windows",
        (
            "List layer-0 top-level windows known to WindowServer, including "
            "off-screen ones (hidden, minimized, on another Space). Each "
            "record self-contains its owning app identity (pid, app_name) "
            "plus window_id, title, bounds, z_index, is_on_screen, "
            "on_current_space, space_ids. Use this — not cua_list_apps — "
            "for any window-level reasoning."
        ),
        {
            "pid": {"type": "integer", "description": "Optional pid filter — restrict to one pid's windows."},
            "on_screen_only": {
                "type": "boolean",
                "description": "When true, drop windows not currently on the user's Space (minimized, hidden, off-Space). Default false.",
            },
        },
    ),
    _fn(
        "cua_launch_app",
        (
            "Hidden background launch — never raises a window, never steals "
            "the foreground. At least one of bundle_id / name must be given; "
            "bundle_id wins when both are. Returns pid, bundle_id, name, plus "
            "a `windows` array (same shape as cua_list_windows) so the caller "
            "can skip a cua_list_windows round-trip in the common case. NOT "
            "a generic launcher — strictly background-launch."
        ),
        {
            "bundle_id": {"type": "string", "description": "App bundle id (e.g. com.apple.calculator). Preferred."},
            "name": {"type": "string", "description": "App display name. Used only when bundle_id is absent."},
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional file:// or http(s):// URLs handed to the launched app via application(_:open:). For Finder, a folder URL opens a backgrounded Finder window rooted there.",
            },
            "electron_debugging_port": {
                "type": "integer",
                "description": "Launch an Electron app with --remote-debugging-port=<N> for full renderer/DOM access. Use 9222 unless running multiple Electron apps. Ignored for non-Electron apps.",
            },
            "webkit_inspector_port": {
                "type": "integer",
                "description": "Launch a Tauri/WKWebView app with WEBKIT_INSPECTOR_SERVER=127.0.0.1:<N>. Use 9226 (reserved range 9226–9228). Requires developerExtrasEnabled=true.",
            },
            "creates_new_application_instance": {
                "type": "boolean",
                "description": "Force a brand-new process even if the app is already running. Useful for isolated browser sessions when paired with --user-data-dir.",
            },
            "additional_arguments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Extra command-line arguments passed to the launched app.",
            },
        },
    ),

    # ── Perception ────────────────────────────────────────────────────────
    _fn(
        "cua_screenshot",
        (
            "Capture via ScreenCaptureKit. Returns a base64 image content "
            "block. ALL params optional. Without window_id captures the "
            "full main display; with window_id captures just that window. "
            "Requires the Screen Recording TCC grant."
        ),
        {
            "format": {"type": "string", "enum": ["png", "jpeg"], "description": "Image format. Default png."},
            "quality": {"type": "integer", "minimum": 1, "maximum": 95, "description": "JPEG quality 1–95; ignored for png."},
            "window_id": {"type": "integer", "description": "Optional CGWindowID to capture just that window."},
        },
    ),
    _fn(
        "cua_get_window_state",
        (
            "Walk the target window's accessibility tree and return Markdown "
            "tagged with [element_index N] plus a screenshot of window_id. "
            "Mints a fresh index map and invalidates the previous one for "
            "this (pid, window_id). INVARIANT: call this once per turn per "
            "(pid, window_id) before any element-indexed action against that "
            "window. window_id MUST belong to pid. Optional "
            "case-insensitive substring `query` trims the rendered tree "
            "while preserving ancestors and index numbers (the cached "
            "element map is unchanged). Optional `javascript` runs in the "
            "co-located browser tab (Chromium / Safari only; requires "
            "Allow-JavaScript-from-Apple-Events). Capture mode (som / "
            "vision / ax) is set persistently via cua_set_config."
        ),
        {
            "pid": _PID,
            "window_id": _WID_REQUIRED,
            "query": {"type": "string", "description": "Optional substring filter. Trims tree_markdown only."},
            "javascript": {"type": "string", "description": "Optional JS to execute in the browser tab and return alongside the AX snapshot. Prefer read-only queries here; use cua_page for standalone DOM reads or deliberate JS."},
            "screenshot_out_file": {
                "type": "string",
                "description": (
                    "Optional absolute path to write the window screenshot. "
                    "When set, the driver returns screenshot_file_path instead "
                    "of inline image bytes."
                ),
            },
        },
        ["pid", "window_id"],
    ),

    # ── Click family — only `pid` strictly required, addressing modes XOR ─
    _fn(
        "cua_click",
        (
            "Left-click against a target pid. Two addressing modes — exactly "
            "one must be supplied: (a) element_index + window_id (preferred; "
            "pure AX RPC, works on backgrounded windows, no cursor move); "
            "(b) x + y in window-local screenshot pixels (top-left origin "
            "of the cua_get_window_state PNG; CGEvent path). NO `button` "
            "param — for right-click use cua_right_click. On the element "
            "path, `action` selects the AX action; on the pixel path, "
            "`count` enables double/triple click and `modifier` holds keys. "
            "Do not cycle `action` values on the same element after a failure "
            "or no-op; use the advertised action from the latest AX tree, a "
            "different sibling/parent element, or pixel coordinates."
        ),
        {
            "pid": _PID,
            "element_index": _ELEMENT_INDEX,
            "window_id": _WID_OPTIONAL,
            "x": _X_WINDOW,
            "y": _Y_WINDOW,
            "action": {
                "type": "string",
                "enum": ["press", "show_menu", "pick", "confirm", "cancel", "open"],
                "description": "AX action on the element path only. Default 'press'. Ignored on the pixel path. Use only when the latest AX tree advertises that action or the role is known to accept it; do not try open/show_menu/pick against AXStaticText or after a no-op. When using element_index, omit x, y, modifier, count, and from_zoom entirely.",
            },
            "modifier": _MODIFIER_ARRAY,
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
                "description": "1 / 2 / 3 = single / double / triple click. Pixel path only — element-indexed clicks are always single via the chosen AX action.",
            },
            "from_zoom": {
                "type": "boolean",
                "description": "When true, x/y are coords in the last cua_zoom image; the driver maps them back to window coords.",
            },
        },
        ["pid"],
    ),
    _fn(
        "cua_right_click",
        (
            "Right-click against a target pid. Element path performs "
            "AXShowMenu on the cached element when the element supports a "
            "context menu (no cursor move). "
            "Pixel path synthesizes a right-mouse-down/up pair (Chromium "
            "web content has a known coercion-to-left-click caveat). "
            "Same XOR addressing as cua_click. NO `count` (single only). "
            "`modifier` is pixel-path only. Do not right-click AXStaticText "
            "or retry AXShowMenu after it fails; use pixel fallback or another "
            "control."
        ),
        {
            "pid": _PID,
            "element_index": _ELEMENT_INDEX,
            "window_id": _WID_OPTIONAL,
            "x": _X_WINDOW,
            "y": _Y_WINDOW,
            "modifier": _MODIFIER_ARRAY,
        },
        ["pid"],
    ),
    _fn(
        "cua_double_click",
        (
            "Double-click against a target pid. Two addressing modes — exactly "
            "one must be supplied: (a) element_index + window_id from the last "
            "cua_get_window_state; performs AXOpen when advertised, otherwise "
            "falls back to a stamped pixel double-click at the element center; "
            "(b) x + y in window-local screenshot pixels. Prefer this for "
            "open-on-double-click intents instead of cua_click(count=2). If "
            "a double-click on an AXStaticText/static label verifies as no-op, "
            "do not repeat with alternate AX actions; pick a real control, "
            "pixel-coordinate target, keyboard path, or stop."
        ),
        {
            "pid": _PID,
            "element_index": _ELEMENT_INDEX,
            "window_id": _WID_OPTIONAL,
            "x": _X_WINDOW,
            "y": _Y_WINDOW,
            "modifier": _MODIFIER_ARRAY,
        },
        ["pid"],
    ),
    # ── Scroll ────────────────────────────────────────────────────────────
    _fn(
        "cua_scroll",
        (
            "Scroll the target. Posts synthesized arrow-key (line) or "
            "PageUp/PageDown (page) keystrokes via the auth-signed pid "
            "path. Page-sized scrolls use `by=\"page\"`; cua_page is for "
            "browser DOM primitives, not scrolling. element_index + window_id "
            "pre-focuses the element; skip them when focus is already "
            "established."
        ),
        {
            "pid": _PID,
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "amount": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": "Number of keystroke repetitions. Default 3.",
            },
            "by": {
                "type": "string",
                "enum": ["line", "page"],
                "description": "line = arrow-key per repetition; page = PageUp/PageDown per repetition. Default 'line'.",
            },
            "element_index": _ELEMENT_INDEX,
            "window_id": _WID_OPTIONAL,
        },
        ["pid", "direction"],
    ),

    # ── Text input ────────────────────────────────────────────────────────
    _fn(
        "cua_type_text",
        (
            "Insert text into the target pid. Tries AXSetAttribute"
            "(kAXSelectedText) first (standard Cocoa text fields/views) "
            "and silently falls back to per-character CGEvent.postToPid "
            "synthesis when the AX write is rejected — covers "
            "Chromium / Electron inputs that ignore kAXSelectedText. "
            "Does NOT synthesize Return/Tab — use cua_press_key / "
            "cua_hotkey for those. Optional element_index + window_id "
            "pre-focuses the element. Optional `delay_ms` paces the "
            "CGEvent fallback (default 30ms; ignored on the AX path)."
        ),
        {
            "pid": _PID,
            "text": {"type": "string"},
            "element_index": _ELEMENT_INDEX,
            "window_id": _WID_OPTIONAL,
            "delay_ms": {
                "type": "integer",
                "minimum": 0,
                "maximum": 200,
                "description": "Milliseconds between successive characters on the CGEvent fallback path (autocomplete/IME pacing). Default 30. Ignored when AX write succeeds.",
            },
        },
        ["pid", "text"],
    ),
    _fn(
        "cua_set_value",
        (
            "Set a value on a UI element. Two modes: (a) AXPopUpButton / "
            "HTML <select> — finds the child option whose title or value "
            "matches `value` (case-insensitive) and AXPresses it directly; "
            "the native popup menu is never opened. (b) Other elements — "
            "writes AXValue directly (sliders, steppers, date pickers, "
            "native text fields). For free-form text in WebKit inputs use "
            "cua_type_text — AXValue writes are ignored by WebKit."
        ),
        {
            "pid": _PID,
            "window_id": _WID_REQUIRED,
            "element_index": _ELEMENT_INDEX,
            "value": {"type": "string", "description": "New value. AX coerces to the element's native type."},
        },
        ["pid", "window_id", "element_index", "value"],
    ),

    # ── Keys ──────────────────────────────────────────────────────────────
    _fn(
        "cua_press_key",
        (
            "Single key press delivered via auth-signed SLEventPostToPid "
            "(works on backgrounded Chromium). Key vocabulary: return, "
            "tab, escape, up/down/left/right, space, delete, home, end, "
            "pageup, pagedown, f1-f12, letters, digits. Optional "
            "`modifiers` array (cmd/shift/option/ctrl/fn). Optional "
            "element_index + window_id pre-focuses the element via "
            "AXSetAttribute(kAXFocused, true). For true combos prefer "
            "cua_hotkey for clarity."
        ),
        {
            "pid": _PID,
            "key": {"type": "string", "description": "Key name, e.g. 'return', 'tab', 'escape', 'a', '1'."},
            "modifiers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional modifier keys held during the press: cmd / shift / option / ctrl / fn.",
            },
            "element_index": _ELEMENT_INDEX,
            "window_id": _WID_OPTIONAL,
        },
        ["pid", "key"],
    ),
    _fn(
        "cua_hotkey",
        (
            "Press a combination of keys simultaneously, e.g. ['cmd','c'] "
            "for Copy. Recognized modifiers: cmd/command, shift, "
            "option/alt, ctrl/control, fn. Order: modifiers first, one "
            "non-modifier last. Posted via CGEvent.postToPid; target need "
            "NOT be frontmost."
        ),
        {
            "pid": _PID,
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "description": "Modifier(s) and one non-modifier key, e.g. ['cmd','c'].",
            },
        },
        ["pid", "keys"],
    ),

    # ── Cursor / drag ─────────────────────────────────────────────────────
    _fn(
        "cua_move_cursor",
        (
            "Instantly move the mouse cursor to (x, y) in SCREEN POINTS. "
            "Uses CGWarpMouseCursorPosition — no drag, no click, no "
            "CGEvent. NO pid, NO window_id, NO relative dx/dy. Visible "
            "cursor warp — reach for it only when an interaction "
            "genuinely requires the cursor to be somewhere specific "
            "(rare in coworker mode; pid-routed click/drag tools do not "
            "need the cursor on-target)."
        ),
        {
            "x": {"type": "integer", "description": "X in screen points."},
            "y": {"type": "integer", "description": "Y in screen points."},
        },
        ["x", "y"],
    ),
    _fn(
        "cua_drag",
        (
            "Press-drag-release gesture from (from_x, from_y) to "
            "(to_x, to_y) in window-local screenshot pixels — same space "
            "as the cua_get_window_state PNG. Pixel-only by design "
            "(macOS AX has no semantic drag action). window_id is "
            "optional — when omitted the driver picks the frontmost "
            "window of pid. Frontmost target uses cghidEventTap (real "
            "cursor visibly traces the path). Backgrounded target uses "
            "the auth-signed pid-routed path (cursor-neutral; some "
            "OpenGL canvases may filter it)."
        ),
        {
            "pid": _PID,
            "window_id": {
                "type": "integer",
                "description": "Optional CGWindowID for the window the pixel coords were measured against. When omitted the driver picks the frontmost window of pid.",
            },
            "from_x": {"type": "number", "description": "Drag-start X in window-local screenshot pixels. Top-left origin."},
            "from_y": {"type": "number", "description": "Drag-start Y in window-local screenshot pixels. Top-left origin."},
            "to_x": {"type": "number", "description": "Drag-end X in window-local screenshot pixels."},
            "to_y": {"type": "number", "description": "Drag-end Y in window-local screenshot pixels."},
            "duration_ms": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10000,
                "description": "Wall-clock duration of the drag path between mouseDown and mouseUp. Default 500.",
            },
            "steps": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "description": "Number of intermediate mouseDragged events linearly interpolated along the path. Default 20.",
            },
            "modifier": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Modifier keys held across the entire gesture: cmd/shift/option/ctrl. option-drag duplicates, shift-drag axis-constrains.",
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Mouse button used for the drag. Default 'left'.",
            },
            "from_zoom": {
                "type": "boolean",
                "description": "When true, all four coords are pixel coords in the last cua_zoom image; the driver maps them back.",
            },
        },
        ["pid", "from_x", "from_y", "to_x", "to_y"],
    ),

    # ── Browser / vision helpers ──────────────────────────────────────────
    _fn(
        "cua_page",
        (
            "Browser page primitives for Chrome/Brave/Edge/Safari/Electron "
            "when AX does not expose the data. Actions: get_text, query_dom, "
            "execute_javascript, enable_javascript_apple_events. Requires "
            "pid + window_id. Use get_text/query_dom for reading DOM data; "
            "prefer cua_click/cua_set_value for indexed UI elements."
        ),
        {
            "pid": _PID,
            "window_id": _WID_REQUIRED,
            "action": {
                "type": "string",
                "enum": ["execute_javascript", "get_text", "query_dom", "enable_javascript_apple_events"],
            },
            "javascript": {"type": "string", "description": "JS for action=execute_javascript. Wrap complex code in an IIFE."},
            "css_selector": {"type": "string", "description": "CSS selector for action=query_dom."},
            "attributes": {"type": "array", "items": {"type": "string"}, "description": "Attributes to include for query_dom matches."},
            "bundle_id": {"type": "string", "description": "Browser bundle id for enable_javascript_apple_events."},
            "user_has_confirmed_enabling": {"type": "boolean", "description": "Must be true only after explicit user permission for enable_javascript_apple_events."},
        },
        ["pid", "window_id", "action"],
    ),
    _fn(
        "cua_zoom",
        (
            "Zoom into a rectangular region of the last get_window_state "
            "screenshot at native resolution. Coordinates x1/y1/x2/y2 are "
            "in the same resized-image pixel space returned by get_window_state. "
            "Use for small text/icons before pixel fallback."
        ),
        {
            "pid": _PID,
            "x1": {"type": "number", "description": "Left edge in get_window_state screenshot pixels."},
            "y1": {"type": "number", "description": "Top edge in get_window_state screenshot pixels."},
            "x2": {"type": "number", "description": "Right edge in get_window_state screenshot pixels."},
            "y2": {"type": "number", "description": "Bottom edge in get_window_state screenshot pixels."},
        },
        ["pid", "x1", "y1", "x2", "y2"],
    ),

    # ── Diagnostics ───────────────────────────────────────────────────────
    _fn(
        "cua_check_permissions",
        (
            "Report TCC permission status for Accessibility and Screen "
            "Recording. By default also raises the system permission "
            "dialogs for any missing grants — Apple's request APIs no-op "
            "when already granted, so safe to call repeatedly. Pass "
            "{prompt: false} for a purely read-only status check."
        ),
        {
            "prompt": {
                "type": "boolean",
                "description": "Raise system permission prompts for missing grants. Default true.",
            },
        },
    ),
    _fn(
        "cua_get_config",
        "Inspect the driver's current capture/cursor configuration (capture_mode ∈ som / vision / ax, cursor settings, feature flags).",
        {},
    ),
    _fn(
        "cua_set_config",
        (
            "Write one persistent driver config key. Common keys: "
            "capture_mode ('som' | 'vision' | 'ax'), max_image_dimension, "
            "agent_cursor.enabled, agent_cursor.motion.start_handle/end_handle/"
            "arc_size/arc_flow/spring."
        ),
        {
            "key": {"type": "string", "description": "Dotted snake_case config key, e.g. capture_mode."},
            "value": {"description": "JSON value for key, e.g. 'som', 1568, true, or a number."},
        },
        ["key", "value"],
    ),
    _fn(
        "cua_get_screen_size",
        "Return display pixel dimensions. Useful when planning pixel-fallback clicks against `vision` capture mode.",
        {},
    ),
    _fn(
        "cua_get_cursor_position",
        "Return the current OS cursor x/y in screen points.",
        {},
    ),
    _fn(
        "cua_get_agent_cursor_state",
        "Return {enabled, x, y, motion} for the agent-cursor overlay.",
        {},
    ),
    _fn(
        "cua_set_agent_cursor_enabled",
        "Toggle the visible agent-cursor overlay. Off by default.",
        {"enabled": {"type": "boolean"}},
        ["enabled"],
    ),
    _fn(
        "cua_set_agent_cursor_motion",
        (
            "Tune the agent cursor's Bezier-arc + spring-settle motion. "
            "ALL fields optional; only the knobs you pass change. "
            "Defaults: start_handle=0.3, end_handle=0.3, arc_size=0.25, "
            "arc_flow=0.0, spring=0.72, glide_duration_ms=750, "
            "dwell_after_click_ms=400, idle_hide_ms=3000."
        ),
        {
            "start_handle": {"type": "number", "description": "Start-handle fraction in [0, 1]."},
            "end_handle": {"type": "number", "description": "End-handle fraction in [0, 1]."},
            "arc_size": {"type": "number", "description": "Arc deflection as a fraction of path length."},
            "arc_flow": {"type": "number", "description": "Asymmetry bias in [-1, 1]."},
            "spring": {"type": "number", "description": "Settle damping in [0.3, 1]."},
            "glide_duration_ms": {"type": "number", "minimum": 50, "maximum": 5000, "description": "Flight duration per click in ms."},
            "dwell_after_click_ms": {"type": "number", "minimum": 0, "maximum": 5000, "description": "Pause after click ripple in ms."},
            "idle_hide_ms": {"type": "number", "minimum": 0, "maximum": 60000, "description": "Overlay linger after last action in ms. 0 disables auto-hide."},
        },
    ),
    _fn(
        "cua_set_agent_cursor_style",
        (
            "Customize the visual agent-cursor overlay. Omit fields to keep "
            "current values. Empty gradient_colors/bloom_color/image_path "
            "reverts that style to default. shape_size controls drawn cursor "
            "size in points."
        ),
        {
            "gradient_colors": {"type": "array", "items": {"type": "string"}, "description": "CSS hex colors for arrow gradient stops."},
            "bloom_color": {"type": "string", "description": "CSS hex color for halo/focus rect; empty string resets."},
            "shape_size": {"type": "number", "minimum": 10, "maximum": 40, "description": "Drawn cursor size in points."},
            "image_path": {"type": "string", "description": "Absolute or ~ path to PNG/JPEG/PDF/SVG cursor image; empty string resets."},
        },
    ),
    _fn(
        "cua_set_recording",
        (
            "Toggle trajectory recording. Only use when the user explicitly "
            "asks to record. When enabled, action tools write turn folders "
            "under output_dir."
        ),
        {
            "enabled": {"type": "boolean", "description": "True to start recording, false to stop."},
            "output_dir": {"type": "string", "description": "Absolute or ~ directory. Required when enabled=true."},
            "video_experimental": {"type": "boolean", "description": "Also capture main display video to recording.mp4. Off by default."},
        },
        ["enabled"],
    ),
    _fn(
        "cua_get_recording_state",
        "Report whether trajectory recording is enabled and where turns are written.",
        {},
    ),
    _fn(
        "cua_replay_trajectory",
        (
            "Replay a previously recorded trajectory directory. Only use when "
            "the user explicitly asks for replay/regression testing. Element "
            "indices do not survive across sessions; pixel/keyboard actions replay best."
        ),
        {
            "dir": {"type": "string", "description": "Trajectory directory previously written by set_recording."},
            "delay_ms": {"type": "integer", "minimum": 0, "maximum": 10000, "description": "Delay between turns. Default 500."},
            "stop_on_error": {"type": "boolean", "description": "Stop on first error. Default true."},
        },
        ["dir"],
    ),
]


# Set of names exposed to the LLM in coworker mode (used by dispatcher / drift checks).
COWORKER_DRIVER_TOOL_NAMES: set[str] = {
    t["function"]["name"] for t in COWORKER_DRIVER_TOOLS_OPENAI
}


# ═══════════════════════════════════════════════════════════════════════════
# Driver shell-out
# ═══════════════════════════════════════════════════════════════════════════

_CALL_TIMEOUT_S = 30
_ACTIVE_DRIVER_PROCS: dict[str, set[subprocess.Popen[str]]] = {}
_ACTIVE_DRIVER_PROCS_LOCK = threading.Lock()


def _kill_driver_proc(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def cancel_driver_calls(cancel_key: str) -> int:
    """Terminate active emu-cua-driver CLI calls for a running agent step."""
    with _ACTIVE_DRIVER_PROCS_LOCK:
        procs = list(_ACTIVE_DRIVER_PROCS.get(cancel_key, set()))

    killed = 0
    for proc in procs:
        if proc.poll() is None:
            _kill_driver_proc(proc)
            killed += 1
    return killed


def _resolve_driver_bin() -> str | None:
    override = os.environ.get("EMU_CUA_DRIVER_BIN", "").strip()
    if override and Path(override).is_file():
        return override

    home_local = Path.home() / ".local" / "bin" / "emu-cua-driver"
    if home_local.is_file():
        return str(home_local)

    app_bin = Path("/Applications/EmuCuaDriver.app/Contents/MacOS/emu-cua-driver")
    if app_bin.is_file():
        return str(app_bin)

    # Last resort: PATH lookup (covers Homebrew / dev installs)
    found = shutil.which("emu-cua-driver")
    return found


def call_driver_tool(
    name: str,
    args: dict | None = None,
    cancel_key: str | None = None,
) -> dict:
    """
    Forward a tool call to the emu-cua-driver Swift CLI.

    Always returns a dict shaped:

        {"ok": True,  "output": <str>, "json": <obj or None>}
        {"ok": False, "error":  <str>, "code": <int|None>}

    Caller decides how to surface to the model. Never raises on driver
    failure — only on programmer error (bad argument types).
    """
    if not isinstance(name, str) or not name:
        raise TypeError("call_driver_tool: tool name must be a non-empty string")

    args = args or {}
    if not isinstance(args, dict):
        raise TypeError("call_driver_tool: args must be a dict")
    args = dict(args)

    # The Swift driver treats a present `javascript` field as "run browser JS".
    # Models often emit an empty string for optional fields; do not turn that
    # into an unnecessary browser/Electron JS round-trip.
    if name == "get_window_state":
        for key in ("query", "javascript", "screenshot_out_file"):
            value = args.get(key)
            if value == "" or value == []:
                args.pop(key, None)

    if name == "page":
        action = args.get("action")
        if action == "get_text":
            for key in (
                "javascript",
                "css_selector",
                "attributes",
                "bundle_id",
                "user_has_confirmed_enabling",
            ):
                args.pop(key, None)
        elif action == "query_dom":
            for key in ("javascript", "bundle_id", "user_has_confirmed_enabling"):
                args.pop(key, None)
            if args.get("attributes") == []:
                args.pop("attributes", None)
        elif action == "execute_javascript":
            for key in ("css_selector", "attributes", "bundle_id", "user_has_confirmed_enabling"):
                args.pop(key, None)
        elif action == "enable_javascript_apple_events":
            for key in ("javascript", "css_selector", "attributes"):
                args.pop(key, None)

    bin_path = _resolve_driver_bin()
    if bin_path is None:
        return {
            "ok": False,
            "error": (
                "emu-cua-driver binary not found. Set $EMU_CUA_DRIVER_BIN, "
                "install via frontend/coworker-mode/emu-driver/scripts/install-local.sh, "
                "or copy the binary into ~/.local/bin."
            ),
            "code": None,
        }

    try:
        payload = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": f"args not JSON-serialisable: {exc}", "code": None}

    # Image-bearing tools no longer splice their PNG into structuredContent
    # in the default CLI output (upstream commit 9d623c03 — "screenshot_out_file
    # param; CLI no longer dumps base64 by default"). Use `--raw` for these
    # so we receive the full CallTool.Result with `content[].image` blocks,
    # then re-merge the image into a flat dict shaped like the old contract:
    # `{...structuredContent, screenshot_png_b64, screenshot_mime_type}`.
    use_raw = name in _IMAGE_PRODUCING_TOOLS
    cmd = [bin_path, "call"]
    if use_raw:
        cmd.append("--raw")
    cmd.extend([name, payload])

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        if cancel_key:
            with _ACTIVE_DRIVER_PROCS_LOCK:
                _ACTIVE_DRIVER_PROCS.setdefault(cancel_key, set()).add(proc)
        try:
            stdout, stderr = proc.communicate(timeout=_CALL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _kill_driver_proc(proc)
            stdout, stderr = proc.communicate()
            return {"ok": False, "error": f"emu-cua-driver call {name} timed out after {_CALL_TIMEOUT_S}s", "code": None}
        finally:
            if cancel_key:
                with _ACTIVE_DRIVER_PROCS_LOCK:
                    procs = _ACTIVE_DRIVER_PROCS.get(cancel_key)
                    if procs is not None:
                        procs.discard(proc)
                        if not procs:
                            _ACTIVE_DRIVER_PROCS.pop(cancel_key, None)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"emu-cua-driver call {name} timed out after {_CALL_TIMEOUT_S}s", "code": None}
    except FileNotFoundError:
        return {"ok": False, "error": f"emu-cua-driver binary missing at {bin_path}", "code": None}
    except OSError as exc:
        return {"ok": False, "error": f"failed to invoke emu-cua-driver: {exc}", "code": None}

    output = (stdout or "").strip()
    err = (stderr or "").strip()

    if proc.returncode != 0:
        return {
            "ok": False,
            "error": err or output or f"emu-cua-driver call {name} exited {proc.returncode}",
            "code": proc.returncode,
        }

    parsed: Any = None
    if output:
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            parsed = None

    # In raw mode the parsed JSON is a CallTool.Result envelope. Flatten it
    # back into the old shape callers expect, splicing the first image
    # content block into `screenshot_png_b64` so format_driver_result_for_model
    # and _inject_coworker_perception keep working unchanged.
    if use_raw and isinstance(parsed, dict):
        parsed = _flatten_raw_result(parsed)
        # Re-render output so callers that fall back to .output (rare) see
        # the flattened shape, not the raw envelope.
        try:
            output = json.dumps(parsed, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            pass

    return {"ok": True, "output": output, "json": parsed}


# Driver tools that emit an image content block. For these we must use
# `--raw` to preserve access to the PNG bytes (post upstream 9d623c03).
_IMAGE_PRODUCING_TOOLS = frozenset({"get_window_state", "screenshot", "zoom"})


def _flatten_raw_result(envelope: dict) -> dict:
    """Convert a `--raw` CallTool.Result envelope into the legacy flat shape.

    Inputs (raw envelope):
        {
          "content": [
            {"type": "image", "data": "<base64>", "mimeType": "image/png"},
            {"type": "text",  "text": "..."}
          ],
          "structuredContent": {...},
          "isError": false
        }

    Output (legacy flat dict that matches v0.0.13 default-mode output):
        {
          ...structuredContent,
          "screenshot_png_b64": "<base64>",
          "screenshot_mime_type": "image/png"
        }
    """
    structured = envelope.get("structuredContent")
    flat: dict = dict(structured) if isinstance(structured, dict) else {}

    for item in envelope.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "image":
            data = item.get("data")
            mime = item.get("mimeType")
            if isinstance(data, str) and "screenshot_png_b64" not in flat:
                flat["screenshot_png_b64"] = data
            if isinstance(mime, str) and "screenshot_mime_type" not in flat:
                flat["screenshot_mime_type"] = mime
            break

    return flat


def _driver_result_guidance(name: str, text: str, ok: bool) -> str:
    """Return short recovery guidance for common driver dead ends."""
    lowered = text.lower()
    guidance: list[str] = []

    if name == "cua_screenshot" and not ok and "timed out" in lowered:
        guidance.append(
            "Window screenshot timed out. Do not repeat the same screenshot "
            "call immediately; use cua_get_window_state/list_windows to "
            "re-orient, or switch strategy."
        )
        return "\n[driver guidance] " + " ".join(guidance)

    if name not in {"cua_click", "cua_right_click", "cua_double_click", "cua_press_key", "cua_hotkey", "cua_type_text", "cua_set_value"}:
        return ""

    if ok:
        guidance.append(
            "A successful tool result only means the input was posted/accepted; "
            "verify the visible or AX state changed before reporting success."
        )

    if "axstatictext" in lowered:
        guidance.append(
            "AXStaticText is usually a read-only/static label. If the follow-up "
            "snapshot does not change, do not try AXOpen/AXShowMenu/pick on the "
            "same element; use a parent/sibling control, pixel coordinates from "
            "the screenshot, a keyboard shortcut, or stop."
        )

    if not ok and "ax action" in lowered and "failed" in lowered:
        guidance.append(
            "Treat this AX action failure as a strategy-change signal, not as "
            "an invitation to cycle other AX actions on the same element."
        )

    if "disabled" in lowered or "axenabled = false" in lowered:
        guidance.append(
            "Disabled menu/items in a backgrounded app are not usable through "
            "foreground menu navigation. Do not activate the app or use "
            "AppleScript as a workaround; choose an in-window driver action or "
            "report the limitation."
        )

    if not guidance:
        return ""
    return "\n[driver guidance] " + " ".join(dict.fromkeys(guidance))


def format_driver_result_for_model(name: str, result: dict) -> str:
    """Render a call_driver_tool result as a string the LLM can read.

    Special-cases the image-bearing tools (`cua_screenshot`,
    `cua_get_window_state`, `cua_zoom`): when invoked via `--raw` (see
    `_IMAGE_PRODUCING_TOOLS`) ``call_driver_tool`` flattens the response
    so the PNG ends up under `screenshot_png_b64`. Keep the text channel
    compact by stripping the bytes here; the dispatcher attaches the image
    as a real multimodal message immediately after the tool result.
    """
    if result.get("ok"):
        parsed = result.get("json")
        if isinstance(parsed, dict) and "screenshot_png_b64" in parsed:
            stripped = dict(parsed)
            b64 = stripped.pop("screenshot_png_b64", None) or ""
            stripped.pop("screenshot_mime_type", None)
            stripped["_screenshot_attached"] = bool(b64)
            stripped["_screenshot_bytes"] = len(b64)
            try:
                out = json.dumps(stripped, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                out = result.get("output") or "(empty)"
        else:
            out = result.get("output") or "(empty)"
        # Cap to avoid blowing up context if the driver returns a huge AX dump.
        if len(out) > 8000:
            out = out[:8000] + "\n... [truncated]"
        out += _driver_result_guidance(name, out, ok=True)
        return f"[{name}] {out}"
    err = result.get("error") or "unknown error"
    code = result.get("code")
    suffix = f" (exit {code})" if code is not None else ""
    err += _driver_result_guidance(name, err, ok=False)
    return f"[{name} error{suffix}] {err}"


def driver_screenshot_for_context(result: dict) -> str | None:
    """Return a screenshot data URI from a successful driver result, if present."""
    if not result.get("ok"):
        return None
    parsed = result.get("json")
    if not isinstance(parsed, dict):
        return None
    b64 = parsed.get("screenshot_png_b64")
    if not isinstance(b64, str) or not b64:
        return None
    mime = parsed.get("screenshot_mime_type")
    if not isinstance(mime, str) or not mime:
        mime = "image/png"
    return f"data:{mime};base64,{b64}"
