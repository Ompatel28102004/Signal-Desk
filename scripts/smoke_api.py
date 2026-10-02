import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


def _request(base_url: str, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the local FastAPI/Supabase flow")
    parser.add_argument("--keyword", default="Toyota")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10:
        parser.error("--limit must be between 1 and 10 to keep the source request small")

    os.environ.update(
        {
            "APP_ENV": "development",
            "DATABASE_URL": "postgresql+psycopg://postgres:postgres@127.0.0.1:54322/postgres",
            "RSS_FEED_URLS": "[]",
            "YOUTUBE_API_KEY": "",
            "GEMINI_API_KEY": "",
            "OLLAMA_BASE_URL": "http://127.0.0.1:9",
            "AI_REQUEST_TIMEOUT_SECONDS": "1",
            "CORS_ORIGINS": '["http://localhost:5173"]',
        }
    )
    base_url = f"http://127.0.0.1:{args.port}"
    server = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(80):
            if server.poll() is not None:
                raise RuntimeError("FastAPI process exited before becoming ready")
            try:
                health = _request(base_url, "/health")
                if health.get("application", {}).get("status") == "running":
                    break
            except (URLError, TimeoutError, json.JSONDecodeError):
                time.sleep(0.25)
        else:
            raise RuntimeError("FastAPI did not become ready")

        collection = _request(
            base_url,
            "/api/collect",
            body={"keyword": args.keyword, "limit": args.limit},
        )
        stored_page = _request(
            base_url,
            f"/api/mentions?keyword={args.keyword}&page=1&page_size=100",
        )
        analytics = _request(base_url, f"/api/analytics?keyword={args.keyword}&days=365")
        insights = _request(base_url, f"/api/insights?keyword={args.keyword}&limit=100")
        sources = _request(base_url, "/api/sources")
        trends = _request(base_url, f"/api/analytics/trends?keyword={args.keyword}&period_days=7")
        spike = _request(base_url, f"/api/alerts/negative-spike?keyword={args.keyword}&window_days=7")
        competitors = _request(base_url, "/api/competitors?days=365")

        stored_ids = {item["id"] for item in stored_page["items"]}
        returned_ids = {item["id"] for item in collection["mentions"]}
        persisted_matches = len(stored_ids & returned_ids)
        if collection["collected"] and persisted_matches == 0:
            raise RuntimeError("Collected records were not returned by the persisted mention query")
        if collection["classified"] != collection["collected"]:
            raise RuntimeError("Not all collected mentions received classification")

        print(
            " ".join(
                [
                    "health=ok",
                    f"keyword={args.keyword}",
                    f"collected={collection['collected']}",
                    f"inserted={collection['inserted']}",
                    f"already_present={collection['already_present']}",
                    f"persisted_matches={persisted_matches}",
                    f"analytics_total={analytics['total']}",
                    f"insight_provider={insights['insights']['provider']}",
                    f"source_count={len(sources['sources'])}",
                    f"trend_count={len(trends['trends'])}",
                    f"spike_endpoint={'ok' if 'detected' in spike else 'invalid'}",
                    f"competitor_count={len(competitors['competitors'])}",
                ]
            )
        )
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Local API smoke failed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1)