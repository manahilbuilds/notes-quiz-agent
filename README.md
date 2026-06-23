# Notes Quiz Agent

Turn your notes into a quiz. Upload or point it at `.md` / `.txt` / `.pdf`
notes; it generates questions, asks you, grades you, and shows what to review.

Two ways to use it:
- **Web app** (`app.py`) — Streamlit UI, runs locally or deploys to the cloud.
- **Terminal** (`quiz_agent.py`) — CLI that quizzes you on a folder of notes.

Both share one engine (`quiz_core.py`).

## Web app

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then upload notes or paste text, pick your settings, and take the quiz in the
browser. To put it online, see [DEPLOY.md](DEPLOY.md) (free on Streamlit Cloud).

## Terminal

```bash
python quiz_agent.py            # quiz from ./notes (a sample note ships there)
python quiz_agent.py --offline --num 12
python quiz_agent.py --notes "C:/path/to/notes" --types mcq
```

CLI options:

```
--notes PATH               Folder of .md / .txt / .pdf notes (default: ./notes)
--num N                    Number of questions (default: 8)
--offline                  Force offline generation, no API call
--types {mcq,short,both}   Question types (default: both)
```

In the terminal: type the option letter for multiple choice, type your answer
for short answer, `s` to skip, `Ctrl+C` to stop early. Scores append to
`quiz_results.json`.

## How questions are generated

- **With a Gemini key** (`GOOGLE_GENAI_API_KEY`): real comprehension questions —
  multiple choice + short answer — each with an explanation and a verbatim
  source snippet from your notes. Uses `gemini-2.5-flash`.
- **Without a key / offline / `--offline`**: a rule-based generator builds
  fill-in-the-blank questions straight from your notes. Free and fully private.

It prefers Gemini and silently falls back to offline if no key is set or the
call fails (e.g. quota exhausted).

### Where the key comes from
- **Local CLI / app:** `.env` file (`GOOGLE_GENAI_API_KEY=...`) — copy
  `.env.example`.
- **Streamlit Cloud:** app **Secrets** — see [DEPLOY.md](DEPLOY.md).

## Files

```
app.py             Streamlit web app
quiz_agent.py      Terminal CLI
quiz_core.py       Shared engine: note reading, question generation, grading
notes/             Sample notes (CLI default folder)
requirements.txt   Dependencies
DEPLOY.md          Streamlit Cloud deploy guide
```

This is a standalone side project — independent of any other repo.
