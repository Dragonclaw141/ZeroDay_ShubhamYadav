import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import httpx
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.events.schemas import (
    EventVenue,
    ensure_utc_datetime,
    resolve_doc_price_type,
)
from app.notifications.service import (
    schedule_registration_notifications,
    suppress_notifications_for_event,
    suppress_notifications_for_registration,
)
from app.registrations.schemas import (
    BookingEventSummary,
    PaymentAttemptResponse,
    PaymentFailureReportRequest,
    PaymentReconcileRequest,
    PaymentVerifyRequest,
    RazorpayCheckoutConfig,
    RegistrationCancelRequest,
    RegistrationListResponse,
    RegistrationMutationResponse,
    RegistrationResponse,
    booking_status_label,
)

logger = logging.getLogger(__name__)

RESERVATION_TTL_MINUTES = 15

# Optional test hook for simulating Razorpay API order/payment state during verification & reconciliation:
# signature: hook(order_id: str, payment_id: Optional[str], expected_amount_paise: int) -> dict[str, Any]
_razorpay_provider_hook: Optional[
    Callable[[str, Optional[str], int], Optional[dict[str, Any]]]
] = None


def set_razorpay_provider_hook(
    hook: Optional[Callable[[str, Optional[str], int], Optional[dict[str, Any]]]],
) -> None:
    """Configure or clear a test hook for Razorpay server-side payment reconciliation."""
    global _razorpay_provider_hook
    _razorpay_provider_hook = hook


def is_local_razorpay_sandbox() -> bool:
    key_id = (settings.RAZORPAY_KEY_ID or "").strip()
    return not key_id or key_id.startswith("rzp_test_local")


def compute_razorpay_signature(order_id: str, payment_id: str) -> str:
    """Compute the standard Razorpay HMAC-SHA256 checkout signature."""
    secret = (settings.RAZORPAY_KEY_SECRET or "rzp_test_secret_local_eventadda").encode(
        "utf-8"
    )
    payload = f"{order_id}|{payment_id}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def verify_razorpay_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify a Razorpay checkout signature in constant time."""
    if not order_id or not payment_id or not signature:
        return False
    expected = compute_razorpay_signature(order_id, payment_id)
    return hmac.compare_digest(expected, signature.strip())


def _parse_object_id(raw_id: str, not_found_detail: str) -> ObjectId:
    try:
        return ObjectId(raw_id)
    except (InvalidId, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        ) from exc


def serialize_payment_attempt(doc: dict[str, Any]) -> PaymentAttemptResponse:
    created = ensure_utc_datetime(doc["created_at"])
    amount_val = round(float(doc.get("amount", 0.0)), 2)
    amount_paise = int(doc.get("amount_paise", round(amount_val * 100)))
    return PaymentAttemptResponse(
        id=str(doc["_id"]),
        registration_id=str(doc["registration_id"]),
        event_id=str(doc["event_id"]),
        participant_id=str(doc["participant_id"]),
        attempt_number=int(doc.get("attempt_number", 1)),
        amount=amount_val,
        amount_paise=amount_paise,
        currency=doc.get("currency", "INR"),
        razorpay_order_id=doc["razorpay_order_id"],
        razorpay_payment_id=doc.get("razorpay_payment_id"),
        status=doc["status"],
        failure_reason=doc.get("failure_reason"),
        verified_at=(
            ensure_utc_datetime(doc["verified_at"])
            if doc.get("verified_at") is not None
            else None
        ),
        reconciled_at=(
            ensure_utc_datetime(doc["reconciled_at"])
            if doc.get("reconciled_at") is not None
            else None
        ),
        created_at=created,
        updated_at=ensure_utc_datetime(doc.get("updated_at") or created),
    )


def _build_event_summary(event_doc: Optional[dict[str, Any]]) -> Optional[BookingEventSummary]:
    if not event_doc:
        return None
    start_dt = ensure_utc_datetime(event_doc["start_date"])
    end_dt = ensure_utc_datetime(event_doc.get("end_date") or start_dt)
    deadline_dt = ensure_utc_datetime(event_doc.get("registration_deadline") or start_dt)
    pt = resolve_doc_price_type(event_doc)
    raw_amt = event_doc.get("price_amount")
    amt = round(float(raw_amt), 2) if pt == "paid" and isinstance(raw_amt, (int, float)) else None
    venue_raw = event_doc.get("venue") or {"name": "TBD", "city": "Online"}
    return BookingEventSummary(
        id=str(event_doc["_id"]),
        title=event_doc.get("title", "Event"),
        category=event_doc.get("category", "hackathons"),
        venue=EventVenue(**venue_raw),
        mode=event_doc.get("mode") or "In-person",
        start_date=start_dt,
        end_date=end_dt,
        registration_deadline=deadline_dt,
        status=event_doc.get("status", "published"),
        organizer_name=event_doc.get("organizer_name") or "Event Organizer",
        price_type=pt,
        price_amount=amt,
    )


