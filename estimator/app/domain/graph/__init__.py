"""Session 13 — the estimation flow re-expressed as an explicit LangGraph StateGraph.

Five sequential nodes (extract_requirements -> classify_components ->
search_budgets -> generate_estimate -> validate_and_consolidate) over a typed
state with an accumulator reducer, checkpointed on the project's Postgres and
traced through Logfire (one span per node). Parallel search, retries/fallback
nodes and human-in-the-loop are explicitly out of scope here (live-session work).
"""
