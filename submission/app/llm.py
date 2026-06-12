"""LLM integration.

Uses OpenAI when OPENAI_API_KEY is configured and falls back to the local mock
LLM for offline labs.
"""
import logging
from typing import Any

from app.config import settings
from utils.mock_llm import ask as mock_ask

logger = logging.getLogger(__name__)

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - only used before dependencies are installed
    AsyncOpenAI = None


_client = AsyncOpenAI(api_key=settings.openai_api_key) if AsyncOpenAI and settings.openai_api_key else None


def _history_to_input(history: list[dict[str, Any]], question: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in history[-10:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    return messages


async def ask_llm(question: str, history: list[dict[str, Any]] | None = None) -> str:
    if not _client:
        return mock_ask(question)

    try:
        response = await _client.responses.create(
            model=settings.llm_model,
            instructions=settings.llm_system_prompt,
            input=_history_to_input(history or [], question),
            max_output_tokens=settings.llm_max_output_tokens,
        )
        answer = response.output_text.strip()
        return answer or "Xin loi, minh chua tao duoc cau tra loi. Ban thu hoi lai nhe."
    except Exception as exc:
        logger.exception("openai_response_failed")
        if settings.environment == "production":
            raise
        return f"{mock_ask(question)}\n\n[OpenAI fallback: {exc}]"