async def serialize_registration(
    db: AsyncIOMotorDatabase,
    reg_doc: dict[str, Any],
    *,
    event_doc: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> RegistrationResponse:
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    if event_doc is None:
        event_doc = await db["events"].find_one({"_id": reg_doc["event_id"]})

    pay_cursor = db["payments"].find({"registration_id": reg_doc["_id"]})
    pay_docs = await pay_cursor.to_list(length=50)
    pay_docs.sort(key=lambda d: int(d.get("attempt_number", 0)))
    latest_pay_doc = pay_docs[-1] if pay_docs else None

    reg_status = reg_doc["status"]
    event_status = event_doc.get("status") if event_doc else "published"
    deadline = (
        ensure_utc_datetime(event_doc.get("registration_deadline") or event_doc["start_date"])
        if event_doc
        else current_now
    )
    expires_at = (
        ensure_utc_datetime(reg_doc["reservation_expires_at"])
        if reg_doc.get("reservation_expires_at") is not None
        else None
    )

    has_ambiguous_payment = any(p.get("status") == "pending" for p in pay_docs)
    can_cancel = bool(
        reg_status in ("confirmed", "pending_payment")
        and event_status == "published"
        and deadline > current_now
        and not has_ambiguous_payment
    )
    can_retry_payment = bool(
        reg_status == "pending_payment"
        and event_status == "published"
        and expires_at is not None
        and expires_at > current_now
        and not has_ambiguous_payment
    )

    created = ensure_utc_datetime(reg_doc["created_at"])
    return RegistrationResponse(
        id=str(reg_doc["_id"]),
        participant_id=str(reg_doc["participant_id"]),
        event_id=str(reg_doc["event_id"]),
        status=reg_status,
        status_label=booking_status_label(reg_status),
        seat_held=bool(reg_doc.get("seat_held", False)),
        price_type=reg_doc.get("price_type", "free"),
        price_amount=round(float(reg_doc.get("price_amount") or 0.0), 2),
        currency=reg_doc.get("currency", "INR"),
        reservation_expires_at=expires_at,
        confirmed_at=(
            ensure_utc_datetime(reg_doc["confirmed_at"])
            if reg_doc.get("confirmed_at") is not None
            else None
        ),
        cancelled_at=(
            ensure_utc_datetime(reg_doc["cancelled_at"])
            if reg_doc.get("cancelled_at") is not None
            else None
        ),
        cancellation_reason=reg_doc.get("cancellation_reason"),
        resolution_reason=reg_doc.get("resolution_reason"),
        can_cancel=can_cancel,
        can_retry_payment=can_retry_payment,
        event=_build_event_summary(event_doc),
        latest_payment=(
            serialize_payment_attempt(latest_pay_doc) if latest_pay_doc else None
        ),
        payment_attempts_count=len(pay_docs),
        created_at=created,
        updated_at=ensure_utc_datetime(reg_doc.get("updated_at") or created),
    )


async def _release_event_seat(
    db: AsyncIOMotorDatabase,
    event_oid: ObjectId,
    current_now: datetime,
) -> None:
    """Atomically decrement registered_count on an event document, floored at 0."""
    await db["events"].find_one_and_update(
        {"_id": event_oid, "registered_count": {"$gt": 0}},
        {
            "$inc": {"registered_count": -1},
            "$set": {"updated_at": current_now},
        },
        return_document=ReturnDocument.AFTER,
    )


async def expire_stale_reservations(
    db: AsyncIOMotorDatabase,
    *,
    event_id: Optional[ObjectId] = None,
    participant_id: Optional[ObjectId] = None,
    now: Optional[datetime] = None,
) -> int:
    """Safely expire overdue 15m pending_payment reservations and release their held seats.

    Rule: Never expire or release a seat if any payment attempt on the booking is in 'pending'
    (ambiguous) or 'succeeded' state without reconciliation.
    """
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    query: dict[str, Any] = {
        "status": "pending_payment",
        "reservation_expires_at": {"$lte": current_now},
    }
    if event_id is not None:
        query["event_id"] = event_id
    if participant_id is not None:
        query["participant_id"] = participant_id

    cursor = db["registrations"].find(query)
    overdue_docs = await cursor.to_list(length=500)
    expired_count = 0

    for reg_doc in overdue_docs:
        reg_id = reg_doc["_id"]
        pay_cursor = db["payments"].find({"registration_id": reg_id})
        pay_docs = await pay_cursor.to_list(length=50)

        # Do not unsafely release a seat if a payment attempt is ambiguous ('pending') or 'succeeded'
        if any(p.get("status") in ("pending", "succeeded") for p in pay_docs):
            continue

        transitioned = await db["registrations"].find_one_and_update(
            {
                "_id": reg_id,
                "status": "pending_payment",
                "seat_held": True,
            },
            {
                "$set": {
                    "status": "expired",
                    "seat_held": False,
                    "updated_at": current_now,
                },
                "$unset": {"active_slot_key": ""},
            },
            return_document=ReturnDocument.AFTER,
        )
        if transitioned is not None:
            await _release_event_seat(db, reg_doc["event_id"], current_now)
            expired_count += 1

    return expired_count


async def _try_allocate_event_seat(
    db: AsyncIOMotorDatabase,
    event_oid: ObjectId,
    current_now: datetime,
    *,
    enforce_deadline: bool = True,
) -> Optional[dict[str, Any]]:
    """Atomically allocate 1 seat on a published event if registered_count < max_capacity."""
    query: dict[str, Any] = {
        "_id": event_oid,
        "status": "published",
        "$expr": {"$lt": ["$registered_count", "$max_capacity"]},
    }
    if enforce_deadline:
        query["registration_deadline"] = {"$gt": current_now}

    allocated = await db["events"].find_one_and_update(
        query,
        {
            "$inc": {"registered_count": 1},
            "$set": {"updated_at": current_now},
        },
        return_document=ReturnDocument.AFTER,
    )
    return allocated


async def _diagnose_allocation_failure(
    db: AsyncIOMotorDatabase,
    event_oid: ObjectId,
    current_now: datetime,
) -> HTTPException:
    event_doc = await db["events"].find_one({"_id": event_oid})
    if not event_doc:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    ev_status = event_doc.get("status")
    if ev_status != "published":
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Event is not open for registration (current status: {ev_status})",
        )
    deadline = ensure_utc_datetime(
        event_doc.get("registration_deadline") or event_doc["start_date"]
    )
    if deadline <= current_now:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Registration deadline for this event has passed",
        )
    reg_count = int(event_doc.get("registered_count", 0))
    max_cap = int(event_doc.get("max_capacity", 100))
    if reg_count >= max_cap:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event is sold out. No seats remaining.",
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Could not allocate a seat for this event.",
    )


async def _create_razorpay_order(
    *,
    registration_id: ObjectId,
    attempt_number: int,
    amount_paise: int,
    currency: str = "INR",
) -> str:
    """Create a Razorpay Test Mode order ID via API or deterministic local test sandbox."""
    receipt = f"rcpt_{str(registration_id)[-10:]}_{attempt_number}"
    if not is_local_razorpay_sandbox():
        secret = (settings.RAZORPAY_KEY_SECRET or "").strip()
        if not secret or secret == "rzp_test_secret_local_eventadda":
            logger.error(
                "Razorpay API secret is missing or using default local secret in live/test mode"
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Razorpay API credentials misconfigured on server",
            )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{settings.RAZORPAY_API_BASE_URL.rstrip('/')}/orders",
                    auth=(settings.RAZORPAY_KEY_ID, secret),
                    json={
                        "amount": amount_paise,
                        "currency": currency,
                        "receipt": receipt,
                        "notes": {
                            "registration_id": str(registration_id),
                            "attempt_number": str(attempt_number),
                        },
                    },
                )
            if resp.status_code in (200, 201):
                data = resp.json()
                if data.get("id"):
                    return str(data["id"])
            if resp.status_code == 401:
                logger.warning("Razorpay Orders API authentication failed (HTTP 401)")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Payment gateway authentication failed. Please verify Razorpay credentials.",
                )
            logger.warning(
                "Razorpay Orders API returned HTTP %s: %s",
                resp.status_code,
                resp.text[:200],
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not create Razorpay payment order with payment gateway",
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Razorpay order creation network error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payment gateway is temporarily unreachable",
            ) from exc

    token_hex = secrets.token_hex(6)
    return f"order_test_{str(registration_id)[-6:]}_{attempt_number}_{token_hex}"


