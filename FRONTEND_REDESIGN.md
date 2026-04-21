# Frontend Redesign — Emu Handoff Implementation Plan

## Status Update (April 2026)

- The frontend is now actively using the modular style architecture under `frontend/styles/`.
- The store/services/action split is in place and is the baseline for new UI work.
- Documentation in `frontend/FRONTEND.md` now reflects the current module boundaries.
- Remaining redesign work should be treated as incremental frame parity and polish, not a greenfield rewrite.

Ground truth: `Emu-handoff.zip → project/Emu Frames.html` plus the shared chrome + frame JSX files in `project/frames/`. Everything in this doc derives from those five source files.

**Non-goals.** No backend changes. No tech-stack migration (staying vanilla JS / `Component.mount()` / Electron renderer). No Sign-in / Onboarding / Permissions frames (deferred — not in current Emu).

**Scope in one sentence:** replace 18 legacy components + a monolithic 1,110-line `Chat.js` + 1,403-line `styles.css` with a token-driven, component-based UI that renders 10 frames from the handoff. All existing WebSocket / IPC / action dispatch wiring stays intact.

---

## 1. Design tokens (verbatim from `design-emu/tokens.css`)

### Color palette

**Linen (light) — default:**
| Token | Value |
|---|---|
| `--paper` | `#ede7d8` |
| `--ink` | `#221e16` |
| `--ink-55` | `rgba(34, 30, 22, 0.55)` |
| `--ink-30` | `rgba(34, 30, 22, 0.30)` |
| `--ink-22` | `rgba(34, 30, 22, 0.22)` |
| `--ink-14` | `rgba(34, 30, 22, 0.14)` |
| `--ink-08` | `rgba(34, 30, 22, 0.08)` |
| `--wash` | `#1f1d18` (canvas behind windows) |

**Ink (dark) — toggled via `.ink` on `<body>`:**
| Token | Value |
|---|---|
| `--paper` | `#15140f` |
| `--ink` | `#ede7d8` |
| `--ink-55/30/22/14/08` | same alpha on `(237, 231, 216)` |
| `--wash` | `#0e0d0a` |

Every color in the UI resolves through these seven variables. No other colors allowed.

### Typography

| Family | Use | Google Fonts |
|---|---|---|
| Instrument Serif | display, italics, labels, hint text, "Emu" / "You" | `ital@0;1` |
| Inter Tight | body copy, buttons, UI metadata | `wght@400;500` |

**Scale:** 11 / 13 / 15 / 17 / 19 / 22 / 28 / 36 / 44 / 56 / 64

**Italic serif is the voice** — all labels ("You", "Emu", "ready", "working"), hints, section headers, and status copy are Instrument Serif italic. Body is Inter Tight.

### Motion

- `--ease: cubic-bezier(.2, .6, .2, 1)`
- `@keyframes emuPulse` — 1.8s ease-in-out infinite (status dot)
- `@keyframes emuBlink` — 1s steps(1) infinite (caret/cursor)

### Radii

- `--radius-sm: 3px` (small buttons)
- `--radius: 4px` (cards, inputs, primary buttons)
- `--radius-lg: 10px` (mac-window)

### Theme switch

- Handoff uses `.ink` on `<body>`. Current app uses `.dark` on `#app`.
- **Decision:** rename current class to `.ink`. One-line change in `app.js` + `store.js`. Matches handoff tokens directly; no aliasing layer needed.

---

## 2. Shared chrome components (net-new)

These live in `frontend/components/chrome/` and are the structural primitives every frame reuses.

### `MacWindow`
The whole app-window shell. Mac traffic-light dots (monochrome rings, not colored), centered italic-serif title, 10px radius, subtle shadow, 1px `--ink-14` border. Host for all body content.

### `WindowHeader`
`"Emu"` mark on the left (italic serif, size 22, letter-spacing -0.2), status pill on the right (italic serif size 14, a 5×5 dot that pulses when live). States: `ready` / `working` / `waiting` / `finished` / `stopped`.

### `WindowBody`
Flex column, 48px gap, `padding: 48px 40px 32px`. Two modes: `centered` (for Idle/Composing greeting) and `left` (for Working/Finished/etc conversation stream).

### `Composer`
Replaces `ChatInput.js`. Borderless text field with italic-serif placeholder, italic-serif "send" / "stop" button, optional `hint` slot above (with pulsing dot), 1px top border only. States: `idle` / `working` / `done` / `confirm` / `disabled`. The "stop" verb only appears in `working` state.

### `You`
User turn block. Italic serif "You" label above a size-19 paragraph, 1.4 line-height, 560px max-width.

### `Emu`
Agent turn block. Italic serif "Emu" label above size-17 body, 1.6 line-height, 560px max-width.

### `Trace`
The "Emu's thinking / doing" stream. Left border (`--ink-14`), 18px left-padding, italic serif size-15, 1.75 line-height, `--ink-55` color. Optional blinking caret when live.

