---
name: hermes-agent-skill
description: "Use this skill when Emu or another computer-use model should hand off work to Hermes Agent. Hermes is a TERMINAL AGENT: strongest at shell commands, file operations, code changes, research, structured content generation, PowerPoint/document production, debugging, automation, and multi-step workflows. On Windows, activate/use WSL before invoking Hermes; on macOS, Hermes can be used directly from Terminal/iTerm. Use this skill when GUI navigation is easy for Emu but execution, generation, transformation, analysis, or automation is better done in a terminal-driven agent."
---

## Hermes Agent Skill

### What Hermes is

Hermes is a TERMINAL AGENT.

That means Hermes is best when the task benefits from:
- shell commands
- scripts
- file reads/writes/patches
- code generation or editing
- structured document generation
- data transformation
- debugging and verification
- automation across many steps
- repeatable workflows with logs and evidence

Hermes is not primarily a mouse-first or GUI-first agent. Emu should handle visual navigation, clicking, dragging, app switching, and reaching the correct page or application state. Hermes should handle the parts that are more reliable, faster, or more precise in a terminal or tool-driven environment.

Use this skill whenever Emu can reach a destination visually, but wants Hermes to do the actual heavy lifting.

### Platform expectations

#### Windows

On Windows, Emu should activate or enter WSL before using Hermes.

Reason:
- Hermes is commonly run inside Linux/WSL environments
- shell workflows, package managers, scripts, git, and developer tooling are more predictable there
- Windows files are still accessible from WSL under `/mnt/c/`, `/mnt/d/`, etc.

Practical rule:
- if Emu is on Windows, open WSL first and then run Hermes from the WSL shell
- Windows desktop files typically map like `C:\Users\<name>\Desktop` -> `/mnt/c/Users/<name>/Desktop`

#### macOS

On macOS, Emu can use Hermes directly from Terminal or iTerm.

No WSL step is needed.

### How to activate and use Hermes

Common ways to activate Hermes:

```bash
# interactive chat
hermes

# one-shot prompt
hermes chat -q "Summarize these notes into a slide outline"

# setup wizard
hermes setup

# health check
hermes doctor
```

Practical activation guidance:
- On Windows: open WSL first, then run Hermes inside the WSL shell.
- On macOS: open Terminal or iTerm and run Hermes directly.
- If Emu is delegating a task, it should first ensure the shell is open and Hermes is available on PATH.

### Basic interaction model

Once Hermes is running, the user or calling system can:
- type a request directly into the terminal chat
- run a one-shot query with `hermes chat -q "..."`
- ask Hermes to inspect files, generate content, debug errors, or create artifacts
- provide exact file paths and output requirements for best results

Good activation examples:
- `hermes`
- `hermes chat -q "Create a 12-slide deck from /mnt/c/Users/.../notes.md"`
- `hermes chat -q "Inspect this repo, fix the failing test, and summarize the patch"`

### Hermes UI description

Hermes is a terminal-native interface rather than a traditional desktop GUI.

Typical UI characteristics:
- a command-line chat interface inside Terminal, iTerm, or a Linux shell
- a scrolling conversation view showing user prompts, assistant responses, and tool activity
- tool execution output displayed inline or as command results
- slash-style session commands in interactive mode such as `/help`, `/model`, `/tools`, `/status`, `/skill name`, `/quit`
- status or progress information depending on the terminal skin/configuration

What Emu should expect visually:
- a text prompt waiting for input
- printed assistant responses in the terminal buffer
- tool activity summaries while Hermes works
- command output, logs, file paths, or summaries returned as text
- no ribbon, canvas, or conventional app chrome like PowerPoint/Word/browser apps

This means Hermes should be treated as a text-first execution environment. Emu can launch and focus the terminal window, but the interaction itself is conversational and command-driven.

### Collaboration model: Emu + Hermes

Recommended division of labor:

Emu handles:
- opening apps and websites
- navigating menus and ribbons
- authenticating in visual interfaces
- selecting files in GUI dialogs
- positioning windows
- handling UI states that require vision
- operating native desktop apps through mouse and keyboard

Hermes handles:
- terminal commands
- file manipulation
- code edits
- generating presentation outlines and content
- programmatic creation of documents and slide decks
- converting data between formats
- research and summarization
- creating automation scripts
- debugging error messages and logs
- running tests and validating outputs
- producing reusable artifacts in the filesystem

The most effective pattern is:
1. Emu navigates to the right context.
2. Emu decides whether the next step is GUI-heavy or terminal-heavy.
3. If terminal-heavy, Emu hands the task to Hermes with precise context.
4. Hermes executes and returns the result, file path, summary, or next required GUI step.
5. Emu resumes visual interaction if needed.

### What Hermes can do especially well

#### 1. Terminal and shell execution
Hermes can:
- run commands
- inspect system state
- install packages
- manage processes
- run build steps
- launch scripts
- inspect logs
- gather diagnostics
- compress, move, rename, and transform files

This is one of Hermes' strongest capabilities.

#### 2. File and code operations
Hermes can:
- read files precisely
- search across codebases or folders
- patch existing files
- write new files
- refactor code
- generate scripts
- update configs
- create structured markdown, JSON, YAML, CSV, HTML, Python, shell, and more

Hermes is especially useful when exact text editing matters more than GUI interaction.

#### 3. Presentation creation and editing
Hermes can help create PowerPoint presentations by:
- drafting the deck structure
- writing slide titles and bullets
- generating speaker notes
- producing content from docs, research, code, or data
- turning outlines into polished slide copy
- preparing markdown/JSON/tabular content that another tool converts to slides
- creating or modifying `.pptx` files programmatically when the environment supports it

