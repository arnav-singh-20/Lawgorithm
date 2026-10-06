"""
LAWGORITHM AGENT -- v4

    REASON -> ACT -> OBSERVE -> ... -> FINAL -> VALIDATE -> SCORE -> ROUTE

Same hand-built ReAct loop as version1.py, now with a trust layer on
top of it:

  1. The model gets up to MAX_TOOL_CALLS (3) searches. After that it's
     cut off (tools=[] on the next turn) and must answer with whatever
     evidence it already has -- it never gets to search indefinitely
     chasing a good answer.
  2. The model's structured output (ModelClauseOutput) makes claims,
     each with supporting_source_ids -- not just a final paragraph.
  3. citation_validator checks every cited source_id was actually
     retrieved this run (catches invented sections/acts).
  4. claim_validator asks an independent verifier call whether the
     cited source TEXT actually supports each claim (catches real-but-
     irrelevant citations).
  5. confidence/engine.py combines retrieval quality, grounding score,
     citation validity, output consistency, and the model's own
     self-rating into one confidence number -- never just the model's
     self-rating alone.
  6. That confidence (+ citation validity + grounding score) determines
     an abstention status: grounded / partially_grounded /
     insufficient_grounding / human_review_required. Uncertain never
     means "guess anyway".
  7. Before the loop, the clause-precedent index (rag/clause_index.py)
     predicts the clause TYPE from ~63k labelled example clauses. The
     type and a statute-search suggestion go to the model as a hint
     only -- precedents never enter retrieved_sources, so they can't be
     cited as law.
  8. After scoring, Phase 9 routing flags (conflicting sources,
     jurisdiction uncertainty, unverified source) are computed and any
     of them forces human review.
"""

import json
import logging

from pydantic import ValidationError

from backend.agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_PREFETCH
from backend.agent.tools import TOOLS, MAX_TOOL_CALLS, execute_tool
from backend.agent.schemas import ModelClauseOutput, ClauseAnalysisResult
from backend.rag.clause_index import classify_clause_type
from backend.rag.retrieval import best_retrieval_score, format_results, search_legal_reference_structured
from backend.config import AGENT_MODE, PREFETCH_EXCERPT_CHARS, PREFETCH_MAX_SOURCES
from backend.validation.citation_validator import validate_citations
from backend.validation.claim_validator import verify_grounding, grounding_score_and_status
from backend.confidence.engine import ConfidenceInputs, calculate_confidence, determine_status
from backend.risk.risk_rules import should_send_for_verification
from backend.risk.routing_flags import compute_review_flags
from backend.risk.decision import clause_decision

logger = logging.getLogger(__name__)

_provider = None


def _get_provider():
    """
    Lazy singleton -- the Gemini SDK is only imported/instantiated the
    first time an agent actually runs, not at module import time. Keeps
    `import backend.agent.agent` safe in contexts that don't have the
    SDK installed (e.g. a test importing something else from this
    module, or future tooling that just wants _parse_final_answer /
    _consistency_score without touching Gemini at all).
    """
    global _provider
    if _provider is None:
        from backend.llm import get_provider

        _provider = get_provider()
    return _provider


