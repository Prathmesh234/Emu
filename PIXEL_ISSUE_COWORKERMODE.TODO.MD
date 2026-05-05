# Pixel Issue In Coworker Mode TODO

Date: 2026-05-04

This file records the coordinate-alignment findings for coworker mode and the fixes to make later. No implementation changes are included here.

## Goal

Make coworker mode choose targets in this order:

1. Use the Accessibility tree (`element_index`) whenever the target appears in the latest `cua_get_window_state(pid, window_id)` tree.
2. Fall back to pixel coordinates only when AX is sparse, custom-rendered, canvas/video-backed, or visually ambiguous.
3. When using pixels, make the model and driver agree on the exact same window frame, screenshot size, resize ratio, backing scale, and zoom crop so coordinates land on the intended point.

The intended pixel contract is:

- Coordinates are window-local pixels measured from the attached driver image, with `(0, 0)` at the image's top-left.
- The model must pass the same `pid` and `window_id` that produced the screenshot or zoom image.
- The model must not manually apply Retina, display, backing-scale, `screenshot_scale_factor`, `screenshot_original_width`, or `screenshot_original_height` math.
- The driver must do all image-to-native-pixel and native-pixel-to-screen-point conversion internally.
- Fresh UI state is required after scroll, resize, window move, navigation, sheet/menu open, or content change.

## Current Findings

### 1. Prompt Is Mostly Correct

Current [backend/prompts/coworker_system_prompt.py](backend/prompts/coworker_system_prompt.py) already tells the model to:

- Prefer `element_index` from `tree_markdown`.
- Use pixel `x`/`y` only when AX is sparse or the surface is custom-rendered.
- Treat pixels as window-local screenshot pixels.
- Pass the same `pid` and `window_id` that produced the screenshot.
- Avoid global screen coordinates, CSS coordinates, normalized coordinates, AX point coordinates, and manual scale math.
- Use `cua_zoom` for small/dense targets.

Gap to close later: the zoom instruction should explicitly say to call `cua_zoom` with the same `window_id`, then call pixel tools with `from_zoom=true` and the same `window_id`.

### 2. Backend Tool Definitions Are Close, But Zoom Is Under-Specified

Current [backend/tools/coworker_tools.py](backend/tools/coworker_tools.py) has good shared descriptions for `_WID_OPTIONAL`, `_X_WINDOW`, and `_Y_WINDOW`.

Gaps to close later:

- `cua_zoom` does not expose `window_id`, so the model cannot explicitly bind a zoom crop to the same window that produced the base screenshot.
- `from_zoom` descriptions for `cua_click` and `cua_drag` do not remind the model to pass the same `window_id` as the zoom/source image.
- Tool descriptions should say pixel actions are not just `pid` actions; they are image-context actions and should stay bound to the captured window whenever possible.

### 3. Driver Resize Metadata Is Per-PID, Not Per-Window

Current [frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/ImageResizeRegistry.swift](frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/ImageResizeRegistry.swift) stores resize ratio and zoom context by `pid` only.

Risk:

- A process with multiple windows can produce a resize ratio for one window and then reuse it for a different window.
- A later capture from the same app can overwrite or clear context needed by a previous window.
- If the model supplies a correct `window_id`, the driver still may use a ratio that is only keyed by `pid`.

Fix later:

- Store image context by `(pid, window_id)`, not just `pid`.
- Keep a latest-per-pid fallback only for backward compatibility when callers omit `window_id`.
- Store enough metadata to validate coordinates: screenshot width, screenshot height, original width, original height, ratio, scale factor, capture time, and source type.

### 4. Left Click Scales Resized Screenshot Coordinates, But Right/Double Pixel Paths Do Not

Current [ClickTool.swift](frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/ClickTool.swift) scales pixel `x/y` through `ImageResizeRegistry.ratio(forPid:)` before converting to screen points.

Current [RightClickTool.swift](frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/RightClickTool.swift) and [DoubleClickTool.swift](frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/DoubleClickTool.swift) convert `x/y` directly to screen points without applying the resize ratio.

Risk:

- If `cua_get_window_state` downscaled a large screenshot with `max_image_dimension`, left-click can land correctly while right-click and double-click land too high/left or generally off-target.
- This creates model-visible inconsistency: the same coordinate from the same screenshot can behave differently depending on the pixel action tool.

Fix later:

- Route all pixel actions through one shared coordinate resolver.
- Apply the same resize/zoom/window conversion for `click`, `right_click`, `double_click`, `drag`, and any other screenshot-coordinate action.

### 5. Drag Already Applies Resize Ratio, But It Still Uses Per-PID Context

Current [DragTool.swift](frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/DragTool.swift) scales via `ImageResizeRegistry.ratio(forPid:)`, which is good.

Remaining risk:

- Because the ratio is per-pid, drag can still be wrong when multiple windows exist or stale context remains.
- `from_zoom=true` drag uses the latest pid zoom context, not a window-scoped zoom context.

