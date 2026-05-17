import asyncio
from dataclasses import dataclass
from unittest import TestCase

from app.core.config import Settings
from app.services.llm_service import LLMJsonParseError, LLMService, parse_json_response


@dataclass
class FakeMessage:
    content: str


class FakeChatModel:
    async def ainvoke(self, input: list[tuple[str, str]]) -> FakeMessage:
        return FakeMessage(content='{"ok": true}')


class LLMServiceTests(TestCase):
    def test_parse_json_response_returns_object(self) -> None:
        self.assertEqual(parse_json_response('{"status": "ok"}'), {"status": "ok"})

    def test_parse_json_response_supports_json_fence(self) -> None:
        self.assertEqual(parse_json_response('```json\n{"status": "ok"}\n```'), {"status": "ok"})

    def test_parse_json_response_failure_is_clear(self) -> None:
        with self.assertRaisesRegex(LLMJsonParseError, "not valid JSON"):
            parse_json_response("not json")

    def test_service_uses_injected_model_without_api_call(self) -> None:
        service = LLMService(
            settings=Settings(openai_api_key="", default_llm_model="test-model"),
            chat_model=FakeChatModel(),
        )

        result = asyncio.run(
            service.generate_json(
                system_prompt="Test prompt",
                user_prompt="Return JSON",
                schema_hint={"ok": "boolean"},
            )
        )

        self.assertEqual(result, {"ok": True})
