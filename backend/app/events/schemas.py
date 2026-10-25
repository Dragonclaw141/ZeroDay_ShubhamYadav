from datetime import datetime, timezone
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.auth.schemas import GeoPoint

EventStatusLiteral = Literal["draft", "published", "cancelled"]
OrganizerCreateStatusLiteral = Literal["draft", "published"]
PriceTypeLiteral = Literal["free", "paid"]

CATEGORY_DISPLAY_NAMES: dict[str, str] = {
    "hackathons": "Hackathons",
    "workshops": "Workshops",
    "summits_conferences": "Summits & Conferences",
    "meetups": "Meetups",
    "tech": "Tech Talk",
    "business": "Startup",
    "arts": "Music & Arts",
    "sports": "Sports",
    "design": "Art & Design",
}

CATEGORY_ALIASES: dict[str, str] = {
    # Canonical 4 categories
    "hackathons": "hackathons",
    "hackathon": "hackathons",
    "workshops": "workshops",
    "workshop": "workshops",
    "summits_conferences": "summits_conferences",
    "summits & conferences": "summits_conferences",
    "summit": "summits_conferences",
    "conference": "summits_conferences",
    "conferences": "summits_conferences",
    "tech talk": "summits_conferences",
    "tech_talk": "summits_conferences",
    "meetups": "meetups",
    "meetup": "meetups",
    # Extended frontend category labels
    "startup": "business",
    "business": "business",
    "music": "arts",
    "arts": "arts",
    "sports": "sports",
    "sport": "sports",
    "art": "design",
    "design": "design",
    "food": "meetups",
    "tech": "tech",
    "science": "science",
    "education": "education",
    "health": "health",
}


def normalize_category(value: str) -> str:
    """Normalize a category name or alias into a canonical category slug."""
    if not isinstance(value, str):
        raise ValueError("Category must be a string.")
    cleaned = value.strip().lower()
    if cleaned not in CATEGORY_ALIASES:
        allowed = ", ".join(sorted(set(CATEGORY_ALIASES.values())))
        raise ValueError(f"Unsupported category '{value}'. Allowed categories: {allowed}")
    return CATEGORY_ALIASES[cleaned]


