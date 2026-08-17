#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "openai>=1.40"]
# ///
"""Session 9 pre-work: manual trace of a raw transcript through the current system.

Client script only. Two calls, exactly what the exercise asks for:

  1. Embed the transcript directly with OpenAI (the service has no endpoint that
     returns a raw vector -- embedding only happens inside POST /search).
  2. POST the transcript to /search (k=5) and print the raw JSON response.

Usage::

    export OPENAI_API_KEY=sk-...
    uv run examples/trace_s09.py examples/transcripts/02_ambiguous.txt

ESTIMATOR_BASE_URL overrides the default http://localhost:8000.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import httpx
from openai import OpenAI

MODEL = "text-embedding-3-small"


def main() -> int:
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    base_url = os.environ.get("ESTIMATOR_BASE_URL", "http://localhost:8000")

    print(f"--- step 1: embed {path.name} directly (OpenAI, model={MODEL}) ---")
    vector = OpenAI().embeddings.create(model=MODEL, input=text).data[0].embedding
    norm = math.sqrt(sum(v * v for v in vector))
    print(f"dimensions: {len(vector)}")
    print(f"l2_norm: {norm:.6f}")
    print(f"first_component: {vector[0]:.6f}")
    print(f"last_component: {vector[-1]:.6f}")

    print(f"\n--- step 2: POST {base_url}/search  (k=5) ---")
    response = httpx.post(f"{base_url}/search", json={"query": text, "k": 5}, timeout=60.0)
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
