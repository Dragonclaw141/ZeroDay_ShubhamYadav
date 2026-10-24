from datetime import datetime
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.dependencies import require_organizer, require_participant
from app.core.security import decode_access_token
from app.events.schemas import (
    CategoryEventListResponse,
    EventCancelResponse,
    EventCreateRequest,
    EventListResponse,
    EventMutationResponse,
    EventResponse,
    EventUpdateRequest,
    RecommendationListResponse,
)
from app.events.service import (
    cancel_organizer_event,
    create_organizer_event,
    get_event_details,
    get_organizer_event_detail,
    get_participant_recommendations,
    list_events_by_category,
    list_organizer_events,
    list_public_events,
    publish_organizer_event,
    update_organizer_event,
)

optional_bearer = HTTPBearer(auto_error=False)


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> Optional[dict[str, Any]]:
    """Optionally resolve the authenticated user if a valid Bearer token is present."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        user_oid = ObjectId(payload.get("sub"))
    except (JWTError, InvalidId, TypeError, ValueError):
        return None
    user = await db["users"].find_one({"_id": user_oid})
    if not user or not user.get("is_active", True):
        return None
    return user


router = APIRouter(tags=["Events"])


# ==================== Public & Participant Event Discovery ====================

@router.get(
    "/api/events",
    response_model=EventListResponse,
    status_code=status.HTTP_200_OK,
    summary="List published events with optional search, category, city, price_type, and date filters",
)
async def get_published_events(
    category: Optional[str] = Query(default=None, description="Filter by category slug or label"),
    city: Optional[str] = Query(default=None, description="Filter by venue city"),
    price_type: Optional[str] = Query(default=None, description="Filter by price type: free or paid"),
    search: Optional[str] = Query(default=None, description="Keyword search across title, description, tags, and venue"),
    date_from: Optional[datetime] = Query(default=None, description="Events starting on or after this ISO datetime"),
    date_to: Optional[datetime] = Query(default=None, description="Events starting on or before this ISO datetime"),
    sort: str = Query(default="date_asc", pattern="^(date_asc|date_desc|popularity)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EventListResponse:
    return await list_public_events(
        db,
        category=category,
        city=city,
        price_type=price_type,
        search=search,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        page=page,
        limit=limit,
    )


@router.get(
    "/api/events/recommendations",
    response_model=RecommendationListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get personalized event recommendations for an onboarded participant",
)
async def get_recommendations(
    limit: int = Query(default=10, ge=1, le=50),
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RecommendationListResponse:
    return await get_participant_recommendations(db, current_user, limit=limit)


@router.get(
    "/api/events/categories/{category}",
    response_model=CategoryEventListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get published events for a specific category card drill-down",
)
async def get_category_events(
    category: str,
    city: Optional[str] = Query(default=None, description="Filter by venue city"),
    price_type: Optional[str] = Query(default=None, description="Filter by price type: free or paid"),
    sort: str = Query(default="date_asc", pattern="^(date_asc|date_desc|popularity)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> CategoryEventListResponse:
    return await list_events_by_category(
        db,
        category,
        city=city,
        price_type=price_type,
        sort=sort,
        page=page,
        limit=limit,
    )


@router.get(
    "/api/events/{event_id}",
    response_model=EventResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full details of a published event (or own draft for the organizer)",
)
async def get_single_event(
    event_id: str,
    current_user: Optional[dict[str, Any]] = Depends(get_optional_current_user),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EventResponse:
    return await get_event_details(db, event_id, current_user=current_user)


# ==================== Organizer Event Management ====================

@router.post(
    "/api/organizer/events",
    response_model=EventMutationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new event (as draft or published)",
)
async def create_event(
    payload: EventCreateRequest,
    current_user: dict[str, Any] = Depends(require_organizer),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EventMutationResponse:
    return await create_organizer_event(db, current_user, payload)


@router.get(
    "/api/organizer/events",
    response_model=EventListResponse,
    status_code=status.HTTP_200_OK,
    summary="List events belonging to the authenticated organizer",
)
async def get_my_organizer_events(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: dict[str, Any] = Depends(require_organizer),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EventListResponse:
    return await list_organizer_events(
        db,
        current_user,
        status_filter=status_filter,
        page=page,
        limit=limit,
    )


@router.get(
    "/api/organizer/events/{event_id}",
    response_model=EventResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full details and stats for an event owned by the authenticated organizer",
)
async def get_my_organizer_event_by_id(
    event_id: str,
    current_user: dict[str, Any] = Depends(require_organizer),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EventResponse:
    return await get_organizer_event_detail(db, current_user, event_id)


@router.put(
    "/api/organizer/events/{event_id}",
    response_model=EventMutationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an event owned by the authenticated organizer",
)
async def update_event(
    event_id: str,
    payload: EventUpdateRequest,
    current_user: dict[str, Any] = Depends(require_organizer),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EventMutationResponse:
    return await update_organizer_event(db, current_user, event_id, payload)


@router.patch(
    "/api/organizer/events/{event_id}/publish",
    response_model=EventMutationResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish a draft event owned by the authenticated organizer",
)
async def publish_event(
    event_id: str,
    current_user: dict[str, Any] = Depends(require_organizer),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EventMutationResponse:
    return await publish_organizer_event(db, current_user, event_id)


@router.patch(
    "/api/organizer/events/{event_id}/cancel",
    response_model=EventCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an event owned by the authenticated organizer",
)
async def cancel_event(
    event_id: str,
    current_user: dict[str, Any] = Depends(require_organizer),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> EventCancelResponse:
    return await cancel_organizer_event(db, current_user, event_id)
