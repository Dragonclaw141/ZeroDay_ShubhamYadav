import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from httpx import AsyncClient

from app.notifications.email import (
    clear_sent_emails_log,
    get_sent_emails_log,
    set_email_failure_hook,
)
from app.notifications.service import process_due_notifications
from app.registrations.service import (
    compute_razorpay_signature,
    expire_stale_reservations,
    set_razorpay_provider_hook,
)
from tests.conftest import FakeDatabase

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_hooks_and_email_log(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_local_eventadda")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "rzp_test_secret_local_eventadda")
    clear_sent_emails_log()
    set_email_failure_hook(None)
    set_razorpay_provider_hook(None)
    yield
    set_email_failure_hook(None)
    set_razorpay_provider_hook(None)


async def _create_user_and_headers(
    client: AsyncClient,
    *,
    email: str,
    phone: str,
    role: str = "participant",
    full_name: str = "Test User",
) -> tuple[dict[str, str], dict]:
    body = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "password": "Password123",
        "role": role,
    }
    if role == "organizer":
        body["organization_name"] = "Test Org"
    res = await client.post("/api/auth/signup", json=body)
    assert res.status_code == 201, res.text
    data = res.json()
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    return headers, data["user"]


async def _create_published_event(
    client: AsyncClient,
    org_headers: dict[str, str],
    *,
    title: str = "Stage 3 Test Event",
    price_type: str = "free",
    price_amount: float | None = None,
    max_capacity: int = 10,
    start_offset_hours: float = 72.0,
    deadline_offset_hours: float | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    start_dt = now + timedelta(hours=start_offset_hours)
    end_dt = start_dt + timedelta(hours=3)
    deadline_dt = (
        now + timedelta(hours=deadline_offset_hours)
        if deadline_offset_hours is not None
        else start_dt - timedelta(hours=1)
    )
    payload = {
        "title": title,
        "description": "Comprehensive Stage 3 event for testing bookings, payments, and reminders.",
        "category": "hackathons",
        "tags": ["python", "fastapi"],
        "venue": {
            "name": "Innovation Hall",
            "address": "Main Campus Road",
            "city": "Mumbai",
        },
        "mode": "In-person",
        "start_date": start_dt.isoformat(),
        "end_date": end_dt.isoformat(),
        "registration_deadline": deadline_dt.isoformat(),
        "max_capacity": max_capacity,
        "status": "published",
        "price_type": price_type,
        "price_amount": price_amount if price_type == "paid" else None,
    }
    res = await client.post("/api/organizer/events", headers=org_headers, json=payload)
    assert res.status_code == 201, res.text
    return res.json()["event"]


async def test_free_event_booking_confirmation_and_event_detail_state(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    org_headers, _ = await _create_user_and_headers(
        client, email="org_free@example.com", phone="+919100000001", role="organizer"
    )
    part_headers, _ = await _create_user_and_headers(
        client, email="part_free@example.com", phone="+919100000002", role="participant"
    )
    event = await _create_published_event(
        client, org_headers, title="Free AI Workshop", price_type="free", max_capacity=5
    )

    # Initially not registered
    detail_before = await client.get(f"/api/events/{event['id']}", headers=part_headers)
    assert detail_before.status_code == 200
    assert detail_before.json()["is_registered"] is False
    assert detail_before.json()["my_registration"] is None

    # Client overrides for price_amount or participant_id must be rejected (422)
    tamper_res = await client.post(
        f"/api/registrations/{event['id']}",
        headers=part_headers,
        json={"price_amount": 0, "participant_id": "fake"},
    )
    assert tamper_res.status_code == 422

    # Register for free event -> immediate confirmation (201)
    reg_res = await client.post(
        f"/api/registrations/{event['id']}",
        headers=part_headers,
        json={},
    )
    assert reg_res.status_code == 201, reg_res.text
    reg_data = reg_res.json()
    assert reg_data["booking_status"] == "confirmed"
    assert reg_data["registration"]["status"] == "confirmed"
    assert reg_data["registration"]["seat_held"] is True
    assert reg_data["razorpay_checkout"] is None

    # Duplicate active booking for same participant & event -> 409 Conflict
    dup_res = await client.post(
        f"/api/registrations/{event['id']}",
        headers=part_headers,
    )
    assert dup_res.status_code == 409

    # GET /api/events/{id} reflects confirmed registration and decremented spots_remaining
    detail_after = await client.get(f"/api/events/{event['id']}", headers=part_headers)
    assert detail_after.status_code == 200
    after_json = detail_after.json()
    assert after_json["is_registered"] is True
    assert after_json["registered_count"] == 1
    assert after_json["spots_remaining"] == 4
    assert after_json["my_registration"]["status"] == "confirmed"

    # Both acknowledgement (sent) and 24h reminder (pending, since event is 72h away) exist
    notif_res = await client.get("/api/notifications/me", headers=part_headers)
    assert notif_res.status_code == 200
    notifs = {n["notification_type"]: n for n in notif_res.json()["notifications"]}
    assert "registration_acknowledgement" in notifs
    assert notifs["registration_acknowledgement"]["status"] == "sent"
    assert "event_reminder" in notifs
    assert notifs["event_reminder"]["status"] == "pending"


async def test_last_seat_concurrency_free_and_paid(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    org_headers, _ = await _create_user_and_headers(
        client, email="org_race@example.com", phone="+919100000010", role="organizer"
    )
    p1_headers, _ = await _create_user_and_headers(
        client, email="p1_race@example.com", phone="+919100000011", role="participant"
    )
    p2_headers, _ = await _create_user_and_headers(
        client, email="p2_race@example.com", phone="+919100000012", role="participant"
    )

    # 1. Free event with max_capacity = 1
    free_ev = await _create_published_event(
        client, org_headers, title="1-Seat Free Event", price_type="free", max_capacity=1
    )
    r1, r2 = await asyncio.gather(
        client.post(f"/api/registrations/{free_ev['id']}", headers=p1_headers),
        client.post(f"/api/registrations/{free_ev['id']}", headers=p2_headers),
    )
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [201, 409]
    ev_doc = await test_db["events"].find_one({"_id": ObjectId(free_ev["id"])})
    assert ev_doc["registered_count"] == 1

    # 2. Paid event with max_capacity = 1
    paid_ev = await _create_published_event(
        client,
        org_headers,
        title="1-Seat Paid Event",
        price_type="paid",
        price_amount=499.0,
        max_capacity=1,
    )
    pr1, pr2 = await asyncio.gather(
        client.post(f"/api/registrations/{paid_ev['id']}", headers=p1_headers),
        client.post(f"/api/registrations/{paid_ev['id']}", headers=p2_headers),
    )
    assert sorted([pr1.status_code, pr2.status_code]) == [201, 409]
    paid_doc = await test_db["events"].find_one({"_id": ObjectId(paid_ev["id"])})
    assert paid_doc["registered_count"] == 1


async def test_paid_booking_verification_idempotency_and_invalid_signature(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    org_headers, _ = await _create_user_and_headers(
        client, email="org_paid@example.com", phone="+919100000020", role="organizer"
    )
    p1_headers, _ = await _create_user_and_headers(
        client, email="p1_paid@example.com", phone="+919100000021", role="participant"
    )
    p2_headers, _ = await _create_user_and_headers(
        client, email="p2_paid@example.com", phone="+919100000022", role="participant"
    )

    paid_ev = await _create_published_event(
        client,
        org_headers,
        title="Paid Summit",
        price_type="paid",
        price_amount=750.0,
        max_capacity=5,
    )

    # Create paid booking -> reserves seat for 15 minutes
    create_res = await client.post(f"/api/registrations/{paid_ev['id']}", headers=p1_headers)
    assert create_res.status_code == 201
    cdata = create_res.json()
    assert cdata["booking_status"] == "pending_payment"
    reg_id = cdata["registration"]["id"]
    order_id = cdata["payment_attempt"]["razorpay_order_id"]
    assert cdata["payment_attempt"]["amount"] == 750.0
    assert cdata["payment_attempt"]["amount_paise"] == 75000
    assert cdata["payment_attempt"]["attempt_number"] == 1

    # Calling POST /api/registrations/{event_id} again while pending_payment recovers the same booking (200 OK)
    recover_res = await client.post(f"/api/registrations/{paid_ev['id']}", headers=p1_headers)
    assert recover_res.status_code == 200
    assert recover_res.json()["recovered_existing"] is True
    assert recover_res.json()["registration"]["id"] == reg_id
    ev_doc = await test_db["events"].find_one({"_id": ObjectId(paid_ev["id"])})
    assert ev_doc["registered_count"] == 1

    # Invalid signature must be rejected (400) and leave booking pending_payment
    bad_sig_res = await client.post(
        f"/api/registrations/{reg_id}/verify-payment",
        headers=p1_headers,
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_valid_001",
            "razorpay_signature": "0000deadbeefinvalid",
        },
    )
    assert bad_sig_res.status_code == 400

    # Valid signature confirms booking and transitions payment to succeeded
    valid_sig = compute_razorpay_signature(order_id, "pay_valid_001")
    verify_res = await client.post(
        f"/api/registrations/{reg_id}/verify-payment",
        headers=p1_headers,
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_valid_001",
            "razorpay_signature": valid_sig,
        },
    )
    assert verify_res.status_code == 200, verify_res.text
    vdata = verify_res.json()
    assert vdata["booking_status"] == "confirmed"
    assert vdata["payment_status"] == "succeeded"
    assert vdata["payment_attempt"]["razorpay_payment_id"] == "pay_valid_001"

    # Repeating verification with the same payment is idempotent
    repeat_res = await client.post(
        f"/api/registrations/{reg_id}/verify-payment",
        headers=p1_headers,
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_valid_001",
            "razorpay_signature": valid_sig,
        },
    )
    assert repeat_res.status_code == 200
    assert repeat_res.json()["booking_status"] == "confirmed"
    ev_doc_after = await test_db["events"].find_one({"_id": ObjectId(paid_ev["id"])})
    assert ev_doc_after["registered_count"] == 1

    # Reusing the same razorpay_payment_id on another participant's booking is rejected (409)
    p2_booking = await client.post(f"/api/registrations/{paid_ev['id']}", headers=p2_headers)
    assert p2_booking.status_code == 201
    p2_reg_id = p2_booking.json()["registration"]["id"]
    p2_order_id = p2_booking.json()["payment_attempt"]["razorpay_order_id"]
    p2_sig_dup = compute_razorpay_signature(p2_order_id, "pay_valid_001")
    dup_pay_res = await client.post(
        f"/api/registrations/{p2_reg_id}/verify-payment",
        headers=p2_headers,
        json={
            "razorpay_order_id": p2_order_id,
            "razorpay_payment_id": "pay_valid_001",
            "razorpay_signature": p2_sig_dup,
        },
    )
    assert dup_pay_res.status_code == 409


async def test_failed_payment_retry_and_reservation_expiry_releases_seat(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    org_headers, _ = await _create_user_and_headers(
        client, email="org_retry@example.com", phone="+919100000030", role="organizer"
    )
    p1_headers, _ = await _create_user_and_headers(
        client, email="p1_retry@example.com", phone="+919100000031", role="participant"
    )
    p2_headers, _ = await _create_user_and_headers(
        client, email="p2_retry@example.com", phone="+919100000032", role="participant"
    )

    paid_ev = await _create_published_event(
        client,
        org_headers,
        title="Paid Retry Bootcamp",
        price_type="paid",
        price_amount=300.0,
        max_capacity=1,
    )

    # P1 reserves the single seat
    res1 = await client.post(f"/api/registrations/{paid_ev['id']}", headers=p1_headers)
    assert res1.status_code == 201
    reg_id = res1.json()["registration"]["id"]
    order_1 = res1.json()["payment_attempt"]["razorpay_order_id"]

    # Attempt #1 fails -> booking stays pending_payment and seat stays held
    fail_res = await client.post(
        f"/api/registrations/{reg_id}/payment-failed",
        headers=p1_headers,
        json={
            "razorpay_order_id": order_1,
            "razorpay_payment_id": "pay_fail_1",
            "error_code": "BAD_REQUEST_ERROR",
            "error_description": "Card declined",
        },
    )
    assert fail_res.status_code == 200
    assert fail_res.json()["booking_status"] == "pending_payment"
    assert fail_res.json()["payment_status"] == "failed"

    # P2 still cannot book while P1's 15m reservation is active
    p2_blocked = await client.post(f"/api/registrations/{paid_ev['id']}", headers=p2_headers)
    assert p2_blocked.status_code == 409

    # P1 initiates a retry -> creates Attempt #2 on the same booking
    retry_res = await client.post(
        f"/api/registrations/{reg_id}/payment-order",
        headers=p1_headers,
    )
    assert retry_res.status_code == 200
    assert retry_res.json()["payment_attempt"]["attempt_number"] == 2
    order_2 = retry_res.json()["payment_attempt"]["razorpay_order_id"]
    assert order_2 != order_1

    # Simulate 16 minutes passing without payment completion -> reservation expires and releases seat
    future_now = datetime.now(timezone.utc) + timedelta(minutes=16)
    expired_count = await expire_stale_reservations(test_db, now=future_now)
    assert expired_count == 1

    ev_doc = await test_db["events"].find_one({"_id": ObjectId(paid_ev["id"])})
    assert ev_doc["registered_count"] == 0

    # P2 can now book the released seat!
    p2_ok = await client.post(f"/api/registrations/{paid_ev['id']}", headers=p2_headers)
    assert p2_ok.status_code == 201


async def test_ambiguous_authorized_payment_preserves_seat_and_late_payment_reconciliation(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    org_headers, _ = await _create_user_and_headers(
        client, email="org_amb@example.com", phone="+919100000040", role="organizer"
    )
    p1_headers, _ = await _create_user_and_headers(
        client, email="p1_amb@example.com", phone="+919100000041", role="participant"
    )
    p2_headers, _ = await _create_user_and_headers(
        client, email="p2_amb@example.com", phone="+919100000042", role="participant"
    )

    ev = await _create_published_event(
        client,
        org_headers,
        title="Ambiguous & Late Payment Event",
        price_type="paid",
        price_amount=600.0,
        max_capacity=1,
    )

    # 1. Ambiguous ('authorized') payment state
    b1 = await client.post(f"/api/registrations/{ev['id']}", headers=p1_headers)
    assert b1.status_code == 201
    reg_id = b1.json()["registration"]["id"]
    order_id = b1.json()["payment_attempt"]["razorpay_order_id"]

    set_razorpay_provider_hook(
        lambda o_id, p_id, amt: {
            "outcome": "authorized",
            "payment_id": "pay_auth_inflight",
            "reason": "Payment authorized and awaiting capture",
        }
    )
    rec_auth = await client.post(
        f"/api/registrations/{reg_id}/reconcile",
        headers=p1_headers,
        json={"razorpay_order_id": order_id},
    )
    assert rec_auth.status_code == 200
    assert rec_auth.json()["booking_status"] == "pending_payment"
    assert rec_auth.json()["payment_status"] == "pending"

    # While payment is 'pending', expiry sweep must NOT expire the booking or release its seat
    future_20m = datetime.now(timezone.utc) + timedelta(minutes=20)
    swept = await expire_stale_reservations(test_db, now=future_20m)
    assert swept == 0

    # Starting another payment order or cancelling is blocked while payment is 'pending'
    blocked_order = await client.post(f"/api/registrations/{reg_id}/payment-order", headers=p1_headers)
    assert blocked_order.status_code == 409
    blocked_cancel = await client.post(f"/api/registrations/{reg_id}/cancel", headers=p1_headers)
    assert blocked_cancel.status_code == 409

    # Suppose gateway later reports failure -> booking now expires once swept, releasing the seat
    set_razorpay_provider_hook(
        lambda o_id, p_id, amt: {
            "outcome": "failed",
            "payment_id": "pay_auth_inflight",
            "reason": "Capture failed at bank",
        }
    )
    rec_fail = await client.post(f"/api/registrations/{reg_id}/reconcile", headers=p1_headers)
    assert rec_fail.status_code == 200
    assert rec_fail.json()["payment_status"] == "failed"

    swept_after_fail = await expire_stale_reservations(test_db, now=future_20m)
    assert swept_after_fail == 1
    reg_doc_exp = await test_db["registrations"].find_one({"_id": ObjectId(reg_id)})
    assert reg_doc_exp["status"] == "expired"
    assert reg_doc_exp["seat_held"] is False

    # 2A. Late payment succeeds after expiry when capacity IS still available -> transitions expired -> confirmed!
    set_razorpay_provider_hook(
        lambda o_id, p_id, amt: {
            "outcome": "captured",
            "payment_id": "pay_late_success_1",
        }
    )
    rec_late_ok = await client.post(f"/api/registrations/{reg_id}/reconcile", headers=p1_headers)
    assert rec_late_ok.status_code == 200
    assert rec_late_ok.json()["booking_status"] == "confirmed"
    assert rec_late_ok.json()["payment_status"] == "succeeded"
    ev_doc_after = await test_db["events"].find_one({"_id": ObjectId(ev["id"])})
    assert ev_doc_after["registered_count"] == 1

    # 2B. Late payment succeeds after expiry when event is SOLD OUT -> transitions to resolution_required!
    ev2 = await _create_published_event(
        client,
        org_headers,
        title="Sold Out Late Payment Event",
        price_type="paid",
        price_amount=600.0,
        max_capacity=1,
    )
    set_razorpay_provider_hook(None)
    b_p1 = await client.post(f"/api/registrations/{ev2['id']}", headers=p1_headers)
    assert b_p1.status_code == 201
    p1_reg2_id = b_p1.json()["registration"]["id"]

    # Expire P1's reservation
    await expire_stale_reservations(
        test_db, now=datetime.now(timezone.utc) + timedelta(minutes=18)
    )

    # P2 books and confirms the only seat on ev2
    b_p2 = await client.post(f"/api/registrations/{ev2['id']}", headers=p2_headers)
    assert b_p2.status_code == 201
    p2_reg2_id = b_p2.json()["registration"]["id"]
    p2_order2 = b_p2.json()["payment_attempt"]["razorpay_order_id"]
    p2_sig = compute_razorpay_signature(p2_order2, "pay_p2_confirmed")
    v_p2 = await client.post(
        f"/api/registrations/{p2_reg2_id}/verify-payment",
        headers=p2_headers,
        json={
            "razorpay_order_id": p2_order2,
            "razorpay_payment_id": "pay_p2_confirmed",
            "razorpay_signature": p2_sig,
        },
    )
    assert v_p2.status_code == 200
    assert v_p2.json()["booking_status"] == "confirmed"

    # Now P1's late payment reconciles as captured after ev2 is sold out
    set_razorpay_provider_hook(
        lambda o_id, p_id, amt: {
            "outcome": "captured",
            "payment_id": "pay_p1_late_soldout",
        }
    )
    rec_late_soldout = await client.post(
        f"/api/registrations/{p1_reg2_id}/reconcile",
        headers=p1_headers,
    )
    assert rec_late_soldout.status_code == 200
    assert rec_late_soldout.json()["booking_status"] == "resolution_required"
    assert rec_late_soldout.json()["payment_status"] == "resolution_required"

    # Capacity was NOT exceeded (registered_count remains 1)
    ev2_doc = await test_db["events"].find_one({"_id": ObjectId(ev2["id"])})
    assert ev2_doc["registered_count"] == 1


async def test_participant_cancellation_organizer_guards_and_booking_views(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    org_headers, _ = await _create_user_and_headers(
        client, email="org_canc@example.com", phone="+919100000050", role="organizer"
    )
    p1_headers, _ = await _create_user_and_headers(
        client, email="p1_canc@example.com", phone="+919100000051", role="participant"
    )
    p2_headers, _ = await _create_user_and_headers(
        client, email="p2_canc@example.com", phone="+919100000052", role="participant"
    )

    ev = await _create_published_event(
        client, org_headers, title="Cancellation Test Event", price_type="free", max_capacity=3
    )

    # P1 and P2 register
    r1 = await client.post(f"/api/registrations/{ev['id']}", headers=p1_headers)
    r2 = await client.post(f"/api/registrations/{ev['id']}", headers=p2_headers)
    assert r1.status_code == 201 and r2.status_code == 201
    reg1_id = r1.json()["registration"]["id"]

    # Organizer cannot reduce max_capacity below registered_count (2)
    cap_fail = await client.put(
        f"/api/organizer/events/{ev['id']}",
        headers=org_headers,
        json={"max_capacity": 1},
    )
    assert cap_fail.status_code == 400

    # P1 appears in Upcoming Confirmed Events
    up_before = await client.get("/api/registrations/upcoming", headers=p1_headers)
    assert up_before.json()["total"] == 1

    # P1 cancels before deadline -> seat released, reminder suppressed, history preserved
    canc_res = await client.post(
        f"/api/registrations/{reg1_id}/cancel",
        headers=p1_headers,
        json={"reason": "Schedule conflict"},
    )
    assert canc_res.status_code == 200
    assert canc_res.json()["booking_status"] == "cancelled"
    assert "does not perform or imply a payment refund" in canc_res.json()["message"]

    # P1 no longer in upcoming, but still in My Bookings history under cancelled_or_expired
    up_after = await client.get("/api/registrations/upcoming", headers=p1_headers)
    assert up_after.json()["total"] == 0

    hist_canc = await client.get(
        "/api/registrations/me?status=cancelled_or_expired", headers=p1_headers
    )
    assert hist_canc.json()["total"] == 1
    assert hist_canc.json()["registrations"][0]["status"] == "cancelled"

    # Reminder for P1 was suppressed
    p1_notifs = await client.get(
        f"/api/notifications/me?registration_id={reg1_id}", headers=p1_headers
    )
    rem = [
        n
        for n in p1_notifs.json()["notifications"]
        if n["notification_type"] == "event_reminder"
    ][0]
    assert rem["status"] == "suppressed"

    # Organizer cancels the event -> P2's reminder is suppressed and P2's upcoming list becomes empty
    org_cancel = await client.patch(
        f"/api/organizer/events/{ev['id']}/cancel", headers=org_headers
    )
    assert org_cancel.status_code == 200
    p2_up = await client.get("/api/registrations/upcoming", headers=p2_headers)
    assert p2_up.json()["total"] == 0


async def test_notifications_24h_reminder_retries_crash_recovery_and_isolation(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    org_headers, _ = await _create_user_and_headers(
        client, email="org_notif@example.com", phone="+919100000060", role="organizer"
    )
    p1_headers, _ = await _create_user_and_headers(
        client, email="p1_notif@example.com", phone="+919100000061", role="participant"
    )

    # 1. Acknowledgement failure must NOT block booking confirmation or event reminder!
    ev_near = await _create_published_event(
        client,
        org_headers,
        title="Starting in 6 Hours Event",
        price_type="free",
        max_capacity=10,
        start_offset_hours=6.0,
        deadline_offset_hours=5.0,
    )

    # Fail only registration_acknowledgement emails
    set_email_failure_hook(
        lambda ntype, recipient: ntype == "registration_acknowledgement"
    )

    reg_res = await client.post(f"/api/registrations/{ev_near['id']}", headers=p1_headers)
    assert reg_res.status_code == 201
    assert reg_res.json()["booking_status"] == "confirmed"
    reg_id = reg_res.json()["registration"]["id"]

    notifs_res = await client.get(
        f"/api/notifications/me?registration_id={reg_id}", headers=p1_headers
    )
    notifs = {n["notification_type"]: n for n in notifs_res.json()["notifications"]}
    # Because event is < 24h away (6h), reminder was scheduled immediately and succeeded!
    assert notifs["event_reminder"]["status"] == "sent"
    assert notifs["registration_acknowledgement"]["status"] == "pending"
    assert notifs["registration_acknowledgement"]["attempt_count"] == 1

    # 2. Bounded retries (3 attempts -> failed) on persistent failure
    ack_id = notifs["registration_acknowledgement"]["id"]
    t_base = datetime.now(timezone.utc)
    await process_due_notifications(test_db, now=t_base + timedelta(minutes=2))
    await process_due_notifications(test_db, now=t_base + timedelta(minutes=10))

    ack_doc = await test_db["notifications"].find_one({"_id": ObjectId(ack_id)})
    assert ack_doc["status"] == "failed"
    assert ack_doc["attempt_count"] == 3

    # Manual retry endpoint recovers once email service is restored
    set_email_failure_hook(None)
    manual_retry = await client.post(
        f"/api/notifications/{ack_id}/retry", headers=p1_headers
    )
    assert manual_retry.status_code == 200
    assert manual_retry.json()["status"] == "sent"

    # 3. Stale processing lease recovery (simulated worker crash mid-delivery)
    ev_future = await _create_published_event(
        client,
        org_headers,
        title="48h Future Event",
        price_type="free",
        max_capacity=10,
        start_offset_hours=48.0,
    )
    reg2_res = await client.post(f"/api/registrations/{ev_future['id']}", headers=p1_headers)
    reg2_id = reg2_res.json()["registration"]["id"]

    rem_doc = await test_db["notifications"].find_one(
        {"registration_id": ObjectId(reg2_id), "notification_type": "event_reminder"}
    )
    assert rem_doc["status"] == "pending"

    # Simulate a crashed worker that claimed the reminder 10 minutes ago and left an expired lease
    sim_now = datetime.now(timezone.utc) + timedelta(hours=25)
    await test_db["notifications"].update_one(
        {"_id": rem_doc["_id"]},
        {
            "$set": {
                "status": "processing",
                "processing_lease_until": sim_now - timedelta(minutes=5),
            }
        },
    )
    summary_counts = await process_due_notifications(test_db, now=sim_now)
    assert summary_counts["sent"] >= 1
    recovered_doc = await test_db["notifications"].find_one({"_id": rem_doc["_id"]})
    assert recovered_doc["status"] == "sent"
    assert len(get_sent_emails_log()) >= 3


async def test_authorization_and_cross_participant_isolation(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    org_headers, _ = await _create_user_and_headers(
        client, email="org_authz@example.com", phone="+919100000070", role="organizer"
    )
    p1_headers, _ = await _create_user_and_headers(
        client, email="p1_authz@example.com", phone="+919100000071", role="participant"
    )
    p2_headers, _ = await _create_user_and_headers(
        client, email="p2_authz@example.com", phone="+919100000072", role="participant"
    )

    ev = await _create_published_event(client, org_headers, title="Authz Event")

    # Unauthenticated -> 401
    unauth = await client.post(f"/api/registrations/{ev['id']}")
    assert unauth.status_code in (401, 403)

    # Organizer cannot register as participant -> 403
    org_reg = await client.post(f"/api/registrations/{ev['id']}", headers=org_headers)
    assert org_reg.status_code == 403

    # P1 creates booking; P2 cannot view or cancel P1's booking -> 404
    p1_reg = await client.post(f"/api/registrations/{ev['id']}", headers=p1_headers)
    reg_id = p1_reg.json()["registration"]["id"]

    p2_get = await client.get(f"/api/registrations/{reg_id}", headers=p2_headers)
    assert p2_get.status_code == 404

    p2_cancel = await client.post(f"/api/registrations/{reg_id}/cancel", headers=p2_headers)
    assert p2_cancel.status_code == 404


# ---------------------------------------------------------------------------
# Regression: paid checkout failed with
#   "razorpay_signature: String should have at least 8 characters"
# because the modal read non-existent checkout fields (test_signature,
# test_payment_id, prefill) and sent an empty signature.
# ---------------------------------------------------------------------------


async def _setup_paid_booking(client: AsyncClient, suffix: str, max_capacity: int = 2):
    org_headers, _ = await _create_user_and_headers(
        client, email=f"org_{suffix}@example.com", phone=f"+91920000{suffix}0", role="organizer"
    )
    part_headers, part_user = await _create_user_and_headers(
        client,
        email=f"part_{suffix}@example.com",
        phone=f"+91920000{suffix}1",
        role="participant",
        full_name="Priya Sharma",
    )
    ev = await _create_published_event(
        client,
        org_headers,
        title=f"Paid Checkout {suffix}",
        price_type="paid",
        price_amount=499.0,
        max_capacity=max_capacity,
    )
    res = await client.post(f"/api/registrations/{ev['id']}", headers=part_headers)
    assert res.status_code == 201, res.text
    return ev, part_headers, part_user, res.json()


async def test_regression_old_frontend_payload_empty_signature_is_rejected(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    ev, headers, _, data = await _setup_paid_booking(client, "101")
    checkout = data["razorpay_checkout"]
    reg_id = data["registration"]["id"]

    # The old modal sent checkout.test_signature || '' -> '' (field never existed)
    assert "test_signature" not in checkout
    old_payload = {
        "razorpay_order_id": checkout["order_id"],
        "razorpay_payment_id": "pay_test_1729800000000",
        "razorpay_signature": checkout.get("test_signature") or "",
    }
    res = await client.post(
        f"/api/registrations/{reg_id}/verify-payment", headers=headers, json=old_payload
    )
    assert res.status_code == 422
    assert any(err["loc"][-1] == "razorpay_signature" for err in res.json()["detail"])

    # A real-looking signature for a payment ID other than the one signed is still rejected
    res_mismatch = await client.post(
        f"/api/registrations/{reg_id}/verify-payment",
        headers=headers,
        json={
            "razorpay_order_id": checkout["order_id"],
            "razorpay_payment_id": "pay_test_somethingelse",
            "razorpay_signature": checkout["local_test_signature_Token"],
        },
    )
    assert res_mismatch.status_code == 400

    reg_doc = await test_db["registrations"].find_one({"_id": ObjectId(reg_id)})
    assert reg_doc["status"] == "pending_payment"
    ev_doc = await test_db["events"].find_one({"_id": ObjectId(ev["id"])})
    assert ev_doc["registered_count"] == 1


async def test_sandbox_checkout_config_exposes_participant_and_signed_payment_id(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    _, _, part_user, data = await _setup_paid_booking(client, "102")
    checkout = data["razorpay_checkout"]
    assert checkout["sandbox_mode"] is True
    assert checkout["participant_name"] == "Priya Sharma"
    assert checkout["participant_email"] == part_user["email"]
    assert checkout["amount_inr"] == 499.0
    assert checkout["amount_paise"] == 49900
    assert checkout["local_test_payment_id"]
    assert checkout["local_test_signature_Token"] == compute_razorpay_signature(
        checkout["order_id"], checkout["local_test_payment_id"]
    )
    # Secret is never exposed to the client
    assert "secret" not in str(checkout).lower()

    pay_doc = await test_db["payments"].find_one(
        {"razorpay_order_id": checkout["order_id"]}
    )
    assert pay_doc["gateway_mode"] == "local_sandbox"


async def test_paid_checkout_success_with_frontend_payload_confirms_and_schedules_emails(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    ev, headers, _, data = await _setup_paid_booking(client, "103")
    checkout = data["razorpay_checkout"]
    reg_id = data["registration"]["id"]

    # Exactly what the fixed modal sends
    payload = {
        "razorpay_order_id": checkout["order_id"],
        "razorpay_payment_id": checkout["local_test_payment_id"],
        "razorpay_signature": checkout["local_test_signature_Token"],
    }
    res = await client.post(
        f"/api/registrations/{reg_id}/verify-payment", headers=headers, json=payload
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["booking_status"] == "confirmed"
    assert body["payment_status"] == "succeeded"

    # Idempotent repeat does not double-count capacity
    again = await client.post(
        f"/api/registrations/{reg_id}/verify-payment", headers=headers, json=payload
    )
    assert again.status_code == 200
    ev_doc = await test_db["events"].find_one({"_id": ObjectId(ev["id"])})
    assert ev_doc["registered_count"] == 1

    notifs = await client.get(
        f"/api/notifications/me?registration_id={reg_id}", headers=headers
    )
    by_type = {n["notification_type"]: n for n in notifs.json()["notifications"]}
    assert by_type["registration_acknowledgement"]["status"] == "sent"
    assert by_type["event_reminder"]["status"] == "pending"


async def test_paid_checkout_failure_then_retry_succeeds_with_new_attempt(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    ev, headers, _, data = await _setup_paid_booking(client, "104", max_capacity=1)
    checkout = data["razorpay_checkout"]
    reg_id = data["registration"]["id"]

    fail = await client.post(
        f"/api/registrations/{reg_id}/payment-failed",
        headers=headers,
        json={
            "razorpay_order_id": checkout["order_id"],
            "razorpay_payment_id": "pay_failed_1",
            "error_code": "BAD_REQUEST_ERROR",
            "error_description": "Simulated test payment declined by bank",
        },
    )
    assert fail.status_code == 200
    assert fail.json()["booking_status"] == "pending_payment"
    assert fail.json()["payment_status"] == "failed"
    ev_doc = await test_db["events"].find_one({"_id": ObjectId(ev["id"])})
    assert ev_doc["registered_count"] == 1  # seat still held

    retry = await client.post(f"/api/registrations/{reg_id}/payment-order", headers=headers)
    assert retry.status_code == 200
    retry_checkout = retry.json()["razorpay_checkout"]
    assert retry.json()["payment_attempt"]["attempt_number"] == 2
    assert retry_checkout["order_id"] != checkout["order_id"]

    # The attempt-1 token cannot confirm attempt 2
    stale = await client.post(
        f"/api/registrations/{reg_id}/verify-payment",
        headers=headers,
        json={
            "razorpay_order_id": retry_checkout["order_id"],
            "razorpay_payment_id": checkout["local_test_payment_id"],
            "razorpay_signature": checkout["local_test_signature_Token"],
        },
    )
    assert stale.status_code == 400

    ok = await client.post(
        f"/api/registrations/{reg_id}/verify-payment",
        headers=headers,
        json={
            "razorpay_order_id": retry_checkout["order_id"],
            "razorpay_payment_id": retry_checkout["local_test_payment_id"],
            "razorpay_signature": retry_checkout["local_test_signature_Token"],
        },
    )
    assert ok.status_code == 200
    assert ok.json()["booking_status"] == "confirmed"
    ev_doc = await test_db["events"].find_one({"_id": ObjectId(ev["id"])})
    assert ev_doc["registered_count"] == 1


async def test_non_sandbox_mode_issues_no_client_signature(monkeypatch):
    from app.config import settings as app_settings
    from app.registrations import service as reg_service

    monkeypatch.setattr(app_settings, "RAZORPAY_KEY_ID", "rzp_test_RealKeyExample")
    cfg = reg_service._build_checkout_config(
        order_id="order_RealTest123456",
        amount_inr=499.0,
        amount_paise=49900,
        event_doc={"_id": ObjectId(), "title": "Real Mode Event"},
        reg_doc={"_id": ObjectId(), "currency": "INR"},
        user_doc={"full_name": "Priya", "email": "p@example.com", "phone": "+919000000000"},
    )
    assert cfg.sandbox_mode is False
    assert cfg.local_test_payment_id is None
    assert cfg.local_test_signature_Token is None


async def test_frontend_modal_uses_backend_checkout_fields():
    from pathlib import Path

    main_js = (
        Path(__file__).resolve().parent.parent.parent / "frontend" / "js" / "main.js"
    ).read_text(encoding="utf-8")
    assert "checkout.local_test_signature_Token" in main_js
    assert "checkout.local_test_payment_id" in main_js
    assert "checkout.participant_name" in main_js
    assert "checkout.test_signature" not in main_js
    assert "checkout.prefill" not in main_js


async def test_razorpay_checkout_js_and_frontend_contract():
    from pathlib import Path

    root_dir = Path(__file__).resolve().parent.parent.parent
    event_html = (root_dir / "frontend" / "event.html").read_text(encoding="utf-8")
    dashboard_html = (root_dir / "frontend" / "dashboard-participant.html").read_text(
        encoding="utf-8"
    )
    main_js = (root_dir / "frontend" / "js" / "main.js").read_text(encoding="utf-8")

    # Script tag inclusion
    assert "https://checkout.razorpay.com/v1/checkout.js" in event_html
    assert "https://checkout.razorpay.com/v1/checkout.js" in dashboard_html

    # Dynamic loader and checkout integration
    assert "function loadRazorpayScript()" in main_js
    assert "async function startRazorpayCheckout(mutationRes, onComplete)" in main_js
    assert "new window.Razorpay(options)" in main_js
    assert "ondismiss: function" in main_js
    assert "rzp.on('payment.failed'" in main_js
    assert "/verify-payment" in main_js
    assert "/payment-failed" in main_js
    assert "checkout.sandbox_mode" in main_js
    assert "checkout.participant_phone" not in main_js
    assert "contact:" not in main_js


async def test_real_razorpay_order_creation_and_payment_flow(monkeypatch, client, test_db):
    import hashlib
    import hmac
    import httpx
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "RAZORPAY_KEY_ID", "rzp_test_LiveTestKey999")
    monkeypatch.setattr(app_settings, "RAZORPAY_KEY_SECRET", "LiveTestSecretABC789")

    mock_order_id = "order_live_rzp_mock_12345"
    mock_payment_id = "pay_live_rzp_mock_67890"

    class MockResponse:
        def __init__(self, status_code: int, json_data: dict, text: str = ""):
            self.status_code = status_code
            self._json_data = json_data
            self.text = text

        def json(self):
            return self._json_data

    orig_post = httpx.AsyncClient.post
    orig_get = httpx.AsyncClient.get

    async def mock_post(self, url, **kwargs):
        if "api.razorpay.com" in str(url):
            assert "orders" in str(url)
            assert kwargs.get("auth") == ("rzp_test_LiveTestKey999", "LiveTestSecretABC789")
            assert kwargs.get("json", {}).get("amount") == 49900
            return MockResponse(201, {"id": mock_order_id, "amount": 49900, "currency": "INR"})
        return await orig_post(self, url, **kwargs)

    async def mock_get(self, url, **kwargs):
        if "api.razorpay.com" in str(url):
            assert f"payments/{mock_payment_id}" in str(url)
            assert kwargs.get("auth") == ("rzp_test_LiveTestKey999", "LiveTestSecretABC789")
            return MockResponse(
                200,
                {
                    "id": mock_payment_id,
                    "order_id": mock_order_id,
                    "status": "captured",
                    "amount": 49900,
                    "currency": "INR",
                },
            )
        return await orig_get(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    org_headers, _ = await _create_user_and_headers(
        client,
        email="org_real_rzp@example.com",
        phone="+919810011001",
        role="organizer",
    )
    ev = await _create_published_event(
        client,
        org_headers,
        title="Real RZP Mode Paid Event",
        price_type="paid",
        price_amount=499.0,
        max_capacity=5,
    )

    p_headers, _ = await _create_user_and_headers(
        client,
        email="part_real_rzp@example.com",
        phone="+919810022002",
        role="participant",
        full_name="Real Participant",
    )

    # 1. Start booking in real Razorpay Test Mode
    book_res = await client.post(f"/api/registrations/{ev['id']}", headers=p_headers, json={})
    assert book_res.status_code in (200, 201)
    bdata = book_res.json()
    assert bdata["booking_status"] == "pending_payment"
    checkout = bdata["razorpay_checkout"]
    assert checkout["order_id"] == mock_order_id
    assert checkout["key_id"] == "rzp_test_LiveTestKey999"
    assert checkout["amount_paise"] == 49900
    assert checkout["amount_inr"] == 499.0
    assert checkout["sandbox_mode"] is False
    assert checkout["local_test_payment_id"] is None
    assert checkout["local_test_signature_Token"] is None

    # 2. Complete payment verification with genuine HMAC signature
    sig_payload = f"{mock_order_id}|{mock_payment_id}".encode("utf-8")
    valid_sig = hmac.new(b"LiveTestSecretABC789", sig_payload, hashlib.sha256).hexdigest()

    reg_id = bdata["registration"]["id"]
    verify_res = await client.post(
        f"/api/registrations/{reg_id}/verify-payment",
        headers=p_headers,
        json={
            "razorpay_order_id": mock_order_id,
            "razorpay_payment_id": mock_payment_id,
            "razorpay_signature": valid_sig,
        },
    )
    assert verify_res.status_code == 200
    vdata = verify_res.json()
    assert vdata["booking_status"] == "confirmed"
    assert vdata["payment_status"] == "succeeded"

    # Confirm event capacity was updated
    ev_doc = await test_db["events"].find_one({"_id": ObjectId(ev["id"])})
    assert ev_doc["registered_count"] == 1


async def test_real_mode_missing_secret_fails_gracefully(monkeypatch, client, test_db):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "RAZORPAY_KEY_ID", "rzp_test_LiveTestKey999")
    monkeypatch.setattr(app_settings, "RAZORPAY_KEY_SECRET", "")

    org_headers, _ = await _create_user_and_headers(
        client,
        email="org_no_secret@example.com",
        phone="+919810033003",
        role="organizer",
    )
    ev = await _create_published_event(
        client,
        org_headers,
        title="No Secret Event",
        price_type="paid",
        price_amount=299.0,
    )

    p_headers, _ = await _create_user_and_headers(
        client,
        email="part_no_secret@example.com",
        phone="+919810044004",
        role="participant",
    )

    res = await client.post(f"/api/registrations/{ev['id']}", headers=p_headers, json={})
    assert res.status_code == 502
    assert "Razorpay API credentials misconfigured on server" in res.json()["detail"]


async def test_real_mode_razorpay_api_401_fails_gracefully(monkeypatch, client, test_db):
    import httpx
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "RAZORPAY_KEY_ID", "rzp_test_LiveTestKey999")
    monkeypatch.setattr(app_settings, "RAZORPAY_KEY_SECRET", "BadSecret123")

    class MockResponse:
        def __init__(self, status_code: int, text: str = "Unauthorized"):
            self.status_code = status_code
            self.text = text

        def json(self):
            return {"error": {"description": "Invalid key secret"}}

    orig_post = httpx.AsyncClient.post

    async def mock_post_401(self, url, **kwargs):
        if "api.razorpay.com" in str(url):
            return MockResponse(401, "Unauthorized")
        return await orig_post(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post_401)

    org_headers, _ = await _create_user_and_headers(
        client,
        email="org_401@example.com",
        phone="+919810055005",
        role="organizer",
    )
    ev = await _create_published_event(
        client,
        org_headers,
        title="401 Auth Event",
        price_type="paid",
        price_amount=199.0,
    )

    p_headers, _ = await _create_user_and_headers(
        client,
        email="part_401@example.com",
        phone="+919810066006",
        role="participant",
    )

    res = await client.post(f"/api/registrations/{ev['id']}", headers=p_headers, json={})
    assert res.status_code == 502
    assert "Payment gateway authentication failed" in res.json()["detail"]


async def test_real_mode_razorpay_api_timeout_fails_gracefully(monkeypatch, client, test_db):
    import httpx
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "RAZORPAY_KEY_ID", "rzp_test_LiveTestKey999")
    monkeypatch.setattr(app_settings, "RAZORPAY_KEY_SECRET", "ValidSecretXYZ")

    orig_post = httpx.AsyncClient.post

    async def mock_post_timeout(self, url, **kwargs):
        if "api.razorpay.com" in str(url):
            raise httpx.ConnectTimeout("Connection timed out")
        return await orig_post(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post_timeout)

    org_headers, _ = await _create_user_and_headers(
        client,
        email="org_timeout@example.com",
        phone="+919810077007",
        role="organizer",
    )
    ev = await _create_published_event(
        client,
        org_headers,
        title="Timeout Event",
        price_type="paid",
        price_amount=350.0,
    )

    p_headers, _ = await _create_user_and_headers(
        client,
        email="part_timeout@example.com",
        phone="+919810088008",
        role="participant",
    )

    res = await client.post(f"/api/registrations/{ev['id']}", headers=p_headers, json={})
    assert res.status_code == 502
    assert "Payment gateway is temporarily unreachable" in res.json()["detail"]
