import re
from datetime import datetime
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


def _redact(text: str) -> str:
    """Scrub sensitive patterns from a log string."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def log_entry(session_id: str, entry: str) -> None:
    """Append a timestamped line to .emu/sessions/<id>/logs/conversation.log"""
    from workspace import get_sessions_dir
    log_dir = get_sessions_dir() / session_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H:%M:%S")
    safe_entry = _redact(entry)
    with open(log_dir / "conversation.log", "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {safe_entry}\n")


async def log_and_send(session_id: str, entry: str, manager: ConnectionManager) -> None:
    """Log + push to frontend via websocket."""
    log_entry(session_id, entry)
    await manager.send(session_id, {"type": "log", "message": entry})
