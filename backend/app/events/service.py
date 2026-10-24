import re
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.events.recommendations import rank_recommended_events
from app.events.schemas import (
    CATEGORY_DISPLAY_NAMES,
    CategoryEventListResponse,
    EventCancelResponse,
    EventCreateRequest,
    EventListResponse,
    EventMutationResponse,
    EventResponse,
    EventUpdateRequest,
    RecommendationListResponse,
    ensure_utc_datetime,
    normalize_category,
    resolve_doc_price_type,
    serialize_event,
    validate_and_normalize_pricing,
)


def _parse_event_object_id(event_id: str) -> ObjectId:
    try:
        return ObjectId(event_id)
    except (InvalidId, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        ) from exc


async def _get_owned_event_or_error(
    db: AsyncIOMotorDatabase,
    event_id: str,
    organizer_user: dict[str, Any],
) -> dict[str, Any]:
    event_oid = _parse_event_object_id(event_id)
    event_doc = await db["events"].find_one({"_id": event_oid})
    if not event_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    if event_doc.get("organizer_id") != organizer_user["_id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only manage your own events",
        )
    return event_doc


async def create_organizer_event(
    db: AsyncIOMotorDatabase,
    organizer_user: dict[str, Any],
    payload: EventCreateRequest,
) -> EventMutationResponse:
    now = datetime.now(timezone.utc)
    org_name = (
        organizer_user.get("organization_name")
        or organizer_user.get("full_name")
        or "Event Organizer"
    )
    event_doc: dict[str, Any] = {
        "title": payload.title,
        "description": payload.description,
        "category": payload.category,
        "tags": payload.tags,
        "organizer_id": organizer_user["_id"],
        "organizer_name": org_name,
        "organizer_full_name": organizer_user.get("full_name") or org_name,
        "organizer_organization": organizer_user.get("organization_name"),
        "venue": payload.venue.model_dump(exclude_none=True),
        "mode": payload.mode or "In-person",
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "registration_deadline": payload.registration_deadline,
        "max_capacity": payload.max_capacity,
        "registered_count": 0,
        "status": payload.status,
        "cover_image_url": payload.cover_image_url,
        "contact_email": payload.contact_email or organizer_user.get("email"),
        "price_type": payload.price_type or "free",
        "price_amount": payload.price_amount,
        "registration_url": payload.registration_url,
        "is_free": bool(payload.is_free if payload.is_free is not None else True),
        "created_at": now,
        "updated_at": now,
    }

    insert_res = await db["events"].insert_one(event_doc)
    event_doc["_id"] = insert_res.inserted_id
    return EventMutationResponse(
        message="Event created successfully",
        event=serialize_event(event_doc, is_registered=False),
        notifications_sent=0,
    )