def run_agent(
    clause_text: str,
    clause_id: str = None,
    clause_title: str = None,
    provider=None,
    known_states: set[str] | None = None,
    document_context: str = "",
    mode: str | None = None,
) -> dict:
    """
    `document_context` is the whole-document summary
    (agent/summarizer.py::summary_as_context) so a clause is judged
    against the rest of the contract, not in isolation.
    `known_states` are Indian states the whole document has been
    established to concern (detected by the API layer from the full
    text); used by the Phase 9 jurisdiction check.

    `provider` is an optional LLMProvider override, purely for testing
    the ReAct loop's mechanics (tool-calling, the 3-search cutoff,
    multi-turn evidence gathering) with a scripted fake instead of a
    live Gemini call -- see tests/test_agent_react_loop.py. Production
    callers should never pass this; it defaults to the real lazy
    Gemini singleton.
    """
    logger.info("Agent start for clause_id=%s", clause_id)
    llm = provider or _get_provider()

    clause_type_info = classify_clause_type(clause_text)
    context = {
        "retrieved_sources": [],
        "clause_text": clause_text,
        "clause_type_info": clause_type_info,
        "known_states": set(known_states or ()),
    }

    if (mode or AGENT_MODE) == "prefetch":
        law_block = _prefetch_law(clause_text, clause_title, clause_type_info, context)
        turn = llm.start_turn(
            system_prompt=SYSTEM_PROMPT_PREFETCH,
            user_input=_build_user_input(clause_text, clause_type_info, document_context, law_block),
            tools=[],
        )
        return _finalize(_parse_final_answer(turn.final_text or ""), context, clause_id, clause_title)

    turn = llm.start_turn(
        system_prompt=SYSTEM_PROMPT,
        user_input=_build_user_input(clause_text, clause_type_info, document_context),
        tools=TOOLS,
    )

    searches_done = 0
    # Worst case turn count: 1 initial turn + MAX_TOOL_CALLS turns that
    # each execute a real search + 1 more turn to process whatever the
    # model says after being cut off (tools=[]). That's MAX_TOOL_CALLS+2
    # turns to *inspect*, not MAX_TOOL_CALLS+1 -- a model that ignores
    # the cutoff instruction and asks for one more search anyway still
    # needs its post-cutoff response actually read, or the loop gives up
    # and returns a bare {"error": ...} with no clause detail at all,
    # which is worse than the insufficient_grounding abstention this
    # whole mechanism exists to produce instead.
    for _ in range(MAX_TOOL_CALLS + 2):
        if not turn.tool_calls:
            parsed = _parse_final_answer(turn.final_text)
            return _finalize(parsed, context, clause_id, clause_title)

        if searches_done >= MAX_TOOL_CALLS:
            # Cut off further searching -- force a final answer from
            # whatever evidence has already been gathered. Never let the
            # model search indefinitely chasing a confident-sounding answer.
            cutoff_results = [
                {
                    "type": "function_result",
                    "name": call.name,
                    "call_id": call.id,
                    "result": [
                        {
                            "type": "text",
                            "text": (
                                f"Maximum of {MAX_TOOL_CALLS} searches reached. "
                                "Provide your final JSON analysis now using only "
                                "the evidence already retrieved. If it isn't "
                                "enough, say so plainly and lower llm_confidence."
                            ),
                        }
                    ],
                }
                for call in turn.tool_calls
            ]
            turn = llm.continue_turn(
                system_prompt=SYSTEM_PROMPT,
                previous_state=turn.raw_state,
                tool_results=cutoff_results,
                tools=[],
            )
            continue

        tool_results = []
        for call in turn.tool_calls:
            # Name only: the arguments are search queries derived from the
            # contract, and contract content must not end up in logs.
            logger.info("Tool call: %s", call.name)
            result_text = execute_tool(call.name, call.arguments, context)
            tool_results.append(
                {
                    "type": "function_result",
                    "name": call.name,
                    "call_id": call.id,
                    "result": [{"type": "text", "text": result_text}],
                }
            )
        searches_done += 1

        turn = llm.continue_turn(
            system_prompt=SYSTEM_PROMPT,
            previous_state=turn.raw_state,
            tool_results=tool_results,
            tools=TOOLS,
        )

    return {"error": "Agent did not produce a final answer after the search cutoff."}


import re


CLAUSE_MARKER = "CLAUSE TO EXPLAIN"


def _prefetch_law(clause_text: str, clause_title: str | None, clause_type_info: dict | None, context: dict) -> str:
    """
    Prefetch mode: search the statute library on the model's behalf --
    with the clause-type hint's statute query (precise legal vocabulary)
    and with the clause's own words (catches what the hint misses) -- and
    keep the best PREFETCH_MAX_SOURCES sections, alternating between the
    two result lists. They go into context["retrieved_sources"] exactly as
    tool results would, so citation checking is unchanged.
    """
    queries = []
    if clause_type_info and clause_type_info.get("statute_query"):
        queries.append(clause_type_info["statute_query"])
    queries.append(f"{clause_title or ''} {clause_text[:500]}".strip())

    # When the contract's state is known, another state's rent law is
    # never the right source (seen live: a Bengaluru lease got Tamil Nadu
    # and UP sections). Central Acts and the Model Tenancy Act stay.
    known_states = {s.lower() for s in context.get("known_states") or ()}

    def applies(source: dict) -> bool:
        jurisdiction = (source.get("jurisdiction") or "India").strip()
        if not known_states or jurisdiction == "India" or jurisdiction.startswith("Model"):
            return True
        return jurisdiction.lower() in known_states

    result_lists = [[r for r in search_legal_reference_structured(q, top_k=8) if applies(r)][:4] for q in queries]
    chosen, seen = [], set()
    for rank in range(max((len(r) for r in result_lists), default=0)):
        for results in result_lists:
            if rank < len(results) and results[rank]["id"] not in seen and len(chosen) < PREFETCH_MAX_SOURCES:
                seen.add(results[rank]["id"])
                chosen.append(results[rank])
    context.setdefault("retrieved_sources", []).extend(chosen)
    if not chosen:
        return "LAW FOUND FOR THIS CLAUSE: none -- the library has no matching section."
    return "LAW FOUND FOR THIS CLAUSE:\n\n" + format_results(chosen, " ".join(queries), PREFETCH_EXCERPT_CHARS)


