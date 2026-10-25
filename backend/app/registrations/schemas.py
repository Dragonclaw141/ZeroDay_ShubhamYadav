from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.events.schemas import EventVenue, PriceTypeLiteral

BookingStatusLiteral = Literal[
    "pending_payment",
    "confirmed",
    "cancelled",
    "expired",
    "resolution_required",
]

PaymentStatusLiteral = Literal[
    "created",
    "pending",
    "succeeded",
    "failed",
    "resolution_required",
]


class RegistrationCreateRequest(BaseModel):
    """Request body for creating a registration. Forbids client-supplied price or participant overrides."""

    model_config = ConfigDict(extra="forbid")

    notes: Optional[str] = Field(default=None, max_length=300)


class RegistrationCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Optional[str] = Field(default=None, max_length=300)


class PaymentVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    razorpay_order_id: str = Field(..., min_length=4, max_length=120)
    razorpay_payment_id: str = Field(..., min_length=4, max_length=120)
    razorpay_signature: str = Field(..., min_length=8, max_length=256)


class PaymentFailureReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    razorpay_order_id: str = Field(..., min_length=4, max_length=120)
    razorpay_payment_id: Optional[str] = Field(default=None, max_length=120)
    error_code: Optional[str] = Field(default=None, max_length=100)
    error_description: Optional[str] = Field(default=None, max_length=500)


class PaymentReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    razorpay_order_id: Optional[str] = Field(default=None, max_length=120)
    razorpay_payment_id: Optional[str] = Field(default=None, max_length=120)


class RazorpayCheckoutConfig(BaseModel):
    key_id: str
    order_id: str
    amount_paise: int
    amount_inr: float
    currency: str = "INR"
    event_id: str
    event_title: str
    registration_id: str
    participant_name: str
    participant_email: str
    participant_phone: str
    test_mode: bool = True
    sandbox_mode: bool = Field(
        default=False,
        description="True only for the local simulated checkout (RAZORPAY_KEY_ID starting with rzp_test_local). No real Razorpay payment occurs in this mode.",
    )
    local_test_payment_id: Optional[str] = Field(
        default=None,
        description="Local sandbox only: the simulated payment ID that local_test_signature_Token was signed for.",
    )
    local_test_signature_Token: Optional[str] = Field(
        default=None,
        description="Populated only in local sandbox test mode (rzp_test_local*) so the in-app Razorpay Test Checkout modal can simulate signed test payments without external keys.",
    )


class PaymentAttemptResponse(BaseModel):
    id: str
    registration_id: str
    event_id: str
    participant_id: str
    attempt_number: int
    amount: float
    amount_paise: int
    currency: str = "INR"
    razorpay_order_id: str
    razorpay_payment_id: Optional[str] = None
    status: PaymentStatusLiteral
    failure_reason: Optional[str] = None
    verified_at: Optional[datetime] = None
    reconciled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class BookingEventSummary(BaseModel):
    id: str
    title: str
    category: str
    venue: EventVenue
    mode: str = "In-person"
    start_date: datetime
    end_date: datetime
    registration_deadline: datetime
    status: str
    organizer_name: str
    price_type: PriceTypeLiteral
    price_amount: Optional[float] = None


class RegistrationResponse(BaseModel):
    id: str
    participant_id: str
    event_id: str
    status: BookingStatusLiteral
    status_label: str
    seat_held: bool
    price_type: PriceTypeLiteral
    price_amount: float = 0.0
    currency: str = "INR"
    reservation_expires_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    resolution_reason: Optional[str] = None
    can_cancel: bool = False
    can_retry_payment: bool = False
    attendance_note: str = (
        "Confirmed registration reserves your seat; venue check-in is handled separately."
    )
    refund_policy_note: str = (
        "Cancellations preserve booking history and do not perform or imply a payment refund."
    )
    event: Optional[BookingEventSummary] = None
    latest_payment: Optional[PaymentAttemptResponse] = None
    payment_attempts_count: int = 0
    created_at: datetime
    updated_at: datetime


class RegistrationMutationResponse(BaseModel):
    message: str
    booking_status: BookingStatusLiteral
    payment_status: Optional[PaymentStatusLiteral] = None
    recovered_existing: bool = False
    registration: RegistrationResponse
    payment_attempt: Optional[PaymentAttemptResponse] = None
    razorpay_checkout: Optional[RazorpayCheckoutConfig] = None


class RegistrationListResponse(BaseModel):
    registrations: list[RegistrationResponse]
    total: int


def booking_status_label(status_val: str) -> str:
    labels = {
        "confirmed": "Confirmed",
        "pending_payment": "Payment Pending (15m Seat Hold)",
        "cancelled": "Cancelled",
        "expired": "Reservation Expired",
        "resolution_required": "Resolution Required",
    }
    return labels.get(status_val, status_val.replace("_", " ").title())