def _build_checkout_config(
    *,
    order_id: str,
    amount_inr: float,
    amount_paise: int,
    event_doc: dict[str, Any],
    reg_doc: dict[str, Any],
    user_doc: dict[str, Any],
) -> RazorpayCheckoutConfig:
    sandbox = is_local_razorpay_sandbox()
    sample_pay_id = f"pay_test_{order_id[-10:]}" if sandbox else None
    local_sig = compute_razorpay_signature(order_id, sample_pay_id) if sandbox else None
    return RazorpayCheckoutConfig(
        key_id=settings.RAZORPAY_KEY_ID or "rzp_test_local_eventadda",
        order_id=order_id,
        amount_paise=amount_paise,
        amount_inr=amount_inr,
        currency=reg_doc.get("currency", "INR"),
        event_id=str(event_doc["_id"]),
        event_title=event_doc.get("title", "Event"),
        registration_id=str(reg_doc["_id"]),
        participant_name=user_doc.get("full_name", "Participant"),
        participant_email=user_doc.get("email", ""),
        participant_phone=user_doc.get("phone", ""),
        test_mode=True,
        sandbox_mode=sandbox,
        local_test_payment_id=sample_pay_id,
        local_test_signature_Token=local_sig,
    )


async def _create_payment_attempt_for_registration(
    db: AsyncIOMotorDatabase,
    reg_doc: dict[str, Any],
    event_doc: dict[str, Any],
    user_doc: dict[str, Any],
    current_now: datetime,
) -> tuple[dict[str, Any], RazorpayCheckoutConfig]:
    """Create or reuse an active 'created' payment attempt for a pending_payment registration."""
    pay_cursor = db["payments"].find({"registration_id": reg_doc["_id"]})
    existing_attempts = await pay_cursor.to_list(length=50)
    existing_attempts.sort(key=lambda d: int(d.get("attempt_number", 0)))

    # If any attempt is 'pending' (ambiguous), block starting a new attempt until reconciled
    if any(p.get("status") == "pending" for p in existing_attempts):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A payment attempt is currently pending verification. Please reconcile payment status before starting another attempt.",
        )

    # If the latest attempt is still 'created' (unused order), reuse it for interrupted checkout recovery
    if existing_attempts and existing_attempts[-1].get("status") == "created":
        latest = existing_attempts[-1]
        checkout = _build_checkout_config(
            order_id=latest["razorpay_order_id"],
            amount_inr=round(float(latest["amount"]), 2),
            amount_paise=int(latest["amount_paise"]),
            event_doc=event_doc,
            reg_doc=reg_doc,
            user_doc=user_doc,
        )
        return latest, checkout

    next_attempt_num = (
        int(existing_attempts[-1]["attempt_number"]) + 1 if existing_attempts else 1
    )
    amount_inr = round(float(reg_doc["price_amount"]), 2)
    amount_paise = int(round(amount_inr * 100))
    currency = reg_doc.get("currency", "INR")

    order_id = await _create_razorpay_order(
        registration_id=reg_doc["_id"],
        attempt_number=next_attempt_num,
        amount_paise=amount_paise,
        currency=currency,
    )

    attempt_doc: dict[str, Any] = {
        "registration_id": reg_doc["_id"],
        "event_id": reg_doc["event_id"],
        "participant_id": reg_doc["participant_id"],
        "attempt_number": next_attempt_num,
        "amount": amount_inr,
        "amount_paise": amount_paise,
        "currency": currency,
        "razorpay_order_id": order_id,
        "gateway_mode": "local_sandbox" if is_local_razorpay_sandbox() else "razorpay_test",
        "status": "created",
        "failure_reason": None,
        "verified_at": None,
        "reconciled_at": None,
        "created_at": current_now,
        "updated_at": current_now,
    }
    res = await db["payments"].insert_one(attempt_doc)
    attempt_doc["_id"] = res.inserted_id

    checkout = _build_checkout_config(
        order_id=order_id,
        amount_inr=amount_inr,
        amount_paise=amount_paise,
        event_doc=event_doc,
        reg_doc=reg_doc,
        user_doc=user_doc,
    )
    return attempt_doc, checkout


async def create_or_recover_registration(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    event_id: str,
    *,
    now: Optional[datetime] = None,
) -> tuple[RegistrationMutationResponse, int]:
    """Create a booking (confirming immediately for free events or reserving a seat for 15m for paid events),
    or recover an existing pending_payment booking without creating duplicates.
    """
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    event_oid = _parse_object_id(event_id, "Event not found")
    participant_oid = participant_user["_id"]

    # 1. Reclaim any expired 15m seat holds on this event before checking active bookings or capacity
    await expire_stale_reservations(db, event_id=event_oid, now=current_now)

    active_slot_key = f"{participant_oid}:{event_oid}"
    existing = await db["registrations"].find_one({"active_slot_key": active_slot_key})
    if existing:
        ex_status = existing.get("status")
        if ex_status == "confirmed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have a confirmed booking for this event",
            )
        if ex_status == "resolution_required":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have a booking for this event awaiting payment resolution",
            )
        if ex_status == "pending_payment":
            event_doc = await db["events"].find_one({"_id": event_oid})
            if not event_doc or event_doc.get("status") != "published":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Event is no longer available for checkout",
                )
            attempt_doc, checkout = await _create_payment_attempt_for_registration(
                db, existing, event_doc, participant_user, current_now
            )
            serialized_reg = await serialize_registration(
                db, existing, event_doc=event_doc, now=current_now
            )
            return (
                RegistrationMutationResponse(
                    message="Resumed your active seat reservation. Complete payment to confirm your booking.",
                    booking_status="pending_payment",
                    payment_status=attempt_doc["status"],
                    recovered_existing=True,
                    registration=serialized_reg,
                    payment_attempt=serialize_payment_attempt(attempt_doc),
                    razorpay_checkout=checkout,
                ),
                status.HTTP_200_OK,
            )

    # 2. Atomically allocate 1 seat on the published event
    allocated_event = await _try_allocate_event_seat(
        db, event_oid, current_now, enforce_deadline=True
    )
    if allocated_event is None:
        raise await _diagnose_allocation_failure(db, event_oid, current_now)

    # 3. Derive price strictly from the database event document (never from client input)
    price_type = resolve_doc_price_type(allocated_event)
    raw_price = allocated_event.get("price_amount")
    price_amount = (
        round(float(raw_price), 2)
        if price_type == "paid" and isinstance(raw_price, (int, float))
        else 0.0
    )

    is_free_event = price_type == "free" or price_amount <= 0
    initial_status = "confirmed" if is_free_event else "pending_payment"
    reservation_expires_at = (
        None
        if is_free_event
        else current_now + timedelta(minutes=RESERVATION_TTL_MINUTES)
    )
    confirmed_at = current_now if is_free_event else None

    reg_doc: dict[str, Any] = {
        "participant_id": participant_oid,
        "event_id": event_oid,
        "active_slot_key": active_slot_key,
        "status": initial_status,
        "seat_held": True,
        "price_type": "free" if is_free_event else "paid",
        "price_amount": 0.0 if is_free_event else price_amount,
        "currency": "INR",
        "reservation_expires_at": reservation_expires_at,
        "confirmed_at": confirmed_at,
        "cancelled_at": None,
        "cancellation_reason": None,
        "resolution_reason": None,
        "created_at": current_now,
        "updated_at": current_now,
    }

    try:
        insert_res = await db["registrations"].insert_one(reg_doc)
        reg_doc["_id"] = insert_res.inserted_id
    except DuplicateKeyError as exc:
        # Roll back the allocated seat immediately if a concurrent request for the same user/event won the race
        await _release_event_seat(db, event_oid, current_now)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active booking or reservation for this event",
        ) from exc

    if is_free_event:
        await schedule_registration_notifications(
            db, reg_doc, allocated_event, participant_user, now=current_now
        )
        serialized_reg = await serialize_registration(
            db, reg_doc, event_doc=allocated_event, now=current_now
        )
        return (
            RegistrationMutationResponse(
                message="Booking confirmed! A confirmation email and 24-hour reminder have been scheduled.",
                booking_status="confirmed",
                payment_status=None,
                recovered_existing=False,
                registration=serialized_reg,
                payment_attempt=None,
                razorpay_checkout=None,
            ),
            status.HTTP_201_CREATED,
        )

    # Paid event: create Attempt #1 and Razorpay Test Mode order
    attempt_doc, checkout = await _create_payment_attempt_for_registration(
        db, reg_doc, allocated_event, participant_user, current_now
    )
    serialized_reg = await serialize_registration(
        db, reg_doc, event_doc=allocated_event, now=current_now
    )
    return (
        RegistrationMutationResponse(
            message="Seat reserved for 15 minutes. Complete Razorpay Test Mode payment to confirm your booking.",
            booking_status="pending_payment",
            payment_status=attempt_doc["status"],
            recovered_existing=False,
            registration=serialized_reg,
            payment_attempt=serialize_payment_attempt(attempt_doc),
            razorpay_checkout=checkout,
        ),
        status.HTTP_201_CREATED,
    )


