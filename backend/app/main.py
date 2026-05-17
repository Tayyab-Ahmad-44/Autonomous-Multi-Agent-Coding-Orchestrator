from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import feature_tasks_router, missions_router


app = FastAPI(title="Agent Orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(feature_tasks_router)
app.include_router(missions_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
