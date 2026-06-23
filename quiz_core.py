"""
Shared core for the Notes Quiz Agent.

Pure logic used by BOTH the CLI (quiz_agent.py) and the Streamlit web app
(app.py): reading note content, generating questions (Gemini + offline), and
grading. No I/O loops, no Streamlit, no argparse — so both front-ends import
exactly one source of truth.
"""

from __future__ import annotations

import json
import os
import random
import re

# Conventions shared with the rest of the user's tooling.
API_KEY_ENV = "GOOGLE_GENAI_API_KEY"
PLACEHOLDER_KEYS = {"PASTEKEY", "your_gemini_api_key_here", "your_key_here", ""}
MODEL_NAME = "gemini-2.5-flash"

# Keep well within model context limits; truncate beyond this.
MAX_NOTE_CHARS = 24_000


# ──────────────────────────────────────────────────────────────────────────
# Reading note content
# ──────────────────────────────────────────────────────────────────────────
def extract_pdf_text(source) -> str:
    """Extract text from a PDF given a path string or a file-like object.

    `source` may be a filesystem path or any binary file-like object (e.g. a
    Streamlit UploadedFile). Raises ImportError if pdfplumber is missing.
    """
    import pdfplumber  # raises ImportError if not installed

    parts: list[str] = []
    with pdfplumber.open(source) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                parts.append(txt)
    return "\n".join(parts)


def decode_text_bytes(data: bytes) -> str:
    """Best-effort decode of raw bytes from a .md/.txt upload."""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def clamp_notes(text: str) -> tuple[str, bool]:
    """Return (text, was_truncated) clamped to MAX_NOTE_CHARS."""
    if len(text) > MAX_NOTE_CHARS:
        return text[:MAX_NOTE_CHARS], True
    return text, False


# ──────────────────────────────────────────────────────────────────────────
# API key resolution
# ──────────────────────────────────────────────────────────────────────────
def resolve_api_key(explicit: str | None = None) -> str | None:
    """Return a usable key, or None. `explicit` (e.g. from st.secrets) wins."""
    key = (explicit or os.environ.get(API_KEY_ENV, "")).strip()
    if key in PLACEHOLDER_KEYS:
        return None
    return key


# ──────────────────────────────────────────────────────────────────────────
# Question generation — Gemini
# ──────────────────────────────────────────────────────────────────────────
QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["mcq", "short"]},
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "answer": {"type": "string"},
                    "acceptable_keywords": {
                        "type": "array", "items": {"type": "string"}
                    },
                    "explanation": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["type", "question", "answer", "explanation"],
            },
        }
    },
    "required": ["questions"],
}


def generate_with_gemini(notes: str, num: int, types: set[str],
                         api_key: str) -> list[dict]:
    from google import genai  # type: ignore
    from google.genai import types as genai_types  # type: ignore

    client = genai.Client(api_key=api_key)

    if types == {"mcq"}:
        type_rule = "Every question MUST be type 'mcq'."
    elif types == {"short"}:
        type_rule = "Every question MUST be type 'short'."
    else:
        type_rule = "Mix the two types — roughly half 'mcq' and half 'short'."

    prompt = f"""You are a study coach. Create exactly {num} quiz questions that test
understanding of the NOTES below. {type_rule}

Rules:
- Questions must be answerable purely from the notes. Do not invent facts.
- For 'mcq': provide exactly 4 entries in "options"; set "answer" to the FULL
  TEXT of the correct option (it must match one option exactly). Make the three
  distractors plausible but clearly wrong per the notes.
- For 'short': "answer" is a concise model answer (1-2 sentences). Also fill
  "acceptable_keywords" with 2-5 essential words/phrases that a correct answer
  must contain (lowercase), used for grading.
- "explanation": one sentence on why the answer is correct.
- "source": a short verbatim snippet (<= 25 words) from the notes that supports
  the answer, so the learner can verify it.
- Vary difficulty and cover different parts of the notes.

NOTES:
\"\"\"
{notes}
\"\"\"
"""

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=QUESTION_SCHEMA,
        ),
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response.")
    data = json.loads(text)
    return [q for q in data.get("questions", []) if valid_question(q)]


def valid_question(q: dict) -> bool:
    if not isinstance(q, dict):
        return False
    if q.get("type") not in ("mcq", "short"):
        return False
    if not q.get("question") or not q.get("answer"):
        return False
    if q["type"] == "mcq":
        opts = q.get("options") or []
        if len(opts) < 2 or q["answer"] not in opts:
            return False
    return True