Fix later:

- Keep the drag scaling behavior, but pull context from `(pid, window_id)`.
- Reject mismatched `from_zoom` coordinates if the provided `window_id` does not match the stored zoom context.

### 6. Zoom Can Capture A Different Window Than The Original Screenshot

Current [ZoomTool.swift](frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/ZoomTool.swift) uses `captureFrontmostWindow(pid:)` when creating the native-resolution crop.

Risk:

- The model may select a zoom rectangle from `cua_get_window_state(pid, window_id=A)`.
- `cua_zoom(pid, x1, y1, x2, y2)` may then crop the pid's current frontmost window, which may not be window A.
- On multi-window apps, a correct rectangle can become a wrong crop even before the final click happens.

Fix later:

- Add optional, strongly recommended `window_id` to `cua_zoom`.
- Validate that `window_id` belongs to `pid`.
- Capture that exact window when supplied.
- Store zoom context with `window_id`.
- Require or strongly enforce matching `window_id` when using `from_zoom=true`.

### 7. Raw Screenshot Can Leave Stale Resize Context Behind

Current [ScreenshotTool.swift](frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/ScreenshotTool.swift) captures a specific `window_id`, but it does not update or clear `ImageResizeRegistry`.

Risk:

- The model calls `cua_get_window_state`, creating a resize ratio for a large downscaled image.
- Later it calls `cua_screenshot(window_id)` and reads coordinates from the raw screenshot image.
- A following pixel action may still use the older resize ratio, shifting the coordinate.

Fix later:

- Treat every image-producing tool as producing coordinate context.
- `cua_screenshot` should store a no-resize context or clear the resize ratio for `(pid, window_id)` after resolving the window owner.
- Make click/drag/zoom use the context attached to the image source, preferably by `(pid, window_id)`.

### 8. WindowCoordinateSpace Is The Correct Final Conversion Layer

Current [WindowCoordinateSpace.swift](frontend/coworker-mode/emu-driver/Sources/CuaDriverCore/Windows/WindowCoordinateSpace.swift) converts window-local image/native pixels to screen points using the window bounds and backing scale.

This layer is directionally correct. The issue is not the final backing-scale conversion itself; the risk is feeding it the wrong image-space coordinate because of stale/missing resize context, missing `window_id`, or a zoom crop from a different window.

### 9. Naming Note

The Swift path `CuaDriverCore/Windows` refers to application windows and window geometry, not Microsoft Windows OS support. The coworker driver being inspected here is the macOS Swift driver used by coworker mode.

## Fix Plan

### Phase 1: Tighten Model-Facing Instructions

- [ ] Update [backend/prompts/coworker_system_prompt.py](backend/prompts/coworker_system_prompt.py) to explicitly say `cua_zoom` should use the same `pid/window_id` as the source screenshot.
- [ ] Add a short warning that `from_zoom=true` coordinates must be paired with the same `window_id` as the zoom image.
- [ ] Keep AX-first instructions prominent: if `[element_index N]` exists in the latest tree, use it before pixels.
- [ ] Keep the no-manual-scaling rule explicit.

### Phase 2: Align Backend Tool Schemas With The Coordinate Contract

- [ ] Add optional `window_id` to the `cua_zoom` schema in [backend/tools/coworker_tools.py](backend/tools/coworker_tools.py).
- [ ] Update `cua_zoom` description to say its rectangle is measured from the latest `cua_get_window_state`/`cua_screenshot` image for the same `pid/window_id`.
- [ ] Update `from_zoom` descriptions for `cua_click` and `cua_drag` to say the same `window_id` should be supplied.
- [ ] Audit all `cua_*` pixel tools to ensure the schema never implies global screen coordinates, CSS pixels, normalized coordinates, or model-side scaling.

### Phase 3: Make Image Context Window-Scoped

- [ ] Replace the per-pid resize context in `ImageResizeRegistry` with a per-window context keyed by `(pid, window_id)`.
- [ ] Preserve a latest-per-pid fallback for old callers that omit `window_id`, but make the preferred path window-scoped.
- [ ] Add a `ScreenshotContext` or equivalent struct with:
  - `pid`
  - `window_id`
  - delivered image width/height
  - original/native width/height
  - resize ratio
  - backing scale factor
  - capture mode/source (`get_window_state`, `screenshot`, `zoom`)
  - capture timestamp or monotonic sequence
- [ ] Clear stale zoom context when a new base screenshot/window state is captured for the same `(pid, window_id)`.

### Phase 4: Use One Shared Pixel Coordinate Resolver

- [ ] Add a shared resolver, for example `PixelCoordinateResolver`, that accepts:
  - `pid`
  - optional `window_id`
  - `x/y` or endpoints
  - coordinate source: base image or zoom image
- [ ] The resolver should:
  - validate `window_id` belongs to `pid` when supplied
  - fetch the correct `(pid, window_id)` image context
  - convert delivered-image pixels to native window pixels using the stored ratio
  - convert native window pixels to screen points using `WindowCoordinateSpace`
  - reject or warn on missing context when the coordinate came from an image-producing tool
  - optionally bounds-check the coordinate against delivered image dimensions