def ensure_utc_datetime(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_registration_url(value: Optional[str]) -> Optional[str]:
    """Validate that an external registration URL is a well-formed http/https URL."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("registration_url must be a valid URL string.")
    cleaned = value.strip()
    if not cleaned:
        return None
    if any(ch.isspace() for ch in cleaned):
        raise ValueError("registration_url must not contain spaces.")
    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").lower()
    if scheme not in ("http", "https") or not hostname:
        raise ValueError("registration_url must be a valid http or https URL.")
    if "." not in hostname and hostname != "localhost":
        raise ValueError("registration_url must have a valid domain name.")
    return cleaned


def validate_and_normalize_pricing(
    price_type: Optional[str],
    price_amount: Optional[float],
    is_free: Optional[bool],
) -> tuple[PriceTypeLiteral, Optional[float], bool]:
    """Validate and synchronize price_type, price_amount, and legacy is_free."""
    cleaned_pt: Optional[PriceTypeLiteral] = None
    if price_type is not None:
        if not isinstance(price_type, str):
            raise ValueError("price_type must be 'free' or 'paid'.")
        norm_pt = price_type.strip().lower()
        if norm_pt not in ("free", "paid"):
            raise ValueError("price_type must be either 'free' or 'paid'.")
        cleaned_pt = "free" if norm_pt == "free" else "paid"

    if cleaned_pt is not None and is_free is not None:
        if (cleaned_pt == "free" and is_free is False) or (
            cleaned_pt == "paid" and is_free is True
        ):
            raise ValueError("Conflicting price_type and is_free values.")

    if cleaned_pt is not None:
        resolved_type: PriceTypeLiteral = cleaned_pt
    elif is_free is not None:
        resolved_type = "free" if is_free else "paid"
    else:
        resolved_type = "free"

    if resolved_type == "free":
        if price_amount is not None and price_amount != 0:
            raise ValueError(
                "Free events must not have a positive or non-zero price_amount."
            )
        return "free", None, True

    # resolved_type == "paid"
    if price_amount is None or price_amount <= 0:
        raise ValueError("Paid events must have a valid positive price_amount.")
    return "paid", round(float(price_amount), 2), False


class EventVenue(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    address: Optional[str] = Field(default="", max_length=250)
    city: str = Field(..., min_length=1, max_length=100)
    coordinates: Optional[GeoPoint] = None

    @field_validator("name", "city")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Venue name and city cannot be empty.")
        return cleaned

    @field_validator("address")
    @classmethod
    def strip_address(cls, value: Optional[str]) -> str:
        return value.strip() if value else ""


class EventCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=3, max_length=150)
    description: str = Field(..., min_length=10, max_length=5000)
    category: str
    tags: list[str] = Field(default_factory=list)
    venue: EventVenue
    start_date: datetime
    end_date: Optional[datetime] = None
    registration_deadline: Optional[datetime] = None
    max_capacity: int = Field(default=100, ge=1, le=100000)
    status: OrganizerCreateStatusLiteral = "draft"
    mode: Optional[str] = Field(default="In-person", max_length=40)
    cover_image_url: Optional[str] = Field(default=None, max_length=500)
    contact_email: Optional[EmailStr] = None
    price_type: Optional[PriceTypeLiteral] = None
    price_amount: Optional[float] = None
    registration_url: Optional[str] = Field(default=None, max_length=500)
    is_free: Optional[bool] = None

    @field_validator("title", "description")
    @classmethod
    def strip_text_fields(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty.")
        return cleaned

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        return normalize_category(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value or []:
            if isinstance(item, str):
                tag = item.strip().lower()
                if tag and tag not in out:
                    out.append(tag)
        return out[:20]

    @field_validator("registration_url")
    @classmethod
    def validate_create_registration_url(cls, value: Optional[str]) -> Optional[str]:
        return validate_registration_url(value)

    @model_validator(mode="after")
    def validate_event_dates_and_pricing(self) -> "EventCreateRequest":
        start = ensure_utc_datetime(self.start_date)
        end = ensure_utc_datetime(self.end_date) if self.end_date is not None else start
        deadline = (
            ensure_utc_datetime(self.registration_deadline)
            if self.registration_deadline is not None
            else start
        )
        if end < start:
            raise ValueError("end_date must be greater than or equal to start_date.")
        if deadline > start:
            raise ValueError("registration_deadline must be on or before start_date.")
        self.start_date = start
        self.end_date = end
        self.registration_deadline = deadline

        resolved_type, resolved_amount, resolved_is_free = validate_and_normalize_pricing(
            self.price_type,
            self.price_amount,
            self.is_free,
        )
        self.price_type = resolved_type
        self.price_amount = resolved_amount
        self.is_free = resolved_is_free
        return self


class EventUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=3, max_length=150)
    description: Optional[str] = Field(default=None, min_length=10, max_length=5000)
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    venue: Optional[EventVenue] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    registration_deadline: Optional[datetime] = None
    max_capacity: Optional[int] = Field(default=None, ge=1, le=100000)
    mode: Optional[str] = Field(default=None, max_length=40)
    cover_image_url: Optional[str] = Field(default=None, max_length=500)
    contact_email: Optional[EmailStr] = None
    price_type: Optional[PriceTypeLiteral] = None
    price_amount: Optional[float] = None
    registration_url: Optional[str] = Field(default=None, max_length=500)
    is_free: Optional[bool] = None

    @field_validator("title", "description")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty when provided.")
        return cleaned

    @field_validator("category")
    @classmethod
    def validate_optional_category(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return normalize_category(value)

    @field_validator("tags")
    @classmethod
    def normalize_optional_tags(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                tag = item.strip().lower()
                if tag and tag not in out:
                    out.append(tag)
        return out[:20]

    @field_validator("registration_url")
    @classmethod
    def validate_update_registration_url(cls, value: Optional[str]) -> Optional[str]:
        return validate_registration_url(value)


class EventOrganizerInfo(BaseModel):
    id: str
    full_name: str
    organization_name: Optional[str] = None


class EventResponse(BaseModel):
    id: str
    title: str
    description: str
    category: str
    tags: list[str] = Field(default_factory=list)
    venue: EventVenue
    mode: str = "In-person"
    start_date: datetime
    end_date: datetime
    registration_deadline: datetime
    max_capacity: int
    registered_count: int = 0
    spots_remaining: int
    registration_open: bool
    status: EventStatusLiteral
    price_type: PriceTypeLiteral = "free"
    price_amount: Optional[float] = None
    registration_url: Optional[str] = None
    is_free: bool = True
    cover_image_url: Optional[str] = None
    contact_email: Optional[str] = None
    organizer_id: str
    organizer_name: str
    organizer: EventOrganizerInfo
    is_registered: Optional[bool] = None
    my_registration: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class EventMutationResponse(BaseModel):
    message: str
    event: EventResponse
    notifications_sent: int = 0


class EventCancelResponse(BaseModel):
    message: str
    event: EventResponse
    notifications_sent: int = 0


class EventListResponse(BaseModel):
    events: list[EventResponse]
    total: int
    page: int
    limit: int


class CategoryEventListResponse(BaseModel):
    category: str
    category_display: str
    events: list[EventResponse]
    total: int
    page: int
    limit: int


class RecommendedEventItem(EventResponse):
    relevance_score: float
    match_reasons: list[str] = Field(default_factory=list)


class RecommendationListResponse(BaseModel):
    recommendations: list[RecommendedEventItem]
    total: int


def resolve_doc_price_type(event_doc: dict[str, Any]) -> PriceTypeLiteral:
    """Resolve price_type ('free' or 'paid') from an event document with legacy fallback."""
    raw_pt = event_doc.get("price_type")
    if isinstance(raw_pt, str) and raw_pt.strip().lower() in ("free", "paid"):
        return "free" if raw_pt.strip().lower() == "free" else "paid"
    if event_doc.get("is_free") is False:
        return "paid"
    raw_amount = event_doc.get("price_amount")
    if isinstance(raw_amount, (int, float)) and raw_amount > 0:
        return "paid"
    return "free"


def serialize_event(
    event_doc: dict[str, Any],
    *,
    is_registered: Optional[bool] = None,
    my_registration: Optional[dict[str, Any]] = None,
) -> EventResponse:
    """Convert a MongoDB event document into a complete EventResponse."""
    now = datetime.now(timezone.utc)
    start_date = ensure_utc_datetime(event_doc["start_date"])
    end_date = ensure_utc_datetime(event_doc.get("end_date") or start_date)
    deadline = ensure_utc_datetime(event_doc.get("registration_deadline") or start_date)
    max_capacity = int(event_doc.get("max_capacity", 100))
    registered_count = int(event_doc.get("registered_count", 0))
    spots_remaining = max(0, max_capacity - registered_count)
    status_val: EventStatusLiteral = event_doc.get("status", "draft")
    registration_open = bool(
        status_val == "published"
        and deadline > now
        and spots_remaining > 0
    )

    organizer_id_str = str(event_doc["organizer_id"])
    organizer_name = event_doc.get("organizer_name") or "Event Organizer"
    organizer_org = event_doc.get("organizer_organization")

    venue_raw = event_doc.get("venue") or {}
    venue_obj = EventVenue(**venue_raw)

    resolved_pt = resolve_doc_price_type(event_doc)
    raw_amount = event_doc.get("price_amount")
    resolved_amount = (
        round(float(raw_amount), 2)
        if resolved_pt == "paid" and isinstance(raw_amount, (int, float))
        else None
    )

    return EventResponse(
        id=str(event_doc["_id"]),
        title=event_doc["title"],
        description=event_doc["description"],
        category=event_doc["category"],
        tags=list(event_doc.get("tags") or []),
        venue=venue_obj,
        mode=event_doc.get("mode") or "In-person",
        start_date=start_date,
        end_date=end_date,
        registration_deadline=deadline,
        max_capacity=max_capacity,
        registered_count=registered_count,
        spots_remaining=spots_remaining,
        registration_open=registration_open,
        status=status_val,
        price_type=resolved_pt,
        price_amount=resolved_amount,
        registration_url=event_doc.get("registration_url"),
        is_free=(resolved_pt == "free"),
        cover_image_url=event_doc.get("cover_image_url"),
        contact_email=event_doc.get("contact_email"),
        organizer_id=organizer_id_str,
        organizer_name=organizer_name,
        organizer=EventOrganizerInfo(
            id=organizer_id_str,
            full_name=event_doc.get("organizer_full_name") or organizer_name,
            organization_name=organizer_org,
        ),
        is_registered=is_registered,
        my_registration=my_registration,
        created_at=ensure_utc_datetime(event_doc["created_at"]),
        updated_at=ensure_utc_datetime(event_doc.get("updated_at") or event_doc["created_at"]),
    )