### `Sidebar` (for Working + Sidebar frame)
240px fixed width, 1px right-border `--ink-14`, sections: "Emu" mark → "+ new session" → grouped sessions (Today / Yesterday / Earlier). Active session gets a pulsing dot + `--ink-08` background. Bottom: user avatar (22px circle, `--ink` bg, `--paper` letter) + name.

---

## 3. Frame → current-page mapping

Current Emu has exactly one page (`Chat.js`). The new design cuts that page into named *states* that render different frame layouts. No new routes; the backend-facing behavior is identical.

| Handoff frame | Maps to | Trigger |
|---|---|---|
| **04 Idle** | empty chat, no session active | app launch with no chats |
| **05 Composing** | user is typing before submit | input focused + non-empty |
| **06 Working** | agent is generating, sidebar hidden | `store.state.isGenerating === true && !sidebarOpen` |
| **06b Working + Sidebar** | same + sessions sidebar open | `isGenerating && sidebarOpen` |
| **07 Confirm** | agent paused on shell_exec or sensitive action | `requires_confirmation === true` |
| **08 Finished** | last step was `done: true` | `response.done` |
| **09 Artifact** | user clicks a session file from sidebar | new "viewing artifact" state |
| **10 History** | user clicks history button | `_historyPanelOpen === true` (already wired) |
| **11 Error / paused** | step errored or was stopped | `store.state.isStopped` or error message received |
| **12 Settings** | user clicks settings icon | new route (modal or full-frame — see §7) |

The existing `Chat.js` state machine (`isGenerating`, `isStopped`, `_historyPanelOpen`) already drives most of this — we're restyling and restructuring, not rewriting flow logic.

---

## 4. Component inventory — old vs new

### Keep and restyle
| Current | New role |
|---|---|
| `Button.js` | internal utility; restyle defaults to token-driven |
| `Tooltip.js` | keep, restyle to quiet aesthetic |
| `StatusIndicator.js` | absorbed by `WindowHeader`'s status pill |

### Replace (same responsibility, new look)
| Current | Replacement |
|---|---|
| `Header.js` | `WindowHeader` (net-new) |
| `ChatInput.js` | `Composer` (net-new) |
| `Sidebar.js` | `Sidebar` (net-new, per §2) |
| `Message.js` | `You` + `Emu` pair (net-new) |
| `HistoryPanel.js` | `HistoryFrame` (grouped Today / Yesterday / Earlier) |
| `EmptyState.js` | `IdleFrame` greeting block |
| `PanelButton.js` + `PanelToggle.js` | merged into sidebar items |

### Fold into `Trace`
These currently render as separate boxy cards; handoff absorbs them into a single italic-serif trace stream with left border.

| Current | New role |
|---|---|
| `StepCard.js` | `Trace` line ("opening Resy") |
| `PlanCard.js` | `Trace` block with heavier weight first line |
| `FileCard.js` | `Trace` line + underlined filename link |
| `SkillCard.js` | `Trace` line ("using skill: web-search") |

### Net-new
| Name | Purpose |
|---|---|
| `MacWindow` | outer window chrome |
| `WindowHeader` | top bar with title + status |
| `WindowBody` | scrollable flex container |
| `Composer` | input (replaces `ChatInput`) |
| `You` / `Emu` / `Trace` | conversation turn blocks |
| `Greeting` | "Good afternoon, Prathmesh" block (Idle/Composing) |
| `ConfirmCard` | table-of-details card (Confirm frame) |
| `ActionRow` | 1-3 button row (Confirm / Error frames) |
| `ArtifactView` | screenshot placeholder + bulleted list |
| `HistoryList` | grouped-by-date session list |
| `SettingsList` | grouped-by-section setting rows |

**Net change in file count:** drops from 18 → ~17 components but each is tighter and single-responsibility. `Chat.js` goes from 1,110 lines → estimated ~350 once the frame composition moves into named state-renderers.

### `EmuRunner.js`
Pure IPC glue (no UI). Untouched by this refactor.

---

## 5. Style architecture

Replace the single 1,403-line `styles.css` with:

```
frontend/styles/
├── tokens.css              # design tokens (§1) — lifted verbatim from handoff
├── base.css                # body, scrollbars, font-face @import, reset
├── chrome/
│   ├── mac-window.css
│   ├── window-header.css
│   ├── window-body.css
│   └── composer.css
├── conversation/
│   ├── you.css
│   ├── emu.css
│   └── trace.css
├── frames/
│   ├── idle.css            # greeting block
│   ├── confirm.css         # details card + action row
│   ├── artifact.css        # screenshot + list
│   ├── history.css         # grouped list
│   └── settings.css        # grouped rows
├── sidebar.css
├── animations.css          # emuPulse, emuBlink, ease
└── index.css               # @imports the above in order
```

`index.html` imports a single `styles/index.css`. No inline `<style>`s. All colors via `var(--token)`.

