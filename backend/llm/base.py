"""
LLM provider abstraction.

agent/agent.py drives the REASON -> ACT -> OBSERVE loop; this module
is the only thing that actually talks to a specific vendor SDK. Swap
Gemini for GPT/Claude/a local model by writing one new class here and
changing a single import in agent.py -- nothing about the ReAct loop,
tool dispatch, schema validation, or risk gating has to change.

A "turn" is intentionally modeled as: give the model the current
conversation state (system prompt + either the initial input or a
tool result), get back either more tool calls or a final text answer.
This maps directly onto Gemini's Interactions API
(client.interactions.create / previous_interaction_id) but is generic
enough to implement against OpenAI's or Anthropic's tool-use APIs too.
"""

from dataclasses import dataclass
from typing import Any, List, Optional


class LLMUnavailableError(RuntimeError):
    """
    The LLM can't be used at all right now -- quota exhausted, bad/missing
    API key, unknown model, or the API is unreachable. Distinct from a
    one-off bad response: retrying the next clause won't help, so the API
    layer aborts the whole document with a clear 503 instead of grinding
    through every clause (and the SDK's retry back-off) only to fail each one.
    """

    def __init__(self, message: str, reason: str):
        super().__init__(message)
        self.reason = reason  # quota | auth | model | network


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class TurnResult:
    """
    Exactly one of (tool_calls, final_text) should be populated.
    """
    tool_calls: List[ToolCall]
    final_text: Optional[str]
    raw_state: Any  # provider-specific handle (e.g. interaction object/id) needed to continue the conversation


class LLMProvider:
    def start_turn(self, system_prompt: str, user_input: str, tools: list[dict]) -> TurnResult:
        raise NotImplementedError

    def continue_turn(
        self,
        system_prompt: str,
        previous_state: Any,
        tool_results: List[dict],
        tools: list[dict],
    ) -> TurnResult:
        raise NotImplementedError

    def simple_completion(self, system_prompt: str, user_input: str) -> str:
        """For single-shot calls with no tools, e.g. translation."""
        raise NotImplementedError
