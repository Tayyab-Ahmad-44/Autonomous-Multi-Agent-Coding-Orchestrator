"""Renders the three memory tiers into prompt sections, for every agent that takes memory.

One formatter, shared by Planner, SpecAgent and Worker. Everything active is injected - there is no
relevance filter, because at realistic sizes (tens of facts) the whole block is smaller than the
git diff the worker already sends, and every retriever we could build here fails in the direction
that hurts: a task titled "Add profile page" shares no keywords with `auth_scheme: OAuth`, but the
profile page still has to call an authenticated API.
"""
from __future__ import annotations

from typing import Any


MEMORY_PRECEDENCE_RULE = (
    "Where a user preference conflicts with what this repo currently does, follow the preference "
    "for new code, and match the repo's existing convention when modifying existing code - unless "
    "the task explicitly asks you to migrate."
)


def format_memory_sections(
    *,
    mission_decisions: list[Any] | None = None,
    repo_memories: list[Any] | None = None,
    user_preferences: list[Any] | None = None,
) -> str:
    """Render whichever tiers have content, as labeled sections.

    Conflicts BETWEEN tiers are surfaced, not resolved. If the user prefers pytest and the repo
    currently uses unittest, the agent sees both, plus the precedence rule. Silently dropping
    either one would hide the single most useful thing in the prompt - that the repo has drifted
    from what the user asked for - and leave the agent unable to tell "write a new test" from
    "migrate an existing suite".
    """
    user_block = _format_entries(user_preferences)
    repo_block = _format_entries(repo_memories)
    mission_block = _format_entries(mission_decisions)

    sections: list[str] = []
    if user_block:
        sections.append(
            "Your preferences (stated by the user - these take precedence for new code):\n"
            f"{user_block}"
        )
    if repo_block:
        sections.append(
            f"What we know about this repo (learned from prior missions):\n{repo_block}"
        )
    if mission_block:
        sections.append(
            f"Prior decisions in this mission (stay consistent with these):\n{mission_block}"
        )
    if user_block and repo_block:
        sections.append(MEMORY_PRECEDENCE_RULE)

    if not sections:
        return ""
    return "\n\n" + "\n\n".join(sections)


def _format_entries(entries: list[Any] | None) -> str:
    lines: list[str] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key", "")
        value = entry.get("value", "")
        if key or value:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)
