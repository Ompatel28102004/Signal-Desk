# Social Listening Platform

## Overview

I built this project to explore a practical social-listening workflow: enter a brand or product, collect public conversations, and turn them into a useful overview. The app currently searches Hacker News, configured RSS/Atom feeds, and YouTube.

The backend cleans results, removes duplicates and weak matches, saves accepted mentions in Supabase PostgreSQL, then assigns sentiment and topic labels. The React dashboard shows saved mentions, totals, sentiment, topics, activity over time, and a discussion summary.

The classifier runs locally. For summaries, the backend tries Ollama first, Gemini second, and a deterministic summary if neither model is available. Only aggregate counts and a few short example texts are sent to a summary provider.

## Features

- Collect and preview public mentions from Hacker News, RSS/Atom, and YouTube.
- Normalize text and URLs; filter irrelevant results and deduplicate records.
- Classify sentiment and discussion topics locally.
- Browse mentions, source links, filters, analytics, and AI summaries.
- View topic trends, negative-spike alerts, and Toyota/Hyundai/Kia comparisons.
- Optionally schedule collection in a separate worker.

## How It Works

```text
Keyword
  -> Data Collection
  -> Cleaning
  -> Deduplication and Relevance Filtering
  -> Sentiment and Topic Classification
  -> PostgreSQL Storage
  -> Bounded AI Summary
  -> Dashboard
```

Each source adapter returns a common mention format. The ingestion manager normalizes and filters results, then the API stores them with a unique source ID. The local classifier labels saved mentions. The summary service builds aggregate context and validates provider output before returning it to the dashboard.

## Tech Stack

| Area | Technology |
| --- | --- |
| Backend | Python, FastAPI |
| Database | Supabase PostgreSQL, SQLAlchemy, Alembic |
| Frontend | React, Vite |
| NLP | Local deterministic classifier |
| AI summary | Ollama, Gemini fallback, deterministic fallback |
| Testing | Pytest |
| Deployment target | Vercel, Render, Supabase |

## Project Structure

```text
backend/
  app/
    ai/                 # summary providers and context building
    api/                # routes, schemas, and request orchestration
    db/                 # database session and metadata
    ingestion/
      sources/           # Hacker News, RSS, YouTube
    models/              # SQLAlchemy models
    nlp/                 # deterministic classifier
    repositories/        # PostgreSQL queries and persistence
  migrations/            # Alembic revisions
frontend/
  src/                   # React dashboard and styles
scripts/                 # DB check/baseline, smoke test, benchmark
supabase/                # local Supabase CLI configuration
tests/                   # API, source, processing, DB, NLP, AI tests
.env.example
README.md
ARCHITECTURE.md
Dockerfile
docker-compose.yml
requirements.txt
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for component boundaries, schema details, failure handling, and deployment flow.

## Requirements

- Python 3.12 or later
- Node.js 22 or later
- Supabase/PostgreSQL for persisted collection
- Ollama with `llama3.2:3b` (optional)
- YouTube Data API key (optional)
- Gemini API key from a no-billing Free-tier project (optional)
- Public RSS/Atom feeds (optional)

## Setup

1. Clone the repository and enter its directory:

   ```powershell
   git clone <repository-url>
   Set-Location social-listening-platform
   ```

2. Create and activate a Python environment:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install backend dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Install frontend dependencies:

   ```powershell
   Set-Location frontend
   npm ci
   Set-Location ..
   ```

5. Create the local environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

6. Set `DATABASE_URL` in `.env` to your Supabase PostgreSQL URI. URL-encode reserved password characters (for example, encode `@` as `%40`). For a pooler connection, include `sslmode=require`. Add optional provider settings only if you use those providers.

7. Start the backend in one terminal:

   ```powershell
   python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
   ```

8. Start the frontend in a second terminal:

   ```powershell
   Set-Location frontend
   npm run dev
   ```

Open `http://localhost:5173`. The default CORS setting expects the `localhost` origin. The Search button previews public results; Collect processes and stores them.

## Environment Variables

Copy `.env.example` to `.env`. Keep `.env` private; it is ignored by Git. Never put database URLs or API keys in frontend variables or source code.

