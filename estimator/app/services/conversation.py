"""Multi-turn estimation service.

Wraps the stateless LLM wrapper with a session layer:
- Sliding-window history (last N turns injected as messages).
- project_metadata block injected into the v2 system prompt.
- Metadata updated after each turn with facts extracted via a structured LLM call.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.guardrails.input import check_input
from app.guardrails.output import enforce_scope_response
from app.prompts.loader import render_conversation_prompt
from app.schemas.estimation import EstimationRequest, EstimationResult
from app.schemas.session import ExtractedProjectFacts, TurnResponse
from app.services.llm_wrapper import LLMWrapper
from app.services.session import SessionState, session_store

log = structlog.get_logger()

PROMPT_VERSION = "v2"

_EXTRACTION_SYSTEM = (
    "You are a fact extractor. Read the project description and extract only facts "
    "that are explicitly stated — do not infer, assume or guess.\n"
    "- project_name: the project name if the text says 'called X', 'named X', 'project X', etc.\n"
    "- assumed_team_size: total team headcount only if a specific number is stated.\n"
    "- mentioned_technologies: every technology, framework, library, database or cloud service "
    "explicitly named (e.g. React, PostgreSQL, AWS, Stripe).\n"
    "Return null for project_name and assumed_team_size if not explicitly present. "
    "Return an empty list for mentioned_technologies if none are named."
)


def _update_metadata(
    metadata: dict,
    request: EstimationRequest,
    result: EstimationResult,
    facts: ExtractedProjectFacts,
) -> dict:
    """Merge typed fields, estimation result, and extracted facts into project_metadata."""
    updated = dict(metadata)

    # From the typed request fields.
    updated["project_type"] = request.project_type.value
    updated["detail_level"] = request.detail_level.value

    # From the structured estimation result.
    if result.confidence_pct >= 30:
        updated["agreed_scope"] = result.summary[:300]

    # From the LLM-extracted facts — only overwrite when explicitly found.
    if facts.project_name is not None:
        updated["project_name"] = facts.project_name
    if facts.assumed_team_size is not None:
        updated["assumed_team_size"] = facts.assumed_team_size

    # Merge technologies: accumulate across turns without duplicates.
    existing = set(updated.get("mentioned_technologies") or [])
    updated["mentioned_technologies"] = sorted(existing | set(facts.mentioned_technologies))

    return updated


class ConversationService:
    """Stateful estimation pipeline that maintains per-session history and metadata."""

    def __init__(
        self,
        *,
        llm_wrapper: LLMWrapper,
        openai_client: Any | None = None,
    ) -> None:
        self.llm_wrapper = llm_wrapper
        self.openai_client = openai_client

    def _extract_project_facts(self, description: str) -> ExtractedProjectFacts:
        """Run a lightweight structured LLM call to extract facts from the description."""
        facts, _ = self.llm_wrapper.complete_structured(
            system_prompt=_EXTRACTION_SYSTEM,
            user_message=description,
            response_model=ExtractedProjectFacts,
            max_retries=2,
        )
        log.info(
            "project_facts_extracted",
            project_name=facts.project_name,
            assumed_team_size=facts.assumed_team_size,
            technologies=facts.mentioned_technologies,
        )
        return facts

    def estimate(self, session_id: str, request: EstimationRequest) -> TurnResponse:
        state: SessionState | None = session_store.get(session_id)
        if state is None:
            raise KeyError(session_id)

        # 1. Input guardrails — same policy as the stateless pipeline.
        check_input(request.description, openai_client=self.openai_client)

        # 2. Extract structured facts from the description before rendering the prompt.
        facts = self._extract_project_facts(request.description)

        # 3. Render v2 prompt with current project_metadata.
        system_prompt, user_message = render_conversation_prompt(
            request, state.project_metadata, version=PROMPT_VERSION
        )

        # 4. LLM call with the sliding-window history.
        result, meta = self.llm_wrapper.complete_structured(
            system_prompt=system_prompt,
            user_message=user_message,
            history=state.get_history(),
            response_model=EstimationResult,
        )
        log.info(
            "conversation_turn_generated",
            session_id=session_id,
            prompt_version=PROMPT_VERSION,
            confidence_pct=result.confidence_pct,
            total_cost_eur=result.total_cost_eur,
            phases=len(result.phases),
            history_turns=len(state.history) // 2,
            **meta,
        )

        # 5. Output guardrail — same filter policy as the stateless pipeline.
        result = enforce_scope_response(result)

        # 6. Persist the turn in the sliding window.
        state.add_turn(user_message, result.summary)

        # 7. Update project_metadata merging typed fields, result and extracted facts.
        state.project_metadata = _update_metadata(
            state.project_metadata, request, result, facts
        )

        turn_number = len(state.history) // 2
        return TurnResponse(
            session_id=session_id,
            turn=turn_number,
            result=result,
            prompt_version=PROMPT_VERSION,
        )
