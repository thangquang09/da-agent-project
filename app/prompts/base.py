from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    prompt_type: Literal["chat", "text", "messages"]
    messages: list[dict[str, str]]
