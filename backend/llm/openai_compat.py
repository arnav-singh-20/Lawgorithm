"""
LLMProvider for any OpenAI-compatible chat-completions API. Used for
Groq (https://api.groq.com/openai/v1), whose free tier needs no credit
card and doesn't train on API data:

    LLM_PROVIDER=groq  GROQ_API_KEY=...   (in .env, never in code)

Free-tier limits are per model: 30 requests/min, 1,000/day, 8,000
tokens/min, 200,000 tokens/day. Two consequences handled here:
  - a 429 with a short retry-after (the per-minute window) is waited
    out and retried, so a 5-clause contract doesn't fail half-way;
  - a 429 with a long retry-after (the daily cap) is reported as
    LLMUnavailableError("quota") so the API can say so plainly.
The work is split across two models (config.GROQ_MODEL_AGENT for the
legal reasoning, GROQ_MODEL_LIGHT for everything else) so each gets its
own budget. Each role also has fallback models: when a model's daily
allowance (TPD) runs out, that model is benched until Groq says it has
room again and the next one in the list answers instead -- every model
has its own free allowance, so the site keeps working.
"""

import json
import logging
import re
import time
import uuid
from typing import Any, List

import httpx

from backend.llm.base import LLMProvider, LLMUnavailableError, ToolCall, TurnResult

logger = logging.getLogger(__name__)

MAX_WAIT_PER_RETRY_S = 65     # longer than this means the daily cap, not the minute window
MAX_RATE_LIMIT_RETRIES = 6

# model id -> time.time() when its daily allowance has room again. Shared
# by every provider instance: the agent and light roles can share a model.
_benched_until: dict[str, float] = {}


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str, name: str = "LLM API", timeout: float = 120,
                 fallback_models: list[str] | None = None):
        if not api_key:
            raise LLMUnavailableError(f"No API key configured for {name} (set GROQ_API_KEY in .env, or as a Space secret).", "auth")
        self._model = model
        self._models = [model] + [m for m in (fallback_models or []) if m != model]
        self._name = name
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    # --- LLMProvider ---------------------------------------------------

    def start_turn(self, system_prompt: str, user_input: str, tools: list[dict]) -> TurnResult:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
        return self._chat(messages, tools)

    def continue_turn(self, system_prompt: str, previous_state: Any, tool_results: List[dict], tools: list[dict]) -> TurnResult:
        messages = list(previous_state)
        for result in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": result.get("call_id"),
                "name": result.get("name"),
                "content": "\n".join(part.get("text", "") for part in result.get("result", [])),
            })
        return self._chat(messages, tools)

    def simple_completion(self, system_prompt: str, user_input: str) -> str:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}]
        return (self._post(messages, tools=None)["choices"][0]["message"].get("content") or "").strip()

    # --- internals -----------------------------------------------------

    def _chat(self, messages: list[dict], tools: list[dict]) -> TurnResult:
        message = self._post(messages, tools)["choices"][0]["message"]
        # keep only the fields the API accepts back on the next turn
        assistant = {"role": "assistant", "content": message.get("content") or ""}
        if message.get("tool_calls"):
            assistant["tool_calls"] = message["tool_calls"]
        history = messages + [assistant]

        calls = message.get("tool_calls") or []
        if calls:
            return TurnResult(
                tool_calls=[
                    ToolCall(
                        id=call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                        name=call["function"]["name"],
                        arguments=_parse_arguments(call["function"].get("arguments")),
                    )
                    for call in calls
                ],
                final_text=None,
                raw_state=history,
            )
        return TurnResult(tool_calls=[], final_text=message.get("content") or "", raw_state=history)

    def _available_model(self) -> str | None:
        now = time.time()
        return next((m for m in self._models if _benched_until.get(m, 0) <= now), None)

    def _post(self, messages: list[dict], tools: list[dict] | None) -> dict:
        payload = {"messages": messages, "temperature": 0.2}
        if tools:
            payload["tools"] = [_to_openai_tool(t) for t in tools]
            payload["tool_choice"] = "auto"

        attempt = 0
        while attempt <= MAX_RATE_LIMIT_RETRIES:
            model = self._available_model()
            if model is None:
                soonest = min(_benched_until.get(m, 0) for m in self._models) - time.time()
                raise LLMUnavailableError(_quota_message(soonest), "quota")
            payload["model"] = model
            if "gpt-oss" in model:
                payload["reasoning_effort"] = "medium"
            else:
                payload.pop("reasoning_effort", None)
            attempt += 1
            try:
                response = self._client.post("/chat/completions", json=payload)
            except httpx.TimeoutException as exc:
                logger.warning("%s timed out", self._name)
                raise LLMUnavailableError("The AI took too long to answer. Please try again in a minute.", "network") from exc
            except httpx.HTTPError as exc:
                logger.warning("%s unreachable: %s", self._name, type(exc).__name__)
                raise LLMUnavailableError("The AI couldn't be reached. Please try again in a minute.", "network") from exc

            if response.status_code == 429:
                wait = _retry_after_seconds(response)
                if _is_daily_limit(response, wait):
                    # this model's daily allowance is used up: bench it and
                    # let the next model answer (doesn't count as a retry)
                    _benched_until[model] = time.time() + (wait or 3600)
                    logger.warning("%s daily limit on %s; switching model", self._name, model)
                    attempt -= 1
                    continue
                if wait is not None and attempt <= MAX_RATE_LIMIT_RETRIES:
                    logger.info("%s per-minute limit on %s: waiting %.1fs", self._name, model, wait)
                    time.sleep(wait + 0.5)
                    continue
                raise LLMUnavailableError("Lawgorithm is very busy right now. Please try again in a few minutes.", "quota")
            if response.status_code in (401, 403):
                logger.error("%s rejected the API key (check GROQ_API_KEY)", self._name)
                raise LLMUnavailableError("The AI service isn't set up correctly right now. Please try again later.", "auth")
            if response.status_code == 404:
                raise LLMUnavailableError(f"{self._name} model '{model}' not found.", "model")
            if response.status_code == 413:
                raise ValueError(f"{self._name}: request too large for the free tier ({_error_message(response)})")
            if response.status_code == 400:
                message = _error_message(response)
                if "tool_use_failed" in message:
                    # gpt-oss sometimes "calls" a non-existent tool (e.g. "json")
                    # to deliver its final answer. Groq rejects it but returns
                    # the attempted output in failed_generation -- usually the
                    # complete answer, so recover it as the reply.
                    recovered = _recover_failed_generation(response)
                    if recovered is not None:
                        return {"choices": [{"message": {"role": "assistant", "content": recovered}}]}
                    if attempt <= 1:
                        logger.info("%s returned a malformed tool call; retrying", self._name)
                        continue
                    if payload.get("tools"):
                        # last resort: ask for a plain-text answer with no tools
                        logger.info("%s: retrying without tools", self._name)
                        payload = {k: v for k, v in payload.items() if k not in ("tools", "tool_choice")}
                        continue
                raise ValueError(f"{self._name} rejected the request: {message}")
            if response.status_code >= 500:
                if attempt <= 2:
                    time.sleep(2 * attempt)
                    continue
                raise LLMUnavailableError("The AI is having problems right now. Please try again in a few minutes.", "network")
            response.raise_for_status()
            return response.json()
        raise LLMUnavailableError("Lawgorithm is very busy right now. Please try again in a few minutes.", "quota")


