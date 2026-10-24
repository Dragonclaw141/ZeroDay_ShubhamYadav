from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.schemas import UserLocation, UserResponse, normalize_phone
from app.onboarding.schemas import validate_interests_list


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    phone: Optional[str] = Field(default=None, min_length=10, max_length=20)
    affiliation_details: Optional[str] = Field(default=None, max_length=150)
    organization_name: Optional[str] = Field(default=None, max_length=150)
    interests: Optional[list[str]] = None
    location: Optional[UserLocation] = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Full name must be at least 2 characters long.")
        return cleaned

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return normalize_phone(value)

    @field_validator("affiliation_details", "organization_name")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None

    @field_validator("interests")
    @classmethod
    def validate_interests(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        if len(value) == 0:
            raise ValueError("Interests list cannot be empty when provided.")
        return validate_interests_list(value)


class ProfileUpdateResponse(BaseModel):
    message: str
    user: UserResponse