async def list_organizer_events(
    db: AsyncIOMotorDatabase,
    organizer_user: dict[str, Any],
    *,
    status_filter: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> EventListResponse:
    query: dict[str, Any] = {"organizer_id": organizer_user["_id"]}
    if status_filter:
        cleaned_status = status_filter.strip().lower()
        if cleaned_status not in ("draft", "published", "cancelled"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid status filter. Allowed: draft, published, cancelled",
            )
        query["status"] = cleaned_status

    cursor = db["events"].find(query)
    docs = await cursor.to_list(length=1000)
    docs.sort(key=lambda d: ensure_utc_datetime(d["created_at"]), reverse=True)

    total = len(docs)
    start_idx = (page - 1) * limit
    paged_docs = docs[start_idx : start_idx + limit]

    return EventListResponse(
        events=[serialize_event(d, is_registered=False) for d in paged_docs],
        total=total,
        page=page,
        limit=limit,
    )


async def get_organizer_event_detail(
    db: AsyncIOMotorDatabase,
    organizer_user: dict[str, Any],
    event_id: str,
) -> EventResponse:
    event_doc = await _get_owned_event_or_error(db, event_id, organizer_user)
    return serialize_event(event_doc, is_registered=False)


async def update_organizer_event(
    db: AsyncIOMotorDatabase,
    organizer_user: dict[str, Any],
    event_id: str,
    payload: EventUpdateRequest,
) -> EventMutationResponse:
    event_doc = await _get_owned_event_or_error(db, event_id, organizer_user)

    if event_doc.get("status") == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot edit a cancelled event",
        )

    update_fields: dict[str, Any] = {}
    if payload.title is not None:
        update_fields["title"] = payload.title
    if payload.description is not None:
        update_fields["description"] = payload.description
    if payload.category is not None:
        update_fields["category"] = payload.category
    if payload.tags is not None:
        update_fields["tags"] = payload.tags
    if payload.venue is not None:
        update_fields["venue"] = payload.venue.model_dump(exclude_none=True)
    if payload.mode is not None:
        update_fields["mode"] = payload.mode
    if payload.cover_image_url is not None:
        update_fields["cover_image_url"] = payload.cover_image_url
    if payload.contact_email is not None:
        update_fields["contact_email"] = payload.contact_email
    if "registration_url" in payload.model_fields_set:
        update_fields["registration_url"] = payload.registration_url

    pricing_fields_touched = bool(
        {"price_type", "price_amount", "is_free"} & payload.model_fields_set
    )
    if pricing_fields_touched:
        existing_pt = resolve_doc_price_type(event_doc)
        existing_amount = event_doc.get("price_amount")

        candidate_pt: Optional[str] = (
            payload.price_type
            if "price_type" in payload.model_fields_set
            else (None if "is_free" in payload.model_fields_set else existing_pt)
        )
        candidate_is_free: Optional[bool] = (
            payload.is_free if "is_free" in payload.model_fields_set else None
        )

        switching_to_free = (
            (candidate_pt is not None and candidate_pt.strip().lower() == "free")
            or (candidate_pt is None and candidate_is_free is True)
        )

        if "price_amount" in payload.model_fields_set:
            candidate_amount = payload.price_amount
        elif switching_to_free:
            candidate_amount = None
        else:
            candidate_amount = existing_amount

        try:
            resolved_pt, resolved_amount, resolved_is_free = (
                validate_and_normalize_pricing(
                    candidate_pt,
                    candidate_amount,
                    candidate_is_free,
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

        update_fields["price_type"] = resolved_pt
        update_fields["price_amount"] = resolved_amount
        update_fields["is_free"] = resolved_is_free

    if payload.max_capacity is not None:
        current_registered = int(event_doc.get("registered_count", 0))
        if payload.max_capacity < current_registered:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"max_capacity cannot be less than current registered_count ({current_registered})",
            )
        update_fields["max_capacity"] = payload.max_capacity

    new_start = (
        ensure_utc_datetime(payload.start_date)
        if payload.start_date is not None
        else ensure_utc_datetime(event_doc["start_date"])
    )
    new_end = (
        ensure_utc_datetime(payload.end_date)
        if payload.end_date is not None
        else (
            ensure_utc_datetime(payload.start_date)
            if payload.start_date is not None
            and ensure_utc_datetime(event_doc.get("end_date") or event_doc["start_date"]) < new_start
            else ensure_utc_datetime(event_doc.get("end_date") or event_doc["start_date"])
        )
    )
    new_deadline = (
        ensure_utc_datetime(payload.registration_deadline)
        if payload.registration_deadline is not None
        else ensure_utc_datetime(event_doc.get("registration_deadline") or event_doc["start_date"])
    )

    if new_end < new_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="end_date must be greater than or equal to start_date",
        )
    if new_deadline > new_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="registration_deadline must be on or before start_date",
        )

    if payload.start_date is not None:
        update_fields["start_date"] = new_start
    if payload.end_date is not None or "start_date" in update_fields:
        update_fields["end_date"] = new_end
    if payload.registration_deadline is not None:
        update_fields["registration_deadline"] = new_deadline

    update_fields["updated_at"] = datetime.now(timezone.utc)

    updated_doc = await db["events"].find_one_and_update(
        {"_id": event_doc["_id"]},
        {"$set": update_fields},
        return_document=ReturnDocument.AFTER,
    )
    return EventMutationResponse(
        message="Event updated successfully",
        event=serialize_event(updated_doc, is_registered=False),
        notifications_sent=0,
    )


