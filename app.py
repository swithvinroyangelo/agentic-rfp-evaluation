"""Procurement evaluation dashboard."""

from __future__ import annotations

import html
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
    intake_status,
    explain_ranking,
    leaderboard_csv,
    leaderboard_rows,
    partition_suppliers,
    resolve_api_key,
    SAMPLE_SUPPLIER_NAMES,
    scorecard_rows,
    suggest_supplier_name,
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
from rfp_eval.proposals import PROPOSAL_FILENAMES

DB_PATH = default_database_path(ROOT)
STEPS = ("Upload", "Criteria", "Evaluate")
STEP_HINTS = {
    "Upload": "Add the supplier PDFs, then enter a name, date, and experience rating for each file.",
    "Criteria": "Confirm the active weights total 100% before a batch can be scored.",
    "Evaluate": "Start the batch here, then read the leaderboard and scorecards.",
}


def main() -> None:
    load_project_env(ROOT / ".env")
    st.set_page_config(
        page_title="Supplier ranking",
        page_icon="▣",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _style()
    initialize_database(DB_PATH)
    _hero()
    api_key, model = _sidebar()
    page = _guide()
    if page == "Upload":
        render_upload()
    elif page == "Criteria":
        render_criteria()
    else:
        render_evaluate(api_key, model)
    _step_nav(page)


def render_criteria() -> None:
    criteria = list_all_criteria(DB_PATH)
    active_weight = sum(item.weight for item in criteria if item.is_active)
    reason = evaluation_block_reason(criteria)
    ready, weight_card, count_card = st.columns(3)
    ready.metric("Ready to score", "Yes" if reason is None else "No")
    weight_card.metric("Active weight", f"{active_weight}%")
    count_card.metric("Active criteria", sum(1 for item in criteria if item.is_active))
    if reason:
        st.warning(reason)
    else:
        st.success("Active weights total 100%. Evaluation can run.")

    with st.form("criteria_form"):
        edits = []
        for criterion in criteria:
            with st.container(border=True):
                name_col, weight_col, max_col, active_col = st.columns([3.2, 1, 1, 1])
                state = "Active" if criterion.is_active else "Inactive"
                name_col.markdown(f"**{criterion.name}**")
                name_col.caption(f"{state} · {criterion.description}")
                name_col.markdown(
                    f"<div class='weight-track'><span style='width:{int(criterion.weight)}%'></span></div>",
                    unsafe_allow_html=True,
                )
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


def render_upload() -> None:
    st.subheader("Upload proposals")
    st.caption("Add the PDFs and supplier details. The next step checks the criteria. Evaluation is the last step.")
    sample_col, clear_col = st.columns(2)
    if sample_col.button("Load sample proposals", use_container_width=True):
        st.session_state["use_samples"] = True
        for filename, name in SAMPLE_SUPPLIER_NAMES.items():
            st.session_state[f"name_{filename}"] = name
        st.rerun()
    if clear_col.button("Clear sample proposals", use_container_width=True):
        st.session_state["use_samples"] = False
        st.rerun()
    uploads = st.file_uploader(
        "Drop supplier PDFs here",
        type=["pdf"],
        accept_multiple_files=True,
    )
    if uploads:
        st.session_state["saved_uploads"] = [
            {"name": upload.name, "file_id": upload.file_id, "data": upload.getvalue()}
            for upload in uploads
        ]
        st.session_state["use_samples"] = False
    else:
        st.session_state["saved_uploads"] = []
    sources = _proposal_sources(uploads)
    if sources and st.button("Fill names from file names"):
        for source in sources:
            filename, identity = _source_identity(source)
            st.session_state[f"name_{identity}"] = suggest_supplier_name(filename)
        st.rerun()
    rows: list[SupplierFormRow] = []
    for source in sources:
        filename, identity = _source_identity(source)
        with st.container(border=True):
            name_col, date_col, experience_col = st.columns([2, 1.2, 1])
            supplier_name = name_col.text_input(
                "Supplier name",
                key=f"name_{identity}",
                placeholder=filename,
            )
            submitted = date_col.date_input("Submission date", key=f"date_{identity}")
            experience_key = f"experience_{identity}"
            experience_args = {
                "min_value": 1,
                "max_value": 5,
                "step": 1,
                "key": experience_key,
            }
            if experience_key not in st.session_state:
                experience_args["value"] = 3
            experience = experience_col.number_input("Experience rating", **experience_args)
            if supplier_name.strip():
                st.caption(f"{filename} is ready.")
            else:
                st.caption(f"{filename} still needs a supplier name.")
        rows.append(
            SupplierFormRow(
                supplier_name=supplier_name,
                submission_date=submitted.isoformat(),
                experience_rating=int(experience),
                filename=filename,
            )
        )

    errors = validate_supplier_rows(rows)
    for error in errors:
        if error != "Upload at least one PDF.":
            st.error(error)
    if not sources:
        st.info("No files yet. Upload PDFs or load the sample proposals, then continue to Criteria.")
        return
    named = sum(1 for row in rows if row.supplier_name.strip())
    st.caption(f"{named} of {len(rows)} proposals have a supplier name. Use Next when this step is complete.")


def render_evaluate(api_key: str, model: str) -> None:
    criteria = list_all_criteria(DB_PATH)
    reason = evaluation_block_reason(criteria)
    sources = _saved_sources()
    rows = _rows_from_sources(sources)
    errors = validate_supplier_rows(rows)
    st.subheader("Evaluate")
    st.caption("This is the last step. The batch runs only when you click the button.")
    _checklist(bool(api_key), reason is None, len(rows), errors)
    if sources:
        for row in rows:
            st.write(f"{row.filename}: {row.supplier_name or 'name missing'} · {row.submission_date} · experience {row.experience_rating}")
    else:
        st.info("Go back to Upload and add proposals before evaluating.")
    if reason:
        st.error(f"Evaluation is blocked. {reason}")
    if not api_key:
        st.warning("Enter your OpenAI API key in the sidebar. The proposals stay here until you do.")
    for error in errors:
        if error != "Upload at least one PDF.":
            st.error(error)
    if sources:
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
            _run_batch(sources, rows, token, api_key, model)
    render_results()


def render_results() -> None:
    st.subheader("Results")
    runs = list_evaluation_runs(DB_PATH)
    if not runs:
        st.info("No evaluations yet. Finish Upload and Criteria, then start a batch here.")
        return
    labels = {f"{run['created_at']} · {run['status']} · {run['rfp_run_id']}": run["rfp_run_id"] for run in runs}
    preferred = st.session_state.get("selected_run_id", runs[0]["rfp_run_id"])
    default_label = next((label for label, run_id in labels.items() if run_id == preferred), next(iter(labels)))
    selected_label = st.selectbox("Saved run", list(labels), index=list(labels).index(default_label))
    _show_run(labels[selected_label])


def _saved_sources() -> list:
    saved = st.session_state.get("saved_uploads") or []
    if saved:
        return [_StoredPdf(item["name"], item["file_id"], item["data"]) for item in saved]
    if st.session_state.get("use_samples"):
        return [ROOT / "sample_proposals" / filename for filename in PROPOSAL_FILENAMES]
    return []


def _rows_from_sources(sources) -> list[SupplierFormRow]:
    rows = []
    for source in sources:
        filename, identity = _source_identity(source)
        submitted = st.session_state.get(f"date_{identity}", "")
        if hasattr(submitted, "isoformat"):
            submitted = submitted.isoformat()
        experience = st.session_state.get(f"experience_{identity}", 3)
        rows.append(
            SupplierFormRow(
                supplier_name=str(st.session_state.get(f"name_{identity}", "")),
                submission_date=str(submitted),
                experience_rating=int(experience),
                filename=filename,
            )
        )
    return rows


class _StoredPdf:
    def __init__(self, name: str, file_id: str, data: bytes) -> None:
        self.name = name
        self.file_id = file_id
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _proposal_sources(uploads) -> list:
    if uploads:
        return list(uploads)
    if st.session_state.get("use_samples"):
        return [ROOT / "sample_proposals" / filename for filename in PROPOSAL_FILENAMES]
    return []


def _source_identity(source) -> tuple[str, str]:
    if isinstance(source, Path):
        return source.name, source.name
    return source.name, source.file_id


def _run_batch(sources, rows: list[SupplierFormRow], token: str, api_key: str, model: str) -> None:
    progress = st.progress(0, text="Preparing proposals")
    try:
        with tempfile.TemporaryDirectory() as folder:
            submissions = []
            for source, row in zip(sources, rows):
                if isinstance(source, Path):
                    path = source
                else:
                    path = Path(folder) / source.name
                    path.write_bytes(source.getvalue())
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
    st.rerun()


def _show_run(run_id: str) -> None:
    stored = load_evaluation_run(DB_PATH, run_id)
    payloads = [row["result_json"] for row in stored["suppliers"]]
    scored, failed = partition_suppliers(payloads)
    level, message = completion_message(stored["status"])
    if level == "success":
        st.success(message)
    else:
        st.error(message)

    id_col, time_col, status_col, download_col = st.columns([1.1, 1.4, 1.2, 1])
    id_col.metric("RFP run", stored["rfp_run_id"][:8])
    time_col.metric("Created", stored["created_at"])
    status_col.metric("Status", stored["status"].replace("_", " "))
    with download_col:
        st.download_button(
            "Download JSON",
            data=json.dumps(stored, indent=2),
            file_name=f"{stored['rfp_run_id']}.json",
            mime="application/json",
            key=f"json_{stored['rfp_run_id']}",
        )
        if scored:
            st.download_button(
                "Download CSV",
                data=leaderboard_csv(leaderboard_rows(scored)),
                file_name=f"{stored['rfp_run_id']}_leaderboard.csv",
                mime="text/csv",
                key=f"csv_{stored['rfp_run_id']}",
            )
    st.caption(f"Full run id: {stored['rfp_run_id']}")
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
        _rank_cards(leaderboard_rows(scored))
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


def _checklist(has_key: bool, criteria_ready: bool, upload_count: int, errors: list[str]) -> None:
    steps = intake_status(has_key, criteria_ready, upload_count, errors)
    columns = st.columns(len(steps))
    for column, (label, done) in zip(columns, steps):
        column.metric(label, "Done" if done else "Needed")


def _guide() -> str:
    current = st.session_state.get("section", "Upload")
    if current == "Results":
        current = "Evaluate"
    if current not in STEPS:
        current = "Upload"
    st.session_state["section"] = current
    columns = st.columns(len(STEPS))
    for index, (column, name) in enumerate(zip(columns, STEPS), start=1):
        selected = name == current
        if column.button(
            f"{index}. {name}",
            key=f"step_{name}",
            type="primary" if selected else "secondary",
            use_container_width=True,
        ):
            st.session_state["section"] = name
            st.rerun()
    st.caption(f"Step {STEPS.index(current) + 1} of {len(STEPS)}. {STEP_HINTS[current]}")
    return current


def _step_nav(current: str) -> None:
    index = STEPS.index(current)
    back, spacer, forward = st.columns([1, 2, 1])
    if index > 0 and back.button("Back", use_container_width=True):
        st.session_state["section"] = STEPS[index - 1]
        st.rerun()
    if index < len(STEPS) - 1 and forward.button("Next", type="primary", use_container_width=True):
        st.session_state["section"] = STEPS[index + 1]
        st.rerun()
    spacer.caption("Use Back and Next to move through the evaluation.")


def _hero() -> None:
    st.markdown(
        """
        <div class="masthead">
          <p class="kicker">Procurement evaluation</p>
          <h1>Supplier ranking</h1>
          <p>Upload the proposals, check the criteria, then evaluate. Python calculates the weighted score, PPI, and rank.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _rank_cards(rows: list[dict]) -> None:
    shown = rows[:3]
    columns = st.columns(len(shown))
    for column, row in zip(columns, shown):
        with column:
            supplier = html.escape(str(row["Supplier"]))
            column.markdown(
                f"""
                <div class="rank-card">
                  <p class="rank-no">Rank {row["Rank"]}</p>
                  <h3>{supplier}</h3>
                  <p class="rank-score">{row["PPI"]} PPI</p>
                  <p class="rank-meta">Absolute {row["Absolute score"]} · Experience {row["Experience"]}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.markdown("<p class='kicker'>Session</p>", unsafe_allow_html=True)
        st.header("API access")
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
        .stApp,
        section[data-testid="stSidebar"],
        section[data-testid="stSidebar"] > div,
        .block-container,
        div[data-testid="stVerticalBlockBorderWrapper"],
        div[data-testid="stMetric"],
        div[data-testid="stFileUploader"],
        div[data-testid="stExpander"],
        .masthead,
        .rank-card {
            background: #1a1f27 !important;
            background-image: none !important;
            color: #e7edf4;
        }
        .block-container {padding-top: 1.1rem; max-width: 1120px;}
        .masthead {padding: 0 0 0.6rem; margin-bottom: 0.4rem;}
        .masthead h1, .rank-card h3, h1, h2, h3, p, label, span {color: #e7edf4;}
        .masthead h1 {font-size: 1.7rem; line-height: 1.2; margin: 0.1rem 0 0.3rem;}
        .masthead p, .rank-meta, .kicker {margin: 0; color: #c5d0dc;}
        .kicker {
            letter-spacing: 0.08em;
            text-transform: uppercase;
            font-size: 0.72rem;
            font-weight: 700;
        }
        section[data-testid="stSidebar"] {border-right: 0;}
        div[data-testid="stFileUploader"] {border: 1px solid #3a4554; border-radius: 8px; padding: 0.4rem 0.6rem 0.2rem;}
        div[data-testid="stMetric"] {border: 0; padding: 0.2rem 0;}
        .weight-track {height: 6px; background: #2c3542; border-radius: 99px; overflow: hidden; margin-top: 0.35rem;}
        .weight-track span {display: block; height: 100%; background: #9eb6d4;}
        .rank-card {border: 0; padding: 0.2rem 0; min-height: 0;}
        .rank-no {margin: 0; color: #9eb6d4; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;}
        .rank-score {margin: 0; font-size: 1.25rem; font-weight: 700; color: #e7edf4;}
        input, textarea {background: #1a1f27 !important; color: #e7edf4 !important;}
        .stButton > button {border-radius: 6px; background: #1a1f27; color: #e7edf4; border: 1px solid #9eb6d4;}
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
