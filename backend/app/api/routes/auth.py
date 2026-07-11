from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.core.security import create_access_token
from app.schemas import LoginRequest, SignupRequest, TokenResponse, UserRead
from app.services import auth as auth_service


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: DbSession) -> UserRead:
    try:
        return auth_service.create_user(db, email=payload.email, password=payload.password)
    except auth_service.EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = auth_service.authenticate_user(db, email=payload.email, password=payload.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    access_token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> UserRead:
    return current_user