async def create_payment_order_for_booking(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    registration_id: str,
    *,
    now: Optional[datetime] = None,
) -> RegistrationMutationResponse:
    """Create a new payment attempt (or reuse an unused order) for an existing pending_payment booking."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    reg_oid = _parse_object_id(registration_id, "Registration not found")

    await expire_stale_reservations(
        db, participant_id=participant_user["_id"], now=current_now
    )

    reg_doc = await db["registrations"].find_one({"_id": reg_oid})
    if not reg_doc or reg_doc.get("participant_id") != participant_user["_id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    event_doc = await db["events"].find_one({"_id": reg_doc["event_id"]})
    if not event_doc or event_doc.get("status") != "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot initiate payment because the event is no longer published",
        )

    reg_status = reg_doc.get("status")
    if reg_status == "confirmed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This booking is already confirmed",
        )
    if reg_status == "expired":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your 15-minute seat reservation has expired. Please start a new booking if seats remain.",
        )
    if reg_status != "pending_payment":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot start payment for booking in '{reg_status}' state",
        )

    # Mark any previous 'created' attempt as 'failed' (abandoned) if the user explicitly requests a fresh retry order
    pay_cursor = db["payments"].find({"registration_id": reg_oid})
    existing_attempts = await pay_cursor.to_list(length=50)
    existing_attempts.sort(key=lambda d: int(d.get("attempt_number", 0)))

    if any(p.get("status") == "pending" for p in existing_attempts):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An existing payment attempt is awaiting reconciliation. Reconcile status before creating a new order.",
        )

    if existing_attempts and existing_attempts[-1].get("status") == "created":
        await db["payments"].update_one(
            {"_id": existing_attempts[-1]["_id"], "status": "created"},
            {
                "$set": {
                    "status": "failed",
                    "failure_reason": "Superseded by a new payment attempt",
                    "updated_at": current_now,
                }
            },
        )

    attempt_doc, checkout = await _create_payment_attempt_for_registration(
        db, reg_doc, event_doc, participant_user, current_now
    )
    serialized_reg = await serialize_registration(
        db, reg_doc, event_doc=event_doc, now=current_now
    )
    return RegistrationMutationResponse(
        message=f"Payment order created (Attempt #{attempt_doc['attempt_number']}).",
        booking_status=reg_doc["status"],
        payment_status=attempt_doc["status"],
        recovered_existing=False,
        registration=serialized_reg,
        payment_attempt=serialize_payment_attempt(attempt_doc),
        razorpay_checkout=checkout,
    )


async def _inspect_authoritative_payment_status(
    *,
    order_id: str,
    payment_id: Optional[str],
    expected_amount_paise: int,
    signature_verified: bool,
) -> dict[str, Any]:
    """Query the authoritative payment status from the test hook, Razorpay API, or local sandbox."""
    if _razorpay_provider_hook is not None:
        hook_res = _razorpay_provider_hook(order_id, payment_id, expected_amount_paise)
        if hook_res is not None:
            return hook_res

    if not is_local_razorpay_sandbox():
        secret = (settings.RAZORPAY_KEY_SECRET or "").strip()
        if not secret or secret == "rzp_test_secret_local_eventadda":
            return {
                "outcome": "ambiguous",
                "payment_id": payment_id,
                "reason": "Razorpay API credentials misconfigured on server",
            }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if payment_id:
                    resp = await client.get(
                        f"{settings.RAZORPAY_API_BASE_URL.rstrip('/')}/payments/{payment_id}",
                        auth=(settings.RAZORPAY_KEY_ID, secret),
                    )
                    if resp.status_code == 401:
                        logger.warning("Razorpay Payments API authentication failed (HTTP 401)")
                        return {
                            "outcome": "ambiguous",
                            "payment_id": payment_id,
                            "reason": "Payment gateway authentication failed. Please verify Razorpay credentials.",
                        }
                    if resp.status_code == 200:
                        pdata = resp.json()
                        p_status = pdata.get("status")
                        p_order = pdata.get("order_id")
                        p_amt = int(pdata.get("amount", 0))
                        if p_order != order_id or p_amt != expected_amount_paise:
                            return {
                                "outcome": "mismatch",
                                "payment_id": payment_id,
                                "reason": "Order ID or amount mismatch with Razorpay record",
                            }
                        if p_status == "captured":
                            return {"outcome": "captured", "payment_id": payment_id}
                        if p_status == "authorized":
                            return {
                                "outcome": "authorized",
                                "payment_id": payment_id,
                                "reason": "Payment is authorized but not yet captured",
                            }
                        if p_status == "failed":
                            return {
                                "outcome": "failed",
                                "payment_id": payment_id,
                                "reason": pdata.get("error_description") or "Payment failed at gateway",
                            }
                else:
                    resp = await client.get(
                        f"{settings.RAZORPAY_API_BASE_URL.rstrip('/')}/orders/{order_id}/payments",
                        auth=(settings.RAZORPAY_KEY_ID, secret),
                    )
                    if resp.status_code == 401:
                        logger.warning("Razorpay Orders Payments API authentication failed (HTTP 401)")
                        return {
                            "outcome": "ambiguous",
                            "payment_id": payment_id,
                            "reason": "Payment gateway authentication failed. Please verify Razorpay credentials.",
                        }
                    if resp.status_code == 200:
                        items = resp.json().get("items") or []
                        for item in items:
                            if item.get("status") == "captured":
                                if int(item.get("amount", 0)) != expected_amount_paise:
                                    return {
                                        "outcome": "mismatch",
                                        "payment_id": item.get("id"),
                                        "reason": "Captured payment amount mismatch",
                                    }
                                return {
                                    "outcome": "captured",
                                    "payment_id": item.get("id"),
                                }
                        for item in items:
                            if item.get("status") == "authorized":
                                return {
                                    "outcome": "authorized",
                                    "payment_id": item.get("id"),
                                    "reason": "Payment is authorized and awaiting capture",
                                }
                        if items and all(i.get("status") == "failed" for i in items):
                            return {
                                "outcome": "failed",
                                "payment_id": items[-1].get("id"),
                                "reason": items[-1].get("error_description") or "Payment failed",
                            }
                        return {"outcome": "created", "payment_id": None}
            return {
                "outcome": "ambiguous",
                "payment_id": payment_id,
                "reason": "Could not verify authoritative status from Razorpay API",
            }
        except Exception as exc:
            logger.warning("Razorpay reconciliation network error: %s", exc)
            return {
                "outcome": "ambiguous",
                "payment_id": payment_id,
                "reason": f"Gateway reconciliation unreachable: {type(exc).__name__}",
            }

    # Local sandbox mode: requires cryptographic HMAC signature verification when verifying a payment_id
    if signature_verified and payment_id:
        return {"outcome": "captured", "payment_id": payment_id}
    return {"outcome": "created", "payment_id": payment_id}


async def _apply_reconciled_outcome(
    db: AsyncIOMotorDatabase,
    reg_doc: dict[str, Any],
    attempt_doc: dict[str, Any],
    event_doc: Optional[dict[str, Any]],
    participant_user: dict[str, Any],
    provider_result: dict[str, Any],
    current_now: datetime,
    *,
    is_verify_endpoint: bool = False,
) -> RegistrationMutationResponse:
    """Apply authoritative payment outcome to both the payment attempt and booking safely."""
    outcome = provider_result.get("outcome")
    payment_id = provider_result.get("payment_id") or attempt_doc.get("razorpay_payment_id")
    reason = provider_result.get("reason")
    reg_oid = reg_doc["_id"]
    event_oid = reg_doc["event_id"]
    participant_oid = reg_doc["participant_id"]
    active_slot_key = f"{participant_oid}:{event_oid}"

    # 1. Ambiguous / in-flight payment ('authorized' or gateway unreachable)
    if outcome in ("authorized", "ambiguous"):
        pay_update: dict[str, Any] = {
            "status": "pending",
            "reconciled_at": current_now,
            "failure_reason": reason,
            "updated_at": current_now,
        }
        if payment_id:
            pay_update["razorpay_payment_id"] = payment_id
        updated_attempt = await db["payments"].find_one_and_update(
            {"_id": attempt_doc["_id"]},
            {"$set": pay_update},
            return_document=ReturnDocument.AFTER,
        )
        fresh_reg = await db["registrations"].find_one({"_id": reg_oid})
        serialized_reg = await serialize_registration(
            db, fresh_reg, event_doc=event_doc, now=current_now
        )
        return RegistrationMutationResponse(
            message=reason
            or "Payment status is currently pending confirmation with the payment gateway. Your seat remains held while we reconcile.",
            booking_status=fresh_reg["status"],
            payment_status=updated_attempt["status"],
            recovered_existing=False,
            registration=serialized_reg,
            payment_attempt=serialize_payment_attempt(updated_attempt),
        )

    # 2. Mismatched payment metadata -> resolution_required
    if outcome == "mismatch":
        pay_update = {
            "status": "resolution_required",
            "reconciled_at": current_now,
            "failure_reason": reason or "Payment amount or order mismatch",
            "updated_at": current_now,
        }
        if payment_id:
            pay_update["razorpay_payment_id"] = payment_id
        updated_attempt = await db["payments"].find_one_and_update(
            {"_id": attempt_doc["_id"]},
            {"$set": pay_update},
            return_document=ReturnDocument.AFTER,
        )
        updated_reg = await db["registrations"].find_one_and_update(
            {"_id": reg_oid},
            {
                "$set": {
                    "status": "resolution_required",
                    "resolution_reason": reason or "Payment verification mismatch",
                    "updated_at": current_now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        serialized_reg = await serialize_registration(
            db, updated_reg, event_doc=event_doc, now=current_now
        )
        return RegistrationMutationResponse(
            message="Payment requires manual resolution due to a verification mismatch.",
            booking_status=updated_reg["status"],
            payment_status=updated_attempt["status"],
            recovered_existing=False,
            registration=serialized_reg,
            payment_attempt=serialize_payment_attempt(updated_attempt),
        )

    # 3. Explicit failure
    if outcome == "failed":
        pay_update = {
            "status": "failed",
            "reconciled_at": current_now,
            "failure_reason": reason or "Payment failed",
            "updated_at": current_now,
        }
        if payment_id:
            pay_update["razorpay_payment_id"] = payment_id
        updated_attempt = await db["payments"].find_one_and_update(
            {"_id": attempt_doc["_id"]},
            {"$set": pay_update},
            return_document=ReturnDocument.AFTER,
        )
        # Re-run expiry check in case the 15-minute window has now elapsed
        await expire_stale_reservations(db, event_id=event_oid, now=current_now)
        fresh_reg = await db["registrations"].find_one({"_id": reg_oid})
        serialized_reg = await serialize_registration(
            db, fresh_reg, event_doc=event_doc, now=current_now
        )
        return RegistrationMutationResponse(
            message=reason or "Payment attempt failed. You can retry payment while your reservation remains active.",
            booking_status=fresh_reg["status"],
            payment_status=updated_attempt["status"],
            recovered_existing=False,
            registration=serialized_reg,
            payment_attempt=serialize_payment_attempt(updated_attempt),
        )

    # 4. Authoritative success ('captured')
    if outcome == "captured":
        # Guard against applying the same razorpay_payment_id to a different registration
        if payment_id:
            dup_pay = await db["payments"].find_one(
                {
                    "razorpay_payment_id": payment_id,
                    "_id": {"$ne": attempt_doc["_id"]},
                }
            )
            if dup_pay:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This Razorpay payment ID has already been applied to another payment record",
                )

        # Refresh event_doc and reg_doc
        event_doc = await db["events"].find_one({"_id": event_oid})
        fresh_reg = await db["registrations"].find_one({"_id": reg_oid})

        # Case 4A: Booking was already confirmed -> idempotent response
        if fresh_reg.get("status") == "confirmed" and attempt_doc.get("status") == "succeeded":
            serialized_reg = await serialize_registration(
                db, fresh_reg, event_doc=event_doc, now=current_now
            )
            return RegistrationMutationResponse(
                message="Payment already verified and booking is confirmed.",
                booking_status="confirmed",
                payment_status="succeeded",
                recovered_existing=False,
                registration=serialized_reg,
                payment_attempt=serialize_payment_attempt(attempt_doc),
            )

        # Case 4B: Event was cancelled before payment completed -> retain payment & flag resolution_required
        if not event_doc or event_doc.get("status") != "published":
            pay_update = {
                "status": "resolution_required",
                "verified_at": current_now if is_verify_endpoint else attempt_doc.get("verified_at"),
                "reconciled_at": current_now,
                "failure_reason": "Payment succeeded after event was cancelled by organizer",
                "updated_at": current_now,
            }
            if payment_id:
                pay_update["razorpay_payment_id"] = payment_id
            updated_attempt = await db["payments"].find_one_and_update(
                {"_id": attempt_doc["_id"]},
                {"$set": pay_update},
                return_document=ReturnDocument.AFTER,
            )
            was_holding = bool(fresh_reg.get("seat_held"))
            updated_reg = await db["registrations"].find_one_and_update(
                {"_id": reg_oid},
                {
                    "$set": {
                        "status": "resolution_required",
                        "seat_held": False,
                        "active_slot_key": active_slot_key,
                        "resolution_reason": "Payment succeeded for a cancelled event; record preserved for organizer resolution (no automatic refund).",
                        "updated_at": current_now,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
            if was_holding:
                await _release_event_seat(db, event_oid, current_now)
            serialized_reg = await serialize_registration(
                db, updated_reg, event_doc=event_doc, now=current_now
            )
            return RegistrationMutationResponse(
                message="Payment was captured, but this event has been cancelled by the organizer. Your payment record is preserved and flagged for resolution.",
                booking_status=updated_reg["status"],
                payment_status=updated_attempt["status"],
                recovered_existing=False,
                registration=serialized_reg,
                payment_attempt=serialize_payment_attempt(updated_attempt),
            )

        # Case 4C: Booking still holds its reserved seat (pending_payment or already confirmed)
        if fresh_reg.get("seat_held") and fresh_reg.get("status") in ("pending_payment", "confirmed"):
            pay_update = {
                "status": "succeeded",
                "verified_at": current_now,
                "reconciled_at": current_now,
                "failure_reason": None,
                "updated_at": current_now,
            }
            if payment_id:
                pay_update["razorpay_payment_id"] = payment_id
            updated_attempt = await db["payments"].find_one_and_update(
                {"_id": attempt_doc["_id"]},
                {"$set": pay_update},
                return_document=ReturnDocument.AFTER,
            )
            updated_reg = await db["registrations"].find_one_and_update(
                {"_id": reg_oid},
                {
                    "$set": {
                        "status": "confirmed",
                        "seat_held": True,
                        "active_slot_key": active_slot_key,
                        "confirmed_at": fresh_reg.get("confirmed_at") or current_now,
                        "updated_at": current_now,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )
            await schedule_registration_notifications(
                db, updated_reg, event_doc, participant_user, now=current_now
            )
            serialized_reg = await serialize_registration(
                db, updated_reg, event_doc=event_doc, now=current_now
            )
            return RegistrationMutationResponse(
                message="Payment verified and booking confirmed!",
                booking_status="confirmed",
                payment_status="succeeded",
                recovered_existing=False,
                registration=serialized_reg,
                payment_attempt=serialize_payment_attempt(updated_attempt),
            )

        # Case 4D: Late payment succeeded after reservation expired (seat_held == False)
        # Attempt atomic seat allocation on the event!
        allocated_late = await _try_allocate_event_seat(
            db, event_oid, current_now, enforce_deadline=False
        )
        if allocated_late is not None:
            try:
                updated_reg = await db["registrations"].find_one_and_update(
                    {"_id": reg_oid},
                    {
                        "$set": {
                            "status": "confirmed",
                            "seat_held": True,
                            "active_slot_key": active_slot_key,
                            "confirmed_at": current_now,
                            "resolution_reason": None,
                            "updated_at": current_now,
                        }
                    },
                    return_document=ReturnDocument.AFTER,
                )
            except DuplicateKeyError:
                # Participant created another active booking in the meantime -> release seat & flag resolution_required
                await _release_event_seat(db, event_oid, current_now)
                allocated_late = None

        if allocated_late is not None:
            pay_update = {
                "status": "succeeded",
                "verified_at": current_now,
                "reconciled_at": current_now,
                "failure_reason": None,
                "updated_at": current_now,
            }
            if payment_id:
                pay_update["razorpay_payment_id"] = payment_id
            updated_attempt = await db["payments"].find_one_and_update(
                {"_id": attempt_doc["_id"]},
                {"$set": pay_update},
                return_document=ReturnDocument.AFTER,
            )
            await schedule_registration_notifications(
                db, updated_reg, allocated_late, participant_user, now=current_now
            )
            serialized_reg = await serialize_registration(
                db, updated_reg, event_doc=allocated_late, now=current_now
            )
            return RegistrationMutationResponse(
                message="Late payment verified and seat allocated — booking confirmed!",
                booking_status="confirmed",
                payment_status="succeeded",
                recovered_existing=False,
                registration=serialized_reg,
                payment_attempt=serialize_payment_attempt(updated_attempt),
            )

        # No capacity left for late payment -> preserve payment record & flag resolution_required
        pay_update = {
            "status": "resolution_required",
            "verified_at": current_now,
            "reconciled_at": current_now,
            "failure_reason": "Late payment captured after reservation expired and event reached full capacity",
            "updated_at": current_now,
        }
        if payment_id:
            pay_update["razorpay_payment_id"] = payment_id
        updated_attempt = await db["payments"].find_one_and_update(
            {"_id": attempt_doc["_id"]},
            {"$set": pay_update},
            return_document=ReturnDocument.AFTER,
        )
        updated_reg = await db["registrations"].find_one_and_update(
            {"_id": reg_oid},
            {
                "$set": {
                    "status": "resolution_required",
                    "seat_held": False,
                    "resolution_reason": "Late payment succeeded after seat reservation expired and event sold out; payment record preserved for manual resolution.",
                    "updated_at": current_now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        serialized_reg = await serialize_registration(
            db, updated_reg, event_doc=event_doc, now=current_now
        )
        return RegistrationMutationResponse(
            message="Payment was captured after your seat reservation expired and the event is now full. Your payment record is preserved and flagged for resolution.",
            booking_status="resolution_required",
            payment_status="resolution_required",
            recovered_existing=False,
            registration=serialized_reg,
            payment_attempt=serialize_payment_attempt(updated_attempt),
        )

    # 5. Still 'created' (no payment completed yet)
    fresh_reg = await db["registrations"].find_one({"_id": reg_oid})
    serialized_reg = await serialize_registration(
        db, fresh_reg, event_doc=event_doc, now=current_now
    )
    return RegistrationMutationResponse(
        message="No completed payment found yet for this order.",
        booking_status=fresh_reg["status"],
        payment_status=attempt_doc["status"],
        recovered_existing=False,
        registration=serialized_reg,
        payment_attempt=serialize_payment_attempt(attempt_doc),
    )


async def verify_booking_payment(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    registration_id: str,
    payload: PaymentVerifyRequest,
    *,
    now: Optional[datetime] = None,
) -> RegistrationMutationResponse:
    """Verify Razorpay checkout signature server-side and reconcile authoritative payment state."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    reg_oid = _parse_object_id(registration_id, "Registration not found")

    reg_doc = await db["registrations"].find_one({"_id": reg_oid})
    if not reg_doc or reg_doc.get("participant_id") != participant_user["_id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    attempt_doc = await db["payments"].find_one(
        {
            "registration_id": reg_oid,
            "razorpay_order_id": payload.razorpay_order_id.strip(),
        }
    )
    if not attempt_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment order not found for this booking",
        )

    event_doc = await db["events"].find_one({"_id": reg_doc["event_id"]})

    # Idempotency check: if this exact payment was already verified and succeeded
    if (
        attempt_doc.get("status") == "succeeded"
        and attempt_doc.get("razorpay_payment_id") == payload.razorpay_payment_id.strip()
        and reg_doc.get("status") == "confirmed"
    ):
        serialized_reg = await serialize_registration(
            db, reg_doc, event_doc=event_doc, now=current_now
        )
        return RegistrationMutationResponse(
            message="Payment already verified and booking is confirmed.",
            booking_status="confirmed",
            payment_status="succeeded",
            recovered_existing=False,
            registration=serialized_reg,
            payment_attempt=serialize_payment_attempt(attempt_doc),
        )

    # Verify HMAC-SHA256 signature server-side
    sig_ok = verify_razorpay_signature(
        payload.razorpay_order_id.strip(),
        payload.razorpay_payment_id.strip(),
        payload.razorpay_signature.strip(),
    )
    if not sig_ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Razorpay payment signature. Payment could not be verified.",
        )

    provider_result = await _inspect_authoritative_payment_status(
        order_id=payload.razorpay_order_id.strip(),
        payment_id=payload.razorpay_payment_id.strip(),
        expected_amount_paise=int(attempt_doc["amount_paise"]),
        signature_verified=True,
    )
    return await _apply_reconciled_outcome(
        db,
        reg_doc,
        attempt_doc,
        event_doc,
        participant_user,
        provider_result,
        current_now,
        is_verify_endpoint=True,
    )


