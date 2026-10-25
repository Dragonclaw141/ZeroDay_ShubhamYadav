from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel

from app.events.schemas import ensure_utc_datetime

NotificationTypeLiteral = Literal["registration_acknowledgement", "event_reminder"]
NotificationStatusLiteral = Literal["pending", "processing", "sent", "failed", "suppressed"]


class NotificationResponse(BaseModel):
    id: str
    notification_type: NotificationTypeLiteral
    registration_id: str
    participant_id: str
    event_id: str
    recipient_email: str
    subject: str
    scheduled_at: datetime
    status: NotificationStatusLiteral
    attempt_count: int
    max_attempts: int = 3
    next_retry_at: Optional[datetime] = None
    processing_lease_until: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    provider_message_id: Optional[str] = None
    delivery_semantics: str = (
        "Provider acceptance recorded; final inbox delivery depends on the recipient mail server."
    )
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    total: int


def serialize_notification(doc: dict[str, Any]) -> NotificationResponse:
    created = ensure_utc_datetime(doc["created_at"])
    return NotificationResponse(
        id=str(doc["_id"]),
        notification_type=doc["notification_type"],
        registration_id=str(doc["registration_id"]),
        participant_id=str(doc["participant_id"]),
        event_id=str(doc["event_id"]),
        recipient_email=doc.get("recipient_email", ""),
        subject=doc.get("subject", ""),
        scheduled_at=ensure_utc_datetime(doc["scheduled_at"]),
        status=doc["status"],
        attempt_count=int(doc.get("attempt_count", 0)),
        max_attempts=int(doc.get("max_attempts", 3)),
        next_retry_at=(
            ensure_utc_datetime(doc["next_retry_at"])
            if doc.get("next_retry_at") is not None
            else None
        ),
        processing_lease_until=(
            ensure_utc_datetime(doc["processing_lease_until"])
            if doc.get("processing_lease_until") is not None
            else None
        ),
        sent_at=(
            ensure_utc_datetime(doc["sent_at"])
            if doc.get("sent_at") is not None
            else None
        ),
        provider_message_id=doc.get("provider_message_id"),
        last_error=doc.get("last_error"),
        created_at=created,
        updated_at=ensure_utc_datetime(doc.get("updated_at") or created),
    )
