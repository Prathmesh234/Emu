# Deep Research: OpenClaw vs Emu — System Prompt, Compaction & Harness Engineering

> **Date:** 2026-03-29  
> **Goal:** Identify the biggest bottlenecks in Emu's harness, compare with OpenClaw's approach and industry best practices, and propose a concrete plan to fix them.
> **Status:** Research complete, plan outlined.

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Prompt Comparison](#system-prompt-comparison)
3. [Compaction: OpenClaw vs Emu](#compaction-openclaw-vs-emu)
4. [Ad-Hoc Problems in Emu](#ad-hoc-problems-in-emu)
5. [Harness Engineering: Industry Best Practices](#harness-engineering)
6. [The Core Problem: Over-Steering vs Model Autonomy](#core-problem)
7. [Concrete Plan: What to Change](#concrete-plan)

---

## Executive Summary

Emu's current harness has three compounding problems:

1. **The system prompt is a 750-line monolith** that mixes identity, tool definitions, execution protocol, loop prevention rules, vision modes, workspace instructions, examples, and a full bootstrap interview flow — all stuffed into a single string. The model receives ~35KB of instructions before it even sees the user's first message.

2. **Compaction is infrastructure-driven, not model-driven.** The system counts messages (`>40`), hits a threshold, and fires compaction behind the model's back. The model doesn't know compaction is coming, doesn't get to decide *when* it's appropriate, and doesn't control *what* gets preserved. It's a fire-and-forget side effect in `agent_step()`.

3. **The prompt over-steers with ad-hoc rules** instead of trusting the model. There are 40+ lines of loop prevention heuristics, 10+ "NEVER do X" rules, two separate vision blocks conditionally injected, coordinate system explanations repeated 3 times, and a 100-line bootstrap interview script. This creates a *brittle, defensive* prompt that fights the model rather than guiding it.

**OpenClaw's approach is fundamentally different:** modular files (`SOUL.md`, `AGENTS.md`, `TOOLS.md`), token-budget-aware compaction with configurable models, persistent summarization in session transcripts, and a separation between *identity* (stable) and *operational context* (dynamic). The model manages its own context lifecycle.

**The fix is not incremental.** We need to restructure the harness around three principles:
1. **Separation of concerns** — split the monolith into modular, independently loadable files
2. **Model-driven compaction** — give the model a `compact_context` tool so it decides when/what to compress
3. **Plan-as-anchor** — make `plan.md` the single source of truth, referenced automatically, not via ad-hoc reminders

---

## System Prompt Comparison

### Emu's Current Prompt (~750 lines, ~35KB)

| Section | Lines | Tokens (~) | Purpose |
|---------|-------|------------|---------|
| `<identity>` | 16 | ~200 | Who Emu is, date injection, session references |
| `<personality>` | 16 | ~200 | Tone rules, anti-sycophancy |
| `<system>` | 8 | ~100 | Device info, coordinate basics |
| `<vision_mode>` / `<omniparser>` | 45-75 | ~600 | How to interpret screenshots (ONE of two blocks) |
| `<action_model>` | 18 | ~250 | Mouse/click separation rules |
| `<available_actions>` | 90 | ~1200 | 13 action types with full descriptions + examples |
| `<loop_prevention>` | 50 | ~700 | 8 specific loop trap detections |
| `<tool_selection>` | 12 | ~150 | Keyboard vs shell vs mouse heuristics |
| `<execution_protocol>` | 65 | ~800 | Plan-first mandate, one-action rule, completion rules, memory writes |
| `<response_format>` | 55 | ~700 | JSON schema, anti-batching rules |
| `<workspace>` | 55 | ~700 | .emu/ file system layout, when to read/write |
| `<example>` | 30 | ~400 | Docker example walkthrough |
| Bootstrap block (conditional) | ~130 | ~1700 | Full first-time interview script |
| **Total (non-bootstrap)** | **~460** | **~6000** | |
| **Total (with bootstrap)** | **~600** | **~7700** | |

*Plus workspace files injected at runtime:*
| File | Tokens (~) |
|------|------------|
| SOUL.md | ~500 |
| AGENTS.md | ~300 |
| IDENTITY.md | ~250 |
| USER.md | ~100 |
| MEMORY.md | ~50 |
| **Total workspace injection** | **~1200** |

**Grand total at session start: ~7,200-8,900 tokens** of instructions before the model sees anything.

### OpenClaw's Approach

OpenClaw separates concerns into **independent files**, each injected into context:

| File | Purpose | Injected When |
|------|---------|---------------|
| `SOUL.md` | Core personality, values, ethical boundaries | Every session |
| `AGENTS.md` | Boot order, SOPs, behavioral rules | Every session |
| `TOOLS.md` | Tool definitions and usage patterns | Every session |
| `USER.md` | User identity and preferences | Every session |
| `IDENTITY.md` | Agent profile and capabilities | Every session |
| Skills (`SKILL.md` per skill) | Modular capability packs | On demand |
| Memory files | Session history, facts | On demand |

**Key differences:**

1. **Modularity over monolith.** Each concern lives in its own file. You can edit `SOUL.md` without touching tool definitions. You can swap `TOOLS.md` without changing personality.

2. **User-editable separation.** OpenClaw makes it explicit: SOUL.md is read-only to the agent but editable by the user. This is the "constitution" — the agent never overrides its core values.

3. **Skills as hot-loadable modules.** Instead of stuffing every capability into the system prompt, OpenClaw uses a skills registry (`~/.openclaw/workspace/skills/<name>/SKILL.md`). Skills are loaded *only when relevant*, keeping the default prompt lean.

4. **No ad-hoc rules.** You won't find 50 lines of "NEVER do X" or "CRITICAL: ALWAYS do Y" in OpenClaw's core files. They trust the model to handle nuance and rely on structured tool definitions to guide behavior.

### What Other Agents Do

| Agent | System Prompt Strategy |
|-------|----------------------|
| **Claude Code** | Modular prompt segments, conditionally assembled. Agent-specific prompts for Explore/Plan/Code modes. Observability-first — the agent can introspect its own context. |
| **SWE-Agent** | Custom Agent-Computer Interface (ACI) with tool definitions as the primary prompt mechanism. Minimal system prompt, heavy tool docstrings. |
| **Open Interpreter** | Configurable system message via `default.yaml`. Profile-based customization. Minimal core prompt, behavior emerges from tool use. |
| **Anthropic's guidance** | "Write your system prompt as if briefing a competent new colleague." Use XML tags for structure. Avoid negative constraints. Examples > descriptions. |

---

## Compaction: OpenClaw vs Emu

### Emu's Current Compaction

```
main.py → agent_step() → after model responds:
  if needs_compact and not response.done:
    → get_compact_messages()      # strip screenshots, system prompt
    → compact_model(messages)     # call haiku/cheap model
    → reset_with_summary()        # replace chain with summary
```

**Problems:**

| Issue | Description |
|-------|-------------|
| **Infrastructure-driven** | Compaction fires when `len(messages) > 40`. The model has ZERO say in when this happens. |
| **Model is blindsided** | The model is mid-task, sends an action, and then its entire history is replaced with a summary it never saw. It gets a `CONTINUATION_DIRECTIVE` on the next turn and has to re-orient from scratch. |
| **No semantic awareness** | The threshold is message count, not token count or semantic relevance. 40 messages of "mouse_move → click" noise triggers the same as 40 messages of complex multi-step reasoning. |
| **Hardcoded summary format** | The compact prompt defines a rigid structure (PRIMARY TASK, PLAN, ACTION LOG, LIVE STATE, KEY DATA, USER TRANSCRIPT). The model generating the summary can't adapt to what's actually important in this specific session. |
| **No memory flush first** | OpenClaw triggers a "memory flush" (save important facts to persistent files) BEFORE compacting. Emu doesn't — potentially losing important observations the model hasn't written to disk yet. |
| **Double compression risk** | Emu also has `MAX_CHAIN_LENGTH = 60` middle-trimming in `build_request()`. So the context is being managed by TWO independent mechanisms that don't talk to each other. |
| **Fake assistant response** | After compaction, Emu injects a *fake* assistant message: `"Context compacted. I have read the state snapshot..."` This pretends the model said something it didn't, which can confuse the model's sense of its own trajectory. |

### OpenClaw's Compaction

OpenClaw uses a **two-tier system** with explicit model control:

#### Tier 1: Compaction (Persistent Summarization)

- **Token-budget trigger**: Fires when context approaches `contextWindow - reserveTokens`, not a fixed message count. This adapts to different models with different context sizes.
- **Staged summarization**: `summarizeInStages()` chunks messages by token budget, summarizes each chunk, then summarizes the summaries. This prevents information loss from trying to compress everything in one pass.
- **Persistent**: The summary is saved to the session's JSONL history file. Even if the process crashes, the summary persists.
- **Configurable model**: You can specify a different (cheaper, faster) model for compaction via `agents.defaults.compaction.model`. Emu does this too, but OpenClaw makes it a first-class config.
- **Identifier policy**: `identifierPolicy: "strict"` ensures the summarizer preserves UUIDs, file paths, and other opaque strings verbatim — no hallucinated rewrites.
- **Manual trigger**: `/compact` command lets the user force compaction with optional focus: `/compact Focus on API design decisions`.

#### Tier 2: Pruning (Transient Cleanup)

- **Purpose**: Reduce per-request token usage WITHOUT altering the persistent transcript.
- **Mechanism**: Removes old/large tool outputs and verbose logs from the in-memory prompt only. The JSONL history is unchanged.
- **Key insight**: This is Emu's `build_request()` screenshot replacement, but OpenClaw applies it more broadly to all tool output, not just images.

#### Why OpenClaw's Approach Is Better

1. **Token-based, not message-based.** A session with 20 long shell outputs might hit the limit faster than 60 short clicks. Token counting adapts.
2. **Model gets to participate.** Through the `/compact` command and auto-memory-flush, the model has input into what's preserved.
3. **Two tiers don't fight each other.** Pruning happens on every request (transient); compaction happens rarely (persistent). They're complementary, not competing.
4. **No fake messages.** The summary is injected as a first-class history entry, not dressed up as something the model "said."

---

## Ad-Hoc Problems in Emu

### What "Ad-Hoc" Means Here

"Ad-hoc" = rules added reactively to fix specific failure modes, rather than designing a system that prevents them structurally. Emu's prompt is full of these:

### Inventory of Ad-Hoc Rules

| Category | Example | Why It's Ad-Hoc |
|----------|---------|-----------------|
| **Loop prevention** | "BEFORE EVERY ACTION, ask yourself these three questions..." (lines 270-274) | This is a manual checklist the model is supposed to follow on every turn. Models don't reliably execute procedural checklists. |
| **Loop traps** | "mouse_move → mouse_move: FORBIDDEN" (line 283) | Hardcoded pattern matching. What about `scroll → scroll → scroll`? Or `screenshot → wait → screenshot → wait`? Every new loop pattern requires a new rule. |
| **Minimum distances** | "MINIMUM MOVE DISTANCE: 0.01 in normalized coords" (line 171) | Parameter tuning embedded in the prompt. Should be in the action execution layer, not the model's instructions. |
| **Minimum scroll** | "MINIMUM amount: 3" (line 212) | Same — this is action-layer validation, not model guidance. |
| **Anti-patterns** | "ANTI-PATTERN: Taking a screenshot after completing..." (line 364) | Describing what NOT to do is less effective than describing what TO do. |
| **Response format** | 50+ lines of "WRONG (batching two steps)" examples (lines 446-450) | Should be enforced by the response parsing layer, not by hoping the model reads these rules. |
| **Coordinate repetition** | Explained 3 times: `<system>`, `<action_model>`, `<omniparser>` | Redundancy wastes tokens and signals uncertainty ("let me say it again in case you missed it"). |
| **Memory writes** | "When the user confirms success...write session learnings to memory" (lines 372-391) | A multi-step protocol described in prose. Should be a structured tool the model calls, not a paragraph to remember. |
| **Blocked commands** | "BLOCKED COMMANDS: find / or ls -R" (lines 247-251) | Should be enforced by the shell_exec implementation, not by asking the model nicely. |

### The Pattern

Every time the model exhibits a failure mode, a new rule gets added to the prompt:
```
Model loops on mouse_move → Add "mouse_move → mouse_move: FORBIDDEN"
Model over-verifies → Add "ANTI-PATTERN: Taking a screenshot after completing..."  
Model batches actions → Add 10 lines of "WRONG" examples
Model uses find / → Add "BLOCKED COMMANDS" section
```

This is **reactive whack-a-mole**. Each rule adds tokens but doesn't address *why* the model makes these mistakes. The result: a bloated prompt that the model may not even read carefully because it's so long.

### What to Do Instead

**Structural prevention > Prompt-level rules:**

1. **Action validation layer**: Block invalid actions (double mouse_move, scroll < 3, mouse move < 0.01 distance) in the action execution code, not in the prompt. Return an error message the model can learn from.
2. **Response schema enforcement**: Use structured output / JSON mode so the model *cannot* return invalid responses. Parse and validate server-side.
3. **Loop detection in the harness**: Track action patterns in the backend. If the model repeats the same action 3 times, inject a system message: "Your last 3 actions were identical. The approach isn't working. Try something different." This is *reactive guidance at runtime*, not *static rules the model might forget*.
4. **Tool-based memory writes**: Instead of a paragraph explaining the memory protocol, give the model a `write_memory` tool with clear parameters. The model calls it when appropriate.

---

## Harness Engineering: Industry Best Practices {#harness-engineering}

### What the Best Agents Get Right

Based on research into OpenClaw, Claude Code, SWE-Agent, Anthropic's guidance (2025-2026), and Open Interpreter:

#### 1. "Context Engineering" > "Prompt Engineering"

**Anthropic (Sept 2025):** Context engineering = curating the smallest possible set of high-signal tokens within the model's attention budget.

**What this means for Emu:**
- Don't front-load everything. The model doesn't need to know about OmniParser coordinate normalization when it's just answering a question.
- Load context progressively: identity → task → tools → relevant skills → memory (only if needed).
- Treat every token in the system prompt as having a cost. If a rule can be enforced in code, remove it from the prompt.

#### 2. Separation of Static vs Dynamic Context

| Type | Definition | Emu Today | Should Be |
|------|-----------|-----------|-----------|
| **Static** | Identity, personality, ethical boundaries | Mixed into monolith | Separate files, cached (prompt caching) |
| **Dynamic** | Current task, tools needed, screen state | Mixed into monolith | Assembled per-request based on task type |
| **Ephemeral** | Loop detection, recent actions | Hardcoded rules | Runtime injection based on actual behavior |

#### 3. Plan-Action-Reflection (PAR) Loop

The dominant architecture in 2025-2026:

```
PLAN → Create plan.md (Emu does this ✓)
ACT  → Execute actions against the plan
REFLECT → After N steps or on failure, review plan.md and adjust
```

**Emu's problem**: The "reflect" step is ad-hoc. The prompt says "re-read plan.md when confused" but doesn't structurally ensure it happens. In practice:
- The model gets lost and keeps trying the same thing
- It doesn't re-read the plan until it's already deep in a loop
- There's no periodic checkpoint ("every 10 steps, re-read plan.md")

**Fix**: Make plan reference automatic. Every 8-10 action turns, inject `plan.md` content into the context as a system message: "Here is your current plan for reference." The model doesn't need to remember to do this — the harness does it.

#### 4. Model Autonomy vs Steering

**The key insight from Anthropic's 2025 guidance:**

> "Avoid Over-Constraint: Avoid heavy 'YOU MUST' or 'NEVER' language, which can lead to brittle performance. Instead, provide clear objectives and allow the model's inherent reasoning to guide execution."

Emu's prompt has:
- 14 occurrences of "MUST"
- 12 occurrences of "NEVER"  
- 8 occurrences of "CRITICAL"
- 5 occurrences of "ABSOLUTE"
- 3 occurrences of "FORBIDDEN"

This creates a **compliance-oriented agent** that spends cognitive capacity on rule-following rather than task-solving. The model becomes overly cautious, over-verifies, and sometimes hallucinates violations of rules it's anxious about.

**OpenClaw's approach**: Brief, clear SOPs in `AGENTS.md`. Two sentences per rule. No ALL CAPS threats. The model is treated as a competent colleague, not a suspect under surveillance.

#### 5. Tool Design Is Prompt Engineering

**Anthropic (2025):** "The way you define your tools is as critical as the system prompt itself."

**Emu's tools**: Defined in the system prompt as a numbered list with embedded examples and caveats. This couples tool definitions with identity and behavioral rules.

**Better approach**: Define tools via the LLM's native tool/function-calling schema. Each tool has a `name`, `description`, and `parameters` schema. The model sees this as structured metadata, not prose to parse. Add tools like:
- `compact_context`: Model decides when to summarize and what to preserve
- `read_plan`: Model requests its own plan for reference
- `write_memory`: Structured memory writes
- `reflect`: Model explicitly pauses to assess progress vs plan

---

## The Core Problem: Over-Steering vs Model Autonomy {#core-problem}

Emu's harness treats the model as an unreliable executor that needs to be constrained at every turn. The system prompt is a 750-line contract of obligations and prohibitions.

OpenClaw treats the model as a capable agent that needs to be informed, not constrained. Identity is stable (SOUL.md). Operations are brief (AGENTS.md). Tools are self-documenting.

**The fundamental shift needed:**

| Current (Emu) | Target (New Emu) |
|----------------|-------------------|
| "NEVER do X" | Enforce X in code, return error |
| "CRITICAL: ALWAYS do Y" | Make Y the default in the tool design |
| "BEFORE EVERY ACTION, ask yourself..." | Inject reflection at runtime when needed |
| "Re-read plan.md when confused" | Auto-inject plan.md every N turns |
| "Compaction fires at 40 messages" | Model calls `compact_context` when it senses degradation |
| "Write memory when user confirms success" | Model calls `write_memory` tool when appropriate |
| "FORBIDDEN: mouse_move → mouse_move" | Action validator rejects and returns error |
| 750-line monolith system prompt | ~150-200 lines of core identity + dynamic assembly |

---

## Concrete Plan: What to Change {#concrete-plan}

### Phase 1: Prompt Restructuring (Separation of Concerns)

**Goal: Split the monolith into modular, independently manageable files.**

#### 1.1 Core Identity (always injected, ~150 tokens)
```
<identity>
You are Emu, a desktop automation agent. You observe the screen via 
screenshots and execute one action per turn to complete the user's task.
Today: {date} | Time: {time} | Session: {session_id}
{device_info}
</identity>
```
That's it. No personality rules, no workspace paths, no coordinate explanations.

#### 1.2 Personality → SOUL.md (already exists, already injected)
The existing `SOUL.md` is actually good. It's already separate. But the system prompt ALSO contains `<personality>` which duplicates it. **Remove `<personality>` from the system prompt entirely** — let SOUL.md be the single source of truth.

#### 1.3 Tools → Native Tool Definitions (not prose)
Move the 90 lines of `<available_actions>` out of the system prompt. Define them as structured tool schemas passed via the API's tool/function-calling mechanism. Each tool gets a clear `description` and `parameters` schema. The model uses tools natively, not by reading a numbered list.

#### 1.4 Operational Rules → AGENTS.md (already exists, streamline)
The existing `AGENTS.md` has good discipline rules. Consolidate `<loop_prevention>`, `<tool_selection>`, and `<execution_protocol>` into a tighter version of AGENTS.md. Target: 300 tokens max. Remove all "NEVER", "CRITICAL", "ABSOLUTE" language. State rules positively.

#### 1.5 Vision Context → Conditional Injection (already done, simplify)
Keep `<omniparser>` and `<vision_mode>` as separate blocks but make them shorter. Remove coordinate system explanations that are already in IDENTITY.md.

#### 1.6 Bootstrap → Separate flow entirely
The 130-line bootstrap block should not be conditionally injected into the system prompt. It should be a COMPLETELY separate system prompt used only for the bootstrap session. Different prompt, different behavior, different response format.

### Phase 2: Model-Driven Compaction

**Goal: The model decides when to compact, not the infrastructure.**

#### 2.1 Add `compact_context` as a tool

```json
{
  "name": "compact_context",
  "description": "Summarize and compress the conversation history to free up context space. Call this when you notice your task is complex, when the conversation is getting long, or when you're about to start a new sub-task. You decide what's important to preserve.",
  "parameters": {
    "focus": {
      "type": "string",
      "description": "Optional. What aspects to prioritize in the summary (e.g., 'API design decisions', 'file paths and error messages')."
    }
  }
}
```

The model can call this like any other tool. The backend handles the actual summarization and context reset.

#### 2.2 Add `flush_memory` as a pre-compaction step

Before compacting, the model should have the opportunity to save important observations to persistent storage. This is OpenClaw's "memory flush" pattern:

```json
{
  "name": "write_memory",
  "description": "Save important observations, decisions, or learned preferences to persistent memory. Use before context compaction or when you learn something worth remembering across sessions.",
  "parameters": {
    "content": { "type": "string", "description": "What to remember" },
    "target": { "type": "string", "enum": ["daily_log", "long_term", "preferences"] }
  }
}
```

#### 2.3 Remove automatic compaction (or make it a fallback)

Keep the `needs_compaction()` check as a **last-resort safety net** at a much higher threshold (e.g., 80 messages or 80% of context window). But the primary mechanism should be model-initiated via the `compact_context` tool.

#### 2.4 Token-based thresholds

Replace `AUTO_COMPACT_THRESHOLD = 40` (message count) with a token-based estimate. The model's context window size varies by provider — use `estimate_token_count()` against the provider's known context limit.

### Phase 3: Plan-as-Anchor Architecture

**Goal: plan.md is the single source of truth, referenced automatically.**

#### 3.1 Auto-inject plan every N turns

After every 8-10 assistant turns, inject the content of `plan.md` as a system/user message:

```
[PLAN CHECKPOINT — Turn {step_index}]
Here is your current plan for reference:
{plan_md_content}
Continue from the next [TODO] step.
```

This eliminates the need for "re-read plan.md when confused" instructions. The model always has its plan fresh in context.

#### 3.2 Add `read_plan` tool

```json
{
  "name": "read_plan",
  "description": "Re-read your session plan. Call this when you're unsure what to do next or need to re-orient after a failed approach."
}
```

This replaces the ad-hoc "shell_exec → cat plan.md" pattern with a first-class tool.

#### 3.3 Add `update_plan` tool

```json
{
  "name": "update_plan",
  "description": "Update the session plan with new information. Mark steps as DONE, add new steps, or adjust the approach based on what you've learned.",
  "parameters": {
    "updates": { "type": "string", "description": "The updated plan content" }
  }
}
```

This makes plan management a structured operation, not a shell command.

### Phase 4: Runtime Guardrails (Replace Prompt Rules)

**Goal: Move behavioral enforcement from prompt to code.**

#### 4.1 Action validator in the harness

```python
def validate_action(current_action, action_history) -> ValidationResult:
    """
    Called before executing any action. Returns either OK or an error 
    message that gets injected back to the model.
    """
    # Block consecutive mouse_moves
    if current_action.type == "mouse_move" and last_action.type == "mouse_move":
        return Error("Cannot move twice without an interaction. Click, type, or scroll first.")
    
    # Block micro-movements
    if current_action.type == "mouse_move" and distance(current, last) < 0.01:
        return Error("Cursor is already at this position. Just click.")
    
    # Block scroll < 3
    if current_action.type == "scroll" and current_action.amount < 3:
        return Error("Minimum scroll amount is 3.")
    
    # Detect action loops
    if same_action_repeated(current, action_history, count=3):
        return Error("You've repeated this action 3 times with no screen change. Try a different approach.")
```

These rules get REMOVED from the system prompt. The model learns about constraints through runtime feedback, not up-front memorization.

#### 4.2 Response parsing with schema enforcement

Use structured output / JSON schema mode (supported by Claude, GPT-4, Gemini). The model CANNOT return invalid JSON because the API enforces the schema. Remove all "NEVER respond with plain text" and "WRONG (batching two steps)" examples from the prompt.

#### 4.3 Loop detection as runtime injection

Track the last N actions in the backend. When a loop is detected (same action type 3+ times, or no screen change after 2 actions), inject a guidance message:

```
[LOOP DETECTED] Your last 3 actions ({action_type}) produced no visible change. 
The current approach isn't working. Consider:
1. Try a keyboard shortcut instead
2. Use shell_exec for a different approach  
3. If truly stuck, call done and explain the blocker
```

This is **dynamic, contextual** guidance — much more effective than static rules the model reads once and might forget.

### Phase 5: Bootstrap Separation

**Goal: Bootstrap is a separate mode, not a conditional block in the main prompt.**

Create a dedicated `build_bootstrap_prompt()` that returns a completely different system prompt — shorter, conversational, no tool definitions, no action format. The bootstrap flow doesn't need to know about mouse_move coordinates or loop prevention.

---

## Summary: Before vs After

| Dimension | Before (Current Emu) | After (Proposed) |
|-----------|---------------------|-------------------|
| **System prompt size** | ~750 lines, ~7-9K tokens | ~150-200 lines, ~2-3K tokens |
| **Prompt style** | Defensive monolith with 40+ rules | Concise identity + modular injection |
| **Compaction trigger** | Message count threshold (40) | Model-initiated tool call + fallback threshold |
| **Compaction awareness** | Model is blindsided | Model decides timing and focus |
| **Loop prevention** | 50 lines of static rules | Runtime action validator + dynamic injection |
| **Plan management** | "Re-read when confused" (ad-hoc) | Auto-inject every N turns + dedicated tools |
| **Memory management** | Paragraph of instructions in prompt | Structured `write_memory` tool |
| **Tool definitions** | Numbered prose list in prompt | Native tool/function schemas |
| **Bootstrap** | 130-line conditional block | Separate prompt entirely |
| **Guardrails** | "NEVER do X" in prompt | Code enforcement + error feedback |
| **Model autonomy** | Low — constrained at every turn | High — informed, not constrained |

---

## Priority Order

1. **🔴 P0: Model-driven compaction** — Add `compact_context` tool. This fixes the biggest runtime issue (context degradation).
2. **🔴 P0: Prompt pruning** — Remove duplicated content, move enforcement to code. This reduces prompt tokens by 50-60%.
3. **🟡 P1: Plan auto-injection** — Inject plan.md every N turns. This fixes the "model gets lost" failure mode.
4. **🟡 P1: Action validator** — Move loop prevention to runtime code. This removes ~50 lines from the prompt and provides better guardrails.
5. **🟢 P2: Tool-based memory** — Add `write_memory`, `read_plan`, `update_plan` tools.
6. **🟢 P2: Bootstrap separation** — Extract bootstrap into its own prompt builder.
7. **🔵 P3: Structured output enforcement** — Use JSON schema mode to eliminate format instructions.
8. **🔵 P3: Token-based compaction threshold** — Replace message count with provider-aware token budget.

---

## References

- [OpenClaw Compaction Docs](https://docs.openclaw.ai/concepts/compaction)
- [OpenClaw GitHub](https://github.com/openclaw/openclaw) — `src/agents/compaction.ts`, `compaction-safeguard.ts`
- [Anthropic: Building Effective Agents (2025)](https://www.anthropic.com/research/building-effective-agents)
- [Anthropic: Effective Context Engineering (Sept 2025)](https://www.anthropic.com/engineering/context-engineering)
- [Anthropic: Writing Effective Tools (Sept 2025)](https://www.anthropic.com/engineering/writing-effective-tools)
- [SWE-Agent](https://swe-agent.com/) — Agent-Computer Interface (ACI) design
- [SE-Agent (NeurIPS)](https://neurips.cc/) — Trajectory-level evolution and cross-trajectory knowledge synthesis
- [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter) — Minimal system prompt, profile-based customization
