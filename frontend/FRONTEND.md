# Frontend Reference

Frontend is an Electron renderer app under `frontend/` with modular UI, service, and action layers.

## Main structure

- `app.js`: app bootstrap and page mount.
- `pages/Chat.js`: chat orchestration and user interaction.
- `components/`: reusable UI modules.
- `services/api.js`: HTTP backend calls.
- `services/websocket.js`: realtime event channel.
- `state/store.js`: centralized client state.
- `actions/`: desktop action bridge (renderer -> main process handlers).
- `process/psProcess.js`: persistent shell process manager.

## Action execution path

1. Backend returns desktop action payload.
2. Frontend maps action type in `actions/actionProxy.js`.
3. Renderer invokes IPC handler.
4. Main process executes OS command path and returns result.
5. Frontend posts action completion back to backend.

## Action modules

Key handlers include:

- screenshot and full capture
- pointer move/click variants
- drag and scroll
- keyboard typing and keypress
- window controls

## State model

The store tracks:

- active chat/session identifiers
- generation status (`isGenerating`, stop state)
- websocket connection state
- message timeline
- side panel and UI mode flags

## UI redesign status

The frontend styling/layout is being aligned to the redesign specification in `FRONTEND_REDESIGN.md` with:

- tokenized styles in `frontend/styles/`
- chrome/conversation/frame CSS separation
- cleaner state-driven frame rendering

## Startup

Preferred:

```bash
./frontend.sh
```

Manual:

```bash
npm install
npm start
```

## Common frontend issues

## Blank responses or no updates

- Backend not reachable on `127.0.0.1:8000`.
- WebSocket session mismatch.

## Unauthorized API calls

- Token mismatch between frontend and backend process.

## Desktop actions not firing

- Missing OS permissions (especially on macOS).
- IPC handler not registered or action map mismatch.

## Inconsistent UI state after failures

- Verify `isGenerating` and stop/reset transitions in page/store logic.
