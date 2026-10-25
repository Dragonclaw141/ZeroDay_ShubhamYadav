from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.dependencies import require_participant
from app.notifications.schemas import NotificationListResponse, NotificationResponse
from app.notifications.service import (
    list_participant_notifications,
    retry_failed_notification,
)

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


@router.get(
    "/me",
    response_model=NotificationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List registration acknowledgements and event reminders for the authenticated participant",
)
async def get_my_notifications(
    registration_id: Optional[str] = Query(
        default=None, description="Optional registration ID filter"
    ),
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> NotificationListResponse:
    return await list_participant_notifications(
        db, current_user, registration_id=registration_id
    )


@router.post(
    "/{notification_id}/retry",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Manually retry a failed notification after the automatic retry limit",
)
async def manual_retry_notification(
    notification_id: str,
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> NotificationResponse:
    return await retry_failed_notification(db, current_user, notification_id)
