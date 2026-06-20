from pydantic import BaseModel, Field

from app.schemas.estimation import EstimationResult


class ExtractedProjectFacts(BaseModel):
    """Facts extracted from a turn description by the LLM. All fields are optional:
    None means the fact was not mentioned in the text."""

    project_name: str | None = Field(
        default=None,
        description="Project name if explicitly mentioned (e.g. 'called X', 'named X'). Null otherwise.",
    )
    assumed_team_size: int | None = Field(
        default=None,
        ge=1,
        le=200,
        description="Total headcount if a specific number is stated. Null otherwise.",
    )
    mentioned_technologies: list[str] = Field(
        default_factory=list,
        description="Technologies, frameworks, libraries or cloud services explicitly named. Empty list if none.",
    )


class SessionResponse(BaseModel):
    session_id: str


class TurnResponse(BaseModel):
    session_id: str
    turn: int
    result: EstimationResult
    prompt_version: str


class SessionStateResponse(BaseModel):
    session_id: str
    turn_count: int
    history: list[dict]
    project_metadata: dict
