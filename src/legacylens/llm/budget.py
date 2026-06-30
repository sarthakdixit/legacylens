"""Token budgeting and cost control.

A :class:`TokenBudget` tracks tokens consumed across a run and enforces a hard
ceiling. The gateway estimates a request's prompt cost before calling (so it can
refuse a call that would blow the budget) and records actual usage afterwards. This
keeps large-estate runs from running away on cost, which matters most exactly when
there are millions of lines to analyze.

Estimation is deliberately simple (~4 chars/token); it is a guardrail, not billing.
"""

from __future__ import annotations

from ..errors import BudgetExceededError


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class TokenBudget:
    def __init__(self, max_tokens: int | None = None):
        self.max_tokens = max_tokens
        self.spent = 0

    @property
    def remaining(self) -> float:
        if self.max_tokens is None:
            return float("inf")
        return max(0, self.max_tokens - self.spent)

    def check(self, estimated: int) -> None:
        """Raise if spending ``estimated`` more tokens would exceed the ceiling."""
        if self.max_tokens is None:
            return
        if self.spent + estimated > self.max_tokens:
            raise BudgetExceededError(
                f"token budget exhausted: {self.spent}/{self.max_tokens} spent, "
                f"request needs ~{estimated} more. Raise budget.max_tokens or narrow scope."
            )

    def record(self, tokens: int) -> None:
        self.spent += max(0, tokens)
