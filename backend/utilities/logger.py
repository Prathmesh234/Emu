import json
import re
from datetime import datetime
from pathlib import Path
from .connection import ConnectionManager

# Patterns that match sensitive data in log entries
_REDACT_PATTERNS = [
    # API keys / tokens (common prefixes)
    (re.compile(r'(sk-[a-zA-Z0-9]{20,})', re.IGNORECASE), '[REDACTED_API_KEY]'),
    (re.compile(r'(AKIA[A-Z0-9]{16,})', re.IGNORECASE), '[REDACTED_AWS_KEY]'),
    (re.compile(r'(ghp_[a-zA-Z0-9]{36,})', re.IGNORECASE), '[REDACTED_GH_TOKEN]'),
    (re.compile(r'(ghu_[a-zA-Z0-9]{36,})', re.IGNORECASE), '[REDACTED_GH_TOKEN]'),
    (re.compile(r'(xox[bpas]-[a-zA-Z0-9-]+)', re.IGNORECASE), '[REDACTED_SLACK_TOKEN]'),
    # Bearer tokens in headers
    (re.compile(r'(Bearer\s+[a-zA-Z0-9._\-]{20,})', re.IGNORECASE), 'Bearer [REDACTED]'),
    # Generic password-like patterns
    (re.compile(r'(password\s*[:=]\s*)\S+', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(secret\s*[:=]\s*)\S+', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(api_key\s*[:=]\s*)\S+', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(token\s*[:=]\s*)\S+', re.IGNORECASE), r'\1[REDACTED]'),
    # Base64 screenshot data (truncate rather than log full payload)
    (re.compile(r'(data:image/[^;]+;base64,).{100,}'), r'\1[BASE64_TRUNCATED]'),
]

# ── Role tag regex: extract [user], [assistant], [tool] prefix from entry ────
_ROLE_RE = re.compile(r'^\[(\w+)\]\s*(.*)$', re.DOTALL)


def _redact(text: str) -> str:
    """Scrub sensitive patterns from a log string."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _parse_role(entry: str) -> tuple[str, str]:
    """Extract role and content from a log entry like '[user] hello'."""
    m = _ROLE_RE.match(entry)
    if m:
        return m.group(1), m.group(2)
    return "system", entry


def _conversation_path(session_id: str) -> Path:
    """Return the path to .emu/sessions/<id>/logs/conversation.json"""
    from workspace import get_sessions_dir
    log_dir = get_sessions_dir() / session_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "conversation.json"


def _load_conversation(path: Path) -> dict:
    """Load existing conversation JSON, or return a fresh structure."""
    if path.exists() and path.stat().st_size > 0:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"messages": []}


def _save_conversation(path: Path, data: dict) -> None:
    """Atomically write the conversation JSON."""
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def log_entry(session_id: str, entry: str, metadata: dict | None = None) -> None:
    """Append a structured JSON message to .emu/sessions/<id>/logs/conversation.json"""
    safe_entry = _redact(entry)
    role, content = _parse_role(safe_entry)
    ts = datetime.now().strftime("%H:%M:%S")

    path = _conversation_path(session_id)
    data = _load_conversation(path)

    next_index = len(data["messages"]) + 1
    msg = {
        "index": next_index,
        "role": role,
        "timestamp": ts,
        "content": content,
    }
    if metadata:
        msg["metadata"] = metadata

    data["messages"].append(msg)
    _save_conversation(path, data)


async def log_and_send(session_id: str, entry: str, manager: ConnectionManager, metadata: dict | None = None) -> None:
    """Log + push to frontend via websocket."""
    log_entry(session_id, entry, metadata)
    await manager.send(session_id, {"type": "log", "message": entry})
