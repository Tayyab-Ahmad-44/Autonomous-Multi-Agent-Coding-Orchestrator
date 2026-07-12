from app.api.routes.auth import router as auth_router
from app.api.routes.feature_tasks import router as feature_tasks_router
from app.api.routes.missions import router as missions_router
from app.api.routes.preferences import router as preferences_router
from app.api.routes.repos import router as repos_router

__all__ = [
    "auth_router",
    "feature_tasks_router",
    "missions_router",
    "preferences_router",
    "repos_router",
]
