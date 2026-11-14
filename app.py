"""Local Streamlit review app. Run: python -m streamlit run app.py."""

from collections import Counter
from hashlib import sha256
import os
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
import streamlit as st

from ingestion import InputValidationError
from pipeline import DocumentExtractionError, extract_file, extract_upload
from review import (approved_download, approve_document, editor_records, expected_pages,
                    load_pages, review_signature, saved_documents)
from runs import load_run
from schemas import OUTPUT_COLUMNS

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)
DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT / "data").resolve()


def clear_approval():
    st.session_state.pop("approval", None)


def changed_review():
    clear_approval()
    st.session_state["confirmed"] = False


def changed_source():
    changed_review()
    st.session_state.pop("new_runs", None)


def choose_runs() -> list[Path]:
    mode = st.sidebar.radio("Workspace", ["Saved results", "New extraction"], on_change=changed_review)
    st.sidebar.caption("01 / Select a sheet\n\n02 / Review every row\n\n03 / Approve & download")
    if mode == "New extraction":
        st.subheader("Start with a sheet")
        source = st.radio("Source", ["Upload a file", "Choose a sample"], horizontal=True, on_change=changed_source)
        upload = None
        sample = None
        if source == "Upload a file":
            upload = st.file_uploader("PDF or image · up to 20 MiB", type=["pdf", "png", "jpg", "jpeg", "webp", "gif"], on_change=changed_source)
        else:
            samples = sorted(path for path in (ROOT / "samples").iterdir()
                             if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif"})
            sample = st.selectbox("Sample file", samples, format_func=lambda path: path.name, on_change=changed_source) if samples else None
        st.caption("Extract sheet sends the file’s prepared pages to the configured LLM and may incur API charges. Editing and downloads do not call the model.")
        if st.button("Extract sheet →", type="primary", disabled=upload is None and sample is None):
            st.session_state.pop("new_runs", None)
            changed_review()
            try:
                with st.spinner("Preparing pages and extracting rows…"):
                    results = (extract_upload(upload.getvalue(), upload.name, data_dir=DATA_DIR) if upload is not None
                               else extract_file(sample, data_dir=DATA_DIR))
                st.session_state.new_runs = [result.run_dir for result in results]
            except (InputValidationError, DocumentExtractionError, ValueError, OSError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("Extraction could not finish. Check the terminal and saved run manifests; no file has been approved.")
        return st.session_state.get("new_runs", [])
    documents, warnings = saved_documents(DATA_DIR)
    for warning in warnings:
        st.sidebar.warning(warning)
    if not documents:
        st.info("No successful saved runs yet. Choose New extraction to upload a sheet.")
        return []
    document_id = st.sidebar.selectbox("Saved document", list(documents),
                                      format_func=lambda value: f"Sheet {value[:12]}", on_change=changed_review)
    attempts = {}
    for directory in documents[document_id]:
        run = load_run(directory)
        attempts.setdefault(run.page_number, []).append(directory)
    chosen = []
    for number, paths in sorted(attempts.items()):
        chosen.append(st.sidebar.selectbox(
            f"Page {number} extraction", paths, key=f"attempt_{document_id}_{number}",
            format_func=lambda path: path.name.split("Z_")[0].replace("_", " ") + " UTC",
            on_change=changed_review))
    st.sidebar.caption("Newest attempt selected for each page. Saved mode makes no model requests.")
    return chosen


def show_review(directories: list[Path]):
    try:
        pages = load_pages(directories)
        count = expected_pages(pages)
    except (ValueError, OSError) as exc:
        st.error(f"Cannot load this review: {exc}")
        return
    token = sha256("|".join(str(page.directory) for page in pages).encode()).hexdigest()
    if st.session_state.get("review_token") != token:
        changed_review()
        st.session_state.review_token = token
    complete = [page.run.page_number for page in pages] == list(range(1, count + 1))
    if not complete:
        st.error(f"Incomplete document: {len(pages)} of {count} pages available. File approval is blocked.")
    records = editor_records(pages)
    risks = Counter(row["risk"] for row in records)
    a, b, c, d = st.columns(4)
    a.metric("Extracted rows", len(records))
    b.metric("High risk", risks["high"])
    c.metric("Medium risk", risks["medium"])
    d.metric("Pages", f"{len(pages)} / {count}")
    st.divider()
    left, right = st.columns([0.36, 0.64], gap="large")
    with left:
        st.subheader("01 / Original sheet")
        page_index = st.selectbox("View page", range(len(pages)), format_func=lambda i: f"Page {pages[i].run.page_number}")
        page = pages[page_index]
        st.image(page.image, caption=f"Source page {page.run.page_number} · open fullscreen to inspect handwriting", width="stretch")
        source = page.run.config.preprocessing.get("source", {})
        original_path = (DATA_DIR / source.get("original_path", "")).resolve()
        if original_path.is_relative_to(DATA_DIR) and original_path.is_file():
            content = original_path.read_bytes()
            if sha256(content).hexdigest() == source.get("original_sha256"):
                st.download_button("Download original file", content, file_name=f"original{original_path.suffix}", key="original_download")
        with st.expander("Source notes & inherited fields"):
            st.caption(f"Run: {page.run.run_id} · Model: {page.run.returned_model or page.run.config.model}")
            for note in page.source.layout_notes + page.source.notes:
                st.text(note)
            for source_row, row in zip(page.source.rows, page.validated.rows):
                st.markdown(f"**Row {row.row_number}** · {row.risk.value}")
                if row.inherited_fields:
                    st.write("Inherited: " + ", ".join(row.inherited_fields))
                for note in source_row.notes:
                    st.text(note)
                details = {name: field.model_dump(mode="json") for name, field in source_row.fields.items()
                           if field.uncertain or field.inference or field.notes}
                if details:
                    st.json(details, expanded=False)
    with right:
        st.subheader("02 / Review the rows")
        st.caption("Edit any business cell. Scroll horizontally for risk and reason at the end of each row. Exclusions need a reason. Risk reflects the saved extraction; edits do not erase its warnings or change other rows.")
        data = pd.DataFrame(records, columns=["_row_id", "Page", "Row", "Exclude", "Exclusion reason", *OUTPUT_COLUMNS, "risk", "risk_reason"])
        for header in [*OUTPUT_COLUMNS, "Exclusion reason"]:
            data[header] = data[header].astype("string")
        edited = st.data_editor(
            data, hide_index=True, width="stretch", height=480, num_rows="fixed",
            disabled=["_row_id", "Page", "Row", "risk", "risk_reason"],
            column_config={"_row_id": None,
                           "Exclude": st.column_config.CheckboxColumn("Exclude", default=False),
                           "risk": st.column_config.TextColumn("risk", width="small"),
                           "risk_reason": st.column_config.TextColumn("risk_reason", width="large"),
                           **{header: st.column_config.TextColumn(header) for header in OUTPUT_COLUMNS}},
            key=f"editor_{token}", on_change=changed_review)
        st.caption("Your draft stays in this browser session. Approval saves a permanent snapshot. Refreshing or closing the tab can discard an unapproved draft.")
        reviewer = st.text_input("Reviewer name", key="reviewer", on_change=changed_review)
        confirmed = st.checkbox("I checked every source page, all included values, exclusions, and risk warnings. This file is ready to export.", key="confirmed", on_change=clear_approval)
        approve = st.button("Approve file & prepare CSV →", type="primary", disabled=not complete, width="stretch")
        current = edited.fillna("").to_dict("records")
        signature = review_signature(pages, current, reviewer)
        previous = st.session_state.get("approval")
        if previous and previous["signature"] != signature:
            st.session_state.pop("approval", None)
        if approve:
            try:
                directory = approve_document(pages, current, reviewer=reviewer, confirmed=confirmed,
                                             reviews_dir=DATA_DIR / "reviews")
                st.session_state.approval = {"directory": str(directory), "signature": signature}
            except (ValueError, OSError) as exc:
                st.error(str(exc))
        approval = st.session_state.get("approval")
        if approval and approval["signature"] == signature:
            try:
                content = approved_download(Path(approval["directory"]), signature)
                st.success("File approved. Your CSV contains only the eight business columns and included rows.")
                st.download_button("Download approved CSV ↓", content, file_name=f"inventory_{pages[0].run.document_id[:12]}_approved.csv", mime="text/csv", type="primary")
            except (ValueError, OSError) as exc:
                st.error(str(exc))


def main():
    st.set_page_config(page_title="Inventory / Review", page_icon="▦", layout="wide")
    st.markdown("""<style>
        .stApp {background: #f8f7f3;}
        .block-container {padding-top:2rem; padding-bottom:2rem;}
        h1, h2, h3, h1 span, h3 span {font-family: Georgia, 'Times New Roman', serif !important; letter-spacing: -.03em;}
        h3 {font-size:1.5rem !important;}
        h1 {font-size: 3.2rem !important; font-weight: 500 !important; line-height: 1.08 !important;}
        h1 em {color: #3635b9;}
        [data-testid="stSidebar"] {border-right: 1px solid #d9d9e4;}
        [data-testid="stMetric"] {border-top: 1px solid #c9cad7; padding-top: 12px;}
        [data-testid="stMetricValue"] {font-family: Georgia, serif;}
        .eyebrow {font: 11px monospace; letter-spacing: .16em; color:#3635b9; padding:8px 0 14px;}
        .masthead {border-bottom:1px solid #c9cad7; padding:0 0 14px; margin-bottom:24px;
                   font:600 15px sans-serif; letter-spacing:.08em;}
        div.stButton > button, div.stDownloadButton > button {border-radius:5px;}
        button[aria-label="Download as CSV"] {display:none;}
        </style><div class="masthead">INVENTORY / REVIEW</div><div class="eyebrow">FROM PAPER TO A REVIEWED RECORD</div>""", unsafe_allow_html=True)
    st.title("Make every row *count.*")
    st.write("Check the source. Correct the details. Export with confidence.")
    directories = choose_runs()
    if directories:
        show_review(directories)
    st.caption("Local review workspace · Every export requires explicit file approval.")


if __name__ == "__main__":
    main()
