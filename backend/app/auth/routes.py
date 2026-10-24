from typing import Any

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth.schemas import (
    AuthResponse,
    LoginRequest,
    SignupRequest,
    UserResponse,
    serialize_user,
)
from app.auth.service import authenticate_user, create_user_account
from app.core.database import get_database
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new participant or organizer account",
)
async def signup(
    payload: SignupRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> AuthResponse:
    return await create_user_account(db, payload)


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and receive a JWT access token",
)
async def login(
    payload: LoginRequest,
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> AuthResponse:
    return await authenticate_user(db, payload)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the authenticated user's profile",
)
async def get_me(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> UserResponse:
    return serialize_user(current_user)
