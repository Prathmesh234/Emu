"""
backend/prompts/plan_prompt.py

Mandatory planning prompt injected as the first user-turn directive
when the agent receives a new task. Forces the model to think through
the task step-by-step before taking any desktop action.

The plan is written to .emu/sessions/<id>/plan.md and auto-injected
periodically to keep the agent anchored.
"""


PLAN_DIRECTIVE = """\
[PLANNING REQUIRED]

Before you touch the keyboard, mouse, or shell — stop and think.

You MUST plan first. Call the update_plan tool to write your plan to plan.md.
This is not optional. No desktop actions until you have a plan.

Think through this step by step:

1. **Understand** — What exactly is the user asking? Restate it in your own words.
2. **Break down** — What are the concrete steps to get there? Number them.
3. **Identify risks** — What could go wrong? What assumptions am I making?
4. **Choose tools** — For each step: keyboard, mouse, shell, or a combination?
5. **Define done** — How will I know the task is complete? What does success look like?

Write your plan by calling update_plan(content=...). Format:

```
## Goal
<one-line restatement of the task>

## Steps
1. [ ] Step one — (tool: keyboard/mouse/shell) — expected outcome
2. [ ] Step two — ...
...

## Risks
- Risk or assumption worth noting

## Done when
- <concrete success criteria>
```

After writing the plan, take a screenshot to orient yourself, then begin from step 1.

Mark steps as [x] in your plan as you complete them. If your approach isn't
working after 2 attempts on a step, update the plan with a new strategy.
Periodically re-read your plan to stay on track.
"""


PLAN_REMINDER = """\
[PLAN CHECK]

Pause. Before your next action, quickly check:
- Are you still following your plan?
- Have you drifted from the original task?
- Should you update your plan based on what you've learned?

If you're on track, continue. If not, use read_plan or update_plan to re-orient.
"""
