"""
providers/agent_tools.py

Shared agent tool definitions for all providers.

These are "thinking" tools the model calls server-side (plan, memory, skills,
context compression). Desktop actions (click, type, scroll) stay as JSON
text responses — they're dispatched to the Electron frontend.

Tools are defined once in OpenAI format. Helpers convert to Anthropic / Gemini
format as needed.
"""

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
            "name": "create_skill",
            "description": (
                "Save a recurring user-personal workflow as a reusable skill "
                "(e.g. 'check my Chase balance', 'file weekly expenses in Concur', "
                "'pay rent on Zelle'). Do NOT use for generic app knowledge — those "
                "are bundled. Writes to .emu/skills/<slug>/ following the open Agent "
                "Skills spec; immediately discoverable via use_skill."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Human-readable skill name. Slugified for the folder "
                            "(lowercase, hyphenated): 'Check Chase Balance' -> "
                            "'check-chase-balance'. Pick something unique and "
                            "task-specific — avoid generic names like 'banking'."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "ONE sentence (≤200 chars) describing WHEN to trigger this "
                            "skill. This is the ONLY part loaded into every prompt turn, "
                            "so it must be specific and trigger-rich. Mention the app, "
                            "the user-facing intent, and concrete trigger phrases. "
                            "Good: 'Check Chase checking-account balance via chase.com — "
                            "use when user asks about bank balance, recent deposits, or "
                            "available funds.' "
                            "Bad: 'Banking stuff.' / 'Helps with money.'"
                        ),
                    },
                    "instructions": {
                        "type": "string",
                        "description": (
                            "FULL markdown body of SKILL.md (everything after the YAML "
                            "frontmatter). Do NOT include the `---` fences or "
                            "`name:`/`description:` — those are auto-generated.\n\n"
                            "REQUIRED structure (use these exact H2 headings, in order):\n"
                            "  • `# <Title>` — H1 skill title.\n"
                            "  • `## When to use this skill` — concrete user trigger "
                            "phrases, target app/site, ambiguities to watch for.\n"
                            "  • `## Prerequisites` — bullet list of required app/browser "
                            "state, hardware, data locations, and bundled files.\n"
                            "  • `## Steps` — numbered list, ONE concrete action per item. "
                            "Must reference exact UI labels, URLs, keyboard shortcuts, and "
                            "field names actually observed. No vague verbs like 'navigate'.\n"
                            "  • `## Pitfalls` — bullet list of known failure modes and "
                            "how to recover from each.\n"
                            "  • `## Bundled scripts` — one bullet per file in `files`: "
                            "purpose, how to invoke via shell_exec, expected output. "
                            "OMIT this section entirely if no `files`.\n\n"
                            "Rules:\n"
                            "  • Headings must match exactly (case + wording).\n"
                            "  • NEVER embed secrets, passwords, OTPs, full account "
                            "numbers, SSNs, or API keys — reference their location "
                            "instead (OS keychain, preferences.md, etc.).\n"
                            "  • For steps that move money, delete data, or send external "
                            "comms, the step itself must say 'PAUSE and confirm with the "
                            "user before clicking'.\n"
                            "  • Keep body under ~400 lines; long data goes in `files` "
                            "under references/.\n"
                            "  • Bundled scripts should be self-contained, idempotent, "
                            "and print machine-readable output (JSON or single value).\n"
                            "  • Folder layout: SKILL.md (required) + optional scripts/, "
                            "references/, assets/."
                        ),
                    },
                    "files": {
                        "type": "array",
                        "description": (
                            "Optional bundled text files written alongside SKILL.md. "
                            "Each item is {path, content}. Path is RELATIVE to the skill "
                            "folder and must live under one of the spec'd subdirs:\n"
                            "  • scripts/  — executable code the skill instructs the agent "
                            "to run via shell_exec (Python, shell, JS). Make scripts "
                            "self-contained and print machine-readable output.\n"
                            "  • references/ — lookup data, docs, account maps, API "
                            "schemas, anything too long to inline in instructions.\n"
                            "  • assets/   — templates, sample inputs, snippets to paste.\n"
                            "Text only — no binaries. Path traversal ('../') is rejected. "
                            "Your `instructions` MUST tell future-you exactly when and how "
                            "to use each file."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": (
                                        "Relative path under the skill folder, e.g. "
                                        "'scripts/fetch.py', 'references/accounts.md', "
                                        "'assets/email-template.txt'."
                                    ),
                                },
                                "content": {
                                    "type": "string",
                                    "description": "File contents (UTF-8 text).",
                                },
                            },
                            "required": ["path", "content"],
                        },
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": (
                            "If true, replace the existing skill with the same slug "
                            "(SKILL.md + any provided files are rewritten; other "
                            "untouched files in the folder remain). Default false — "
                            "refuses to clobber and returns an error so you can pick a "
                            "different name or explicitly opt in."
                        ),
                    },
                },
                "required": ["name", "description", "instructions"],
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
                "(via `hermes chat -Q -q`); you do NOT need to open or focus a "
                "terminal.\n\n"
                "ASYNC SEMANTICS — IMPORTANT: this call returns IMMEDIATELY with a "
                "`job_id`. Hermes runs in the background; Emu is NOT blocked. "
                "After invoking, yield control back to the user immediately. "
                "Do NOT call `check_hermes` in the same turn unless the user "
                "explicitly asked you to wait. The final Hermes output only "
                "arrives via check_hermes when the user later asks for an update.\n\n"
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
    {
        "type": "function",
        "function": {
            "name": "check_hermes",
            "description": (
                "Poll a background Hermes job started by `invoke_hermes`. "
                "Returns one of:\n"
                "  • Completed: the full final stdout + saved-output path. "
                "Read this carefully and act on it (confirm to user, follow "
                "up on clarifying questions Hermes asked, etc).\n"
                "  • Still running: a status snapshot with runtime, last-output "
                "age, and the most recent stdout lines. If `wait_s > 0` you'll "
                "block up to that many seconds for the job to finish first.\n\n"
                "Polling cadence guidance:\n"
                "  • If you have nothing else to do, call with wait_s=60 and "
                "loop until done.\n"
                "  • If you're doing other work in parallel, call with wait_s=0 "
                "every few turns.\n"
                "  • If the snapshot warns 'no output in 120s', the job may be "
                "stuck — tell the user and offer cancel_hermes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": (
                            "The job_id returned by invoke_hermes. Use "
                            "list_hermes_jobs() if you've forgotten it."
                        ),
                    },
                    "wait_s": {
                        "type": "number",
                        "description": (
                            "Optional: how many seconds to block waiting for "
                            "completion before returning the current snapshot. "
                            "Capped at 300. Default 0 (return immediately)."
                        ),
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_hermes",
            "description": (
                "Terminate a running Hermes job. Use when the user asks to "
                "abort, when a job is clearly stuck (no output for >120s), or "
                "when you've decided to take a different approach."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "The job_id returned by invoke_hermes.",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_hermes_jobs",
            "description": (
                "List every Hermes job started in the current session with "
                "id, status, runtime, and goal. Use to recover a job_id you "
                "forgot, or to see what's still running."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shell_exec",
            "description": (
                "Run a shell command inside the .emu directory and return its "
                "combined stdout+stderr. This is a SANDBOXED backend tool, not "
                "a desktop action.\n\n"
                "Scope is enforced: cwd/HOME are `.emu`, absolute paths must "
                "stay under `.emu`, risky/network/destructive programs are "
                "blocked, and output is capped. Use for file-backed inspection "
                "only, not GUI automation or app launching."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "Shell command line to execute. Runs via "
                            "/bin/bash -c with cwd=.emu."
                        ),
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "raise_app",
            "description": (
                "Resolve/prepare a named macOS app. Remote mode activates it. "
                "Coworker mode uses emu-cua-driver `launch_app` and returns "
                "`{pid, bundle_id, name, windows}` without foregrounding. Use "
                "the returned pid/window_id for `cua_*` tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": (
                            "Exact macOS application name, e.g. 'Google Chrome', "
                            "'Finder', 'Visual Studio Code'."
                        ),
                    },
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bring_app_frontmost",
            "description": (
                "User-approved foreground fallback. Requires explicit user "
                "approval; after it succeeds, take a fresh "
                "`cua_get_window_state` and continue with `cua_*` tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Exact macOS application name, e.g. 'TV' or 'Google Chrome'.",
                    },
                    "user_approved": {
                        "type": "boolean",
                        "description": "Must be true only after the user explicitly approved foregrounding.",
                    },
                },
                "required": ["app_name", "user_approved"],
            },
        },
    },
]