def _build_user_input(clause_text: str, clause_type_info: dict | None, document_context: str = "",
                      law_block: str = "") -> str:
    """
    Background first, the clause LAST. Small local models weight the end
    of the prompt most heavily; with the summary after the clause, qwen2.5:3b
    explained the whole contract instead of the one clause (seen live).
    """
    parts = []
    if document_context:
        parts.append(
            "Background about the whole contract (context only -- NOT a legal source, do not cite it, "
            "and do not describe other clauses in your answer):\n" + document_context
        )
    if clause_type_info and clause_type_info.get("clause_type"):
        hint = (
            "Clause-type hint (from similar example clauses, NOT a legal source, do not cite): "
            f"{clause_type_info['label']} (match confidence {clause_type_info['confidence']:.0%})."
        )
        if clause_type_info.get("statute_query"):
            hint += f" A useful statute search may be: \"{clause_type_info['statute_query']}\"."
        if clause_type_info.get("risk_prone"):
            hint += " Clauses of this type are often one-sided in Indian contracts -- check carefully."
        parts.append(hint)
    if law_block:
        parts.append(law_block)
    parts.append(f"{CLAUSE_MARKER} (explain only this clause):\n\n{clause_text}")
    return "\n\n".join(parts)


def clean_consequence(raw) -> str:
    """
    The phrase must slot into "If you don't fix it, <consequence>." -- so
    drop a repeated lead-in, the final full stop and a leading capital.
    """
    text = " ".join(str(raw or "").split())
    text = re.sub(r"^(if you (do not|don't|don’t) fix (it|this)[,:]?\s*)", "", text, flags=re.IGNORECASE)
    text = text.rstrip(" .")
    if text[:1].isupper() and not text[:2].isupper() and not text.startswith("I "):
        text = text[0].lower() + text[1:]
    return text[:300]


def _sanitize_model_payload(parsed: dict, raw_text: str = "") -> dict:
    """
    Sanitize and normalize model output fields to match ModelClauseOutput schema.
    Handles common LLM deviations (e.g. risk='High' instead of 'red', string confidence, etc.).
    """
    if not isinstance(parsed, dict):
        parsed = {}

    plain_explanation = parsed.get("plain_explanation") or raw_text or "Explanation unavailable."
    legal_assessment = parsed.get("legal_assessment") or "No detailed legal assessment provided."

    raw_risk = str(parsed.get("risk_level", "amber")).strip().lower()
    risk_mapping = {
        "red": "red",
        "high": "red",
        "critical": "red",
        "severe": "red",
        "amber": "amber",
        "yellow": "amber",
        "medium": "amber",
        "moderate": "amber",
        "green": "green",
        "low": "green",
        "normal": "green",
        "safe": "green",
    }
    risk_level = risk_mapping.get(raw_risk, "amber")

    raw_conf = parsed.get("llm_confidence", 0.5)
    try:
        llm_confidence = float(raw_conf)
        llm_confidence = max(0.0, min(1.0, llm_confidence))
    except (ValueError, TypeError):
        llm_confidence = 0.5

    recommended_action = parsed.get("recommended_action") or ""
    if not isinstance(recommended_action, str):
        recommended_action = str(recommended_action)

    consequence = "" if risk_level == "green" else clean_consequence(parsed.get("consequence"))

    raw_claims = parsed.get("claims", [])
    sanitized_claims = []
    if isinstance(raw_claims, list):
        for c in raw_claims:
            if isinstance(c, dict) and "claim" in c:
                src_ids = c.get("supporting_source_ids", [])
                if isinstance(src_ids, str):
                    src_ids = [src_ids]
                elif not isinstance(src_ids, list):
                    src_ids = []
                sanitized_claims.append({
                    "claim": str(c["claim"]),
                    "supporting_source_ids": [str(s) for s in src_ids if s],
                })

    return {
        "plain_explanation": str(plain_explanation),
        "risk_level": risk_level,
        "legal_assessment": str(legal_assessment),
        "recommended_action": recommended_action.strip(),
        "consequence": consequence,
        "claims": sanitized_claims,
        "llm_confidence": llm_confidence,
    }


