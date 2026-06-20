"""Jinja2 loader for versioned prompt templates.

The on-disk layout is ``app/prompts/<use_case>/<version>/<role>.j2``. Versioning
is required from day one: switching prompts becomes a string change at the
call site (``version="v2"``), not a code refactor.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas.estimation import EstimationRequest

_BASE_DIR = Path(__file__).resolve().parent

_env = Environment(
    loader=FileSystemLoader(_BASE_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
    keep_trailing_newline=True,
)


def render_estimation_prompt(
    request: EstimationRequest,
    version: str = "v1",
) -> tuple[str, str]:
    """Render the system and user prompts for the estimation use case.

    Returns:
        A tuple ``(system_prompt, user_prompt)`` ready to be sent to the LLM
        as separate ``role: "system"`` and ``role: "user"`` messages.
    """
    context = {
        "description": request.description,
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
    }
    system = _env.get_template(f"estimation/{version}/system.j2").render(**context)
    user = _env.get_template(f"estimation/{version}/user.j2").render(**context)
    return system, user


def render_conversation_prompt(
    request: EstimationRequest,
    metadata: dict,
    version: str = "v2",
) -> tuple[str, str]:
    """Render system and user prompts for the conversational (multi-turn) use case.

    The v2 system template includes a <project_metadata> block populated from
    ``metadata``. The keys recognised by the template are: ``project_name``,
    ``assumed_team_size``, ``mentioned_technologies`` (list), ``agreed_scope``.

    Returns:
        A tuple ``(system_prompt, user_prompt)``.
    """
    _METADATA_KEYS = ("project_name", "assumed_team_size", "mentioned_technologies", "agreed_scope")
    normalised = {k: metadata.get(k) for k in _METADATA_KEYS}
    if "mentioned_technologies" not in metadata:
        normalised["mentioned_technologies"] = []

    metadata_is_empty = not any(
        bool(normalised[k]) for k in _METADATA_KEYS
    )

    context = {
        "description": request.description,
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
        "metadata": normalised,
        "metadata_is_empty": metadata_is_empty,
    }
    system = _env.get_template(f"estimation/{version}/system.j2").render(**context)
    user = _env.get_template(f"estimation/{version}/user.j2").render(**context)
    return system, user
