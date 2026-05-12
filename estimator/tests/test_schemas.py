"""Validation tests for the EstimationRequest contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
)


VALID_PAYLOAD = {
    "description": "A small B2B SaaS to manage employee equipment loans across teams.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}


def test_valid_request_constructs_with_typed_enums() -> None:
    request = EstimationRequest(**VALID_PAYLOAD)
    assert request.description == VALID_PAYLOAD["description"]
    assert request.project_type is ProjectType.WEB_SAAS
    assert request.detail_level is DetailLevel.MEDIUM
    assert request.output_format is OutputFormat.PHASES_TABLE


def test_description_below_minimum_length_fails() -> None:
    payload = {**VALID_PAYLOAD, "description": "too short"}
    with pytest.raises(ValidationError) as exc_info:
        EstimationRequest(**payload)
    assert any(err["loc"] == ("description",) for err in exc_info.value.errors())


def test_description_above_maximum_length_fails() -> None:
    payload = {**VALID_PAYLOAD, "description": "x" * 80001}
    with pytest.raises(ValidationError) as exc_info:
        EstimationRequest(**payload)
    assert any(err["loc"] == ("description",) for err in exc_info.value.errors())


@pytest.mark.parametrize(
    "field",
    ["project_type", "detail_level", "output_format"],
)
def test_each_enum_rejects_unknown_values(field: str) -> None:
    payload = {**VALID_PAYLOAD, field: "definitely_not_a_real_value"}
    with pytest.raises(ValidationError) as exc_info:
        EstimationRequest(**payload)
    assert any(err["loc"] == (field,) for err in exc_info.value.errors())


def test_missing_required_enum_fails() -> None:
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "project_type"}
    with pytest.raises(ValidationError) as exc_info:
        EstimationRequest(**payload)
    assert any(err["loc"] == ("project_type",) for err in exc_info.value.errors())
