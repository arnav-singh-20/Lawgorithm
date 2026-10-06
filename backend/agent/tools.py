"""
Tool schemas + execution dispatcher (Phase 8).

version1.py had one tool (search_legal_reference against a mock dict).
This adds the retrieval tool backed by the real vector store. Risk
classification / simplification stays a single structured LLM call
(same as v1) rather than a separate tool, since it needs the clause
text + retrieved law together in context anyway. Translation is kept
as a separate explicit call (translation/translator.py) invoked by the
API layer after a clause is approved, rather than as an agent tool --
that keeps the ReAct loop for a single clause short and predictable.

`execute_tool` takes a per-run `context` dict and appends any
structured search results to context["retrieved_sources"]. The agent
loop hands in a fresh context for every clause, so this accumulates
every source seen across all tool calls in that clause's ReAct loop
(needed later for citation/grounding validation) without relying on
any global/module-level state that would break under concurrent
requests.
"""

from backend.rag.retrieval import (
    search_legal_reference as _search_legal_reference,
    search_legal_reference_structured,
)

from backend.config import AGENT_MAX_STEPS

MAX_TOOL_CALLS = AGENT_MAX_STEPS  # configurable via the AGENT_MAX_STEPS env var

TOOLS = [
    {
        "type": "function",
        "name": "search_legal_reference",
        "description": (
            "Search the Indian legal reference corpus (Contract Act, "
            "labour codes, rent control acts, etc.) for statutory text "
            "relevant to a clause. Always call this before explaining a "
            "clause. Do not rely on memory of Indian law. You may call "
            f"this up to {MAX_TOOL_CALLS} times per clause if the first "
            "search doesn't return enough evidence -- refine your query "
            "rather than repeating it verbatim."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural-language description of the clause's legal "
                        "topic, e.g. 'post-employment non-compete restraint "
                        "of trade' or 'tenant notice period before vacating'."
                    ),
                },
                "domain": {
                    "type": "string",
                    "description": "Optional filter: 'employment' or 'rental'.",
                },
            },
            "required": ["query"],
        },
    }
]


def execute_tool(name: str, arguments: dict, context: dict) -> str:
    if name == "search_legal_reference":
        structured = search_legal_reference_structured(
            query=arguments["query"],
            domain=arguments.get("domain"),
        )
        context.setdefault("retrieved_sources", []).extend(structured)

        if not structured:
            return "No matching statute found in the reference corpus for this query."
        return _format_for_llm(structured, arguments["query"])

    return f"Unknown tool: {name}"


def _format_for_llm(structured: list[dict], query: str = "") -> str:
    from backend.rag.retrieval import format_results

    return format_results(structured, query)
