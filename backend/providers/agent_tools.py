"""
providers/agent_tools.py

Shared agent tool definitions for all providers.

These are "thinking" tools the model calls server-side (plan, memory, skills,
context compression). Desktop actions (click, type, scroll) stay as JSON
text responses — they're dispatched to the Electron frontend.

Tools are defined once in OpenAI format. Helpers convert to Anthropic / Gemini
format as needed.
"""

import json

# ── OpenAI format (used by OpenRouter, OpenAI, OpenAI-compatible, Modal) ──────

AGENT_TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": (
                "Create or update your task plan (plan.md). "
                "MANDATORY before any desktop action. Write a full plan with "
                "Goal, Steps (numbered checkboxes), Risks, and Done-when criteria."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Full plan content in markdown",
                    }
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_plan",
            "description": (
                "Read your current task plan to re-orient. "
                "Call when unsure what to do next or to check progress."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_skill",
            "description": (
                "Load a skill's full instructions by name. "
                "Skills are listed in the workspace context under <skills>."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill to load",
                    }
                },
                "required": ["skill_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_session_file",
            "description": (
                "Write or overwrite a temporary .md file in the current session. "
                "Use this heavily to store intermediate research, notes, scraped text, "
                "or data you need to remember across steps. Just specify a filename (e.g. 'notes.md')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to create/overwrite (e.g. 'research_draft.md')"
                    },
                    "content": {
                        "type": "string",
                        "description": "The markdown content to write to the file"
                    }
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_session_file",
            "description": (
                "Read the content of a temporary .md file you wrote earlier in this session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to read"
                    }
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_session_files",
            "description": (
                "List all files currently saved in your session workspace."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_memory",
            "description": (
                "Save observations, decisions, or user preferences to persistent memory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "What to save",
                    },
                    "target": {
                        "type": "string",
                        "enum": ["daily_log", "long_term", "preferences"],
                        "description": "Memory target (default: daily_log)",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compact_context",
            "description": (
                "Compress conversation history when it's getting long. "
                "Call when you've taken many steps and context feels bloated."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {
                        "type": "string",
                        "description": "What to prioritize in the summary (optional)",
                    }
                },
            },
        },
    },
]


# ── Anthropic format (used by Claude provider) ────────────────────────────────

def tools_for_anthropic() -> list[dict]:
    """Convert to Anthropic tool format."""
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in AGENT_TOOLS_OPENAI
    ]


# ── Google Gemini format ──────────────────────────────────────────────────────

def tools_for_gemini():
    """Convert to google-genai types. Import here to avoid hard dep."""
    from google.genai import types

    declarations = []
    for t in AGENT_TOOLS_OPENAI:
        fn = t["function"]
        params = fn["parameters"]
        props = params.get("properties", {})
        required = params.get("required", [])

        schema_props = {}
        for k, v in props.items():
            schema_kwargs = {"type": v["type"].upper(), "description": v.get("description", "")}
            if "enum" in v:
                schema_kwargs["enum"] = v["enum"]
            schema_props[k] = types.Schema(**schema_kwargs)

        declarations.append(
            types.FunctionDeclaration(
                name=fn["name"],
                description=fn["description"],
                parameters=types.Schema(
                    type="OBJECT",
                    properties=schema_props,
                    required=required,
                ) if schema_props else None,
            )
        )

    return [types.Tool(function_declarations=declarations)]


# ── Helper: set of agent tool names (for quick lookup) ────────────────────────

AGENT_TOOL_NAMES = {t["function"]["name"] for t in AGENT_TOOLS_OPENAI}
