"""Streamlit UI for the estimator service.

Tab 1 — single stateless estimation (existing behaviour).
Tab 2 — conversational multi-turn session with sliding-window history.
"""

from __future__ import annotations

import os

import httpx
import streamlit as st
from dotenv import load_dotenv

from app.schemas.estimation import DetailLevel, OutputFormat, ProjectType

load_dotenv()

API_BASE_URL = os.getenv("ESTIMATOR_API_BASE_URL", "http://localhost:8000")
ESTIMATE_ENDPOINT = f"{API_BASE_URL.rstrip('/')}/api/v1/estimate"
SESSIONS_ENDPOINT = f"{API_BASE_URL.rstrip('/')}/api/v1/sessions"

st.set_page_config(page_title="Software Estimator", page_icon="📊", layout="wide")
st.title("Software Estimator")

with st.sidebar:
    st.header("Service")
    st.code(API_BASE_URL, language="text")
    primary = os.getenv("PRIMARY_MODEL", "gpt-4o-mini")
    fallback = os.getenv("FALLBACK_MODEL", "claude-haiku-4-5-20251001")
    st.markdown(f"**Primary model:** `{primary}`")
    st.markdown(f"**Fallback model:** `{fallback}`")
    st.markdown(f"**Cache TTL:** `{os.getenv('CACHE_TTL', '86400')}s`")

tab1, tab2 = st.tabs(["📋 Single estimation", "💬 Conversational session"])


# ── TAB 1: single stateless estimation ───────────────────────────────────────
with tab1:
    st.caption("One-shot estimation. Each request is independent — no history is kept.")

    with st.form("estimation_form", clear_on_submit=False):
        description = st.text_area(
            "Project description",
            height=200,
            placeholder="Describe the project: goals, key features, constraints…",
            help="Between 20 and 2000 characters.",
        )
        project_type = st.selectbox(
            "Project type",
            options=[t.value for t in ProjectType],
            index=1,
        )
        detail_level = st.radio(
            "Detail level",
            options=[d.value for d in DetailLevel],
            index=1,
            horizontal=True,
        )
        output_format = st.selectbox(
            "Output format",
            options=[f.value for f in OutputFormat],
            index=0,
        )
        uploaded_file = st.file_uploader(
            "Attach a document to add more context (optional)",
            type=["pdf", "docx"],
            help="PDF or Word document with additional project context.",
        )
        submitted = st.form_submit_button("Generate estimation", type="primary")

    if submitted:
        if len(description.strip()) < 20:
            st.error("The description must be at least 20 characters long.")
        else:
            payload = {
                "description": description.strip(),
                "project_type": project_type,
                "detail_level": detail_level,
                "output_format": output_format,
            }
            with st.spinner("Calling the estimator service…"):
                try:
                    response = httpx.post(
                        ESTIMATE_ENDPOINT,
                        json=payload,
                        timeout=httpx.Timeout(120.0, connect=10.0),
                    )
                    response.raise_for_status()
                    body = response.json()
                except httpx.HTTPStatusError as exc:
                    st.error(f"Service returned {exc.response.status_code}: {exc.response.text}")
                except httpx.HTTPError as exc:
                    st.error(f"Could not reach the estimator at `{ESTIMATE_ENDPOINT}`: {exc}")
                else:
                    st.markdown(f"**Prompt version:** `{body.get('prompt_version', '?')}`")
                    st.markdown(body.get("text", ""))


