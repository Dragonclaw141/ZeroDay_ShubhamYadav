from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Query, Response, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.dependencies import require_participant
from app.registrations.schemas import (
    PaymentFailureReportRequest,
    PaymentReconcileRequest,
    PaymentVerifyRequest,
    RegistrationCancelRequest,
    RegistrationCreateRequest,
    RegistrationListResponse,
    RegistrationMutationResponse,
    RegistrationResponse,
)
from app.registrations.service import (
    cancel_participant_registration,
    create_or_recover_registration,
    create_payment_order_for_booking,
    get_participant_registration_detail,
    list_participant_registrations,
    list_upcoming_confirmed_registrations,
    reconcile_booking_payment,
    record_failed_payment_attempt,
    verify_booking_payment,
)

router = APIRouter(prefix="/api/registrations", tags=["Registrations & Payments"])


@router.get(
    "/me",
    response_model=RegistrationListResponse,
    summary="List authenticated participant's full booking history with optional status filter",
)
async def get_my_registrations(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by booking status: all, confirmed, pending_payment, cancelled, expired, resolution_required, or cancelled_or_expired",
    ),
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RegistrationListResponse:
    return await list_participant_registrations(
        db,
        current_user,
        status_filter=status_filter,
    )


@router.get(
    "/upcoming",
    response_model=RegistrationListResponse,
    summary="List authenticated participant's upcoming confirmed event bookings",
)
async def get_my_upcoming_registrations(
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RegistrationListResponse:
    return await list_upcoming_confirmed_registrations(db, current_user)


@router.get(
    "/{registration_id}",
    response_model=RegistrationResponse,
    summary="Get details of a single booking owned by the authenticated participant",
)
async def get_registration_detail(
    registration_id: str,
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RegistrationResponse:
    return await get_participant_registration_detail(
        db,
        current_user,
        registration_id,
    )


@router.post(
    "/{event_id}",
    response_model=RegistrationMutationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an in-app booking (confirm immediately for free events or reserve seat for 15m for paid events)",
)
async def register_for_event(
    event_id: str,
    response: Response,
    _payload: Optional[RegistrationCreateRequest] = Body(default=None),
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RegistrationMutationResponse:
    result, http_status = await create_or_recover_registration(
        db,
        current_user,
        event_id,
    )
    response.status_code = http_status
    return result


@router.post(
    "/{registration_id}/payment-order",
    response_model=RegistrationMutationResponse,
    summary="Create a new Razorpay Test Mode payment order / attempt for an active pending_payment booking",
)
async def create_booking_payment_order(
    registration_id: str,
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RegistrationMutationResponse:
    return await create_payment_order_for_booking(
        db,
        current_user,
        registration_id,
    )


@router.post(
    "/{registration_id}/verify-payment",
    response_model=RegistrationMutationResponse,
    summary="Verify Razorpay payment signature server-side and confirm the booking",
)
async def verify_registration_payment(
    registration_id: str,
    payload: PaymentVerifyRequest,
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RegistrationMutationResponse:
    return await verify_booking_payment(
        db,
        current_user,
        registration_id,
        payload,
    )


@router.post(
    "/{registration_id}/payment-failed",
    response_model=RegistrationMutationResponse,
    summary="Record a failed checkout attempt while preserving the 15-minute seat reservation for retry",
)
async def report_registration_payment_failure(
    registration_id: str,
    payload: PaymentFailureReportRequest,
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RegistrationMutationResponse:
    return await record_failed_payment_attempt(
        db,
        current_user,
        registration_id,
        payload,
    )


@router.post(
    "/{registration_id}/reconcile",
    response_model=RegistrationMutationResponse,
    summary="Reconcile authoritative payment and booking state server-side",
)
async def reconcile_registration_payment(
    registration_id: str,
    payload: Optional[PaymentReconcileRequest] = Body(default=None),
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RegistrationMutationResponse:
    return await reconcile_booking_payment(
        db,
        current_user,
        registration_id,
        payload=payload,
    )


@router.post(
    "/{registration_id}/cancel",
    response_model=RegistrationMutationResponse,
    summary="Cancel a participant booking before the event registration deadline",
)
async def cancel_registration(
    registration_id: str,
    payload: Optional[RegistrationCancelRequest] = Body(default=None),
    current_user: dict[str, Any] = Depends(require_participant),
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> RegistrationMutationResponse:
    return await cancel_participant_registration(
        db,
        current_user,
        registration_id,
        payload=payload,
    )
