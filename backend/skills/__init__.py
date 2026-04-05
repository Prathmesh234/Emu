"""
backend/skills/__init__.py

Skills system for Emu — adapted from OpenClaw's architecture.

Skills are self-contained markdown files (SKILL.md) with YAML frontmatter
that teach the agent how to perform specific tasks. Only metadata (name +
description) is injected into the system prompt; the full body loads on demand.

Public API:
  - load_skills()           → list[Skill]
  - format_skills_for_prompt(skills) → str
  - get_skill_body(name)    → str | None
"""

from .loader import load_skills, format_skills_for_prompt, get_skill_body, Skill

__all__ = [
    "load_skills",
    "format_skills_for_prompt",
    "get_skill_body",
    "Skill",
]