async def record_failed_payment_attempt(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    registration_id: str,
    payload: PaymentFailureReportRequest,
    *,
    now: Optional[datetime] = None,
) -> RegistrationMutationResponse:
    """Record a failed checkout attempt while preserving the booking and seat reservation for retry."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    reg_oid = _parse_object_id(registration_id, "Registration not found")

    reg_doc = await db["registrations"].find_one({"_id": reg_oid})
    if not reg_doc or reg_doc.get("participant_id") != participant_user["_id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    attempt_doc = await db["payments"].find_one(
        {
            "registration_id": reg_oid,
            "razorpay_order_id": payload.razorpay_order_id.strip(),
        }
    )
    if not attempt_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment order not found for this booking",
        )

    if attempt_doc.get("status") == "succeeded":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot mark an already succeeded payment as failed",
        )

    event_doc = await db["events"].find_one({"_id": reg_doc["event_id"]})
    reason_str = (
        f"{payload.error_code}: {payload.error_description}".strip(": ")
        if (payload.error_code or payload.error_description)
        else "Payment checkout failed or was dismissed"
    )
    provider_result = {
        "outcome": "failed",
        "payment_id": payload.razorpay_payment_id,
        "reason": reason_str,
    }
    return await _apply_reconciled_outcome(
        db,
        reg_doc,
        attempt_doc,
        event_doc,
        participant_user,
        provider_result,
        current_now,
    )


async def reconcile_booking_payment(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    registration_id: str,
    payload: Optional[PaymentReconcileRequest] = None,
    *,
    now: Optional[datetime] = None,
) -> RegistrationMutationResponse:
    """Server-side reconciliation of a booking's latest (or specified) payment attempt."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    reg_oid = _parse_object_id(registration_id, "Registration not found")

    reg_doc = await db["registrations"].find_one({"_id": reg_oid})
    if not reg_doc or reg_doc.get("participant_id") != participant_user["_id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    event_doc = await db["events"].find_one({"_id": reg_doc["event_id"]})

    if payload and payload.razorpay_order_id:
        attempt_doc = await db["payments"].find_one(
            {
                "registration_id": reg_oid,
                "razorpay_order_id": payload.razorpay_order_id.strip(),
            }
        )
    else:
        pay_cursor = db["payments"].find({"registration_id": reg_oid})
        attempts = await pay_cursor.to_list(length=50)
        attempts.sort(key=lambda d: int(d.get("attempt_number", 0)))
        attempt_doc = attempts[-1] if attempts else None

    if not attempt_doc:
        await expire_stale_reservations(db, event_id=reg_doc["event_id"], now=current_now)
        fresh_reg = await db["registrations"].find_one({"_id": reg_oid})
        serialized_reg = await serialize_registration(
            db, fresh_reg, event_doc=event_doc, now=current_now
        )
        return RegistrationMutationResponse(
            message="Booking status reconciled.",
            booking_status=fresh_reg["status"],
            payment_status=None,
            recovered_existing=False,
            registration=serialized_reg,
        )

    payment_id = (
        payload.razorpay_payment_id.strip()
        if payload and payload.razorpay_payment_id
        else attempt_doc.get("razorpay_payment_id")
    )
    provider_result = await _inspect_authoritative_payment_status(
        order_id=attempt_doc["razorpay_order_id"],
        payment_id=payment_id,
        expected_amount_paise=int(attempt_doc["amount_paise"]),
        signature_verified=False,
    )
    return await _apply_reconciled_outcome(
        db,
        reg_doc,
        attempt_doc,
        event_doc,
        participant_user,
        provider_result,
        current_now,
    )


async def cancel_participant_registration(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    registration_id: str,
    payload: Optional[RegistrationCancelRequest] = None,
    *,
    now: Optional[datetime] = None,
) -> RegistrationMutationResponse:
    """Cancel a participant's booking before the event registration deadline, preserving history."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    reg_oid = _parse_object_id(registration_id, "Registration not found")

    reg_doc = await db["registrations"].find_one({"_id": reg_oid})
    if not reg_doc or reg_doc.get("participant_id") != participant_user["_id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )

    reg_status = reg_doc.get("status")
    if reg_status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking is already cancelled",
        )
    if reg_status not in ("confirmed", "pending_payment"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a booking in '{reg_status}' status",
        )

    # Check if there is an ambiguous payment attempt ('pending')
    pay_cursor = db["payments"].find({"registration_id": reg_oid})
    pay_docs = await pay_cursor.to_list(length=50)
    if any(p.get("status") == "pending" for p in pay_docs):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot cancel booking while a payment attempt is pending verification. Please reconcile payment status first.",
        )

    event_doc = await db["events"].find_one({"_id": reg_doc["event_id"]})
    if event_doc:
        deadline = ensure_utc_datetime(
            event_doc.get("registration_deadline") or event_doc["start_date"]
        )
        if deadline <= current_now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bookings cannot be cancelled after the event registration deadline",
            )

    reason_text = (
        payload.reason.strip()
        if payload and payload.reason and payload.reason.strip()
        else "Cancelled by participant"
    )
    was_holding_seat = bool(reg_doc.get("seat_held"))

    updated_reg = await db["registrations"].find_one_and_update(
        {"_id": reg_oid, "status": {"$in": ["confirmed", "pending_payment"]}},
        {
            "$set": {
                "status": "cancelled",
                "seat_held": False,
                "cancelled_at": current_now,
                "cancellation_reason": reason_text,
                "updated_at": current_now,
            },
            "$unset": {"active_slot_key": ""},
        },
        return_document=ReturnDocument.AFTER,
    )
    if not updated_reg:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking status changed concurrently; please refresh.",
        )

    if was_holding_seat:
        await _release_event_seat(db, reg_doc["event_id"], current_now)

    await suppress_notifications_for_registration(
        db,
        reg_oid,
        "Booking cancelled by participant",
        now=current_now,
    )

    fresh_event = await db["events"].find_one({"_id": reg_doc["event_id"]})
    serialized_reg = await serialize_registration(
        db, updated_reg, event_doc=fresh_event, now=current_now
    )
    return RegistrationMutationResponse(
        message="Booking cancelled and record preserved in your history. Note: Cancellation does not perform or imply a payment refund.",
        booking_status="cancelled",
        payment_status=(
            serialized_reg.latest_payment.status if serialized_reg.latest_payment else None
        ),
        recovered_existing=False,
        registration=serialized_reg,
        payment_attempt=serialized_reg.latest_payment,
    )


async def reconcile_bookings_for_cancelled_event(
    db: AsyncIOMotorDatabase,
    event_id: ObjectId,
    *,
    now: Optional[datetime] = None,
) -> int:
    """When an organizer cancels an event:
    - Suppress all unsent reminders for the event.
    - Reconcile pending_payment bookings: if any payment succeeded/pending, flag resolution_required;
      otherwise cancel unpaid reservations and release held seats.
    - Preserve confirmed bookings and payment history.
    """
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    suppressed_count = await suppress_notifications_for_event(
        db, event_id, "Event cancelled by organizer", now=current_now
    )

    cursor = db["registrations"].find(
        {"event_id": event_id, "status": "pending_payment"}
    )
    pending_regs = await cursor.to_list(length=500)
    for reg_doc in pending_regs:
        reg_oid = reg_doc["_id"]
        pay_cursor = db["payments"].find({"registration_id": reg_oid})
        attempts = await pay_cursor.to_list(length=50)
        has_paid_or_inflight = any(
            p.get("status") in ("succeeded", "pending") for p in attempts
        )
        was_holding = bool(reg_doc.get("seat_held"))
        if has_paid_or_inflight:
            await db["registrations"].update_one(
                {"_id": reg_oid},
                {
                    "$set": {
                        "status": "resolution_required",
                        "seat_held": False,
                        "resolution_reason": "Event cancelled by organizer while payment was in progress or completed; preserved for resolution.",
                        "updated_at": current_now,
                    }
                },
            )
        else:
            await db["registrations"].update_one(
                {"_id": reg_oid},
                {
                    "$set": {
                        "status": "cancelled",
                        "seat_held": False,
                        "cancelled_at": current_now,
                        "cancellation_reason": "Event cancelled by organizer before payment completion",
                        "updated_at": current_now,
                    },
                    "$unset": {"active_slot_key": ""},
                },
            )
        if was_holding:
            await _release_event_seat(db, event_id, current_now)

    return suppressed_count


async def list_participant_registrations(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    *,
    status_filter: Optional[str] = None,
    now: Optional[datetime] = None,
) -> RegistrationListResponse:
    """Return full booking history for My Bookings with optional status filtering."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    participant_oid = participant_user["_id"]

    await expire_stale_reservations(
        db, participant_id=participant_oid, now=current_now
    )

    query: dict[str, Any] = {"participant_id": participant_oid}
    if status_filter and status_filter.strip().lower() != "all":
        cleaned = status_filter.strip().lower()
        if cleaned == "cancelled_or_expired":
            query["status"] = {"$in": ["cancelled", "expired"]}
        elif cleaned in (
            "confirmed",
            "pending_payment",
            "cancelled",
            "expired",
            "resolution_required",
        ):
            query["status"] = cleaned
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid booking status filter",
            )

    cursor = db["registrations"].find(query)
    docs = await cursor.to_list(length=500)
    docs.sort(key=lambda d: ensure_utc_datetime(d["created_at"]), reverse=True)

    items = [
        await serialize_registration(db, d, now=current_now) for d in docs
    ]
    return RegistrationListResponse(registrations=items, total=len(items))


