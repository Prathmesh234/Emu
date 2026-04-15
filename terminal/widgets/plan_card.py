"""Plan review card — displayed when the agent creates/updates a task plan.

Shows the plan content in a bordered panel and waits for user
approval (Enter) or rejection (Escape) before the agent continues.
"""

from __future__ import annotations

from textual.widgets import Static


class PlanCard(Static):
    """Displays a task plan and gates continuation on user approval."""

    def __init__(self, content: str) -> None:
        self._plan_content = content
        super().__init__(self._render())

    def _render(self) -> str:
        lines = [
            "Plan Review",
            "-" * 40,
            self._plan_content,
            "-" * 40,
            "[Enter] Approve  |  [Escape] Reject",
        ]
        return "\n".join(lines)
