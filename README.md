# Social Listening Platform

## Overview

This app collects public conversations about a brand or product and presents them in a dashboard. It searches Hacker News, configured RSS/Atom feeds, and YouTube; saves relevant mentions in Supabase PostgreSQL; and shows sentiment, topics, activity, and a discussion summary.

Sentiment and topic labels are assigned locally. Summaries use Ollama first, Gemini second, and a deterministic fallback. Only aggregate counts and a few short examples are sent to a summary provider.

## Features

- Multi-source search and collection
- Normalization, relevance filtering, and duplicate prevention
- Local sentiment and topic classification
- Searchable mentions, source links, analytics, and AI summary
- Topic trends, negative-spike alerts, competitor comparison, and optional scheduled collection

## How It Works

```text
Keyword -> Collection -> Cleaning and filtering -> Deduplication
        -> Sentiment and topics -> PostgreSQL -> AI summary -> Dashboard
```

Adapters return a common mention format. The ingestion manager cleans and filters results, stores accepted records, and classifies them. The summary service uses bounded aggregate context and validates its output.

## Tech Stack

| Area | Technology |
| --- | --- |
| Backend | Python, FastAPI |
| Database | Supabase PostgreSQL, SQLAlchemy, Alembic |
| Frontend | React, Vite |
| NLP | Local deterministic classifier |
| AI | Ollama, Gemini fallback |
| Testing | Pytest |
| Hosting | Render, Supabase |

## Project Structure

```text
backend/       API, ingestion, data models, NLP, AI, migrations
frontend/      React dashboard
scripts/       Database utilities, smoke test, benchmark
tests/         API, source, database, NLP, AI tests
supabase/      Local Supabase configuration
README.md  ARCHITECTURE.md  .env.example
Dockerfile  docker-compose.yml  requirements.txt
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for system details.

## Requirements

Python 3.12+, Node.js 22+, and a Supabase PostgreSQL project. Ollama (`llama3.2:3b`), YouTube API credentials, Gemini API credentials, and RSS feeds are optional.

## Setup

Clone and install dependencies:

```powershell
git clone https://github.com/Ompatel28102004/Signal-Desk.git
Set-Location Signal-Desk
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Set-Location frontend
npm ci
Set-Location ..
Copy-Item .env.example .env
```

Set `DATABASE_URL` in `.env` to your Supabase PostgreSQL URI. URL-encode reserved password characters (such as `@` as `%40`); use `sslmode=require` with a pooler URI. Keep `.env` private; it is Git-ignored.

## Environment Variables

| Variable | Purpose | Required |
| --- | --- | --- |
| `DATABASE_URL` | Supabase PostgreSQL URI | For saved data |
| `TEST_DATABASE_URL` | Loopback DB for integration tests | Tests only |
| `RSS_FEED_URLS` | JSON list of public feeds | Optional |
| `YOUTUBE_API_KEY` | YouTube Data API v3 | Optional |
| `GEMINI_API_KEY` | Gemini summary fallback | Optional |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Local model endpoint and name | Optional |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` | Ollama timeout; default 60 | Optional |
| `CORS_ORIGINS` | Allowed browser origins | Hosting |
| `VITE_API_BASE_URL` | Backend URL used by frontend | Hosting |
| `SCHEDULED_INGESTION_*` | Optional scheduled collection settings | Optional |

## Data Sources

- **Hacker News:** public search endpoint; no key.
- **RSS/Atom:** public feeds configured in `RSS_FEED_URLS`.
- **YouTube:** Data API v3; result and comment requests are capped.

## AI/NLP

The local classifier labels each mention without making per-mention LLM calls. Summaries use aggregate counts and at most three short positive and three short negative examples:

```text
Ollama -> Gemini Free Tier -> deterministic fallback
```

Gemini uses stable `gemini-3.8-flash`, structured output, and no paid grounding tools. Free access depends on project tier and quota; use a no-billing project. Install Ollama and pull the default model with `ollama pull llama3.2:3b`.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Health |
| GET | `/api/sources` | Source status |
| POST | `/api/search` | Search without saving |
| POST | `/api/collect` | Collect and save |
| GET | `/api/mentions`, `/api/mentions/{id}` | Read mentions |
| GET | `/api/analytics` | Totals and timeline |
| GET | `/api/analytics/trends` | Topic trends |
| GET | `/api/alerts/negative-spike` | Negative-spike check |
| GET | `/api/competitors` | Toyota/Hyundai/Kia comparison |
| GET | `/api/insights` | Summary of saved mentions |

## Running Locally

Run the backend from the repository root:

```powershell
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
Set-Location frontend
npm run dev
```

Open `http://localhost:5173`. Search previews results; Collect saves them.

## Running with Docker

```powershell
docker compose config --quiet
docker compose up --build
```

Dashboard: `http://localhost:5173`; API: `http://localhost:8000`. Configure `OLLAMA_BASE_URL` to an address reachable from the backend container. The scheduler is optional: `docker compose --profile scheduler up --build scheduler`.

## Database Migrations

For a fresh database, set a loopback `MIGRATION_DATABASE_URL` and run `python -m alembic upgrade head`. Migrations do not run automatically on app startup.

For an existing database, the baseline utility compares its schema before stamping and refuses if differences exist. It reads `.env` without printing the URL:

```powershell
python -m scripts.db_baseline --from-app-config --allow-remote
python -m scripts.db_baseline --from-app-config --allow-remote --apply
```

Review the zero-difference result before `--apply`. Stamping adds migration tracking only; it does not change mention rows. Check the connection with `python -m scripts.check_database`.

## Testing

```powershell
python -m pytest -q -m "not integration"
Set-Location frontend
npm ci
npm run build
Set-Location ..
docker compose config --quiet
```

Database tests require a loopback `TEST_DATABASE_URL`. Optional live smoke tests:

```powershell
$env:RUN_SOURCE_SMOKE_TESTS = "1"
python -m pytest -q -m integration tests/test_sources_smoke.py tests/test_youtube_smoke.py
```

## Deployment

Live services:

- Frontend: [signal-desk-web.onrender.com](https://signal-desk-web.onrender.com)
- Backend: [signal-desk-ejz6.onrender.com](https://signal-desk-ejz6.onrender.com)
- Repository: [Ompatel28102004/Signal-Desk](https://github.com/Ompatel28102004/Signal-Desk)

The backend needs `DATABASE_URL`, provider settings, and `CORS_ORIGINS`; the frontend needs `VITE_API_BASE_URL`. Render's free service can sleep and has usage limits. Supabase Free has storage limits and may pause after inactivity. Check current [Render](https://render.com/docs/free), [Supabase](https://supabase.com/pricing), and [Vercel](https://vercel.com/pricing) terms before changing hosts.

## Known Limitations

The classifier is rule-based and may miss nuance; public search results can be noisy. Gemini returned `503 UNAVAILABLE` in the last live test, so Ollama or the deterministic fallback may provide summaries. Free hosting can sleep or pause.

## Future Improvements

Evaluate classifier accuracy on labeled data, improve relevance ranking, and add deployment smoke tests.

