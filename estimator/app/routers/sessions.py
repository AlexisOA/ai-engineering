import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from app.dependencies import get_conversation_service
from app.guardrails.input import InputGuardrailViolation
from app.schemas.estimation import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.schemas.session import SessionResponse, SessionStateResponse, TurnResponse
from app.services.conversation import ConversationService
from app.services.document import extract_text
from app.services.session import session_store

log = structlog.get_logger()

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session() -> SessionResponse:
    state = session_store.create()
    log.info("session_created", session_id=state.session_id)
    return SessionResponse(session_id=state.session_id)


@router.get("/{session_id}", response_model=SessionStateResponse)
async def get_session(session_id: str) -> SessionStateResponse:
    state = session_store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return SessionStateResponse(
        session_id=state.session_id,
        turn_count=len(state.history) // 2,
        history=state.history,
        project_metadata=state.project_metadata,
    )


@router.post("/{session_id}/estimate", response_model=TurnResponse)
async def session_estimate(
    session_id: str,
    description: str = Form(...),
    project_type: ProjectType = Form(...),
    detail_level: DetailLevel = Form(...),
    output_format: OutputFormat = Form(...),
    attachments: list[UploadFile] = File(default=[]),
    service: ConversationService = Depends(get_conversation_service),
) -> TurnResponse:
    if session_store.get(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    # Extract text from each attachment and append to the description.
    combined = description
    for attachment in attachments:
        text = await extract_text(attachment)
        if text.strip():
            combined += f"\n\n---\nAttached document ({attachment.filename}):\n{text}"
            log.info(
                "attachment_appended",
                session_id=session_id,
                filename=attachment.filename,
                chars=len(text),
            )

    # Validate the combined description and typed fields via Pydantic.
    try:
        request = EstimationRequest(
            description=combined,
            project_type=project_type,
            detail_level=detail_level,
            output_format=output_format,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    try:
        return service.estimate(session_id, request)
    except InputGuardrailViolation as exc:
        raise HTTPException(
            status_code=400,
            detail={"reason": exc.reason, "message": str(exc)},
        )
    except Exception as exc:
        log.error(
            "session_estimate_error",
            session_id=session_id,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        raise HTTPException(status_code=502, detail="Upstream LLM call failed.")
