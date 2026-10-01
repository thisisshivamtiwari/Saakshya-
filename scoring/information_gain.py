"""Information-gain helpers: the metric itself lives in ``core.strategy``; this adds reporting."""

from __future__ import annotations

from core.strategy import SearchBudget, information_gain


def branch_summary(budget: SearchBudget) -> str:
    """One line per query branch: average gain and whether the branch was exhausted."""
    stats = budget.stats()
    lines = [f"Queries executed: {stats['executed']}/{stats['max_queries']} "
             f"(results {stats['results_total']}, new {stats['new_total']})"]
    branches: dict[str, float] = stats["branches"]  # type: ignore[assignment]
    exhausted = set(stats["exhausted"])  # type: ignore[arg-type]
    for name in sorted(branches):
        flag = " (exhausted)" if name in exhausted else ""
        lines.append(f"  - {name}: avg information gain {branches[name]:.2f}{flag}")
    return "\n".join(lines)


__all__ = ["information_gain", "branch_summary"]
