"""
A scripted fake LLMProvider for exercising backend/agent/agent.py's
ReAct loop mechanics without a live Gemini call. This sandbox has no
network access to Google's API, so this is how the loop's tool-calling,
multi-turn evidence gathering, and 3-search cutoff get tested for real
instead of skipped.

Not a mock of "what Gemini would say" in any deep sense -- just a
sequence of canned TurnResults returned in order, one per start_turn/
continue_turn call, so a test can script exactly the conversation shape
it wants to exercise (single search, weak-then-better evidence, model
stubbornly searching past the cutoff, etc).
"""

from backend.llm.base import LLMProvider, TurnResult


class ScriptedProvider(LLMProvider):
    def __init__(self, turns: list[TurnResult]):
        self._turns = list(turns)
        self._index = 0
        self.start_turn_calls = 0
        self.continue_turn_calls = []  # list of (tools,) per call, for asserting on cutoff behavior

    def start_turn(self, system_prompt, user_input, tools):
        self.start_turn_calls += 1
        return self._next()

    def continue_turn(self, system_prompt, previous_state, tool_results, tools):
        self.continue_turn_calls.append({"tools": tools, "tool_results": tool_results})
        return self._next()

    def simple_completion(self, system_prompt, user_input):
        return self._next().final_text

    def _next(self) -> TurnResult:
        if self._index >= len(self._turns):
            raise AssertionError(
                f"ScriptedProvider ran out of scripted turns after {self._index} calls -- "
                "the agent loop asked for more turns than the test expected."
            )
        turn = self._turns[self._index]
        self._index += 1
        return turn

    @property
    def calls_made(self) -> int:
        return self._index