# ──────────────────────────────────────────────────────────────────────────
# Question generation — offline fallback
# ──────────────────────────────────────────────────────────────────────────
_STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "with", "that", "this", "from",
    "have", "has", "had", "not", "but", "you", "your", "its", "their", "they",
    "them", "then", "than", "which", "what", "when", "where", "who", "whom",
    "will", "would", "can", "could", "should", "shall", "may", "might", "must",
    "into", "onto", "over", "under", "such", "also", "each", "any", "all",
    "one", "two", "three", "these", "those", "there", "here", "been", "being",
    "a", "an", "of", "to", "in", "on", "at", "by", "is", "be", "as", "it",
    "or", "if", "so", "we", "i", "do", "does", "did", "our", "us", "his",
    "her", "him", "she", "he", "more", "most", "some", "very", "about",
}


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"(?m)^#.*$", " ", text)              # drop md/source headers
    text = re.sub(r"[*_`>#\-]{1,}", " ", text)          # strip md punctuation
    text = re.sub(r"\s+", " ", text).strip()
    try:
        import nltk  # type: ignore
        try:
            return [s.strip() for s in nltk.sent_tokenize(text) if s.strip()]
        except LookupError:
            try:
                nltk.download("punkt", quiet=True)
                nltk.download("punkt_tab", quiet=True)
                return [s.strip() for s in nltk.sent_tokenize(text) if s.strip()]
            except Exception:
                pass
    except Exception:
        pass
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _salient_terms(sentence: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", sentence)
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in _STOPWORDS or lw in seen:
            continue
        seen.add(lw)
        out.append(w)
    out.sort(key=lambda w: (w[0].isupper(), len(w)), reverse=True)
    return out


def generate_offline(notes: str, num: int, types: set[str]) -> list[dict]:
    sentences = [s for s in split_sentences(notes) if 8 <= len(s.split()) <= 40]
    random.shuffle(sentences)

    vocab: list[str] = []
    for s in sentences:
        vocab.extend(_salient_terms(s))
    vocab = list(dict.fromkeys(vocab))

    want_mcq = "mcq" in types
    want_short = "short" in types
    questions: list[dict] = []

    for sent in sentences:
        if len(questions) >= num:
            break
        terms = _salient_terms(sent)
        if not terms:
            continue
        answer = terms[0]
        blanked = re.sub(rf"\b{re.escape(answer)}\b", "_____", sent, count=1)
        if "_____" not in blanked:
            continue

        if want_mcq and want_short:
            make_mcq = len(questions) % 2 == 0
        else:
            make_mcq = want_mcq

        if make_mcq:
            distractors = [w for w in vocab if w.lower() != answer.lower()]
            random.shuffle(distractors)
            distractors = distractors[:3]
            if len(distractors) < 3:
                continue
            options = distractors + [answer]
            random.shuffle(options)
            questions.append({
                "type": "mcq",
                "question": f"Fill in the blank: {blanked}",
                "options": options,
                "answer": answer,
                "explanation": f'The notes state: "{sent}"',
                "source": sent,
            })
        else:
            questions.append({
                "type": "short",
                "question": f"Fill in the blank: {blanked}",
                "answer": answer,
                "acceptable_keywords": [answer.lower()],
                "explanation": f'The notes state: "{sent}"',
                "source": sent,
            })

    return questions


# ──────────────────────────────────────────────────────────────────────────
# Grading
# ──────────────────────────────────────────────────────────────────────────
def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def grade_short(user: str, q: dict) -> bool:
    u = _normalize(user)
    if not u:
        return False
    answer_norm = _normalize(q.get("answer", ""))
    if answer_norm and answer_norm in u:
        return True
    keywords = [k for k in (q.get("acceptable_keywords") or []) if k]
    if keywords:
        hits = sum(1 for k in keywords if _normalize(k) in u)
        return hits >= max(1, (len(keywords) + 1) // 2)
    ans_words = set(answer_norm.split())
    user_words = set(u.split())
    if not ans_words:
        return False
    return len(ans_words & user_words) / len(ans_words) >= 0.6


# ──────────────────────────────────────────────────────────────────────────
# Orchestration helper (used by both front-ends)
# ──────────────────────────────────────────────────────────────────────────
def generate_questions(notes: str, num: int, types: set[str],
                       api_key: str | None) -> tuple[list[dict], str]:
    """Generate questions, preferring Gemini, falling back to offline.

    Returns (questions, mode) where mode is "gemini" or "offline".
    """
    if api_key:
        try:
            qs = generate_with_gemini(notes, num, types, api_key)
            if qs:
                return qs[:num], "gemini"
        except Exception:
            pass  # fall through to offline
    return generate_offline(notes, num, types)[:num], "offline"
