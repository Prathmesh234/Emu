# Frontend Architecture (v0.1)

The core philosophy of this frontend is **reusability**. Every UI element should be a self-contained component that can be imported, composed, and reused across different parts of the application. This reduces code duplication, improves maintainability, and makes it easier to build new features by combining existing components.

## Directory Structure

```
frontend/
├── app.js                 # Minimal entry point — mounts the active page
├── index.html             # HTML shell
├── styles.css             # Global styles
├── state/
│   └── store.js           # Centralized state management
├── services/
│   ├── api.js             # HTTP API calls to backend
│   └── websocket.js       # WebSocket connection management
├── pages/
│   ├── index.js           # Page exports
│   └── Chat.js            # Chat page (messages, input, WS handler, actions)
├── components/            # Reusable UI components
│   ├── index.js           # Component exports
│   ├── Button.js          # Button with icon support
│   ├── ChatInput.js       # Text input with send button
│   ├── Message.js         # Chat message bubble
│   ├── Sidebar.js         # Navigation sidebar
│   ├── StepCard.js        # Agent step display (screenshot, reasoning, action)
│   └── Tooltip.js         # Hover tooltip wrapper
├── actions/               # IPC action handlers
│   ├── index.js           # Action registration
│   ├── actionProxy.js     # Action dispatcher and mapping
│   ├── screenshot.js      # Screen capture
│   ├── fullCapture.js     # Full screen capture (excludes panel)
│   ├── leftClick.js       # Left click action
│   ├── rightClick.js      # Right click action
│   ├── leftClickOpen.js   # Double click action
│   ├── navigate.js        # Mouse move action
│   ├── scroll.js          # Scroll action
│   └── window.js          # Window positioning
└── process/
    └── psProcess.js       # Persistent shell process manager (zsh on macOS, bash on Linux)
```

## Components

### Core Components

| Component | File | Description |
|-----------|------|-------------|
| `Button` | `Button.js` | Reusable button with SVG icon support |
| `ChatInput` | `ChatInput.js` | Text area with send button and tooltip integration |
| `Message` | `Message.js` | Chat message bubble (user/assistant variants) |
| `StepCard` | `StepCard.js` | Displays agent step with screenshot, reasoning, and action |
| `DoneCard` | `StepCard.js` | Task completion card |
| `ErrorCard` | `StepCard.js` | Error display card |
| `Tooltip` | `Tooltip.js` | Wraps any element with a hover tooltip |
| `Sidebar` | `Sidebar.js` | Chat history navigation |

### Component Pattern

All components follow the same pattern:

```javascript
function ComponentName(props) {
    const element = document.createElement('div');
    // ... build DOM structure
    return {
        element,           // The DOM element to append
        // ... any methods to update the component
    };
}

module.exports = { ComponentName };
```

### Recent Additions

**Tooltip Component** (`Tooltip.js`)
- Wraps any element with a tooltip
- Automatically shows tooltip when the wrapped element is disabled
- Methods: `setText(text)`, `show()`, `hide()`, `destroy()`

**StepCard Component** (`StepCard.js`)
- Displays agent processing steps
- Shows screenshot thumbnail (click to expand)
- Displays reasoning and action with confidence indicator
- Handles error states with `onerror` fallback

**ChatInput Updates** (`ChatInput.js`)
- Integrated Tooltip component for send button
- Exposes `setTooltip(text)` method for dynamic tooltip updates

## Actions

The `actions/` directory contains IPC handlers that bridge the renderer process with the main process. Each action file exports:

1. A renderer-side function to invoke the action
2. A `register()` function to set up the IPC handler

**actionProxy.js** maps backend `ActionType` values to frontend handlers:

| Action Type | Handler | Description |
|-------------|---------|-------------|
| `screenshot` | `captureScreenshot()` | Capture current screen |
| `left_click` | `leftClick(x, y)` | Left click at coordinates |
| `right_click` | `rightClick(x, y)` | Right click at coordinates |
| `double_click` | `leftClickOpen(x, y)` | Double click at coordinates |
| `mouse_move` | `navigateMouse(x, y)` | Move cursor to coordinates |
| `scroll` | `scroll(x, y, dir, amt)` | Scroll at position |
| `type_text` | (special handling) | Type text string |
| `key_press` | (special handling) | Press key with modifiers |
| `wait` | `setTimeout()` | Pause execution |
| `done` | (no action) | Task complete signal |

