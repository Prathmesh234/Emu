from datetime import datetime
from .connection import ConnectionManager


def log_entry(session_id: str, entry: str) -> None:
    """Append a timestamped line to .emu/sessions/<id>/logs/conversation.log"""
    from workspace import get_sessions_dir
    log_dir = get_sessions_dir() / session_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H:%M:%S")
    with open(log_dir / "conversation.log", "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {entry}\n")


async def log_and_send(session_id: str, entry: str, manager: ConnectionManager) -> None:
    """Log + push to frontend via websocket."""
    log_entry(session_id, entry)
    await manager.send(session_id, {"type": "log", "message": entry})