- [ ] Use this resolver in:
  - `ClickTool`
  - `RightClickTool`
  - `DoubleClickTool`
  - `DragTool`
  - any future pixel-based cursor/action tools

### Phase 5: Fix Zoom Window Anchoring

- [ ] Add `window_id` support in [ZoomTool.swift](frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/ZoomTool.swift).
- [ ] When `window_id` is provided, capture that exact window at native resolution instead of `captureFrontmostWindow(pid:)`.
- [ ] Validate `window_id` owner matches `pid`.
- [ ] Store zoom context with `window_id`.
- [ ] In `ClickTool` and `DragTool`, if `from_zoom=true` and the user provided a mismatching `window_id`, return an error telling the model to use the zoom image's window.
- [ ] If `from_zoom=true` and `window_id` is omitted, use the stored zoom context's `window_id` as the anchor.

### Phase 6: Fix Screenshot Context Handling

- [ ] In [ScreenshotTool.swift](frontend/coworker-mode/emu-driver/Sources/CuaDriverServer/Tools/ScreenshotTool.swift), resolve the captured window's owner `pid`.
- [ ] Store or clear context for `(pid, window_id)` so raw screenshots do not reuse an older downscaled `get_window_state` ratio.
- [ ] Include enough response text/structured metadata for agents to know the coordinate space came from `cua_screenshot`.

### Phase 7: Documentation And Debuggability

- [ ] Update any stale internal comments that suggest callers should use `scaleFactor` themselves. `scaleFactor` should be diagnostic metadata, not an instruction for model-side conversion.
- [ ] Keep or expand `debug_image_out` for pixel clicks so a saved crosshair can verify the exact received coordinate against the source screenshot.
- [ ] Consider adding a debug response field for pixel actions showing:
  - input image coordinate
  - source window id
  - applied resize ratio
  - resolved native window pixel
  - resolved screen point

## Test Plan

### Static Tests

- [ ] Add unit tests for `ImageResizeRegistry` to verify separate contexts for two windows under the same pid.
- [ ] Add tests for resolver behavior when:
  - ratio is absent
  - ratio is present
  - `window_id` mismatches pid
  - zoom context exists but caller passes a different `window_id`
  - coordinate is outside delivered image bounds
- [ ] Add tests confirming `right_click` and `double_click` use the same coordinate conversion path as `click`.

### Manual/Integration Scenarios

- [ ] Retina display: use `cua_get_window_state`, pick a small visible target, then verify `cua_click`, `cua_right_click`, and `cua_double_click` all land on the same visual point.
- [ ] Non-Retina display: repeat the same checks.
- [ ] Multi-display mixed scale: place the target window on a display whose scale differs from the main display.
- [ ] Large browser window that triggers `max_image_dimension` downscaling: verify right-click and double-click no longer drift.
- [ ] Multi-window app: capture window A, make window B frontmost, then pixel-click window A with `window_id=A`; it should still resolve against A.
- [ ] `cua_screenshot` flow: capture a raw screenshot and click from it after a previous downscaled `cua_get_window_state`; stale ratio must not apply.
- [ ] `cua_zoom` flow: zoom from a specific window, click with `from_zoom=true`, and verify the same window is used.
- [ ] Moved/resized window: verify stale coordinates are rejected or fixed by forcing a fresh state.

### Validation Commands

Run these when implementing on macOS:

```bash
cd frontend/coworker-mode/emu-driver
swift test
swift build
```

Run repository checks from the workspace root:

```bash
git diff --check
```

Also use editor diagnostics on touched Python and Swift files.

## Acceptance Criteria

- [ ] The model-facing prompt and tool schemas consistently say AX first, pixels second.
- [ ] Every pixel tool accepts coordinates from the same screenshot coordinate space and resolves them the same way.
- [ ] `window_id` anchors pixel conversion whenever available.
- [ ] Resize ratio is never accidentally reused across windows.
- [ ] `cua_screenshot`, `cua_get_window_state`, and `cua_zoom` each create/maintain accurate coordinate context.
- [ ] `from_zoom=true` cannot silently use the wrong window.
- [ ] The model never needs to manually scale coordinates.
- [ ] Pixel fallback remains non-disruptive where the driver can keep actions pid-routed/background-safe.

## Open Questions

- Should pixel actions without `window_id` remain allowed as a compatibility fallback, or should they become soft errors after the model prompt and schemas are updated?
- Should the driver return a structured `coordinate_context_id` from image-producing tools so future calls can bind to an exact screenshot rather than just `(pid, window_id)`?
- Should `cua_screenshot` use the same `max_image_dimension` behavior as `cua_get_window_state`, or should it remain raw/native and explicitly store a no-resize context?
- Should coordinate bounds checking be strict, or should it warn but still dispatch for edge cases like window shadows and offscreen partial windows?
