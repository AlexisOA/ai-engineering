"""Unit tests for ConversationHistory, ProjectMetadata and SessionStore."""

from __future__ import annotations

import pytest

from app.sessions.models import ConversationHistory, ProjectMetadata, Session
from app.sessions.store import SessionNotFoundError, SessionStore


def test_history_sliding_window_drops_oldest_pairs() -> None:
    history = ConversationHistory(max_turns=2)
    history.append(user="t1u", assistant="t1a")
    history.append(user="t2u", assistant="t2a")
    history.append(user="t3u", assistant="t3a")

    messages = history.to_messages()
    assert len(messages) == 4  # 2 turns * 2 messages
    assert messages[0] == {"role": "user", "content": "t2u"}
    assert messages[-1] == {"role": "assistant", "content": "t3a"}


def test_history_to_messages_excludes_system_prompt() -> None:
    history = ConversationHistory(max_turns=3)
    history.append(user="hi", assistant="hello")
    messages = history.to_messages()
    assert all(m["role"] in {"user", "assistant"} for m in messages)


def test_project_metadata_is_empty_by_default() -> None:
    metadata = ProjectMetadata()
    assert metadata.is_empty()
    assert metadata.mentioned_technologies == []


def test_project_metadata_merge_overwrites_scalars_and_unions_techs() -> None:
    base = ProjectMetadata(
        project_name="Nimbus CRM",
        assumed_team_size=3,
        mentioned_technologies=["React", "Postgres"],
        agreed_scope="Phase 1 only",
    )
    update = ProjectMetadata(
        project_name="Nimbus CRM v2",
        assumed_team_size=None,
        mentioned_technologies=["postgres", "Redis"],
        agreed_scope=None,
    )
    merged = base.merge_with(update)

    assert merged.project_name == "Nimbus CRM v2"  # overwritten
    assert merged.assumed_team_size == 3  # preserved (update was None)
    assert merged.agreed_scope == "Phase 1 only"  # preserved
    # Case-insensitive union, original order preserved
    assert merged.mentioned_technologies == ["React", "Postgres", "Redis"]


def test_session_store_create_returns_unique_ids() -> None:
    store = SessionStore()
    s1 = store.create()
    s2 = store.create()
    assert s1.session_id != s2.session_id
    assert len(store) == 2


def test_session_store_get_or_404_raises_for_unknown() -> None:
    store = SessionStore()
    with pytest.raises(SessionNotFoundError):
        store.get_or_404("nope")


def test_session_store_respects_configured_max_turns() -> None:
    store = SessionStore(max_turns=4)
    session = store.create()
    assert session.history.max_turns == 4


def test_session_round_trip_through_json() -> None:
    """Pydantic serialisation works — useful for the GET /sessions/{id} debug endpoint."""
    session = Session()
    session.history.append(user="hi", assistant="hello")
    session.metadata = ProjectMetadata(project_name="Foo")
    raw = session.model_dump(mode="json")
    restored = Session.model_validate(raw)
    assert restored.metadata.project_name == "Foo"
    assert len(restored.history.messages) == 2