**Dark mode:** `.ink` on `<body>` re-binds the seven CSS variables. Zero component code changes needed for theme switching.

---

## 6. Phased implementation (reviewable chunks)

Each phase is independently shippable and independently reviewable. Backend and WebSocket behavior are identical after every phase.

| Phase | Deliverable | Risk |
|---|---|---|
| **1** | `styles/tokens.css` + `base.css`. Fonts loaded. `<body>` picks up paper/ink colors. No component changes. | Near-zero — pure stylesheet addition. |
| **2** | `MacWindow` / `WindowHeader` / `WindowBody` components. Wrap existing `Chat.js` content in new chrome. Old components still render inside. | Low — structural wrapper only. |
| **3** | `Composer` replacing `ChatInput`. Preserve all existing handlers (onSubmit, onStop, onTooltipChange). | Low — isolated component swap. |
| **4** | `You` / `Emu` / `Trace` replacing `Message` + the four card components. Markdown renderer reused as-is. | Medium — touches per-turn rendering. |
| **5** | `Idle` greeting + `Composing` behavior. Empty state restyled. | Low. |
| **6** | New `Sidebar` layout. Reuse existing session-history data. | Medium — sidebar state hook-up. |
| **7** | `ConfirmCard` / `ActionRow` for the Confirm and Error frames. Replaces current confirmation UI. | Low — contained rewrite. |
| **8** | `HistoryFrame` / `ArtifactView` / `SettingsList`. Last round. | Low. |
| **9** | Delete `styles.css` (legacy), remove retired components, drop `EmptyState.js` / `HistoryPanel.js` / `StepCard.js` / `PlanCard.js` / `FileCard.js` / `SkillCard.js` / `PanelButton.js` / `PanelToggle.js` / `StatusIndicator.js`. | Low — dead-code removal. |

Ship order ensures that at every intermediate commit the app still works and looks consistent (new chrome + old cards visually coexist until phase 4).

---

## 7. Ambiguous bits (where I'll use judgment unless you correct me)

1. **Settings frame routing.** Handoff shows a full-window Settings screen. Current app has no settings route. I'll render it as a full-window state (replaces chat view while open), with an `X` in the title to return — not as a modal. Can revisit if you want a modal.

2. **"Artifact" frame trigger.** Handoff shows a result screen with a screenshot placeholder. Current app surfaces session files via `FileCard` in the stream. I'll wire it so clicking a file in the new `Trace` opens `ArtifactView` as a full-window state.

3. **"Good afternoon, Prathmesh"** is the Idle frame greeting. I'll pull the name from `process.env.USER` (Electron has access). If you want something else (user-configured name), tell me.

4. **Session groupings in sidebar.** Handoff shows `Today` / `Yesterday` / `Earlier`. Current backend returns `last_active` as a unix timestamp. I'll bucket client-side in `Sidebar` render. Pure UI.

5. **Fonts loaded from Google Fonts.** Handoff does this. The app is offline-friendly Electron, so this is a real network dep at first paint. If you want self-hosted fonts, tell me — I can bundle `.woff2` files instead.

6. **Existing dark-mode toggle.** Current key: `emu-dark-mode` in localStorage, `.dark` class. New key: same storage key (no user data loss), class renamed to `.ink`. Completely internal migration.

---

## 8. What comment to put on changed files

Every modified or new file gets a short header comment explaining the design origin, because this is a large refactor. Template:

```js
// <filename> — <purpose>
//
// Part of the Emu Design System v1 refactor (see FRONTEND_REDESIGN.md).
// Design source: Emu-handoff.zip → project/<source-file>.
// Tokens: --paper, --ink, --ink-{55|30|22|14|08}. Fonts: Instrument Serif, Inter Tight.
```

For retired files being deleted: no comment; just delete.

---

## 9. Zero backend contact

This refactor changes nothing in:
- `backend/` (API endpoints, provider wiring, WebSocket protocol)
- `frontend/services/` (api, websocket clients) — wire formats identical
- `frontend/state/` (store) — shape unchanged, only `.dark` → `.ink` class token
- `frontend/actions/` (IPC dispatch) — untouched
- `frontend/emu/` (init + session handling) — untouched

If at any point a UI change seems to require a backend change, stop and ask — that's a scope escape.

---

## 10. Open questions I need you to answer before I start coding

1. **§7.1 — Settings as full-window state vs modal?** (Default: full-window.)
2. **§7.3 — Greeting name source: `process.env.USER` (e.g. "Prathmesh") or something user-configured?** (Default: `process.env.USER`.)
3. **§7.5 — Google Fonts or self-host?** (Default: Google Fonts, consistent with handoff.)
4. **Rollout: all nine phases before I stop, or checkpoint with you after phase 3?** (Default: checkpoint after phase 3 so you can review the chrome + composer before the conversation layer gets redone.)

Answer these and I'll start Phase 1.
