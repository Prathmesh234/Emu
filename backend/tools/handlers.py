from pathlib import Path
from workspace import read_session_plan, write_session_plan, read_memory, read_daily_memory
from skills import get_skill_body


def handle_read_plan(session_id: str) -> str:
    """Handle the model's read_plan tool call."""
    plan = read_session_plan(session_id)
    if plan:
        return f"[YOUR PLAN]\n{plan}"
    return "No plan.md found for this session. You may need to create one."


def handle_update_plan(session_id: str, content: str) -> str:
    """Handle the model's update_plan tool call."""
    if not content:
        return "No content provided for plan update."
    write_session_plan(session_id, content)
    return "Plan updated successfully."


def handle_read_memory(target: str = "long_term") -> str:
    """Handle the model's read_memory tool call."""
    try:
        if target == "long_term":
            content = read_memory()
            if content:
                return f"[MEMORY.md]\n{content}"
            return "MEMORY.md is empty or does not exist yet."
        elif target == "preferences":
            _backend_dir = Path(__file__).parent.parent
            _project_root = _backend_dir.parent
            prefs_path = _project_root / ".emu" / "global" / "preferences.md"
            if prefs_path.exists():
                content = prefs_path.read_text(encoding="utf-8").strip()
                if content:
                    return f"[preferences.md]\n{content}"
            return "preferences.md is empty or does not exist yet."
        elif target == "daily_log":
            content = read_daily_memory()
            if content:
                return f"[Today's daily log]\n{content}"
            return "No daily log for today yet."
        else:
            return f"Unknown memory target: {target}. Use long_term, preferences, or daily_log."
    except Exception as e:
        return f"Memory read failed: {e}"


def handle_use_skill(skill_name: str) -> str:
    """Handle the model's use_skill tool call — load full skill body on demand."""
    from skills import load_skills
    available = [s.name for s in load_skills()]
    available_str = ", ".join(available) if available else "(none)"

    if not skill_name or skill_name.strip() in ("", ":", ": "):
        return (
            f"No valid skill name provided. "
            f"Available skills: {available_str}. "
            f"Call use_skill with one of these exact names."
        )
    body = get_skill_body(skill_name)
    if body:
        return f"[SKILL: {skill_name}]\n\n{body}"
    return (
        f"Skill '{skill_name}' not found. "
        f"Available skills: {available_str}. "
        f"Use one of these exact names."
    )
