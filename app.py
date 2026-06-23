"""
Notes Quiz Agent — Streamlit web app.

Upload or paste notes, generate a quiz, and take it in the browser. Shares all
question logic with the CLI via quiz_core.py.

Run locally:   streamlit run app.py
Deploy:        push to GitHub, then deploy on share.streamlit.io
"""

from __future__ import annotations

import random

import streamlit as st

try:
    from dotenv import load_dotenv  # local dev convenience
    load_dotenv()
except Exception:
    pass

import quiz_core as qc

st.set_page_config(page_title="Notes Quiz Agent", page_icon="🧠", layout="centered")


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def get_api_key() -> str | None:
    """Prefer Streamlit secrets (cloud), fall back to env var (local)."""
    secret = ""
    try:
        secret = (st.secrets.get(qc.API_KEY_ENV, "") or "").strip()
    except Exception:
        secret = ""
    return qc.resolve_api_key(secret or None)


def build_notes_text(uploaded_files, pasted: str) -> tuple[str, list[str]]:
    """Combine uploaded files + pasted text into one notes string."""
    chunks: list[str] = []
    sources: list[str] = []
    for uf in uploaded_files or []:
        name = uf.name
        try:
            if name.lower().endswith(".pdf"):
                text = qc.extract_pdf_text(uf)
            else:
                text = qc.decode_text_bytes(uf.getvalue())
        except Exception as exc:
            st.warning(f"Could not read {name}: {exc}")
            continue
        text = text.strip()
        if text:
            chunks.append(f"# Source: {name}\n{text}")
            sources.append(name)
    if pasted.strip():
        chunks.append(f"# Source: pasted text\n{pasted.strip()}")
        sources.append("pasted text")
    combined, _ = qc.clamp_notes("\n\n".join(chunks))
    return combined, sources


def prepare_questions(questions: list[dict]) -> list[dict]:
    """Shuffle question order + MCQ options once, so reruns stay stable."""
    qs = [dict(q) for q in questions]
    random.shuffle(qs)
    for q in qs:
        if q["type"] == "mcq":
            opts = list(q["options"])
            random.shuffle(opts)
            q["display_options"] = opts
    return qs


def start_over() -> None:
    for key in ("questions", "idx", "score", "feedback", "finished", "mode",
                "wrong", "sources"):
        st.session_state.pop(key, None)


# ──────────────────────────────────────────────────────────────────────────
# Screens
# ──────────────────────────────────────────────────────────────────────────
def render_setup(api_key: str | None) -> None:
    st.title("🧠 Notes Quiz Agent")
    st.write("Upload or paste your notes, then quiz yourself. Runs entirely from "
             "your notes — no accounts, no tracking.")

    with st.sidebar:
        st.header("Settings")
        num = st.slider("Number of questions", 3, 20, 8)
        type_label = st.radio("Question types", ["Both", "Multiple choice", "Short answer"])
        if api_key:
            source = st.radio("Question source",
                              ["Smart (Gemini)", "Offline (no AI)"], index=0)
            st.caption("Gemini key detected — smart questions available.")
        else:
            source = "Offline (no AI)"
            st.info("No Gemini key configured — using offline generation. "
                    f"Add `{qc.API_KEY_ENV}` in app secrets to enable smart questions.")

    types = {"mcq", "short"}
    if type_label == "Multiple choice":
        types = {"mcq"}
    elif type_label == "Short answer":
        types = {"short"}

    uploaded = st.file_uploader(
        "Upload notes (.md, .txt, .pdf) — you can add several",
        type=["md", "markdown", "txt", "text", "pdf"],
        accept_multiple_files=True,
    )
    pasted = st.text_area("…or paste notes here", height=200,
                          placeholder="Paste any text you want to be quizzed on.")

    if st.button("Generate quiz", type="primary"):
        notes, sources = build_notes_text(uploaded, pasted)
        if not notes.strip():
            st.error("Add some notes first — upload a file or paste text above.")
            return
        use_key = api_key if source.startswith("Smart") else None
        with st.spinner("Generating questions…"):
            questions, mode = qc.generate_questions(notes, num, types, use_key)
        if not questions:
            st.error("Couldn't build questions from that — try longer or more "
                     "substantive notes.")
            return
        st.session_state.questions = prepare_questions(questions)
        st.session_state.idx = 0
        st.session_state.score = 0
        st.session_state.feedback = None
        st.session_state.finished = False
        st.session_state.wrong = []
        st.session_state.mode = mode
        st.session_state.sources = sources
        st.rerun()


def render_question() -> None:
    questions = st.session_state.questions
    idx = st.session_state.idx
    total = len(questions)
    q = questions[idx]

    st.progress(idx / total, text=f"Question {idx + 1} of {total}")
    st.caption("Multiple choice" if q["type"] == "mcq" else "Short answer")
    st.subheader(q["question"])

    feedback = st.session_state.feedback

    if feedback is None:
        with st.form(key=f"form_{idx}", clear_on_submit=False):
            if q["type"] == "mcq":
                choice = st.radio("Choose one:", q["display_options"], index=None)
            else:
                choice = st.text_input("Your answer:")
            submitted = st.form_submit_button("Submit", type="primary")
        if submitted:
            if q["type"] == "mcq":
                correct = choice is not None and choice == q["answer"]
            else:
                correct = qc.grade_short(choice or "", q)
            if correct:
                st.session_state.score += 1
            else:
                st.session_state.wrong.append(q)
            st.session_state.feedback = {"correct": correct, "your": choice}
            st.rerun()
        return

    # Feedback view (after submitting this question).
    if feedback["correct"]:
        st.success("✅ Correct!")
    else:
        your = feedback["your"] or "(no answer)"
        st.error(f"❌ Not quite. You said: {your}\n\nAnswer: **{q['answer']}**")
    if q.get("explanation"):
        st.markdown(f"**Why:** {q['explanation']}")
    if q.get("source"):
        st.caption(f'📖 From your notes: "{q["source"]}"')

    last = idx + 1 >= total
    if st.button("See results" if last else "Next question", type="primary"):
        st.session_state.feedback = None
        if last:
            st.session_state.finished = True
        else:
            st.session_state.idx += 1
        st.rerun()


def render_results() -> None:
    score = st.session_state.score
    total = len(st.session_state.questions)
    pct = round(100 * score / total) if total else 0

    st.title("Results")
    st.metric("Score", f"{score} / {total}", f"{pct}%")
    if pct >= 90:
        st.success("Excellent — you know this material well. 🎉")
    elif pct >= 70:
        st.info("Solid. Review the misses below and you're set.")
    elif pct >= 50:
        st.warning("Getting there — worth another pass over the notes.")
    else:
        st.error("Keep going — re-read the notes and retry.")

    st.caption(f"Questions generated: {st.session_state.mode} · "
               f"Sources: {', '.join(st.session_state.sources)}")

    wrong = st.session_state.wrong
    if wrong:
        st.subheader("Review these")
        for q in wrong:
            with st.expander(q["question"]):
                st.markdown(f"**Answer:** {q['answer']}")
                if q.get("explanation"):
                    st.write(q["explanation"])
                if q.get("source"):
                    st.caption(f'From your notes: "{q["source"]}"')

    if st.button("Start a new quiz", type="primary"):
        start_over()
        st.rerun()


# ──────────────────────────────────────────────────────────────────────────
# Router
# ──────────────────────────────────────────────────────────────────────────
def main() -> None:
    api_key = get_api_key()
    if "questions" not in st.session_state:
        render_setup(api_key)
    elif st.session_state.get("finished"):
        render_results()
    else:
        render_question()


main()