def _parse_final_answer(text: str) -> dict:
    if not text or not text.strip():
        return _sanitize_model_payload({}, "")

    raw = text.strip()

    # 1. Direct JSON parse
    try:
        return _sanitize_model_payload(json.loads(raw), raw)
    except json.JSONDecodeError:
        pass

    # 2. Markdown fence stripping
    cleaned = raw
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return _sanitize_model_payload(json.loads(cleaned), raw)
    except json.JSONDecodeError:
        pass

    # 3. Regex extraction of outermost JSON object
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return _sanitize_model_payload(json.loads(match.group(0)), raw)
        except json.JSONDecodeError:
            pass

    # 4. Fallback: Wrap raw text into safe structure
    return _sanitize_model_payload(
        {
            "plain_explanation": raw,
            "risk_level": "amber",
            "legal_assessment": "Unstructured model response; routed for human review.",
            "claims": [],
            "llm_confidence": 0.2,
        },
        raw,
    )


def _finalize(parsed: dict, context: dict, clause_id: str = None, clause_title: str = None) -> dict:
    sanitized = _sanitize_model_payload(parsed)
    try:
        model_output = ModelClauseOutput(**sanitized)
    except ValidationError:
        model_output = ModelClauseOutput(
            plain_explanation=sanitized.get("plain_explanation", "Analysis unavailable."),
            risk_level="amber",
            legal_assessment="Model output failed schema validation; routed for verification.",
            claims=[],
            llm_confidence=0.1,
        )

    retrieved_sources = context.get("retrieved_sources", [])
    retrieved_source_ids = {s["id"] for s in retrieved_sources if s.get("id")}

    claims = [c.model_dump() for c in model_output.claims]

    citation_valid = validate_citations(claims, retrieved_source_ids)

    # A green-risk clause with no claims at all is the "plain
    # explanation available, no legal question raised" case (Issue 4) --
    # e.g. "salary is Rs 50,000/month". There is nothing to ground
    # because no legal claim was made, so running the grounding
    # verifier and scoring it as "unsupported" would be wrong: it would
    # push a perfectly fine, complete answer into insufficient_grounding
    # and the human review queue for no reason. Treat it as its own
    # explicit case instead of forcing it through the same scoring as a
    # clause that tried to find grounding and failed.
    # ...except for clause types that routinely carry one-sided or unlawful
    # terms (eviction, lock-in/notice, penalties, non-competes -- see
    # risk_prone in rag/clause_taxonomy.py). Seen live: a small local model
    # labelled "landlord may repossess without any court proceedings" green
    # with no search at all, and this shortcut auto-approved it. For those
    # types "no legal claim" means the legal check was skipped, not that
    # none was needed.
    clause_type_info = context.get("clause_type_info") or {}
    skipped_risky_check = (
        not claims and model_output.risk_level == "green" and bool(clause_type_info.get("risk_prone"))
    )
    no_legal_claim_needed = not claims and model_output.risk_level == "green" and not skipped_risky_check

    if no_legal_claim_needed:
        grounding_score, grounding_status = 1.0, "not_applicable"
    else:
        verdicts = verify_grounding(claims, retrieved_sources)
        grounding_score, grounding_status = grounding_score_and_status(verdicts)

    retrieval_score = best_retrieval_score(retrieved_sources) if not no_legal_claim_needed else 1.0
    consistency_score = _consistency_score(model_output, claims)

    confidence = calculate_confidence(
        ConfidenceInputs(
            retrieval_score=retrieval_score,
            grounding_score=grounding_score,
            citation_valid=citation_valid,
            consistency_score=consistency_score,
            llm_confidence=model_output.llm_confidence,
        )
    )

    status = determine_status(confidence, citation_valid, grounding_score)
    review_flags = compute_review_flags(
        claims,
        retrieved_sources,
        clause_text=context.get("clause_text", ""),
        known_states=context.get("known_states"),
        legal_assessment=model_output.legal_assessment,
    )
    if skipped_risky_check:
        review_flags.append("skipped_legal_check")
    verification_status = (
        "pending"
        if should_send_for_verification(
            {"status": status, "risk_level": model_output.risk_level, "review_flags": review_flags}
        )
        else "auto_approved"
    )

    decision = clause_decision({
        "risk_level": model_output.risk_level, "status": status, "citation_valid": citation_valid,
        "review_flags": review_flags, "verification_status": verification_status,
    })

    result = ClauseAnalysisResult(
        clause_id=clause_id,
        clause_title=clause_title,
        plain_explanation=model_output.plain_explanation,
        risk_level=model_output.risk_level,
        legal_assessment=model_output.legal_assessment,
        recommended_action=model_output.recommended_action or default_recommended_action(model_output.risk_level, status),
        consequence=model_output.consequence,
        clause_type=(
            {
                "clause_type": clause_type_info.get("clause_type"),
                "label": clause_type_info.get("label"),
                "confidence": clause_type_info.get("confidence", 0.0),
            }
            if clause_type_info
            else None
        ),
        claims=model_output.claims,
        retrieved_source_ids=sorted(retrieved_source_ids),
        cited_sources=_cited_sources(claims, retrieved_sources),
        retrieval_score=retrieval_score,
        grounding_score=grounding_score,
        citation_valid=citation_valid,
        consistency_score=consistency_score,
        llm_confidence=model_output.llm_confidence,
        confidence=confidence,
        grounding_status=grounding_status,
        status=status,
        review_flags=review_flags,
        verification_status=verification_status,
        decision=decision,
    )

    return result.model_dump()


