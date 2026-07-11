from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import User


DbSession = Annotated[Session, Depends(get_db)]

_bearer_scheme = HTTPBearer()
_bearer_scheme_optional = HTTPBearer(auto_error=False)


def _resolve_user_from_token(db: Session, token: str) -> User:
    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
    except (jwt.InvalidTokenError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        ) from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    return user


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> User:
    return _resolve_user_from_token(db, credentials.credentials)


def get_current_user_from_header_or_query(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme_optional)] = None,
    token: str | None = Query(default=None),
) -> User:
    """Same as get_current_user, but also accepts ?token= — the browser's
    native EventSource API can't send an Authorization header, so SSE routes
    need a query-param fallback."""
    raw_token = credentials.credentials if credentials is not None else token
    if raw_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return _resolve_user_from_token(db, raw_token)


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentUserFromStream = Annotated[User, Depends(get_current_user_from_header_or_query)]