# ── TAB 2: conversational multi-turn session ──────────────────────────────────
with tab2:
    st.caption(
        "Multi-turn session: refine scope across several exchanges. "
        "The service keeps a sliding-window history and a project_metadata block."
    )

    # ── Streamlit session state init ─────────────────────────────────────────
    if "conv_session_id" not in st.session_state:
        st.session_state.conv_session_id = None
    if "conv_turns" not in st.session_state:
        st.session_state.conv_turns = []  # list[{description, result, turn}]

    # ── Session header ────────────────────────────────────────────────────────
    col_id, col_btn = st.columns([4, 1])
    with col_id:
        if st.session_state.conv_session_id:
            st.info(f"**Active session:** `{st.session_state.conv_session_id}`  ·  turns: {len(st.session_state.conv_turns)}")
        else:
            st.warning("No active session. Click **New session** to start.")
    with col_btn:
        if st.button("New session", type="primary", use_container_width=True):
            try:
                resp = httpx.post(SESSIONS_ENDPOINT, timeout=10.0)
                resp.raise_for_status()
                st.session_state.conv_session_id = resp.json()["session_id"]
                st.session_state.conv_turns = []
                st.rerun()
            except httpx.HTTPError as exc:
                st.error(f"Could not create session: {exc}")

    # ── Past turns ────────────────────────────────────────────────────────────
    for entry in st.session_state.conv_turns:
        with st.chat_message("user"):
            st.markdown(entry["description"])
        with st.chat_message("assistant"):
            r = entry["result"]
            st.markdown(
                f"**Turn {entry['turn']} · Confidence: {r['confidence_pct']}% · "
                f"{r['total_cost_eur']:,} EUR · {r['total_duration_weeks']} weeks**"
            )
            st.markdown(r["summary"])
            if r.get("phases"):
                st.table(
                    [
                        {
                            "Phase": p["name"],
                            "Weeks": p["duration_weeks"],
                            "Cost (EUR)": f"{p['cost_eur']:,}",
                            "Summary": p["summary"],
                        }
                        for p in r["phases"]
                    ]
                )

    # ── Session state inspector ───────────────────────────────────────────────
    if st.session_state.conv_session_id and st.session_state.conv_turns:
        with st.expander("🔍 Session state (history + project_metadata)", expanded=False):
            try:
                resp = httpx.get(
                    f"{SESSIONS_ENDPOINT}/{st.session_state.conv_session_id}",
                    timeout=5.0,
                )
                resp.raise_for_status()
                state = resp.json()
                col_meta, col_hist = st.columns(2)
                with col_meta:
                    st.markdown("**project_metadata** *(memory — persists across turns)*")
                    st.json(state["project_metadata"])
                with col_hist:
                    st.markdown(f"**history** *(sliding window — {state['turn_count']} turn/s, {len(state['history'])} messages)*")
                    for msg in state["history"]:
                        role_icon = "🧑" if msg["role"] == "user" else "🤖"
                        st.markdown(f"{role_icon} **{msg['role']}:** {msg['content'][:200]}{'…' if len(msg['content']) > 200 else ''}")
            except httpx.HTTPError:
                st.warning("Could not fetch session state.")

    # ── New-turn form ─────────────────────────────────────────────────────────
    if st.session_state.conv_session_id:
        st.divider()
        with st.form("turn_form", clear_on_submit=True):
            turn_description = st.text_area(
                "Describe or refine the project",
                height=180,
                placeholder=(
                    "Give enough detail so the model can estimate with confidence.\n\n"
                    "Example first turn:\n"
                    "  'B2B SaaS platform for construction companies. Features: project dashboard, "
                    "document management (PDF upload/versioning), role-based access (admin, PM, subcontractor), "
                    "Stripe billing, email notifications. Stack: React frontend, FastAPI backend, PostgreSQL. "
                    "Team: 2 senior devs + 1 designer. Target: MVP in 3 months.'\n\n"
                    "Example refinement turn:\n"
                    "  'Add a mobile app (iOS + Android, React Native) with offline mode and push notifications "
                    "for task updates. The desktop scope stays the same.'"
                ),
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                turn_project_type = st.selectbox(
                    "Project type", options=[t.value for t in ProjectType], index=1
                )
            with c2:
                turn_detail = st.selectbox(
                    "Detail level", options=[d.value for d in DetailLevel], index=1
                )
            with c3:
                turn_format = st.selectbox(
                    "Output format", options=[f.value for f in OutputFormat], index=0
                )
            turn_attachment = st.file_uploader(
                "Attach a document (optional)",
                type=["pdf", "docx"],
                help="Text is extracted locally and appended to the description.",
            )
            turn_submitted = st.form_submit_button("Send", type="primary")

        if turn_submitted:
            if len(turn_description.strip()) < 20:
                st.error("The description must be at least 20 characters long.")
            else:
                with st.spinner("Estimating…"):
                    try:
                        form_data = {
                            "description": turn_description.strip(),
                            "project_type": turn_project_type,
                            "detail_level": turn_detail,
                            "output_format": turn_format,
                        }
                        files = []
                        if turn_attachment is not None:
                            files = [("attachments", (turn_attachment.name, turn_attachment.read(), turn_attachment.type))]

                        resp = httpx.post(
                            f"{SESSIONS_ENDPOINT}/{st.session_state.conv_session_id}/estimate",
                            data=form_data,
                            files=files if files else None,
                            timeout=httpx.Timeout(120.0, connect=10.0),
                        )
                        resp.raise_for_status()
                        body = resp.json()
                        st.session_state.conv_turns.append(
                            {
                                "description": turn_description.strip(),
                                "result": body["result"],
                                "turn": body["turn"],
                                "attachment": turn_attachment.name if turn_attachment else None,
                            }
                        )
                        st.rerun()
                    except httpx.HTTPStatusError as exc:
                        detail = exc.response.json().get("detail", exc.response.text)
                        if isinstance(detail, dict):
                            st.error(
                                f"**{detail.get('reason', 'Error')}:** {detail.get('message', '')}"
                            )
                        else:
                            st.error(
                                f"Service returned {exc.response.status_code}: {detail}"
                            )
                    except httpx.HTTPError as exc:
                        st.error(f"Could not reach the estimator: {exc}")
