"""
Gemini implementation of LLMProvider, using the Interactions API
(client.interactions.create / previous_interaction_id).

Requires google-genai>=1.0.0 -- see requirements.txt. If you hit
AttributeError on client.interactions, your installed SDK is too old:
    pip install -U google-genai
"""

import functools
from typing import Any, List

from google import genai
from google.genai import types
from google.genai._interactions import _exceptions as api_errors

from backend.config import GEMINI_API_KEY, LLM_MAX_RETRIES, MODEL
from backend.llm.base import LLMProvider, LLMUnavailableError, ToolCall, TurnResult


def _translate_errors(func):
    """Turns "this LLM can't be used right now" SDK errors into LLMUnavailableError."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except api_errors.RateLimitError as exc:
            raise LLMUnavailableError(
                "The AI service's usage quota is exhausted (HTTP 429). Check the API key's plan/billing "
                "at https://ai.dev/rate-limit, or try again later.", "quota") from exc
        except (api_errors.AuthenticationError, api_errors.PermissionDeniedError) as exc:
            raise LLMUnavailableError(
                "The AI service rejected the API key. Set a valid GEMINI_API_KEY.", "auth") from exc
        except api_errors.NotFoundError as exc:
            raise LLMUnavailableError(
                f"The configured model '{MODEL}' was not found. Set LAWGORITHM_MODEL to an available model.",
                "model") from exc
        except api_errors.APIConnectionError as exc:
            raise LLMUnavailableError("Could not reach the AI service (network error).", "network") from exc

    return wrapper


class GeminiProvider(LLMProvider):
    def __init__(self):
        if not GEMINI_API_KEY:
            raise LLMUnavailableError("No GEMINI_API_KEY (or GOOGLE_API_KEY) is set.", "auth")
        # The SDK's default retry policy backs off for ~100s on a 429
        # before raising; that's a hung upload for the user. Note the SDK
        # passes `attempts` straight through as the RETRY count of the
        # interactions client, not total attempts.
        self._client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=LLM_MAX_RETRIES)),
        )

    @_translate_errors
    def start_turn(self, system_prompt: str, user_input: str, tools: list[dict]) -> TurnResult:
        interaction = self._client.interactions.create(
            model=MODEL,
            system_instruction=system_prompt,
            input=user_input,
            tools=tools,
        )
        return self._to_turn_result(interaction)

    @_translate_errors
    def continue_turn(
        self,
        system_prompt: str,
        previous_state: Any,
        tool_results: List[dict],
        tools: list[dict],
    ) -> TurnResult:
        interaction = self._client.interactions.create(
            model=MODEL,
            system_instruction=system_prompt,
            previous_interaction_id=previous_state.id,
            input=tool_results,
            tools=tools,
        )
        return self._to_turn_result(interaction)

    @_translate_errors
    def simple_completion(self, system_prompt: str, user_input: str) -> str:
        interaction = self._client.interactions.create(
            model=MODEL,
            system_instruction=system_prompt,
            input=user_input,
        )
        return interaction.output_text.strip()

    @staticmethod
    def _to_turn_result(interaction) -> TurnResult:
        tool_call_steps = [
            s for s in interaction.steps if getattr(s, "type", None) == "function_call"
        ]

        if tool_call_steps:
            return TurnResult(
                tool_calls=[
                    ToolCall(id=c.id, name=c.name, arguments=c.arguments) for c in tool_call_steps
                ],
                final_text=None,
                raw_state=interaction,
            )

        return TurnResult(tool_calls=[], final_text=interaction.output_text, raw_state=interaction)