async def list_upcoming_confirmed_registrations(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> RegistrationListResponse:
    """Return only eligible confirmed bookings for future published events (for the dashboard Upcoming widget)."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    participant_oid = participant_user["_id"]

    await expire_stale_reservations(
        db, participant_id=participant_oid, now=current_now
    )

    cursor = db["registrations"].find(
        {"participant_id": participant_oid, "status": "confirmed"}
    )
    docs = await cursor.to_list(length=200)

    upcoming_items: list[RegistrationResponse] = []
    for reg_doc in docs:
        event_doc = await db["events"].find_one({"_id": reg_doc["event_id"]})
        if not event_doc:
            continue
        if event_doc.get("status") != "published":
            continue
        start_dt = ensure_utc_datetime(event_doc["start_date"])
        if start_dt <= current_now:
            continue
        upcoming_items.append(
            await serialize_registration(
                db, reg_doc, event_doc=event_doc, now=current_now
            )
        )

    upcoming_items.sort(
        key=lambda r: r.event.start_date if r.event else current_now
    )
    return RegistrationListResponse(
        registrations=upcoming_items,
        total=len(upcoming_items),
    )


async def get_participant_registration_detail(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    registration_id: str,
    *,
    now: Optional[datetime] = None,
) -> RegistrationResponse:
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    reg_oid = _parse_object_id(registration_id, "Registration not found")

    await expire_stale_reservations(
        db, participant_id=participant_user["_id"], now=current_now
    )

    reg_doc = await db["registrations"].find_one({"_id": reg_oid})
    if not reg_doc or reg_doc.get("participant_id") != participant_user["_id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Registration not found",
        )
    return await serialize_registration(db, reg_doc, now=current_now)
