from app.schemas.estimation import EstimationRequest
from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import DetailLevel, OutputFormat, ProjectType


def test_estimation_prompt_includes_description_in_user_block():
    request = EstimationRequest(
        description="Mobile app with login, chat and push notifications.",
        project_type=ProjectType.MOBILE_APP,
        detail_level=DetailLevel.DETAILED,
        output_format=OutputFormat.PHASES_TABLE,
    )

    system, user = render_estimation_prompt(request)

    assert "<project_description>" in user
    assert "Mobile app with login" in user
    assert "phases_table" in system
    assert "confidence_pct" in system