#!/usr/bin/env python3
"""
Notes Quiz Agent — terminal front-end.

Reads a folder of notes (.md / .txt / .pdf), generates quiz questions, and
quizzes you interactively in the terminal with scoring + feedback. All the
question logic lives in quiz_core.py (shared with the Streamlit app).

Usage:
    python quiz_agent.py                       # quiz from ./notes, 8 questions
    python quiz_agent.py --notes path/to/dir   # point at any notes folder
    python quiz_agent.py --num 12              # number of questions
    python quiz_agent.py --offline             # force offline generation
    python quiz_agent.py --types mcq           # mcq | short | both
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from pathlib import Path

# Windows consoles default to cp1252 and choke on UTF-8 note content.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

import quiz_core as qc

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_NOTES_DIR = SCRIPT_DIR / "notes"
RESULTS_LOG = SCRIPT_DIR / "quiz_results.json"
SUPPORTED_EXTS = {".md", ".txt", ".pdf", ".markdown", ".text"}
LETTERS = "ABCDEFGH"


# ──────────────────────────────────────────────────────────────────────────
# Note loading (folder-based, CLI-specific)
# ──────────────────────────────────────────────────────────────────────────
def read_pdf(path: Path) -> str:
    try:
        return qc.extract_pdf_text(str(path))
    except ImportError:
        print(f"  ! Skipping {path.name}: pdfplumber not installed")
        return ""
    except Exception as exc:
        print(f"  ! Could not read {path.name}: {exc}")
        return ""


def read_text_file(path: Path) -> str:
    try:
        return qc.decode_text_bytes(path.read_bytes())
    except OSError:
        return ""


def load_notes(notes_dir: Path) -> tuple[str, list[str]]:
    if not notes_dir.exists():
        print(f"Notes folder not found: {notes_dir}")
        print("Create it and drop in some .md / .txt / .pdf files, then re-run.")
        sys.exit(1)

    files = sorted(
        p for p in notes_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    )
    if not files:
        print(f"No .md / .txt / .pdf notes found in {notes_dir}")
        sys.exit(1)

    chunks: list[str] = []
    loaded: list[str] = []
    for f in files:
        content = (read_pdf(f) if f.suffix.lower() == ".pdf"
                   else read_text_file(f)).strip()
        if content:
            chunks.append(f"# Source: {f.name}\n{content}")
            loaded.append(f.name)

    combined, truncated = qc.clamp_notes("\n\n".join(chunks))
    if truncated:
        print(f"  (notes are large — using the first {qc.MAX_NOTE_CHARS:,} characters)")
    return combined, loaded


# ──────────────────────────────────────────────────────────────────────────
# Interactive quiz loop
# ──────────────────────────────────────────────────────────────────────────
def ask_mcq(q: dict, idx: int, total: int) -> bool:
    print(f"\nQ{idx}/{total}  (multiple choice)")
    print(q["question"])
    options = list(q["options"])
    random.shuffle(options)
    for i, opt in enumerate(options):
        print(f"   {LETTERS[i]}. {opt}")
    while True:
        raw = input("Your answer (letter, or 's' to skip): ").strip()
        if raw.lower() == "s":
            print(f"   Skipped. Correct answer: {q['answer']}")
            return False
        choice = raw.upper()
        if len(choice) == 1 and choice in LETTERS[:len(options)]:
            picked = options[LETTERS.index(choice)]
            correct = picked == q["answer"]
            print("   [CORRECT]" if correct
                  else f"   [WRONG] Correct answer: {q['answer']}")
            if q.get("explanation"):
                print(f"   -> {q['explanation']}")
            return correct
        print("   Please enter a valid option letter.")


def ask_short(q: dict, idx: int, total: int) -> bool:
    print(f"\nQ{idx}/{total}  (short answer)")
    print(q["question"])
    raw = input("Your answer (or 's' to skip): ").strip()
    if raw.lower() == "s":
        print(f"   Skipped. Model answer: {q['answer']}")
        return False
    correct = qc.grade_short(raw, q)
    print("   [CORRECT]" if correct else f"   [WRONG] Model answer: {q['answer']}")
    if q.get("explanation"):
        print(f"   -> {q['explanation']}")
    return correct


def run_quiz(questions: list[dict]) -> dict:
    random.shuffle(questions)
    total = len(questions)
    score = 0
    wrong: list[dict] = []
    for i, q in enumerate(questions, 1):
        try:
            ok = ask_mcq(q, i, total) if q["type"] == "mcq" else ask_short(q, i, total)
        except (EOFError, KeyboardInterrupt):
            print("\n\nQuiz interrupted. Tallying what you answered so far...")
            total = i - 1
            break
        if ok:
            score += 1
        else:
            wrong.append(q)
        if q.get("source"):
            print(f'   source: "{q["source"]}"')
    return {"score": score, "total": total, "wrong": wrong}


def print_summary(result: dict) -> None:
    score, total = result["score"], result["total"]
    print("\n" + "=" * 52)
    if total == 0:
        print("No questions answered.")
        return
    pct = round(100 * score / total)
    print(f"  RESULT:  {score} / {total}  ({pct}%)")
    if pct >= 90:
        print("  Excellent - you know this material well.")
    elif pct >= 70:
        print("  Solid. Review the misses below and you're set.")
    elif pct >= 50:
        print("  Getting there - worth another pass over the notes.")
    else:
        print("  Keep going - re-read the notes and retry.")
    print("=" * 52)
    if result["wrong"]:
        print("\nReview these:")
        for q in result["wrong"]:
            print(f"  - {q['question']}")
            print(f"      answer: {q['answer']}")


def save_results(result: dict, notes_dir: Path, mode: str) -> None:
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "notes_dir": str(notes_dir),
        "generation": mode,
        "score": result["score"],
        "total": result["total"],
    }
    history: list[dict] = []
    if RESULTS_LOG.exists():
        try:
            history = json.loads(RESULTS_LOG.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.append(record)
    try:
        RESULTS_LOG.write_text(json.dumps(history, indent=2), encoding="utf-8")
        print(f"\n(Result saved to {RESULTS_LOG.name})")
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Quiz yourself on a folder of local notes.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--notes", type=Path, default=DEFAULT_NOTES_DIR,
                   help="Folder containing .md / .txt / .pdf notes.")
    p.add_argument("--num", type=int, default=8, help="Number of questions.")
    p.add_argument("--offline", action="store_true",
                   help="Force offline generation (no API call).")
    p.add_argument("--types", choices=["mcq", "short", "both"], default="both",
                   help="Which question types to include.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    types = {"mcq", "short"} if args.types == "both" else {args.types}

    print("Notes Quiz Agent")
    print("-" * 52)
    notes, loaded = load_notes(args.notes)
    print(f"Loaded {len(loaded)} note file(s): {', '.join(loaded)}")

    api_key = None if args.offline else qc.resolve_api_key()
    if api_key:
        print(f"Generating {args.num} questions with Gemini ({qc.MODEL_NAME})...")
    elif not args.offline:
        print(f"No {qc.API_KEY_ENV} set — generating questions offline.")
    else:
        print(f"Generating {args.num} questions offline...")

    questions, mode = qc.generate_questions(notes, args.num, types, api_key)
    if mode == "offline" and api_key:
        print("  ! Gemini unavailable — used offline generation instead.")

    if not questions:
        print("\nCouldn't generate any questions from these notes.")
        print("Try adding more substantive text to your notes.")
        sys.exit(1)

    print(f"\nReady - {len(questions)} questions. Type 's' to skip any question.\n")
    result = run_quiz(questions)
    print_summary(result)
    save_results(result, args.notes, mode)


if __name__ == "__main__":
    main()
