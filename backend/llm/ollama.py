"""
Local-model implementation of LLMProvider via Ollama (Phase 20: remove
the external LLM dependency).

No API key, no quota: the model runs on this machine. Default model is
qwen2.5:3b (4-bit, ~1.9 GB) -- small enough for an 8 GB Mac, supports
tool calling (needed by the ReAct loop), and handles Indian languages
reasonably for the translation feature.

    brew install ollama && ollama serve        # or the Ollama app
    ollama pull qwen2.5:3b
    LLM_PROVIDER=ollama uvicorn backend.main:app

Conversation state (TurnResult.raw_state) is simply the message list so
far -- Ollama's /api/chat is stateless, so every turn resends it.
"""

import uuid
from typing import Any, List

import httpx

from backend.config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_NUM_CTX, OLLAMA_TIMEOUT_SECONDS
from backend.llm.base import LLMProvider, LLMUnavailableError, ToolCall, TurnResult


class OllamaProvider(LLMProvider):
    def __init__(self, model: str = OLLAMA_MODEL, host: str = OLLAMA_HOST):
        self._model = model
        self._client = httpx.Client(base_url=host, timeout=OLLAMA_TIMEOUT_SECONDS)

    def start_turn(self, system_prompt: str, user_input: str, tools: list[dict]) -> TurnResult:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        return self._chat(messages, tools)

    def continue_turn(
        self,
        system_prompt: str,
        previous_state: Any,
        tool_results: List[dict],
        tools: list[dict],
    ) -> TurnResult:
        messages = list(previous_state)
        for result in tool_results:
            text = "\n".join(part.get("text", "") for part in result.get("result", []))
            messages.append({"role": "tool", "tool_name": result.get("name"), "content": text})
        return self._chat(messages, tools)

    def simple_completion(self, system_prompt: str, user_input: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]
        return (self._post(messages, tools=None)["message"].get("content") or "").strip()

    # --- internals ---

    def _chat(self, messages: list[dict], tools: list[dict]) -> TurnResult:
        data = self._post(messages, tools)
        message = data["message"]
        history = messages + [message]

        calls = message.get("tool_calls") or []
        if calls:
            return TurnResult(
                tool_calls=[
                    ToolCall(
                        id=call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                        name=call["function"]["name"],
                        arguments=call["function"].get("arguments") or {},
                    )
                    for call in calls
                ],
                final_text=None,
                raw_state=history,
            )
        return TurnResult(tool_calls=[], final_text=message.get("content") or "", raw_state=history)

    def _post(self, messages: list[dict], tools: list[dict] | None) -> dict:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": OLLAMA_NUM_CTX},
        }
        if tools:
            payload["tools"] = [_to_ollama_tool(t) for t in tools]

        try:
            response = self._client.post("/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(
                f"Can't reach the local model server at {self._client.base_url}. Start it with `ollama serve`.",
                "network",
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(
                f"The local model took longer than {OLLAMA_TIMEOUT_SECONDS}s to answer.", "network"
            ) from exc

        if response.status_code == 404:
            raise LLMUnavailableError(
                f"Local model '{self._model}' isn't downloaded. Run `ollama pull {self._model}`.", "model"
            )
        response.raise_for_status()
        return response.json()


def _to_ollama_tool(tool: dict) -> dict:
    """Our tool schema (agent/tools.py) -> Ollama/OpenAI function-tool format."""
    if "function" in tool:
        return tool
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
        },
    }
