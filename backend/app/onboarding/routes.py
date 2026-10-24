from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.auth.schemas import UserLocation
from app.core.database import get_database
from app.core.dependencies import require_participant
from app.onboarding.schemas import (
    OnboardingCompleteResponse,
    OnboardingInterestsRequest,
    OnboardingInterestsResponse,
    OnboardingLocationRequest,
    OnboardingLocationResponse,
)

router = APIRouter(prefix="/api/onboarding", tags=["Onboarding"])


@router.put(
    "/interests",
    response_model=OnboardingInterestsResponse,
    status_code=status.HTTP_200_OK,
    summary="Set or update participant interests during onboarding",
)
async def update_onboarding_interests(
    payload: OnboardingInterestsRequest,
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> OnboardingInterestsResponse:
    now = datetime.now(timezone.utc)
    await db["users"].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"interests": payload.interests, "updated_at": now}},
    )
    return OnboardingInterestsResponse(
        message="Interests updated successfully",
        interests=payload.interests,
    )


@router.put(
    "/location",
    response_model=OnboardingLocationResponse,
    status_code=status.HTTP_200_OK,
    summary="Set or update participant preferred location during onboarding",
)
async def update_onboarding_location(
    payload: OnboardingLocationRequest,
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> OnboardingLocationResponse:
    location_model = UserLocation(
        city=payload.city,
        locality=payload.locality,
        coordinates=payload.coordinates,
    )
    location_dict = location_model.model_dump(exclude_none=True)
    now = datetime.now(timezone.utc)
    await db["users"].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"location": location_dict, "updated_at": now}},
    )
    return OnboardingLocationResponse(
        message="Location updated successfully",
        location=location_model,
    )


@router.post(
    "/complete",
    response_model=OnboardingCompleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete participant onboarding after interests and location are set",
)
async def complete_onboarding(
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> OnboardingCompleteResponse:
    fresh_user = await db["users"].find_one({"_id": current_user["_id"]})
    if not fresh_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    interests = fresh_user.get("interests") or []
    location = fresh_user.get("location")
    city = location.get("city", "").strip() if isinstance(location, dict) else ""

    if not interests or not city:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Onboarding cannot be completed until at least one interest and a preferred city are set",
        )

    now = datetime.now(timezone.utc)
    await db["users"].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"onboarding_completed": True, "updated_at": now}},
    )
    return OnboardingCompleteResponse(
        message="Onboarding completed",
        onboarding_completed=True,
    )