# ── Mode-aware catalogue ──────────────────────────────────────────────────────
#
# Coworker mode (per PLAN §4.5) publishes the local-driver `cua_*` toolset
# alongside the always-on agent tools. Remote / default modes only see the
# always-on set. Providers should call ``get_agent_tools_openai(agent_mode)``
# (or the format-specific helpers below) at request time, not at import time.

def _coworker_extra_tools() -> list[dict]:
    # Imported lazily so this module stays importable even if the coworker
    # module ever grows optional deps.
    from tools.coworker_tools import COWORKER_DRIVER_TOOLS_OPENAI
    return COWORKER_DRIVER_TOOLS_OPENAI


def get_agent_tools_openai(agent_mode: str | None = "remote") -> list[dict]:
    """Return the OpenAI-format tool catalogue for the given agent mode."""
    if agent_mode == "coworker":
        return AGENT_TOOLS_OPENAI + _coworker_extra_tools()
    return AGENT_TOOLS_OPENAI


def get_agent_tool_names(agent_mode: str | None = "remote") -> set[str]:
    """Return the set of tool names exposed in the given agent mode."""
    if agent_mode == "coworker":
        return AGENT_TOOL_NAMES | {t["function"]["name"] for t in _coworker_extra_tools()}
    return AGENT_TOOL_NAMES


# ── Anthropic format (used by Claude provider) ────────────────────────────────

def tools_for_anthropic(agent_mode: str | None = "remote") -> list[dict]:
    """Convert to Anthropic tool format for the given agent mode."""
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in get_agent_tools_openai(agent_mode)
    ]


# ── Google Gemini format ──────────────────────────────────────────────────────

def tools_for_gemini(agent_mode: str | None = "remote"):
    """Convert to google-genai types for the given agent mode. Import here to avoid hard dep."""
    from google.genai import types

    declarations = []
    for t in get_agent_tools_openai(agent_mode):
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
