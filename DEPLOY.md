# Deploying to Streamlit Cloud

The web app (`app.py`) deploys to [Streamlit Community Cloud](https://share.streamlit.io)
(free). It pulls your code from a GitHub repo, so the flow is: **push to GitHub → point Streamlit at it**.

The app works with **no API key** (offline question generation). Adding a Gemini
key is optional and only enables smarter, AI-generated questions.

---

## 1. Put this folder on GitHub

From inside `notes-quiz-agent/` (git is already initialized for you):

```bash
git add .
git commit -m "Notes Quiz Agent"            # if not already committed
```

Create an empty repo on github.com (e.g. `notes-quiz-agent`), then:

```bash
git remote add origin https://github.com/<your-username>/notes-quiz-agent.git
git branch -M main
git push -u origin main
```

> `.env`, `quiz_results.json`, and `.streamlit/secrets.toml` are git-ignored, so
> your key and local data never get pushed.

## 2. Deploy on Streamlit Cloud

1. Go to **https://share.streamlit.io** and sign in with GitHub.
2. Click **Create app → Deploy a public app from GitHub** (private repos work too;
   authorize Streamlit to read it).
3. Fill in:
   - **Repository:** `<your-username>/notes-quiz-agent`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **Deploy**. First build takes a couple of minutes (installs
   `requirements.txt`).

You'll get a public URL like `https://<your-app>.streamlit.app`.

## 3. (Optional) Enable smart questions with Gemini

In your deployed app: **⋮ menu → Settings → Secrets**, then paste:

```toml
GOOGLE_GENAI_API_KEY = "your_real_key"
```

Save — the app reruns and the "Smart (Gemini)" option becomes available.
Without this, it stays in offline mode and still works.

> Get a key at https://aistudio.google.com/apikey. Note: a project that has hit
> its spend cap returns `429 RESOURCE_EXHAUSTED` — the app then falls back to
> offline automatically.

---

## Run it locally first (optional)

```bash
pip install -r requirements.txt
streamlit run app.py
```

For a local key, copy `.env.example` to `.env` (or
`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`) and add your key.
