from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from langchain_openai import ChatOpenAI

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)


class LLMServiceError(RuntimeError):
    pass


class LLMJsonParseError(LLMServiceError):
    pass


class AsyncChatModel(Protocol):
    async def ainvoke(self, input: list[tuple[str, str]]) -> Any:
        pass


def parse_json_response(content: str) -> dict[str, Any]:
    cleaned = _strip_json_fence(content)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        preview = cleaned[:200].replace("\n", "\\n")
        raise LLMJsonParseError(
            f"LLM response was not valid JSON: {exc.msg} at character {exc.pos}. "
            f"Response preview: {preview!r}"
        ) from exc

    if not isinstance(parsed, dict):
        raise LLMJsonParseError(
            f"LLM response JSON must be an object, got {type(parsed).__name__}."
        )
    return parsed


class LLMService:
    def __init__(
        self,
        settings: Settings | None = None,
        chat_model: AsyncChatModel | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._chat_model = chat_model

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema_hint: dict[str, Any],
    ) -> dict[str, Any]:
        prompt_name = _prompt_name(system_prompt)
        logger.info(
            "Generating JSON with LLM",
            extra={"prompt_name": prompt_name, "model": self._settings.default_llm_model},
        )
        schema_prompt = (
            f"{user_prompt}\n\n"
            "Return only a valid JSON object matching this schema hint:\n"
            f"{json.dumps(schema_hint, sort_keys=True)}"
        )
        response = await self._model().ainvoke(
            [
                ("system", system_prompt),
                ("human", schema_prompt),
            ]
        )
        return parse_json_response(_message_content(response))

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        prompt_name = _prompt_name(system_prompt)
        logger.info(
            "Generating text with LLM",
            extra={"prompt_name": prompt_name, "model": self._settings.default_llm_model},
        )
        response = await self._model().ainvoke(
            [
                ("system", system_prompt),
                ("human", user_prompt),
            ]
        )
        return _message_content(response)

    def _model(self) -> AsyncChatModel:
        if self._chat_model is not None:
            return self._chat_model
        if not self._settings.openai_api_key:
            raise LLMServiceError("OPENAI_API_KEY is required to call the LLM service.")

        self._chat_model = ChatOpenAI(
            model=self._settings.default_llm_model,
            api_key=self._settings.openai_api_key,
        )
        return self._chat_model


def _strip_json_fence(content: str) -> str:
    cleaned = content.strip()
    if not cleaned.startswith("```"):
        return cleaned

    lines = cleaned.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return cleaned


def _message_content(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content)


def _prompt_name(system_prompt: str) -> str:
    first_line = next((line.strip() for line in system_prompt.splitlines() if line.strip()), "")
    return first_line[:80] or "unnamed_prompt"
