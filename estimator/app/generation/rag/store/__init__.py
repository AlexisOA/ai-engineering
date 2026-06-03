"""Vector store — RESERVED FOR SESSION 8.

Persistence of embedded chunks in PostgreSQL + pgvector (HNSW index). Today
the embedding pipeline returns vectors over HTTP without persisting them; this
package is the home for pgvector persistence when Session 8 lands.
"""
