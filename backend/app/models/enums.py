from __future__ import annotations

import enum


def enum_values(enum_class: type[enum.Enum]) -> list[str]:
    return [item.value for item in enum_class]


class RepositoryProvider(str, enum.Enum):
    github = "github"
    local = "local"
