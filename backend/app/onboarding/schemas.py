from typing import Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.auth.schemas import VALID_INTERESTS, GeoPoint, UserLocation


def validate_interests_list(interests: list[str]) -> list[str]:
    """Validate and deduplicate interests while preserving order."""
    if not interests:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one interest must be selected",
        )
    cleaned: list[str] = []
    invalid: list[str] = []
    for item in interests:
        if not isinstance(item, str):
            raise ValueError("Each interest must be a string.")
        norm = item.strip().lower()
        if norm not in VALID_INTERESTS:
            invalid.append(item)
        elif norm not in cleaned:
            cleaned.append(norm)

    if invalid:
        raise ValueError(
            f"Unsupported interest(s): {', '.join(invalid)}. "
            f"Allowed values: {', '.join(VALID_INTERESTS)}"
        )
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one interest must be selected",
        )
    return cleaned


class OnboardingInterestsRequest(BaseModel):
    interests: list[str] = Field(default_factory=list)

    @field_validator("interests")
    @classmethod
    def check_interests(cls, value: list[str]) -> list[str]:
        return validate_interests_list(value)


class OnboardingInterestsResponse(BaseModel):
    message: str
    interests: list[str]


class OnboardingLocationRequest(BaseModel):
    city: str = Field(..., max_length=100)
    locality: Optional[str] = Field(default=None, max_length=120)
    coordinates: Optional[GeoPoint] = None

    @field_validator("city")
    @classmethod
    def validate_city_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="City is required for location",
            )
        return cleaned

    @field_validator("locality")
    @classmethod
    def normalize_locality(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None


class OnboardingLocationResponse(BaseModel):
    message: str
    location: UserLocation


class OnboardingCompleteResponse(BaseModel):
    message: str
    onboarding_completed: bool
