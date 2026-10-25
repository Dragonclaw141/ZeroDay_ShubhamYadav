import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.core.database import get_database
from app.events.schemas import ensure_utc_datetime
from app.notifications.email import (
    build_event_reminder_email,
    build_registration_acknowledgement_email,
    send_email_message,
)
from app.notifications.schemas import (
    NotificationListResponse,
    NotificationResponse,
    serialize_notification,
)

logger = logging.getLogger(__name__)

MAX_NOTIFICATION_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (60, 300, 900)
LEASE_DURATION_SECONDS = 60

_scheduler_task: Optional[asyncio.Task] = None


async def enqueue_registration_acknowledgement(
    db: AsyncIOMotorDatabase,
    registration_doc: dict[str, Any],
    event_doc: dict[str, Any],
    user_doc: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Create a durable registration_acknowledgement notification job idempotently."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    reg_id = registration_doc["_id"]
    dedupe_key = f"ack:{reg_id}"

    existing = await db["notifications"].find_one({"dedupe_key": dedupe_key})
    if existing:
        return existing

    subject, body = build_registration_acknowledgement_email(
        user_doc, event_doc, registration_doc
    )
    job_doc: dict[str, Any] = {
        "notification_type": "registration_acknowledgement",
        "dedupe_key": dedupe_key,
        "registration_id": reg_id,
        "participant_id": registration_doc["participant_id"],
        "event_id": registration_doc["event_id"],
        "recipient_email": user_doc.get("email", ""),
        "subject": subject,
        "body_text": body,
        "scheduled_at": current_now,
        "status": "pending",
        "attempt_count": 0,
        "max_attempts": MAX_NOTIFICATION_ATTEMPTS,
        "next_retry_at": None,
        "processing_lease_until": None,
        "sent_at": None,
        "provider_message_id": None,
        "last_error": None,
        "created_at": current_now,
        "updated_at": current_now,
    }
    try:
        res = await db["notifications"].insert_one(job_doc)
        job_doc["_id"] = res.inserted_id
        return job_doc
    except DuplicateKeyError:
        return await db["notifications"].find_one({"dedupe_key": dedupe_key})


async def enqueue_event_reminder(
    db: AsyncIOMotorDatabase,
    registration_doc: dict[str, Any],
    event_doc: dict[str, Any],
    user_doc: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Schedule a durable 24-hour event reminder (or immediate reminder if confirmed <24h before start)."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    reg_id = registration_doc["_id"]
    dedupe_key = f"reminder:{reg_id}"

    existing = await db["notifications"].find_one({"dedupe_key": dedupe_key})
    if existing:
        return existing

    event_start = ensure_utc_datetime(event_doc["start_date"])
    target_time = event_start - timedelta(hours=24)

    # If confirmed less than 24h before start while event is still upcoming, schedule as soon as possible
    if event_start <= current_now:
        initial_status = "suppressed"
        scheduled_at = current_now
        last_error = "Event has already started before reminder could be scheduled"
    else:
        initial_status = "pending"
        scheduled_at = max(current_now, target_time)
        last_error = None

    subject, body = build_event_reminder_email(user_doc, event_doc, registration_doc)
    job_doc: dict[str, Any] = {
        "notification_type": "event_reminder",
        "dedupe_key": dedupe_key,
        "registration_id": reg_id,
        "participant_id": registration_doc["participant_id"],
        "event_id": registration_doc["event_id"],
        "recipient_email": user_doc.get("email", ""),
        "subject": subject,
        "body_text": body,
        "scheduled_at": scheduled_at,
        "status": initial_status,
        "attempt_count": 0,
        "max_attempts": MAX_NOTIFICATION_ATTEMPTS,
        "next_retry_at": None,
        "processing_lease_until": None,
        "sent_at": None,
        "provider_message_id": None,
        "last_error": last_error,
        "created_at": current_now,
        "updated_at": current_now,
    }
    try:
        res = await db["notifications"].insert_one(job_doc)
        job_doc["_id"] = res.inserted_id
        return job_doc
    except DuplicateKeyError:
        return await db["notifications"].find_one({"dedupe_key": dedupe_key})


async def schedule_registration_notifications(
    db: AsyncIOMotorDatabase,
    registration_doc: dict[str, Any],
    event_doc: dict[str, Any],
    user_doc: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> dict[str, Optional[dict[str, Any]]]:
    """Enqueue both acknowledgement and 24h reminder independently; deliver due jobs without cross-blocking."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    ack_doc: Optional[dict[str, Any]] = None
    rem_doc: Optional[dict[str, Any]] = None

    try:
        ack_doc = await enqueue_registration_acknowledgement(
            db, registration_doc, event_doc, user_doc, now=current_now
        )
    except Exception as exc:
        logger.error("Failed to enqueue registration acknowledgement: %s", exc)

    try:
        rem_doc = await enqueue_event_reminder(
            db, registration_doc, event_doc, user_doc, now=current_now
        )
    except Exception as exc:
        logger.error("Failed to enqueue event reminder: %s", exc)

    if ack_doc and ack_doc.get("status") == "pending":
        try:
            ack_doc = await process_single_notification_job(
                db, ack_doc["_id"], now=current_now
            )
        except Exception as exc:
            logger.error("Error delivering acknowledgement job %s: %s", ack_doc.get("_id"), exc)

    if (
        rem_doc
        and rem_doc.get("status") == "pending"
        and ensure_utc_datetime(rem_doc["scheduled_at"]) <= current_now
    ):
        try:
            rem_doc = await process_single_notification_job(
                db, rem_doc["_id"], now=current_now
            )
        except Exception as exc:
            logger.error("Error delivering immediate reminder job %s: %s", rem_doc.get("_id"), exc)

    return {"acknowledgement": ack_doc, "reminder": rem_doc}


def _is_job_claimable(doc: dict[str, Any], current_now: datetime) -> bool:
    st = doc.get("status")
    if st == "pending":
        sched = ensure_utc_datetime(doc["scheduled_at"])
        if sched > current_now:
            return False
        nxt = doc.get("next_retry_at")
        if nxt is not None and ensure_utc_datetime(nxt) > current_now:
            return False
        return True
    if st == "processing":
        lease = doc.get("processing_lease_until")
        if lease is None or ensure_utc_datetime(lease) <= current_now:
            return True
    return False


async def _claim_notification_job(
    db: AsyncIOMotorDatabase,
    job_id: ObjectId,
    current_now: datetime,
) -> Optional[dict[str, Any]]:
    """Atomically claim a due pending job or recover a stale processing lease."""
    lease_until = current_now + timedelta(seconds=LEASE_DURATION_SECONDS)
    claimed = await db["notifications"].find_one_and_update(
        {
            "_id": job_id,
            "$or": [
                {
                    "status": "pending",
                    "scheduled_at": {"$lte": current_now},
                    "$or": [
                        {"next_retry_at": None},
                        {"next_retry_at": {"$lte": current_now}},
                    ],
                },
                {
                    "status": "processing",
                    "processing_lease_until": {"$lte": current_now},
                },
            ],
        },
        {
            "$set": {
                "status": "processing",
                "processing_lease_until": lease_until,
                "updated_at": current_now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return claimed


async def _check_delivery_eligibility(
    db: AsyncIOMotorDatabase,
    job_doc: dict[str, Any],
    current_now: datetime,
) -> tuple[bool, Optional[str]]:
    """Recheck booking status, event status, and event start time before sending."""
    reg_doc = await db["registrations"].find_one({"_id": job_doc["registration_id"]})
    if not reg_doc:
        return False, "Registration record no longer exists"
    if reg_doc.get("status") != "confirmed":
        return False, f"Booking status is '{reg_doc.get('status')}' (not confirmed)"

    event_doc = await db["events"].find_one({"_id": job_doc["event_id"]})
    if not event_doc:
        return False, "Event record no longer exists"
    if event_doc.get("status") != "published":
        return False, f"Event status is '{event_doc.get('status')}' (not published)"

    if job_doc.get("notification_type") == "event_reminder":
        event_start = ensure_utc_datetime(event_doc["start_date"])
        if event_start <= current_now:
            return False, "Event has already started; reminder suppressed"

    return True, None


async def process_single_notification_job(
    db: AsyncIOMotorDatabase,
    job_id: ObjectId,
    *,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Claim, validate eligibility, and attempt delivery for a single notification job with bounded retries."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    claimed = await _claim_notification_job(db, job_id, current_now)
    if not claimed:
        return await db["notifications"].find_one({"_id": job_id})

    eligible, reason = await _check_delivery_eligibility(db, claimed, current_now)
    if not eligible:
        return await db["notifications"].find_one_and_update(
            {"_id": job_id},
            {
                "$set": {
                    "status": "suppressed",
                    "processing_lease_until": None,
                    "next_retry_at": None,
                    "last_error": reason,
                    "updated_at": current_now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )

    attempt_num = int(claimed.get("attempt_count", 0)) + 1
    max_attempts = int(claimed.get("max_attempts", MAX_NOTIFICATION_ATTEMPTS))
    idempotency_key = f"{claimed.get('dedupe_key', job_id)}:attempt:{attempt_num}"

    try:
        send_res = await send_email_message(
            to_email=claimed["recipient_email"],
            subject=claimed["subject"],
            body_text=claimed.get("body_text", ""),
            notification_type=claimed["notification_type"],
            idempotency_key=idempotency_key,
        )
        return await db["notifications"].find_one_and_update(
            {"_id": job_id},
            {
                "$set": {
                    "status": "sent",
                    "attempt_count": attempt_num,
                    "sent_at": current_now,
                    "processing_lease_until": None,
                    "next_retry_at": None,
                    "provider_message_id": send_res.get("provider_message_id"),
                    "last_error": None,
                    "updated_at": current_now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        if attempt_num >= max_attempts:
            return await db["notifications"].find_one_and_update(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "failed",
                        "attempt_count": attempt_num,
                        "processing_lease_until": None,
                        "next_retry_at": None,
                        "last_error": err_msg,
                        "updated_at": current_now,
                    }
                },
                return_document=ReturnDocument.AFTER,
            )

        backoff_idx = min(attempt_num - 1, len(RETRY_BACKOFF_SECONDS) - 1)
        delay_secs = RETRY_BACKOFF_SECONDS[backoff_idx]
        next_retry = current_now + timedelta(seconds=delay_secs)
        return await db["notifications"].find_one_and_update(
            {"_id": job_id},
            {
                "$set": {
                    "status": "pending",
                    "attempt_count": attempt_num,
                    "processing_lease_until": None,
                    "next_retry_at": next_retry,
                    "last_error": err_msg,
                    "updated_at": current_now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )


async def process_due_notifications(
    db: AsyncIOMotorDatabase,
    *,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> dict[str, int]:
    """Sweep and process all due pending notifications and stale processing leases."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    cursor = db["notifications"].find(
        {"status": {"$in": ["pending", "processing"]}}
    )
    candidates = await cursor.to_list(length=500)
    due_docs = [doc for doc in candidates if _is_job_claimable(doc, current_now)]
    due_docs.sort(key=lambda d: ensure_utc_datetime(d["scheduled_at"]))

    stats = {"processed": 0, "sent": 0, "retried": 0, "failed": 0, "suppressed": 0}
    for doc in due_docs[:limit]:
        updated = await process_single_notification_job(db, doc["_id"], now=current_now)
        if not updated:
            continue
        stats["processed"] += 1
        st = updated.get("status")
        if st == "sent":
            stats["sent"] += 1
        elif st == "pending":
            stats["retried"] += 1
        elif st == "failed":
            stats["failed"] += 1
        elif st == "suppressed":
            stats["suppressed"] += 1

    return stats


async def suppress_notifications_for_registration(
    db: AsyncIOMotorDatabase,
    registration_id: ObjectId,
    reason: str,
    *,
    now: Optional[datetime] = None,
) -> int:
    """Suppress future reminders when a participant cancels their booking."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    res = await db["notifications"].update_many(
        {
            "registration_id": registration_id,
            "notification_type": "event_reminder",
            "status": {"$in": ["pending", "processing", "failed"]},
        },
        {
            "$set": {
                "status": "suppressed",
                "processing_lease_until": None,
                "next_retry_at": None,
                "last_error": reason,
                "updated_at": current_now,
            }
        },
    )
    return res.modified_count


async def suppress_notifications_for_event(
    db: AsyncIOMotorDatabase,
    event_id: ObjectId,
    reason: str,
    *,
    now: Optional[datetime] = None,
) -> int:
    """Suppress all unsent reminders when an organizer cancels an event."""
    current_now = ensure_utc_datetime(now) if now else datetime.now(timezone.utc)
    res = await db["notifications"].update_many(
        {
            "event_id": event_id,
            "notification_type": "event_reminder",
            "status": {"$in": ["pending", "processing", "failed"]},
        },
        {
            "$set": {
                "status": "suppressed",
                "processing_lease_until": None,
                "next_retry_at": None,
                "last_error": reason,
                "updated_at": current_now,
            }
        },
    )
    return res.modified_count


async def list_participant_notifications(
    db: AsyncIOMotorDatabase,
    participant_user: dict[str, Any],
    *,
    registration_id: Optional[str] = None,
) -> NotificationListResponse:
    query: dict[str, Any] = {"participant_id": participant_user["_id"]}
    if registration_id:
        try:
            query["registration_id"] = ObjectId(registration_id)
        except (InvalidId, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Registration not found",
            ) from exc

    cursor = db["notifications"].find(query)
    docs = await cursor.to_list(length=200)
    docs.sort(key=lambda d: ensure_utc_datetime(d["created_at"]), reverse=True)
    return NotificationListResponse(
        notifications=[serialize_notification(d) for d in docs],
        total=len(docs),
    )


async def retry_failed_notification(
    db: AsyncIOMotorDatabase,
    current_user: dict[str, Any],
    notification_id: str,
) -> NotificationResponse:
    try:
        notif_oid = ObjectId(notification_id)
    except (InvalidId, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        ) from exc

    doc = await db["notifications"].find_one({"_id": notif_oid})
    if not doc or doc.get("participant_id") != current_user["_id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    if doc.get("status") != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only failed notifications can be manually retried (current status: {doc.get('status')})",
        )

    now = datetime.now(timezone.utc)
    await db["notifications"].update_one(
        {"_id": notif_oid},
        {
            "$set": {
                "status": "pending",
                "attempt_count": 0,
                "next_retry_at": None,
                "processing_lease_until": None,
                "updated_at": now,
            }
        },
    )
    updated = await process_single_notification_job(db, notif_oid, now=now)
    return serialize_notification(updated)


async def _scheduler_loop() -> None:
    """Background reminder & notification recovery worker loop."""
    try:
        db = get_database()
        await process_due_notifications(db)
    except Exception as exc:
        logger.debug("Initial notification recovery sweep skipped: %s", exc)

    interval = max(5, int(settings.REMINDER_POLL_INTERVAL_SECONDS or 30))
    while True:
        try:
            await asyncio.sleep(interval)
            db = get_database()
            await process_due_notifications(db)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Notification scheduler poll error: %s", exc)


async def start_notification_scheduler(app: Optional[Any] = None) -> None:
    """Start the single background notification scheduler worker if enabled."""
    global _scheduler_task
    _ = app
    if not settings.REMINDER_SCHEDULER_ENABLED:
        return
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop())


async def stop_notification_scheduler(app: Optional[Any] = None) -> None:
    """Stop the background notification scheduler cleanly on shutdown."""
    global _scheduler_task
    _ = app
    if _scheduler_task is not None:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None
