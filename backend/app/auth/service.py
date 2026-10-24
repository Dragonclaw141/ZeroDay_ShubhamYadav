from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.collation import Collation
from pymongo.errors import DuplicateKeyError

from app.auth.schemas import (
    AuthResponse,
    LoginRequest,
    SignupRequest,
    serialize_user,
)
from app.core.security import create_access_token, hash_password, verify_password

EMAIL_COLLATION = Collation(locale="en", strength=2)


async def create_user_account(
    db: AsyncIOMotorDatabase,
    payload: SignupRequest,
) -> AuthResponse:
    """Create a new user account in MongoDB with unique email/phone validation."""
    users = db["users"]
    normalized_email = payload.email.strip().lower()
    normalized_phone = payload.phone.strip()

    existing_email = await users.find_one(
        {"email": normalized_email},
        collation=EMAIL_COLLATION,
    )
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email address is already registered",
        )

    existing_phone = await users.find_one({"phone": normalized_phone})
    if existing_phone:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phone number is already registered",
        )

    now = datetime.now(timezone.utc)
    affiliation = payload.affiliation_details if payload.role == "participant" else None
    organization = payload.organization_name if payload.role == "organizer" else None

    user_doc: dict[str, Any] = {
        "full_name": payload.full_name,
        "email": normalized_email,
        "phone": normalized_phone,
        "password_hash": hash_password(payload.password),
        "role": payload.role,
        "affiliation_details": affiliation,
        "organization_name": organization,
        "interests": [],
        "location": None,
        "onboarding_completed": False,
        "email_verified": False,
        "phone_verified": False,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }

    try:
        insert_result = await users.insert_one(user_doc)
    except DuplicateKeyError as exc:
        err_msg = str(exc).lower()
        if "phone" in err_msg:
            detail = "Phone number is already registered"
        elif "email" in err_msg:
            detail = "Email address is already registered"
        else:
            detail = "Email or phone number is already registered"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        ) from exc

    user_doc["_id"] = insert_result.inserted_id
    user_response = serialize_user(user_doc)
    token = create_access_token(subject=user_response.id, role=user_response.role)
    return AuthResponse(user=user_response, access_token=token)


async def authenticate_user(
    db: AsyncIOMotorDatabase,
    payload: LoginRequest,
) -> AuthResponse:
    """Authenticate a user by email and password and issue a signed JWT."""
    users = db["users"]
    normalized_email = payload.email.strip().lower()

    user_doc = await users.find_one(
        {"email": normalized_email},
        collation=EMAIL_COLLATION,
    )
    if not user_doc or not user_doc.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(payload.password, user_doc.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_response = serialize_user(user_doc)
    token = create_access_token(subject=user_response.id, role=user_response.role)
    return AuthResponse(user=user_response, access_token=token)
