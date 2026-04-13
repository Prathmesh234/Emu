from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._sockets: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, ws: WebSocket):
        await ws.accept()
        self._sockets[session_id] = ws
        print(f"[ws] connected  session={session_id}")

    def disconnect(self, session_id: str):
        self._sockets.pop(session_id, None)
        print(f"[ws] disconnected session={session_id}")

    async def send(self, session_id: str, message: dict):
        ws = self._sockets.get(session_id)
        if ws:
            await ws.send_json(message)
