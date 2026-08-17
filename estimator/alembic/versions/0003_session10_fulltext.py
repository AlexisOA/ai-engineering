"""Session 10 — full-text search column on chunks.

Adds a generated ``tsvector`` column over ``content`` plus a GIN index, so the
lexical branch of hybrid search can run as a plain Postgres query alongside
the existing pgvector similarity search. The exercise brief assumes a Spanish
corpus, but ``data/budgets_sample.json`` (chunk ``content``, project
summaries, everything) is written in English — checked directly against the
seeded rows before picking a config. The ``english`` text search
configuration is the one that actually stems and matches this data; ``spanish``
would silently return zero hits on every real chunk. Client transcripts are
Spanish, so a future corpus in Spanish would need this flipped back (or a
per-row config, keyed off language).

STORED generated column: Postgres recomputes it on every INSERT/UPDATE of
``content``, so it never drifts out of sync and needs no application code to
maintain.

Revision ID: 0003_session10_fulltext
Revises: 0002_session8_pgvector
Create Date: 2026-08-10 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003_session10_fulltext"
down_revision: Union[str, None] = "0002_session8_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chunks
        ADD COLUMN content_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
        """
    )
    op.create_index(
        "ix_chunks_content_tsv", "chunks", ["content_tsv"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_content_tsv", table_name="chunks")
    op.drop_column("chunks", "content_tsv")
