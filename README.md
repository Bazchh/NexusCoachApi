# Backend (FastAPI)

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
uvicorn app.main:app --reload --port 8000
```

## Config (env)

- You can use a `.env` file in the repo root (see `.env.example`).
- `REDIS_URL` (optional) - session store
- `POSTGRES_DSN` (optional) - session logs and feedback
- If `POSTGRES_DSN` is set, the API also updates `advice_bank` for retrieval.
- `STT_PROVIDER` (default: `openai`)
- `OPENAI_API_KEY` (required for `openai`)
- `WHISPER_MODEL` (default: `whisper-1`)
- `LLM_PROVIDER` (default: `rules`, set to `gemini` to enable)
- `GEMINI_API_KEY` (required for `gemini`)
- `GEMINI_MODEL` (default: `gemini-1.5-flash`)
- `MAX_HISTORY` (default: 20)
- `SESSION_TTL_SECONDS` (default: 21600)

If `STT_PROVIDER=local`, install `faster-whisper` separately.

## Endpoints (MVP)

- POST /session/start
- POST /turn
- POST /turn/audio (multipart)
- POST /session/end (optional feedback)