| Variable | Purpose | Required |
| --- | --- | --- |
| `DATABASE_URL` | Supabase PostgreSQL connection URI | Yes for persistence |
| `TEST_DATABASE_URL` | Loopback-only DB target for integration tests | DB tests only |
| `RSS_FEED_URLS` | JSON array of public feed URLs | Optional |
| `YOUTUBE_API_KEY` | Backend access to YouTube Data API v3 | Optional |
| `GEMINI_API_KEY` | Gemini summary fallback | Optional |
| `OLLAMA_BASE_URL` | Ollama service URL | Optional |
| `OLLAMA_MODEL` | Installed local model; default `llama3.2:3b` | Optional |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` | Local inference timeout; default 60 | Optional |
| `AI_REQUEST_TIMEOUT_SECONDS` | Gemini request timeout; default 12 | Optional |
| `CORS_ORIGINS` | JSON array of allowed browser origins | Set for deployment |
| `VITE_API_BASE_URL` | Backend URL compiled into the frontend | Set for deployment |
| `SCHEDULED_INGESTION_ENABLED` | Enable the separate scheduler | Optional, off by default |
| `SCHEDULED_INGESTION_KEYWORDS` | JSON array of scheduled keywords | Optional |
| `SCHEDULED_INGESTION_INTERVAL_MINUTES` | Scheduler interval; default 360 | Optional |
| `SCHEDULED_INGESTION_LIMIT` | Per-keyword collection limit; default 50 | Optional |
| `SCHEDULED_INGESTION_SOURCES` | Hacker News, RSS, and/or YouTube | Optional |

## Data Sources

- **Hacker News:** public Algolia search endpoint; no key required.
- **RSS:** each configured public feed is queried independently, so one failed feed does not block the others.
- **YouTube:** Data API v3 search with batched video metadata and capped comment requests.

Reddit is not included in the final application.

## AI/NLP

Sentiment and topic labels are produced locally; an LLM is not called for every mention. Summary context contains aggregate counts and at most three short positive and three short negative examples.

```text
Ollama -> Gemini Free Tier -> deterministic fallback
```

The provider output is schema-validated, and a provider error does not stop collection. Gemini is pinned to stable `gemini-3.8-flash`, uses structured output, and requests no paid grounding tools. Google lists model access and rate limits as tier-dependent; use a no-billing Free-tier project. Its free-tier terms may use submitted content to improve products, so only public, bounded context is sent.

Ollama setup:

```powershell
ollama pull llama3.2:3b
```

Keep Ollama running at `OLLAMA_BASE_URL`. In Docker, configure a URL reachable from the backend container.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Backend health |
| `GET` | `/api/sources` | Configured source status |
| `POST` | `/api/search` | Search without saving |
| `POST` | `/api/collect` | Collect, process, save, classify, summarize |
| `GET` | `/api/mentions` | Filtered and paginated mentions |
| `GET` | `/api/mentions/{id}` | One stored mention |
| `GET` | `/api/analytics` | Totals, sentiment, topics, and timeline |
| `GET` | `/api/analytics/trends` | Topic trend comparison |
| `GET` | `/api/alerts/negative-spike` | Negative-spike signal |
| `GET` | `/api/competitors` | Toyota/Hyundai/Kia comparison |
| `GET` | `/api/insights` | Summary of saved mentions |

## Running with Docker

Set the root `.env`, then run:

```powershell
docker compose config --quiet
docker compose up --build
```

Open the dashboard at `http://localhost:5173`; the API is at `http://localhost:8000`. To run the optional scheduled worker:

```powershell
docker compose --profile scheduler up --build scheduler
```

## Database Migrations

The schema is defined in `backend/app/models/mention.py`; migrations are in `backend/migrations/versions/`. Migrations do not run automatically when the backend starts.

For a fresh local database, set a loopback URL and apply the migrations:

```powershell
$env:MIGRATION_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"
python -m alembic upgrade head
```

For an existing database created outside Alembic, use the guarded baseline utility. It compares the database to the model and refuses to stamp if any difference exists. It reads `.env` in-process and does not print the URL:

```powershell
python -m scripts.db_baseline --from-app-config --allow-remote
python -m scripts.db_baseline --from-app-config --allow-remote --apply
```

Review the zero-difference result before using `--apply`. The stamp adds migration tracking only; it does not run migrations or alter mention rows. Check connectivity/schema with `python -m scripts.check_database`.

## Testing

Core tests (no live providers):

```powershell
python -m pytest -q -m "not integration"
```

Database integration tests must use a local PostgreSQL URL; the test guard rejects remote hosts:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres"
python -m pytest -q tests/test_mentions_repository.py
```

Run the frontend build and Compose check with:

```powershell
Set-Location frontend
npm ci
npm run build
Set-Location ..
docker compose config --quiet
```

Optional live smoke tests make small requests:

```powershell
$env:RUN_SOURCE_SMOKE_TESTS = "1"
python -m pytest -q -m integration tests/test_sources_smoke.py tests/test_youtube_smoke.py
```

The YouTube check makes one `search.list` request with `maxResults=1` and requires `YOUTUBE_API_KEY`. The local Hacker News check requires network access. Unit tests for source adapters and AI providers use mocked HTTP clients.

## Deployment

The intended deployment is React on Vercel, FastAPI on Render, and PostgreSQL on Supabase:

- In Vercel, set the project root to `frontend`, build command to `npm run build`, output directory to `dist`, and set `VITE_API_BASE_URL` to the backend URL.
- In Render, deploy the root Dockerfile, configure `/health` as the health check, and set `PORT`, `APP_ENV`, `DATABASE_URL`, `CORS_ORIGINS`, and any provider environment variables in the dashboard. The container binds to `0.0.0.0:$PORT`.
- In Supabase, use a project connection URI in the backend's `DATABASE_URL`.

Free-tier limits apply: Render's free web service sleeps when idle and has ephemeral storage and monthly instance-hour limits; Supabase Free includes 500 MB of database storage and may pause after inactivity; Vercel Hobby is intended for personal/non-commercial projects. See the official [Vercel pricing](https://vercel.com/pricing), [Render free service limits](https://render.com/docs/free), and [Supabase pricing](https://supabase.com/pricing) before deploying.

No public deployment is configured yet. Frontend URL: **Not deployed**. Backend URL: **Not deployed**.

## Known Limitations

- The local classifier is lightweight and rule-based; it can misclassify nuance or sarcasm.
- Hacker News and RSS keyword matches can be noisy.
- External APIs can time out, reach quotas, or be unavailable. Gemini was unavailable (`503 UNAVAILABLE`) in the last live check; Ollama and the deterministic fallback keep summaries available.
- Free hosts can sleep or pause, so they do not provide guaranteed availability.

## Future Improvements

- Evaluate classifier accuracy against a labeled sample and improve relevance quality.
- Add deployment smoke tests and confirm hosting limits as provider plans change.
- Improve data retention and operational monitoring for a longer-running deployment.
