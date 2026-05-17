# Agent Orchestrator

This context defines the domain language for a factory-style multi-agent coding orchestrator.

## Language

**Mission**:
A user-submitted software goal together with its full orchestration lifecycle, from planning through validation.
_Avoid_: Project, repository, chat thread

## Relationships

- A **Mission** owns its planning, validation, execution, reports, and produced artifacts.
- A **Mission** is completed only when its validation contract passes.

## Example dialogue

> **Dev:** "Can a **Mission** be marked completed after workers finish their tasks?"
> **Domain expert:** "No. A **Mission** is completed only after the validators confirm the validation contract passes."

## Flagged ambiguities

- "mission" was clarified as the lifecycle around one submitted goal, not a repository, long-lived project, or chat thread.
