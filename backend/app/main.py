from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes import router as api_router
from backend.app.config import settings

app = FastAPI(title="Data Integration Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
def health() -> dict[str, object]:
    database_configured = bool(settings.database_url)
    return {
        "application": {"status": "running"},
        "database": {
            "configured": database_configured,
            "status": "configured" if database_configured else "not_configured",
        },
        "environment": {"name": settings.app_env, "status": "active"},
    }