## State Management

Centralized in `state/store.js`. All state lives in a single `state` object; components read from it and call mutation functions to update.

| State | Purpose |
|-------|---------|
| `chats` | Array of chat conversations |
| `currentChatId` | Active chat ID |
| `isGenerating` | Whether agent is processing |
| `isSidePanel` | Whether window is in side-panel mode |
| `sessionId` | Backend session ID |
| `ws` | WebSocket connection |
| `currentAssistantEl` | Current assistant message element |
| `currentChat` | Current chat object reference |

**Key functions:** `createChat()`, `setCurrentChat()`, `pushMessage()`, `truncateMessages()`, `getLastUserMessage()`.

## Services

| Service | File | Purpose |
|---------|------|---------|
| API | `services/api.js` | HTTP calls — `createSession()`, `postStep()`, `notifyActionComplete()` |
| WebSocket | `services/websocket.js` | WS connection, reconnect, message routing |

## Pages

| Page | File | Description |
|------|------|-------------|
| Chat | `pages/Chat.js` | Full chat UI — messages, input, status, WS handling, action execution |

Pages expose a `mount(appEl)` function. `app.js` calls `Chat.mount(app)` to render.

### Helper Functions

**`syncGeneratingUI(boolean)`** - Manages the generating state and send button:
- When `true`: Disables send button, shows processing tooltip
- When `false`: Enables send button, clears tooltip

## WebSocket Integration

The frontend maintains a WebSocket connection to receive real-time updates:

```javascript
initWebSocket(sessionId)  // Connect to ws://localhost:8000/ws/{sessionId}
```

**Message Types:**
- `status` - Show status indicator
- `step` - Display agent step (screenshot, reasoning, action)
- `done` - Task completion
- `error` - Error display

---

## FUTURE

### 1. Modular App Architecture  ✅ DONE

Implemented — `app.js` is now a minimal entry point. State lives in `state/store.js`, HTTP calls in `services/api.js`, WebSocket management in `services/websocket.js`, and the chat UI in `pages/Chat.js`.

### 2. Simplified UI

**Current State:** StepCard shows screenshot, reasoning, action, confidence, and status badge - too much information for most users.

**Goals:**
- Remove reasoning section (or make it collapsible/hidden by default)
- Simplify completion messages (no "after X steps")
- Cleaner, more minimal step cards
- Focus on what the agent is doing, not how it's thinking

**Possible Design:**
```
┌─────────────────────────────┐
│ [Screenshot thumbnail]      │
│ Clicking "Submit" button    │  ← Simple action description
│ ✓ Done                      │  ← Status only
└─────────────────────────────┘
```

### 3. Dynamic/Flexible UI

**Goals:**
- Resizable panels (drag to resize chat vs preview areas)
- Collapsible sections (minimize chat history, expand screenshot)
- Detachable windows (pop out screenshot viewer)
- Keyboard shortcuts for common actions
- Responsive layout for different window sizes
- Remember user's layout preferences

**Components to Add:**
- `Resizer` - Draggable divider between panels
- `Collapsible` - Expandable/collapsible container
- `Modal` - Popup dialog/lightbox for screenshots
- `Tabs` - Tab navigation component

### 4. General UX Improvements

**Accessibility:**
- Keyboard navigation throughout
- Screen reader support
- High contrast mode
- Focus indicators

**Feedback:**
- Loading skeletons instead of spinners
- Optimistic UI updates
- Better error messages with recovery options
- Toast notifications for background events

**Polish:**
- Smooth animations and transitions
- Consistent spacing and typography
- Dark mode support
- Customizable themes

**Performance:**
- Virtual scrolling for long chat histories
- Lazy load screenshots
- Debounced input handling
- Efficient DOM updates (consider virtual DOM library)
