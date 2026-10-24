from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.auth.schemas import UserResponse, serialize_user
from app.core.database import get_database
from app.core.dependencies import get_current_user
from app.profile.schemas import ProfileUpdateRequest, ProfileUpdateResponse

router = APIRouter(prefix="/api/profile", tags=["Profile"])


@router.get(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the authenticated user's profile",
)
async def get_profile(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> UserResponse:
    return serialize_user(current_user)


@router.put(
    "",
    response_model=ProfileUpdateResponse,
    status_code=status.HTTP_200_OK,
    summary="Update the authenticated user's profile",
)
async def update_profile(
    payload: ProfileUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> ProfileUpdateResponse:
    users = db["users"]
    update_fields: dict[str, Any] = {}

    if payload.full_name is not None:
        update_fields["full_name"] = payload.full_name

    if payload.phone is not None and payload.phone != current_user.get("phone"):
        existing_phone = await users.find_one(
            {
                "phone": payload.phone,
                "_id": {"$ne": current_user["_id"]},
            }
        )
        if existing_phone:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Phone number is already registered",
            )
        update_fields["phone"] = payload.phone

    if payload.interests is not None:
        update_fields["interests"] = payload.interests

    if payload.location is not None:
        update_fields["location"] = payload.location.model_dump(exclude_none=True)

    update_fields["updated_at"] = datetime.now(timezone.utc)

    try:
        updated_user = await users.find_one_and_update(
            {"_id": current_user["_id"]},
            {"$set": update_fields},
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phone number is already registered",
        ) from exc

    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return ProfileUpdateResponse(
        message="Profile updated successfully",
        user=serialize_user(updated_user),
    )