DEFAULT_ACTIONS = {
    "green": "Standard clause -- no action usually needed. Make sure the details (names, amounts, dates) are correct.",
    "amber": "Read this clause carefully and ask the other party to clarify or soften it before signing if it doesn't suit you.",
    "red": "Don't sign this clause as written. Ask for it to be changed or removed, and get advice from a lawyer if they refuse.",
}


def default_recommended_action(risk_level: str, status: str) -> str:
    """
    Fallback when the model didn't give a recommended_action. Deliberately
    generic -- it only restates what the risk tier already implies, so it
    can't introduce a new legal claim.
    """
    action = DEFAULT_ACTIONS.get(risk_level, DEFAULT_ACTIONS["amber"])
    if status != "grounded":
        action += " (This analysis is pending human review.)"
    return action


def _cited_sources(claims: list[dict], retrieved_sources: list[dict]) -> list[dict]:
    by_id = {s["id"]: s for s in retrieved_sources if s.get("id")}
    cited = []
    for sid in dict.fromkeys(sid for c in claims for sid in c.get("supporting_source_ids", [])):
        source = by_id.get(sid)
        if source:
            cited.append({
                "id": sid,
                "law": source.get("law"),
                "section": source.get("section"),
                "title": source.get("title"),
                "jurisdiction": source.get("jurisdiction"),
                "official_source": source.get("official_source") or None,
                "text": source.get("text"),
            })
    return cited


def _consistency_score(model_output: ModelClauseOutput, claims: list[dict]) -> float:
    """
    Cheap internal-consistency check (the "Output Consistency" factor,
    10% weight). A non-green risk level asserted with zero supporting
    claims is internally inconsistent -- the model is claiming a real
    legal problem exists without backing it with anything checkable.
    This is intentionally simple; a more thorough version could check
    e.g. whether legal_assessment and plain_explanation agree in tone,
    or whether risk_level matches the severity language used.
    """
    if model_output.risk_level != "green" and not claims:
        return 0.3

    if claims and all(not c.get("supporting_source_ids") for c in claims):
        return 0.5

    return 1.0


if __name__ == "__main__":
    sample_clause = (
        "The Employee agrees that for a period of 12 months "
        "following termination of employment, they shall not, "
        "directly or indirectly, engage in any business that "
        "competes with the Company within India."
    )

    result = run_agent(sample_clause, clause_id="4", clause_title="NON-COMPETE")
    print(json.dumps(result, indent=2))
