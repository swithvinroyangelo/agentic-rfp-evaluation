"""Procurement evaluation dashboard."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st

from rfp_eval.dashboard import (
    SupplierFormRow,
    completion_message,
    default_database_path,
    duplicate_submission_message,
    evaluation_block_reason,
    explain_ranking,
    leaderboard_rows,
    partition_suppliers,
    resolve_api_key,
    scorecard_rows,
    submission_token,
    validate_supplier_rows,
)
from rfp_eval.db import (
    initialize_database,
    list_all_criteria,
    list_evaluation_runs,
    load_evaluation_run,
    update_criteria,
)
from rfp_eval.llm_client import DEFAULT_MODEL, OpenAIEvaluationClient, load_project_env, read_setting
from rfp_eval.orchestrator import SupplierSubmission, run_evaluation_batch

DB_PATH = default_database_path(ROOT)


def main() -> None:
    load_project_env(ROOT / ".env")
    st.set_page_config(page_title="RFP Evaluation", layout="wide")
    _style()
    initialize_database(DB_PATH)
    st.title("RFP evaluation")
    st.caption("Score supplier proposals against active criteria. Python calculates benchmarks, PPI, and rank.")
    api_key, model = _sidebar()
    page = st.radio(
        "Section",
        ["Criteria", "Evaluate", "Results"],
        horizontal=True,
        label_visibility="collapsed",
    )
    if page == "Criteria":
        render_criteria()
    elif page == "Evaluate":
        render_evaluate(api_key, model)
    else:
        render_results()


def render_criteria() -> None:
    criteria = list_all_criteria(DB_PATH)
    active_weight = sum(item.weight for item in criteria if item.is_active)
    reason = evaluation_block_reason(criteria)
    left, right = st.columns([3, 1])
    left.subheader("Evaluation criteria")
    right.metric("Active weight", f"{active_weight}%")
    if reason:
        st.warning(reason)
    else:
        st.success("Active weights total 100%. Evaluation can run.")

    with st.form("criteria_form"):
        edits = []
        for criterion in criteria:
            name_col, weight_col, max_col, active_col = st.columns([3.2, 1, 1, 1])
            name_col.markdown(f"**{criterion.name}**")
            name_col.caption(criterion.description)
            weight = weight_col.number_input(
                "Weight",
                min_value=1,
                max_value=100,
                value=int(criterion.weight),
                key=f"weight_{criterion.criterion_id}",
            )
            max_score = max_col.number_input(
                "Maximum score",
                min_value=1,
                max_value=100,
                value=int(criterion.max_score),
                key=f"max_{criterion.criterion_id}",
            )
            is_active = active_col.checkbox(
                "Active",
                value=bool(criterion.is_active),
                key=f"active_{criterion.criterion_id}",
            )
            edits.append(
                {
                    "criterion_id": criterion.criterion_id,
                    "weight": weight,
                    "max_score": max_score,
                    "is_active": is_active,
                }
            )
        if st.form_submit_button("Save criteria"):
            try:
                update_criteria(DB_PATH, edits)
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Criteria saved.")
                st.rerun()


def render_evaluate(api_key: str, model: str) -> None:
    st.subheader("Supplier proposals")
    criteria = list_all_criteria(DB_PATH)
    reason = evaluation_block_reason(criteria)
    if reason:
        st.error(f"Evaluation is blocked. {reason}")
    uploads = st.file_uploader(
        "Upload supplier PDFs",
        type=["pdf"],
        accept_multiple_files=True,
    )
    if not api_key:
        st.warning("Enter your OpenAI API key in the sidebar before you evaluate.")
    if not uploads:
        st.info("Upload one or more PDFs. Nothing is evaluated until you choose Evaluate suppliers.")
        return

    rows: list[SupplierFormRow] = []
    paths: dict[str, object] = {}
    for upload in uploads:
        st.markdown(f"**{upload.name}**")
        name_col, date_col, experience_col = st.columns([2, 1.2, 1])
        supplier_name = name_col.text_input("Supplier name", key=f"name_{upload.file_id}")
        submitted = date_col.date_input("Submission date", key=f"date_{upload.file_id}")
        experience = experience_col.number_input(
            "Experience rating",
            min_value=1,
            max_value=5,
            value=3,
            step=1,
            key=f"experience_{upload.file_id}",
        )
        rows.append(
            SupplierFormRow(
                supplier_name=supplier_name,
                submission_date=submitted.isoformat(),
                experience_rating=int(experience),
                filename=upload.name,
            )
        )
        paths[upload.file_id] = upload

    errors = validate_supplier_rows(rows)
    for error in errors:
        st.error(error)
    token = submission_token(rows)
    duplicate = duplicate_submission_message(
        token,
        st.session_state.get("last_submission_token"),
        st.session_state.get("last_run_id"),
    )
    if duplicate:
        st.warning(duplicate)

    blocked = bool(reason or errors or duplicate or not api_key)
    if st.button("Evaluate suppliers", type="primary", disabled=blocked):
        _run_batch(list(paths.values()), rows, token, api_key, model)


def render_results() -> None:
    st.subheader("Results")
    runs = list_evaluation_runs(DB_PATH)
    if not runs:
        st.info("No evaluations yet. Upload proposals and start a batch from Evaluate.")
        return
    labels = {f"{run['created_at']} · {run['status']} · {run['rfp_run_id']}": run["rfp_run_id"] for run in runs}
    preferred = st.session_state.get("selected_run_id", runs[0]["rfp_run_id"])
    default_label = next((label for label, run_id in labels.items() if run_id == preferred), next(iter(labels)))
    selected_label = st.selectbox("Saved run", list(labels), index=list(labels).index(default_label))
    _show_run(labels[selected_label])


def _run_batch(uploads, rows: list[SupplierFormRow], token: str, api_key: str, model: str) -> None:
    progress = st.progress(0, text="Preparing proposals")
    try:
        with tempfile.TemporaryDirectory() as folder:
            submissions = []
            for upload, row in zip(uploads, rows):
                path = Path(folder) / upload.name
                path.write_bytes(upload.getvalue())
                submissions.append(
                    SupplierSubmission(
                        supplier_name=row.supplier_name.strip(),
                        pdf_path=path,
                        submission_date=row.submission_date,
                        experience_rating=row.experience_rating,
                    )
                )
            client = OpenAIEvaluationClient(api_key=api_key, model=model)

            def on_progress(message: str, fraction: float) -> None:
                progress.progress(min(max(fraction, 0), 1), text=message)

            result = run_evaluation_batch(DB_PATH, submissions, client, on_progress=on_progress)
    except RuntimeError as error:
        progress.empty()
        st.error(str(error))
        return
    except Exception as error:
        progress.empty()
        st.error(f"The evaluation could not be saved. {error}")
        return

    st.session_state["last_submission_token"] = token
    st.session_state["last_run_id"] = result.rfp_run_id
    st.session_state["selected_run_id"] = result.rfp_run_id
    level, message = completion_message(result.status)
    if level == "success":
        st.success(message)
    else:
        st.error(message)
    _show_run(result.rfp_run_id)


def _show_run(run_id: str) -> None:
    stored = load_evaluation_run(DB_PATH, run_id)
    payloads = [row["result_json"] for row in stored["suppliers"]]
    scored, failed = partition_suppliers(payloads)
    level, message = completion_message(stored["status"])
    if level == "success":
        st.success(message)
    else:
        st.error(message)

    id_col, time_col, status_col = st.columns(3)
    id_col.metric("RFP run", stored["rfp_run_id"][:8])
    time_col.metric("Created", stored["created_at"])
    status_col.metric("Status", stored["status"])
    st.caption(f"Full run id: {stored['rfp_run_id']}")
    st.download_button(
        "Download JSON",
        data=json.dumps(stored, indent=2),
        file_name=f"{stored['rfp_run_id']}.json",
        mime="application/json",
    )

    warnings = []
    for payload in payloads:
        for warning in payload.get("warnings", []):
            if warning not in warnings:
                warnings.append(warning)
    if warnings:
        st.subheader("Warnings")
        for warning in warnings:
            st.warning(warning)

    st.subheader("Leaderboard")
    if scored:
        st.dataframe(leaderboard_rows(scored), use_container_width=True, hide_index=True)
        st.subheader("How the rank was decided")
        for line in explain_ranking(scored):
            st.write(line)
        st.subheader("Scorecards")
        for supplier in scored:
            title = f"Rank {supplier['final_rank']} · {supplier['supplier_name']}"
            with st.expander(title):
                st.markdown(supplier["overall_summary"])
                if supplier.get("risks"):
                    st.markdown("**Risks**")
                    for risk in supplier["risks"]:
                        st.markdown(f"- {risk}")
                st.dataframe(scorecard_rows(supplier), use_container_width=True, hide_index=True)
    else:
        st.info("No supplier was ranked in this run.")

    if failed:
        st.subheader("Suppliers that were not ranked")
        for supplier in failed:
            st.error(f"{supplier['supplier_name']} · {supplier.get('stage', 'failed')} · {supplier.get('error', '')}")


def _sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.header("Before you evaluate")
        typed_key = st.text_input(
            "OpenAI API key",
            type="password",
            placeholder="Paste your key here",
            help="Used only in this browser session. It is not saved in the project or shown again.",
        )
        model = st.text_input(
            "Model",
            value=read_setting("OPENAI_MODEL") or DEFAULT_MODEL,
        ).strip() or DEFAULT_MODEL
        api_key = resolve_api_key(typed_key, read_setting("OPENAI_API_KEY"))
        if api_key:
            st.caption("Key ready.")
        else:
            st.warning("Enter a key before you evaluate.")
        return api_key, model


def _style() -> None:
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.4rem; max-width: 1180px;}
        div[data-testid="stMetric"] {
            background: #e7eef5;
            border: 1px solid #d5e0ea;
            padding: 0.6rem 0.8rem;
            border-radius: 6px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
