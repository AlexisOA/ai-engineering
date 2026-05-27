"""Session 7 — embedding pipeline.

Turns historical budget JSON into embedding vectors: a structural chunker
(one budget component = one chunk) plus an OpenAI embedder. Vectors are
produced in memory and returned over HTTP; persistence to a vector DB is
Session 8 territory.
"""
