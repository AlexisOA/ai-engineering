"""Synthetic multi-turn conversations used to stress the CAG.

Each scenario is one conversation about the same project, written to force
a specific failure mode:

- ``growing``       — requirements keep piling on; nothing contradicts, so
                       this isolates the pure cost-growth and context-size
                       curves from any drift-inducing rewrite.
- ``pivot``          — the stack changes mid-conversation (turn 5); tests
                       whether ``mentioned_technologies`` replaces or
                       accumulates, and whether the old stack lingers.
- ``contradiction``  — the budget is stated twice with different values
                       (turns 3 and 8); tests which value the summarizer and
                       the metadata extractor keep.

``TURNS_PER_SCENARIO`` is deliberately smaller than the exercise's own
illustrative 20-turn / 3-repeat run. The exercise's own "done" criteria
say the ≥50-row floor is met by "3 scenarios x 5 sizes x ≥3 repeats x N
turns, adjusting the floors to reach the minimum" — N is the dial meant to
be turned down, not the 3 scenarios x 5 sizes x 3 repeats structure. 9
turns still clears every fact-introducing event in every scenario (pivot
at turn 5, the contradiction's correction at turn 8) with one turn of
room to check whether it survives right after, at a fraction of the
real-LLM wall-clock and OpenAI-rate-limit exposure a 20-turn run costs.
The attachment-size axis (Bloque 3) doesn't need this depth at all — the
exercise's own wording for it is "run the same initial estimation" per
size, i.e. one turn — so the size sweep and the multi-turn scenario sweep
run as two separate, decoupled passes (see ``run.py --max-turns``).

Each turn declares the fact the runner should still be able to find in a
later ``GET /sessions/{id}`` snapshot via ``MemoryDriftMetric``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FactField = Literal["project_name", "technologies", "scope", "summary", "any"]

TURNS_PER_SCENARIO = 9
CHECKPOINT_TURNS = (1, 3, 6, 8, 9)


@dataclass(frozen=True)
class ScenarioTurn:
    """One turn of a synthetic conversation.

    ``fact`` / ``fact_field`` describe what a later turn's snapshot must
    still contain for this turn's contribution to count as "remembered" —
    they feed straight into ``MemoryDriftMetric(fact, fact_field)``. A turn
    that does not introduce a new fact worth tracking (most of them, in a
    20-turn run) leaves both as ``None``.
    """

    transcript: str
    fact: str | None = None
    fact_field: FactField | None = None


@dataclass(frozen=True)
class Scenario:
    name: str
    turns: list[ScenarioTurn] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.turns)


_PROJECT_NAME = "Project Nimbus"
_INITIAL_STACK = ["React", "Node.js", "PostgreSQL"]
_NEW_STACK = "Flutter"

_GROWING_REQUIREMENTS = [
    "user authentication with email + OAuth",
    "multi-tenant workspaces so each customer's data stays isolated",
    "an audit log recording every write to project records",
    "CSV export for the estimation history",
    "role-based permissions (admin / editor / viewer)",
    "email notifications when an estimation is approved",
    "a public read-only sharing link per estimation",
    "rate limiting on the public API",
    "SSO via SAML for enterprise customers",
    "a webhook that fires when an estimation's status changes",
    "soft-delete with a 30-day recovery window",
    "a REST API versioned independently from the web UI",
    "usage analytics dashboard for admins",
    "bulk import of historical estimations from a spreadsheet",
    "two-factor authentication for admin accounts",
    "a mobile-friendly responsive layout",
    "localisation for Spanish and Portuguese",
    "an internal changelog visible to all users",
    "scheduled nightly backups with restore testing",
]


def growing_scenario() -> Scenario:
    """Requirements accumulate turn by turn; nothing is ever retracted.

    Turn 1 fixes ``project_name`` — the fact tracked across the whole run is
    simply "does the name introduced on turn 1 survive to turn 20?".
    """
    turns = [
        ScenarioTurn(
            transcript=(
                f"We're building {_PROJECT_NAME}, a web SaaS platform for "
                f"small agencies to manage client project estimations. Initial "
                f"stack: {', '.join(_INITIAL_STACK)}. Start with the core "
                f"estimation CRUD and a simple dashboard."
            ),
            fact=_PROJECT_NAME,
            fact_field="project_name",
        )
    ]
    for requirement in _GROWING_REQUIREMENTS:
        turns.append(
            ScenarioTurn(
                transcript=(
                    f"Following up on {_PROJECT_NAME}: we also need {requirement}. "
                    f"Please fold this into the existing estimation, keeping the "
                    f"stack unchanged."
                )
            )
        )
    return Scenario(name="growing", turns=turns[:TURNS_PER_SCENARIO])


def pivot_scenario() -> Scenario:
    """Same premise as ``growing``, but turn 5 replaces the stack outright."""
    turns = growing_scenario().turns[:4]
    turns.append(
        ScenarioTurn(
            transcript=(
                f"Change of plan for {_PROJECT_NAME}: we're dropping "
                f"{_INITIAL_STACK[0]} entirely and rebuilding the client on "
                f"{_NEW_STACK} instead, since we need native mobile from day "
                f"one. The backend stack stays the same. Re-estimate assuming "
                f"{_NEW_STACK} for the client."
            ),
            fact=_NEW_STACK,
            fact_field="technologies",
        )
    )
    remaining = _GROWING_REQUIREMENTS[4:]
    for requirement in remaining:
        turns.append(
            ScenarioTurn(
                transcript=(
                    f"Following up on {_PROJECT_NAME} (now on {_NEW_STACK} for "
                    f"the client): we also need {requirement}."
                )
            )
        )
    return Scenario(name="pivot", turns=turns[:TURNS_PER_SCENARIO])


def contradiction_scenario() -> Scenario:
    """Turn 3 sets a 30k EUR budget; turn 8 restates it as 80k EUR.

    Tracks which figure ``agreed_scope`` / the summary end up carrying by
    the end of the run — the interesting failure is *silently* keeping the
    stale figure rather than raising anything.
    """
    turns = growing_scenario().turns[:2]  # turn 1 (project intro) + turn 2 (req 0)
    turns.append(
        ScenarioTurn(
            transcript=(
                f"For {_PROJECT_NAME}, the client confirmed a budget cap of "
                f"30000 EUR for this phase. Please keep every future estimate "
                f"within that cap."
            ),
            fact="30000 EUR",
            fact_field="scope",
        )
    )  # turn 3
    for requirement in _GROWING_REQUIREMENTS[1:5]:  # turns 4-7
        turns.append(
            ScenarioTurn(
                transcript=(
                    f"We also need {requirement} for {_PROJECT_NAME}. Keep it "
                    f"within the agreed budget."
                )
            )
        )
    turns.append(
        ScenarioTurn(
            transcript=(
                f"Correction on {_PROJECT_NAME}'s budget: finance actually "
                f"approved 80000 EUR for this phase, not the earlier figure. "
                f"Use 80000 EUR going forward."
            ),
            fact="80000 EUR",
            fact_field="scope",
        )
    )  # turn 8
    for requirement in _GROWING_REQUIREMENTS[5:]:  # turns 9-20
        turns.append(ScenarioTurn(transcript=f"Also add {requirement} to {_PROJECT_NAME}."))
    return Scenario(name="contradiction", turns=turns[:TURNS_PER_SCENARIO])


ALL_SCENARIOS: dict[str, Scenario] = {
    scenario.name: scenario
    for scenario in (growing_scenario(), pivot_scenario(), contradiction_scenario())
}


def get_scenario(name: str) -> Scenario:
    try:
        return ALL_SCENARIOS[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown scenario {name!r}; available: {sorted(ALL_SCENARIOS)}"
        ) from exc