A strong collaboration pattern is:
- Emu handles PowerPoint navigation and visual layout tweaks
- Hermes generates the actual content, structure, notes, tables, and supporting assets
- If a programmatic path is available, Hermes can often create deck artifacts faster than manual clicking

#### 4. Research and information synthesis
Hermes can:
- search for information when web/search tools are available
- summarize sources
- compare options
- synthesize findings into concise recommendations
- turn raw notes into polished documents or slides
- produce structured outputs for reports, presentations, or follow-up tasks

#### 5. Debugging and troubleshooting
Hermes is very strong at:
- reading logs
- tracing failures
- checking config files
- reproducing errors
- proposing fixes
- applying patches
- verifying the result with tests or follow-up commands

If Emu sees an error dialog, failed install, broken page, or confusing output, handing the details to Hermes is often the fastest way to diagnose it.

#### 6. Planning and long multi-step work
Hermes can:
- break work into a plan
- track sub-steps
- execute tasks in order
- verify outcomes
- summarize status
- maintain continuity across longer workflows

This is useful for project setup, deck creation, report writing, engineering tasks, data cleanup, and repetitive procedures.

#### 7. Structured content generation
Hermes can generate:
- emails
- summaries
- reports
- docs
- meeting notes
- presentations
- code comments
- issue tickets
- release notes
- research briefs
- comparison tables
- checklists
- SOPs

#### 8. Automation and reusable workflows
Hermes can:
- save skills and reusable procedures
- create scripts for repeated tasks
- schedule recurring jobs when supported
- spawn or coordinate subtasks in some environments
- turn one-off workflows into repeatable automation

### When Emu should prefer Hermes

Use Hermes when the task is any of the following:
- "create a slide deck from these notes"
- "summarize these files into a presentation"
- "edit these files exactly"
- "run this command and tell me what failed"
- "rename, reorganize, or transform many files"
- "write a script to automate this"
- "inspect logs / diagnose why this broke"
- "search this project and patch the bug"
- "generate a report from this data"
- "prepare content for Word, PowerPoint, email, markdown, or CSV"
- "work inside git / python / node / shell / config files"
- "do something where precision, repeatability, or verification matters"

### When Emu should not rely on Hermes alone

Hermes is less suitable as the sole agent when the task depends mainly on:
- visual alignment or design judgment from a live canvas
- drag-and-drop interactions with no scriptable route
- handling CAPTCHA-like visual challenges manually
- navigating deeply visual workflows where the app state is only visible onscreen
- interacting with UI elements that require direct mouse manipulation and immediate visual feedback

In those cases:
- Emu should stay in control of the navigation
- Hermes should be used for supporting generation, analysis, or back-end execution

### Best handoff format for Emu -> Hermes

When calling Hermes, provide:
- the concrete goal
- relevant file paths
- current app or page context
- constraints and output format
- whether the result should be a file, command output, summary, or patch
- any deadlines, style requirements, or target audience

Good examples:
- "Create a 10-slide executive deck from `/mnt/c/Users/.../notes.md` with a persuasive tone and output the final outline plus speaker notes."
- "Read these CSVs, summarize the trends, and generate slide-ready bullets plus a table for PowerPoint."
- "Inspect this repo, find the failing test, patch the bug, and report exactly what changed."
- "Draft a client-ready project update in markdown and also create concise slide bullets from it."

### Output patterns Hermes is good at returning

Hermes can reliably return:
- exact command output
- a file path to a created artifact
- a patch summary
- a polished draft
- a deck outline
- slide copy
- speaker notes
- debugging findings
- recommendations and next steps
- structured JSON / YAML / markdown / CSV

### PowerPoint-specific collaboration guidance

For PowerPoint work, the best split is usually:

Emu:
- open PowerPoint
- pick the template
- adjust visual design manually
- place images where visual judgment matters
- fine-tune spacing, alignment, and theme choices

Hermes:
- write the narrative arc
- create slide-by-slide structure
- generate title and subtitle options
- write bullet points
- draft presenter notes
- produce appendix content
- transform raw notes, research, or data into presentation-ready language
- create source files or intermediate artifacts that speed up final deck assembly

If a `.pptx` needs to be created or edited programmatically, Hermes can often help through scripting or document-generation libraries when available.

### Reliability guidance

Hermes is strongest when asked to do things that can be verified.

Good verification patterns:
- ask Hermes to write to a file and return the path
- ask Hermes to run tests after editing
- ask Hermes to summarize exact changes made
- ask Hermes to produce deterministic structured output
- ask Hermes to report assumptions explicitly

### Constraints and realism

Capabilities depend on the available toolsets and environment. Hermes may have access to some or all of:
- terminal tools
- file tools
- browser automation
- web search
- code execution
- vision
- memory and session recall
- scheduling and background jobs
- delegation to subagents
- document and media workflows

So Emu should phrase requests based on the active environment. But as a general rule, Hermes should be treated first and foremost as a TERMINAL AGENT with strong execution, editing, reasoning, and automation abilities.

### Short operational summary for Emu

If the task is mostly:
- click, view, drag, locate, visually inspect -> Emu first
- run, write, patch, transform, generate, debug, automate -> Hermes first

### One-sentence identity to remember

Hermes is a TERMINAL AGENT that excels at executing commands, manipulating files, generating structured artifacts, debugging problems, and turning complex instructions into verified outputs, while Emu handles the visual computer-use layer.