async def publish_organizer_event(
    db: AsyncIOMotorDatabase,
    organizer_user: dict[str, Any],
    event_id: str,
) -> EventMutationResponse:
    event_doc = await _get_owned_event_or_error(db, event_id, organizer_user)
    current_status = event_doc.get("status")
    if current_status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot publish a cancelled event",
        )
    if current_status == "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event is already published",
        )

    now = datetime.now(timezone.utc)
    updated_doc = await db["events"].find_one_and_update(
        {"_id": event_doc["_id"]},
        {"$set": {"status": "published", "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    return EventMutationResponse(
        message="Event published successfully",
        event=serialize_event(updated_doc, is_registered=False),
        notifications_sent=0,
    )


async def cancel_organizer_event(
    db: AsyncIOMotorDatabase,
    organizer_user: dict[str, Any],
    event_id: str,
) -> EventCancelResponse:
    event_doc = await _get_owned_event_or_error(db, event_id, organizer_user)
    if event_doc.get("status") == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event is already cancelled",
        )

    now = datetime.now(timezone.utc)
    updated_doc = await db["events"].find_one_and_update(
        {"_id": event_doc["_id"]},
        {"$set": {"status": "cancelled", "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    return EventCancelResponse(
        message="Event cancelled successfully",
        event=serialize_event(updated_doc, is_registered=False),
        notifications_sent=0,
    )


def _matches_public_filters(
    doc: dict[str, Any],
    *,
    category: Optional[str] = None,
    city: Optional[str] = None,
    price_type: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> bool:
    if doc.get("status") != "published":
        return False

    if category:
        if doc.get("category") != category:
            return False

    if price_type:
        if resolve_doc_price_type(doc) != price_type:
            return False

    if city:
        venue = doc.get("venue") or {}
        venue_city = str(venue.get("city") or "").strip().lower()
        if venue_city != city.strip().lower():
            return False

    start_dt = ensure_utc_datetime(doc["start_date"])
    if date_from is not None and start_dt < ensure_utc_datetime(date_from):
        return False
    if date_to is not None and start_dt > ensure_utc_datetime(date_to):
        return False

    if search:
        q = search.strip().lower()
        venue = doc.get("venue") or {}
        haystack = " ".join(
            [
                str(doc.get("title") or ""),
                str(doc.get("description") or ""),
                str(doc.get("category") or ""),
                " ".join(str(t) for t in (doc.get("tags") or [])),
                str(venue.get("name") or ""),
                str(venue.get("city") or ""),
                str(doc.get("organizer_name") or ""),
            ]
        ).lower()
        if q not in haystack:
            return False

    return True


async def list_public_events(
    db: AsyncIOMotorDatabase,
    *,
    category: Optional[str] = None,
    city: Optional[str] = None,
    price_type: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort: str = "date_asc",
    page: int = 1,
    limit: int = 20,
) -> EventListResponse:
    normalized_cat: Optional[str] = None
    if category and category.strip().lower() != "all":
        try:
            normalized_cat = normalize_category(category)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    normalized_pt: Optional[str] = None
    if price_type and price_type.strip().lower() != "all":
        cleaned_pt = price_type.strip().lower()
        if cleaned_pt not in ("free", "paid"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid price_type filter. Allowed values: free, paid",
            )
        normalized_pt = cleaned_pt

    cursor = db["events"].find({"status": "published"})
    raw_docs = await cursor.to_list(length=1000)

    filtered = [
        doc
        for doc in raw_docs
        if _matches_public_filters(
            doc,
            category=normalized_cat,
            city=city,
            price_type=normalized_pt,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
    ]

    if sort == "date_desc":
        filtered.sort(key=lambda d: ensure_utc_datetime(d["start_date"]), reverse=True)
    elif sort == "popularity":
        filtered.sort(
            key=lambda d: (
                -int(d.get("registered_count", 0)),
                ensure_utc_datetime(d["start_date"]),
            )
        )
    else:
        filtered.sort(key=lambda d: ensure_utc_datetime(d["start_date"]))

    total = len(filtered)
    start_idx = (page - 1) * limit
    paged = filtered[start_idx : start_idx + limit]

    return EventListResponse(
        events=[serialize_event(d, is_registered=None) for d in paged],
        total=total,
        page=page,
        limit=limit,
    )


async def list_events_by_category(
    db: AsyncIOMotorDatabase,
    category: str,
    *,
    city: Optional[str] = None,
    price_type: Optional[str] = None,
    sort: str = "date_asc",
    page: int = 1,
    limit: int = 20,
) -> CategoryEventListResponse:
    try:
        normalized_cat = normalize_category(category)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    list_res = await list_public_events(
        db,
        category=normalized_cat,
        city=city,
        price_type=price_type,
        sort=sort,
        page=page,
        limit=limit,
    )
    display_name = CATEGORY_DISPLAY_NAMES.get(
        normalized_cat,
        normalized_cat.replace("_", " ").title(),
    )
    return CategoryEventListResponse(
        category=normalized_cat,
        category_display=display_name,
        events=list_res.events,
        total=list_res.total,
        page=list_res.page,
        limit=list_res.limit,
    )


async def get_event_details(
    db: AsyncIOMotorDatabase,
    event_id: str,
    current_user: Optional[dict[str, Any]] = None,
) -> EventResponse:
    event_oid = _parse_event_object_id(event_id)
    event_doc = await db["events"].find_one({"_id": event_oid})
    if not event_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    event_status = event_doc.get("status")
    is_owner = bool(
        current_user
        and current_user.get("role") == "organizer"
        and event_doc.get("organizer_id") == current_user.get("_id")
    )

    if event_status != "published" and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    is_reg = False if current_user is not None else None
    return serialize_event(event_doc, is_registered=is_reg)


async def get_participant_recommendations(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    *,
    limit: int = 10,
) -> RecommendationListResponse:
    if not participant_user.get("onboarding_completed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please complete participant onboarding (interests and city) before requesting recommendations",
        )

    cursor = db["events"].find({"status": "published"})
    published_docs = await cursor.to_list(length=1000)
    ranked = rank_recommended_events(published_docs, participant_user, limit=limit)
    return RecommendationListResponse(
        recommendations=ranked,
        total=len(ranked),
    )
