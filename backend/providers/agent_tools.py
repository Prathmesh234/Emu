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
                "Call BEFORE any desktop action on complex tasks (3+ steps). "
                "Include Goal, Steps (numbered checkboxes), and Done-when criteria."
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
                "Call when unsure what to do next, when stuck, or to verify progress."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_skill",
            "description": (
                "Load a skill's full instructions by name. Skills contain step-by-step "
                "guides, keyboard shortcuts, and pitfalls for specific apps (Gmail, Excel, "
                "Chrome, etc.). ALWAYS check available skills before attempting app-specific "
                "tasks — they are listed under '## Skills (mandatory)' in workspace context."
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
                "Save data to a session file. You MUST call this after seeing any factual "
                "information on screen (names, dates, numbers, URLs, emails, meeting times). "
                "If you have taken 3+ screenshot actions without writing anything down, STOP "
                "and call this NOW. Do NOT rely on memory."
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
                "Read a session file you saved earlier. Call BEFORE reporting "
                "results to the user, and when resuming work after switching apps."
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
            "name": "read_memory",
            "description": (
                "Read a memory file from the .emu workspace. "
                "Use to recall past learnings, preferences, or daily logs. "
                "Target: long_term (MEMORY.md), preferences (preferences.md), daily_log (daily log — pass date for past days)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["long_term", "preferences", "daily_log"],
                        "description": "Which memory to read (default: long_term)",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date for daily_log in YYYY-MM-DD format (default: today). Ignored for other targets.",
                    },
                },
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
    {
        "type": "function",
        "function": {
            "name": "invoke_hermes",
            "description": (
                "Delegate a heavy generation, transformation, or codified task to "
                "Hermes Agent (Nous Research) — an autonomous terminal agent that "
                "runs locally. Hermes is invoked HEADLESSLY in the background "
                "(via `hermes chat -q`); you do NOT need to open or focus a "
                "terminal. Hermes's stdout is returned to you as the tool result.\n\n"
                "USE THIS WHEN the next step is far easier in code/shell than in a GUI:\n"
                "  • Building a PowerPoint from scratch (slide structure, bullets, "
                "speaker notes, programmatic .pptx via python-pptx).\n"
                "  • Complex Excel work — multi-sheet workbooks, formulas across "
                "hundreds of rows, pivoting/merging CSVs into .xlsx.\n"
                "  • Generating a Word/PDF/Markdown report from raw notes.\n"
                "  • Multi-file code edits, refactors, debugging from logs.\n"
                "  • Bulk file renaming, conversion, ZIP/extract, data cleanup.\n"
                "  • Scripted research, summarization, comparison tables, SOPs.\n"
                "  • Anything that benefits from precision, repeatability, or "
                "verification — Hermes can run tests and report exact output.\n\n"
                "DO NOT USE for pure GUI tasks (clicking through menus, drag-drop, "
                "visual layout decisions, CAPTCHA, app login flows). Emu owns the "
                "navigation; Hermes owns the execution.\n\n"
                "CRITICAL: Hermes runs in a separate process and CANNOT see your "
                "screen or ask follow-up questions. You MUST pass every single "
                "fact, quote, number, decision, URL, file path, and styling "
                "preference you have gathered into `context` and/or `file_paths`. "
                "If the user asked for a deck summarising a Teams call, first do "
                "all the navigation to read the transcript and conclusions, THEN "
                "paste the FULL transcript + conclusions + any user-stated "
                "preferences into `context` before invoking Hermes. Err on the "
                "side of pasting too much rather than too little — this is a "
                "one-shot handoff."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": (
                            "One or two sentences describing the concrete artifact "
                            "or outcome Hermes should produce. "
                            "E.g. 'Create a 12-slide executive PowerPoint summarising "
                            "the Q2 planning Teams call, save as ~/Desktop/q2-plan.pptx'."
                        ),
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "MOST IMPORTANT FIELD. Paste EVERYTHING Emu has gathered "
                            "that Hermes needs — full transcripts, every conclusion, "
                            "every name/date/number/URL, the user's tone/style "
                            "preferences, prior drafts, error messages, raw data. "
                            "Hermes is blind to your screen; if it isn't here or in "
                            "`file_paths`, Hermes does not know it. Err on the side "
                            "of pasting too much rather than too little."
                        ),
                    },
                    "file_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Absolute paths to files Hermes should read directly "
                            "(transcripts saved to disk, source data, reference "
                            "documents, existing drafts to edit). Use this for "
                            "anything large enough to be awkward in `context`."
                        ),
                    },
                    "output_target": {
                        "type": "string",
                        "description": (
                            "Where/how Hermes should deliver the result. E.g. "
                            "'Save .pptx to ~/Desktop/q2-plan.pptx and print the "
                            "absolute path' or 'Reply in terminal with the patch "
                            "diff'. Optional but strongly recommended."
                        ),
                    },
                    "constraints": {
                        "type": "string",
                        "description": (
                            "Style, tone, format, length, audience, deadline, or "
                            "any 'must-have / must-avoid' rules. Optional."
                        ),
                    },
                },
                "required": ["goal", "context"],
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
            if v["type"] == "array" and "items" in v:
                item_type = v["items"].get("type", "string").upper()
                schema_kwargs["items"] = types.Schema(type=item_type)
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
