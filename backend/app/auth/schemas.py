import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

RoleLiteral = Literal["participant", "organizer"]

VALID_INTERESTS: tuple[str, ...] = (
    "hackathons",
    "workshops",
    "summits_conferences",
    "meetups",
    "tech",
    "design",
    "business",
    "health",
    "arts",
    "science",
    "education",
    "sports",
)

PHONE_REGEX = re.compile(r"^\+?[1-9]\d{9,14}$")


def normalize_phone(phone: str) -> str:
    """Strip whitespace and hyphens and validate phone format (10-15 digits, optional leading +)."""
    cleaned = re.sub(r"[\s\-()]", "", phone.strip())
    if not PHONE_REGEX.match(cleaned):
        raise ValueError("Phone number must be 10 to 15 digits (optional leading +).")
    return cleaned


class GeoPoint(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: list[float] = Field(..., min_length=2, max_length=2)

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, coords: list[float]) -> list[float]:
        lng, lat = coords[0], coords[1]
        if not (-180.0 <= lng <= 180.0):
            raise ValueError("Longitude must be between -180 and 180.")
        if not (-90.0 <= lat <= 90.0):
            raise ValueError("Latitude must be between -90 and 90.")
        return [float(lng), float(lat)]


class UserLocation(BaseModel):
    city: str = Field(..., min_length=1, max_length=100)
    locality: Optional[str] = Field(default=None, max_length=120)
    coordinates: Optional[GeoPoint] = None

    @field_validator("city")
    @classmethod
    def strip_city(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("City cannot be empty.")
        return cleaned

    @field_validator("locality")
    @classmethod
    def strip_locality(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None


class SignupRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=20)
    password: str = Field(..., min_length=8, max_length=72)
    role: RoleLiteral
    affiliation_details: Optional[str] = Field(default=None, max_length=150)
    organization_name: Optional[str] = Field(default=None, max_length=150)

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Full name must be at least 2 characters long.")
        return cleaned

    @field_validator("email")
    @classmethod
    def normalize_email_field(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("phone")
    @classmethod
    def validate_phone_field(cls, value: str) -> str:
        return normalize_phone(value)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password cannot exceed 72 bytes.")
        if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
            raise ValueError("Password must contain at least one letter and one number.")
        return value

    @field_validator("affiliation_details", "organization_name")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned if cleaned else None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def normalize_login_email(cls, value: str) -> str:
        return value.strip().lower()


class UserResponse(BaseModel):
    id: str
    full_name: str
    email: str
    phone: str
    role: RoleLiteral
    affiliation_details: Optional[str] = None
    organization_name: Optional[str] = None
    interests: list[str] = Field(default_factory=list)
    location: Optional[UserLocation] = None
    onboarding_completed: bool = False
    email_verified: bool = False
    phone_verified: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class AuthResponse(BaseModel):
    user: UserResponse
    access_token: str
    token_type: str = "bearer"


def serialize_user(user_doc: dict[str, Any]) -> UserResponse:
    """Convert a MongoDB user document into a safe public UserResponse without password_hash."""
    location_data = user_doc.get("location")
    location_obj = UserLocation(**location_data) if isinstance(location_data, dict) else None
    return UserResponse(
        id=str(user_doc["_id"]),
        full_name=user_doc["full_name"],
        email=user_doc["email"],
        phone=user_doc["phone"],
        role=user_doc["role"],
        affiliation_details=user_doc.get("affiliation_details"),
        organization_name=user_doc.get("organization_name"),
        interests=list(user_doc.get("interests") or []),
        location=location_obj,
        onboarding_completed=bool(user_doc.get("onboarding_completed", False)),
        email_verified=bool(user_doc.get("email_verified", False)),
        phone_verified=bool(user_doc.get("phone_verified", False)),
        is_active=bool(user_doc.get("is_active", True)),
        created_at=user_doc["created_at"],
        updated_at=user_doc.get("updated_at", user_doc["created_at"]),
    )
