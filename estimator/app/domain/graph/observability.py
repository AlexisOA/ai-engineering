"""Logfire wiring for the estimation graph (Session 13) — one span per node.

Works with or without a Logfire account: without a token, spans stay local
(printed to the console, never sent anywhere) rather than being silently
dropped, so ``scripts/run_graph_s13.py --out`` still captures a full trace.
"""

from __future__ import annotations

import logfire
from fastapi import FastAPI

_configured = False


def configure_logfire(app: FastAPI | None = None) -> None:
    """Idempotent: safe to call once at import time and again from a script."""
    global _configured
    if _configured:
        return
    _configured = True

    logfire.configure(
        service_name="estimator",
        send_to_logfire="if-token-present",
        # verbose=True's detail panels draw box-drawing characters that crash on
        # a non-UTF-8 console codepage (e.g. Windows cp1252); one line per span
        # is all the trace needs anyway.
        console=logfire.ConsoleOptions(verbose=False, min_log_level="info"),
    )
    if app is not None:
        logfire.instrument_fastapi(app)
    # LLM calls go through LiteLLM (app/foundation/llm/wrapper.py), which itself
    # calls out over httpx — instrumenting httpx captures every node's LLM call
    # without an extra optional dependency (logfire.instrument_litellm() needs
    # openinference-instrumentation-litellm, not worth adding for this).
    logfire.instrument_httpx()