def _is_daily_limit(response: httpx.Response, wait: float | None) -> bool:
    """Per-day limits (TPD/RPD) vs the per-minute window (TPM/RPM)."""
    message = _error_message(response).lower()
    if "per day" in message or "(tpd)" in message or "(rpd)" in message:
        return True
    if "per minute" in message or "(tpm)" in message or "(rpm)" in message:
        return False
    return wait is None or wait > MAX_WAIT_PER_RETRY_S


def _quota_message(wait_seconds: float | None) -> str:
    # A contract needs many requests, so Groq's retry-after (sized for ONE
    # request) would over-promise; the allowance frees up gradually.
    if wait_seconds and wait_seconds < 45 * 60:
        when = "in about an hour"
    else:
        when = "in a few hours"
    return ("Lawgorithm has used up today's free capacity for checking contracts. "
            f"It frees up gradually -- please try again {when}.")


def _recover_failed_generation(response: httpx.Response) -> str | None:
    """
    Pull a final JSON answer out of Groq's failed_generation, e.g.
    '{"name": "json", "arguments": {"plain_explanation": ...}}' or the bare
    answer object. Only accepted if it looks like our answer schema.
    """
    try:
        raw = response.json().get("error", {}).get("failed_generation") or ""
    except Exception:
        return None
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    for candidate in (obj, obj.get("arguments") if isinstance(obj, dict) else None,
                      obj.get("parameters") if isinstance(obj, dict) else None):
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except json.JSONDecodeError:
                continue
        if isinstance(candidate, dict) and "plain_explanation" in candidate:
            return json.dumps(candidate)
    return None


def _error_message(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        return f"{error.get('code') or error.get('type') or ''}: {error.get('message', '')}"[:300]
    except Exception:
        return response.text[:300]


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return 10.0   # no hint: a short, polite wait
    try:
        return float(value)
    except ValueError:
        return None


def _parse_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _to_openai_tool(tool: dict) -> dict:
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
