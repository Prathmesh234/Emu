"""
backend/prompts/plan_prompt.py

Mandatory planning prompt injected as the first user-turn directive
when the agent receives a new task. Forces the model to think through
the task step-by-step before taking any desktop action.

The plan is written to .emu/sessions/<id>/plan.md and auto-injected
periodically to keep the agent anchored.
"""


PLAN_DIRECTIVE = """\
[PLANNING ASSESSMENT]

Before acting, assess the task complexity:

**Simple task** (1-2 steps, e.g. click a button, type a query): Skip planning. Proceed directly with a screenshot and action.

**Complex task** (3+ steps): You MUST plan first. Call update_plan(content=...) with this format:

```
## Goal
<one-line restatement>

## Steps
1. [ ] Step one — expected outcome
2. [ ] Step two — ...

## Done when
- <success criteria>
```

IMPORTANT: After calling update_plan, STOP. Do not take any desktop actions. The user will review your plan and either approve or request changes. Wait for their response before proceeding.

During execution, mark steps [x] as you complete them. If stuck after 2 attempts on a step, update the plan.
"""


PLAN_REMINDER = """\
[PLAN CHECK]

If you created a plan for this task, pause and quickly check:
- Are you still following it?
- Have you drifted from the original task?
- Should you update your plan based on what you've learned?

If you're on track (or if this is a simple task without a plan), continue. If not, use read_plan or update_plan to re-orient.
"""
