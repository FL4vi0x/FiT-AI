"""The assistant's versioned identity (system prompt).

This text GUIDES the model; it is not a safety layer. Whether an answer about the vehicle is
grounded in real tool data is checked in code in a later phase (P6), never trusted to the prompt.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import resources

from fit_ai.ai.models import ChatMessage

SYSTEM_PROMPT_VERSION = "1"
_PROMPT_FILE = "system_pt_br.md"


@dataclass(frozen=True)
class SystemPrompt:
    version: str
    language: str
    text: str
    sha256: str  # fingerprint for audit: lets a log say which exact prompt was in force

    def as_message(self) -> ChatMessage:
        return ChatMessage.system(self.text)


def load_system_prompt() -> SystemPrompt:
    text = resources.files("fit_ai.ai").joinpath("prompts", _PROMPT_FILE).read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError("the system prompt file is empty")
    return SystemPrompt(
        version=SYSTEM_PROMPT_VERSION,
        language="pt-BR",
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
