from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from bson import ObjectId
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create_organizer(
    client: AsyncClient,
    *,
    email: str = "org1@example.com",
    phone: str = "9100000001",
    full_name: str = "Rahul Mehta",
    org_name: str = "Symbiosis Tech Club",
) -> tuple[str, dict[str, Any]]:
    res = await client.post(
        "/api/auth/signup",
        json={
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "password": "OrganizerPass1",
            "role": "organizer",
            "organization_name": org_name,
        },
    )
    assert res.status_code == 201
    data = res.json()
    return data["access_token"], data["user"]


async def _create_participant(
    client: AsyncClient,
    *,
    email: str = "part1@example.com",
    phone: str = "9200000001",
    interests: list[str] | None = None,
    city: str = "Pune",
    onboard: bool = True,
) -> tuple[str, dict[str, Any]]:
    res = await client.post(
        "/api/auth/signup",
        json={
            "full_name": "Priya Sharma",
            "email": email,
            "phone": phone,
            "password": "ParticipantPass1",
            "role": "participant",
            "affiliation_details": "COEP Pune / CS",
        },
    )
    assert res.status_code == 201
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    if onboard:
        await client.put(
            "/api/onboarding/interests",
            json={"interests": interests or ["hackathons", "tech"]},
            headers=headers,
        )
        await client.put(
            "/api/onboarding/location",
            json={"city": city},
            headers=headers,
        )
        await client.post("/api/onboarding/complete", headers=headers)

    me = await client.get("/api/auth/me", headers=headers)
    return token, me.json()


def _sample_event_payload(
    *,
    title: str = "HackPune 2026 — 36-Hour National Hackathon",
    category: str = "hackathons",
    city: str = "Pune",
    days_ahead: int = 10,
    max_capacity: int = 200,
    status: str = "draft",
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    start_dt = now + timedelta(days=days_ahead)
    end_dt = start_dt + timedelta(hours=36)
    deadline_dt = start_dt - timedelta(days=2)
    return {
        "title": title,
        "description": "Join developers for a coding marathon building AI and Web3 solutions.",
        "category": category,
        "tags": ["AI", "web3", "python"],
        "venue": {
            "name": "Symbiosis Institute of Technology",
            "address": "Gram Lavale, Mulshi",
            "city": city,
            "coordinates": {"type": "Point", "coordinates": [73.7898, 18.5642]},
        },
        "start_date": start_dt.isoformat(),
        "end_date": end_dt.isoformat(),
        "registration_deadline": deadline_dt.isoformat(),
        "max_capacity": max_capacity,
        "status": status,
        "mode": "In-person",
        "is_free": True,
    }


async def test_organizer_create_list_get_and_update_event(client: AsyncClient):
    org_token, _ = await _create_organizer(client)
    headers = {"Authorization": f"Bearer {org_token}"}

    # Create draft event
    create_res = await client.post(
        "/api/organizer/events",
        json=_sample_event_payload(status="draft"),
        headers=headers,
    )
    assert create_res.status_code == 201
    event_data = create_res.json()["event"]
    event_id = event_data["id"]
    assert event_data["status"] == "draft"
    assert event_data["organizer_name"] == "Symbiosis Tech Club"
    assert event_data["spots_remaining"] == 200
    assert event_data["registration_open"] is False

    # List organizer's own events
    list_res = await client.get("/api/organizer/events", headers=headers)
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 1
    assert list_res.json()["events"][0]["id"] == event_id

    # Retrieve single event detail via organizer endpoint
    get_res = await client.get(f"/api/organizer/events/{event_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["title"].startswith("HackPune 2026")

    # Update event title and venue
    upd_res = await client.put(
        f"/api/organizer/events/{event_id}",
        json={
            "title": "HackPune 2026 — Grand Finale Edition",
            "max_capacity": 350,
            "venue": {
                "name": "Balewadi Stadium Tech Center",
                "address": "Baner",
                "city": "Pune",
            },
        },
        headers=headers,
    )
    assert upd_res.status_code == 200
    updated_ev = upd_res.json()["event"]
    assert updated_ev["title"] == "HackPune 2026 — Grand Finale Edition"
    assert updated_ev["max_capacity"] == 350
    assert updated_ev["venue"]["name"] == "Balewadi Stadium Tech Center"


async def test_event_validation_errors(client: AsyncClient):
    org_token, _ = await _create_organizer(client)
    headers = {"Authorization": f"Bearer {org_token}"}

    now = datetime.now(timezone.utc)
    start_dt = now + timedelta(days=5)

    # 1. end_date before start_date -> 422
    bad_end = _sample_event_payload()
    bad_end["start_date"] = start_dt.isoformat()
    bad_end["end_date"] = (start_dt - timedelta(hours=2)).isoformat()
    res1 = await client.post("/api/organizer/events", json=bad_end, headers=headers)
    assert res1.status_code == 422

    # 2. registration_deadline after start_date -> 422
    bad_deadline = _sample_event_payload()
    bad_deadline["start_date"] = start_dt.isoformat()
    bad_deadline["end_date"] = (start_dt + timedelta(hours=5)).isoformat()
    bad_deadline["registration_deadline"] = (start_dt + timedelta(hours=1)).isoformat()
    res2 = await client.post("/api/organizer/events", json=bad_deadline, headers=headers)
    assert res2.status_code == 422

    # 3. Invalid capacity (< 1) -> 422
    bad_cap = _sample_event_payload(max_capacity=0)
    res3 = await client.post("/api/organizer/events", json=bad_cap, headers=headers)
    assert res3.status_code == 422

    # 4. Unsupported category -> 422
    bad_cat = _sample_event_payload(category="invalid_xyz_category")
    res4 = await client.post("/api/organizer/events", json=bad_cat, headers=headers)
    assert res4.status_code == 422


async def test_authorization_and_cross_organizer_ownership(client: AsyncClient):
    org1_token, _ = await _create_organizer(
        client, email="org1@example.com", phone="9100000001"
    )
    org2_token, _ = await _create_organizer(
        client, email="org2@example.com", phone="9100000002"
    )
    part_token, _ = await _create_participant(
        client, email="part@example.com", phone="9200000001"
    )

    h_org1 = {"Authorization": f"Bearer {org1_token}"}
    h_org2 = {"Authorization": f"Bearer {org2_token}"}
    h_part = {"Authorization": f"Bearer {part_token}"}

    # Unauthenticated cannot create event -> 401
    unauth = await client.post("/api/organizer/events", json=_sample_event_payload())
    assert unauth.status_code == 401

    # Participant cannot create or list organizer events -> 403
    part_create = await client.post(
        "/api/organizer/events",
        json=_sample_event_payload(),
        headers=h_part,
    )
    assert part_create.status_code == 403

    part_list = await client.get("/api/organizer/events", headers=h_part)
    assert part_list.status_code == 403

    # Organizer 1 creates an event
    created = await client.post(
        "/api/organizer/events",
        json=_sample_event_payload(status="draft"),
        headers=h_org1,
    )
    event_id = created.json()["event"]["id"]

    # Organizer 2 cannot view, update, publish, or cancel Organizer 1's event -> 403
    assert (
        await client.get(f"/api/organizer/events/{event_id}", headers=h_org2)
    ).status_code == 403
    assert (
        await client.put(
            f"/api/organizer/events/{event_id}",
            json={"title": "Hijacked Title"},
            headers=h_org2,
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/organizer/events/{event_id}/publish", headers=h_org2
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/organizer/events/{event_id}/cancel", headers=h_org2
        )
    ).status_code == 403


async def test_publish_and_cancel_lifecycle_and_visibility(client: AsyncClient):
    org_token, _ = await _create_organizer(client)
    headers = {"Authorization": f"Bearer {org_token}"}

    # Create draft event
    res = await client.post(
        "/api/organizer/events",
        json=_sample_event_payload(status="draft"),
        headers=headers,
    )
    event_id = res.json()["event"]["id"]

    # Draft does NOT appear in public discovery
    pub_list_before = await client.get("/api/events")
    assert pub_list_before.status_code == 200
    assert pub_list_before.json()["total"] == 0

    # Public user cannot view draft event details -> 404
    pub_detail_draft = await client.get(f"/api/events/{event_id}")
    assert pub_detail_draft.status_code == 404

    # Owning organizer CAN view their own draft via GET /api/events/{id}
    owner_detail_draft = await client.get(f"/api/events/{event_id}", headers=headers)
    assert owner_detail_draft.status_code == 200
    assert owner_detail_draft.json()["status"] == "draft"

    # Publish the draft event
    pub_res = await client.patch(
        f"/api/organizer/events/{event_id}/publish",
        headers=headers,
    )
    assert pub_res.status_code == 200
    assert pub_res.json()["event"]["status"] == "published"
    assert pub_res.json()["event"]["registration_open"] is True

    # Publishing again fails with 400
    pub_again = await client.patch(
        f"/api/organizer/events/{event_id}/publish",
        headers=headers,
    )
    assert pub_again.status_code == 400

    # Published event now appears in public discovery and public detail view
    pub_list_after = await client.get("/api/events")
    assert pub_list_after.json()["total"] == 1
    pub_detail_ok = await client.get(f"/api/events/{event_id}")
    assert pub_detail_ok.status_code == 200
    assert pub_detail_ok.json()["id"] == event_id

    # Cancel the event
    cancel_res = await client.patch(
        f"/api/organizer/events/{event_id}/cancel",
        headers=headers,
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["event"]["status"] == "cancelled"
    assert cancel_res.json()["event"]["registration_open"] is False

    # Cancelling again or editing a cancelled event fails with 400
    assert (
        await client.patch(
            f"/api/organizer/events/{event_id}/cancel", headers=headers
        )
    ).status_code == 400
    assert (
        await client.put(
            f"/api/organizer/events/{event_id}",
            json={"title": "Try Edit Cancelled"},
            headers=headers,
        )
    ).status_code == 400

    # Cancelled event is removed from public discovery
    pub_list_cancelled = await client.get("/api/events")
    assert pub_list_cancelled.json()["total"] == 0


async def test_public_discovery_filters_categories_and_pagination(client: AsyncClient):
    org_token, _ = await _create_organizer(client)
    headers = {"Authorization": f"Bearer {org_token}"}

    events_to_seed = [
        _sample_event_payload(
            title="AI Hackathon Pune",
            category="Hackathon",
            city="Pune",
            days_ahead=5,
            status="published",
        ),
        _sample_event_payload(
            title="FastAPI Backend Workshop",
            category="Workshop",
            city="Mumbai",
            days_ahead=8,
            status="published",
        ),
        _sample_event_payload(
            title="Cloud Native Summit 2026",
            category="Tech Talk",
            city="Pune",
            days_ahead=12,
            status="published",
        ),
        _sample_event_payload(
            title="Founders & Builders Meetup",
            category="meetups",
            city="Bangalore",
            days_ahead=15,
            status="published",
        ),
    ]
    for ev in events_to_seed:
        r = await client.post("/api/organizer/events", json=ev, headers=headers)
        assert r.status_code == 201

    # 1. Category drill-down endpoint (supports both canonical slug and UI label)
    cat_res = await client.get("/api/events/categories/hackathons")
    assert cat_res.status_code == 200
    assert cat_res.json()["category"] == "hackathons"
    assert cat_res.json()["category_display"] == "Hackathons"
    assert cat_res.json()["total"] == 1
    assert cat_res.json()["events"][0]["title"] == "AI Hackathon Pune"

    cat_alias_res = await client.get("/api/events/categories/Tech%20Talk")
    assert cat_alias_res.status_code == 200
    assert cat_alias_res.json()["category"] == "summits_conferences"
    assert cat_alias_res.json()["total"] == 1

    # 2. City filter
    pune_res = await client.get("/api/events", params={"city": "Pune"})
    assert pune_res.status_code == 200
    assert pune_res.json()["total"] == 2

    # 3. Keyword search
    search_res = await client.get("/api/events", params={"search": "FastAPI"})
    assert search_res.status_code == 200
    assert search_res.json()["total"] == 1
    assert search_res.json()["events"][0]["title"] == "FastAPI Backend Workshop"

    # 4. Pagination
    page1 = await client.get("/api/events", params={"page": 1, "limit": 2})
    page2 = await client.get("/api/events", params={"page": 2, "limit": 2})
    assert page1.json()["total"] == 4
    assert len(page1.json()["events"]) == 2
    assert len(page2.json()["events"]) == 2
    assert page1.json()["events"][0]["id"] != page2.json()["events"][0]["id"]


async def test_participant_recommendations_ranking_and_eligibility(client: AsyncClient):
    org_token, _ = await _create_organizer(client)
    org_headers = {"Authorization": f"Bearer {org_token}"}

    # Create 3 published events:
    # Event A: Hackathon in Pune (matches both interest & city -> highest score)
    await client.post(
        "/api/organizer/events",
        json=_sample_event_payload(
            title="Pune Hackathon — Perfect Match",
            category="hackathons",
            city="Pune",
            days_ahead=5,
            status="published",
        ),
        headers=org_headers,
    )
    # Event B: Workshop in Delhi (matches neither primary interest nor city -> lower score)
    await client.post(
        "/api/organizer/events",
        json=_sample_event_payload(
            title="Delhi Design Workshop",
            category="workshops",
            city="Delhi",
            days_ahead=25,
            status="published",
        ),
        headers=org_headers,
    )
    # Event C: Draft event in Pune (excluded from recommendations)
    await client.post(
        "/api/organizer/events",
        json=_sample_event_payload(
            title="UnpublishedPuneHack",
            category="hackathons",
            city="Pune",
            days_ahead=4,
            status="draft",
        ),
        headers=org_headers,
    )

    # Participant who has NOT completed onboarding gets 400
    unonboarded_token, _ = await _create_participant(
        client,
        email="newbie@example.com",
        phone="9200000099",
        onboard=False,
    )
    unonboarded_res = await client.get(
        "/api/events/recommendations",
        headers={"Authorization": f"Bearer {unonboarded_token}"},
    )
    assert unonboarded_res.status_code == 400

    # Onboarded participant with interests=["hackathons"] and city="Pune"
    part_token, _ = await _create_participant(
        client,
        email="onboarded@example.com",
        phone="9200000088",
        interests=["hackathons"],
        city="Pune",
        onboard=True,
    )
    rec_res = await client.get(
        "/api/events/recommendations",
        headers={"Authorization": f"Bearer {part_token}"},
    )
    assert rec_res.status_code == 200
    recs = rec_res.json()["recommendations"]
    assert len(recs) == 2
    assert recs[0]["title"] == "Pune Hackathon — Perfect Match"
    assert recs[0]["relevance_score"] > recs[1]["relevance_score"]
    assert any("Pune" in r for r in recs[0]["match_reasons"])


async def test_create_valid_free_and_paid_events_with_registration_url(client: AsyncClient):
    org_token, _ = await _create_organizer(client)
    headers = {"Authorization": f"Bearer {org_token}"}

    # 1. Create a valid free event with registration_url
    free_payload = _sample_event_payload(
        title="Open Source Community Meetup",
        category="meetups",
        status="published",
    )
    free_payload["price_type"] = "free"
    free_payload["price_amount"] = None
    free_payload["registration_url"] = "https://forms.gle/freeMeetupForm123"

    free_res = await client.post("/api/organizer/events", json=free_payload, headers=headers)
    assert free_res.status_code == 201
    free_ev = free_res.json()["event"]
    assert free_ev["price_type"] == "free"
    assert free_ev["price_amount"] is None
    assert free_ev["is_free"] is True
    assert free_ev["registration_url"] == "https://forms.gle/freeMeetupForm123"

    # 2. Create a valid paid event in INR with registration_url
    paid_payload = _sample_event_payload(
        title="Full-Stack GenAI Bootcamp",
        category="workshops",
        status="published",
    )
    paid_payload.pop("is_free", None)
    paid_payload["price_type"] = "paid"
    paid_payload["price_amount"] = 499.5
    paid_payload["registration_url"] = "https://docs.google.com/forms/d/e/1FAIpQLSdPaid/viewform"

    paid_res = await client.post("/api/organizer/events", json=paid_payload, headers=headers)
    assert paid_res.status_code == 201
    paid_ev = paid_res.json()["event"]
    assert paid_ev["price_type"] == "paid"
    assert paid_ev["price_amount"] == 499.5
    assert paid_ev["is_free"] is False
    assert paid_ev["registration_url"] == "https://docs.google.com/forms/d/e/1FAIpQLSdPaid/viewform"


async def test_reject_invalid_pricing_combinations_and_urls(client: AsyncClient):
    org_token, _ = await _create_organizer(client)
    headers = {"Authorization": f"Bearer {org_token}"}

    # 1. Free event with positive price_amount -> 422
    bad_free = _sample_event_payload()
    bad_free["price_type"] = "free"
    bad_free["price_amount"] = 250
    res1 = await client.post("/api/organizer/events", json=bad_free, headers=headers)
    assert res1.status_code == 422

    # 2. Paid event without price_amount -> 422
    bad_paid_missing = _sample_event_payload()
    bad_paid_missing.pop("is_free", None)
    bad_paid_missing["price_type"] = "paid"
    res2 = await client.post("/api/organizer/events", json=bad_paid_missing, headers=headers)
    assert res2.status_code == 422

    # 3. Paid event with zero or negative price_amount -> 422
    for invalid_amt in (0, -100):
        bad_paid_amt = _sample_event_payload()
        bad_paid_amt.pop("is_free", None)
        bad_paid_amt["price_type"] = "paid"
        bad_paid_amt["price_amount"] = invalid_amt
        res_amt = await client.post("/api/organizer/events", json=bad_paid_amt, headers=headers)
        assert res_amt.status_code == 422

    # 4. Conflicting price_type="paid" and is_free=True -> 422
    bad_conflict = _sample_event_payload()
    bad_conflict["price_type"] = "paid"
    bad_conflict["price_amount"] = 300
    bad_conflict["is_free"] = True
    res_conflict = await client.post("/api/organizer/events", json=bad_conflict, headers=headers)
    assert res_conflict.status_code == 422

    # 5. Invalid registration_url values -> 422
    for invalid_url in (
        "not-a-valid-url",
        "javascript:alert(1)",
        "ftp://files.example.com/register",
        "https://invalid_domain_without_tld",
        "https://forms.gle/has spaces in url",
    ):
        bad_url_payload = _sample_event_payload()
        bad_url_payload["registration_url"] = invalid_url
        res_url = await client.post("/api/organizer/events", json=bad_url_payload, headers=headers)
        assert res_url.status_code == 422


async def test_filter_events_by_price_type_and_combined_filters(client: AsyncClient):
    org_token, _ = await _create_organizer(client)
    headers = {"Authorization": f"Bearer {org_token}"}

    # Seed 2 free events and 2 paid events across categories and cities
    ev1 = _sample_event_payload(
        title="Free Pune Hackathon",
        category="hackathons",
        city="Pune",
        days_ahead=4,
        status="published",
    )
    ev1["price_type"] = "free"

    ev2 = _sample_event_payload(
        title="Paid Pune AI Hackathon",
        category="hackathons",
        city="Pune",
        days_ahead=6,
        status="published",
    )
    ev2.pop("is_free", None)
    ev2["price_type"] = "paid"
    ev2["price_amount"] = 399

    ev3 = _sample_event_payload(
        title="Paid Mumbai Cloud Summit",
        category="summits_conferences",
        city="Mumbai",
        days_ahead=8,
        status="published",
    )
    ev3.pop("is_free", None)
    ev3["price_type"] = "paid"
    ev3["price_amount"] = 999

    ev4 = _sample_event_payload(
        title="Free Bangalore Dev Meetup",
        category="meetups",
        city="Bangalore",
        days_ahead=10,
        status="published",
    )
    ev4["price_type"] = "free"

    for payload in (ev1, ev2, ev3, ev4):
        r = await client.post("/api/organizer/events", json=payload, headers=headers)
        assert r.status_code == 201

    # 1. No price_type filter returns all 4 published events
    all_res = await client.get("/api/events")
    assert all_res.status_code == 200
    assert all_res.json()["total"] == 4

    # 2. Filter by price_type=free returns only the 2 free events
    free_res = await client.get("/api/events", params={"price_type": "free"})
    assert free_res.status_code == 200
    assert free_res.json()["total"] == 2
    assert all(ev["price_type"] == "free" and ev["price_amount"] is None for ev in free_res.json()["events"])

    # 3. Filter by price_type=paid returns only the 2 paid events
    paid_res = await client.get("/api/events", params={"price_type": "paid"})
    assert paid_res.status_code == 200
    assert paid_res.json()["total"] == 2
    assert all(ev["price_type"] == "paid" and ev["price_amount"] > 0 for ev in paid_res.json()["events"])

    # 4. Combine price_type=paid with category, city, search, sort, and pagination
    combined_res = await client.get(
        "/api/events",
        params={
            "price_type": "paid",
            "category": "hackathons",
            "city": "Pune",
            "search": "AI",
            "sort": "date_desc",
            "page": 1,
            "limit": 10,
        },
    )
    assert combined_res.status_code == 200
    assert combined_res.json()["total"] == 1
    assert combined_res.json()["events"][0]["title"] == "Paid Pune AI Hackathon"
    assert combined_res.json()["events"][0]["price_amount"] == 399.0

    # 5. Invalid price_type filter returns 422
    bad_pt_res = await client.get("/api/events", params={"price_type": "donation"})
    assert bad_pt_res.status_code == 422


async def test_update_event_pricing_and_ownership_enforcement(client: AsyncClient):
    org1_token, _ = await _create_organizer(
        client, email="org_price1@example.com", phone="9111111111"
    )
    org2_token, _ = await _create_organizer(
        client, email="org_price2@example.com", phone="9111111112"
    )
    h_org1 = {"Authorization": f"Bearer {org1_token}"}
    h_org2 = {"Authorization": f"Bearer {org2_token}"}

    # Create a free event owned by Organizer 1
    create_res = await client.post(
        "/api/organizer/events",
        json=_sample_event_payload(status="published"),
        headers=h_org1,
    )
    assert create_res.status_code == 201
    event_id = create_res.json()["event"]["id"]

    # 1. Invalid update: switching to paid without price_amount -> 422
    bad_to_paid = await client.put(
        f"/api/organizer/events/{event_id}",
        json={"price_type": "paid"},
        headers=h_org1,
    )
    assert bad_to_paid.status_code == 422

    # 2. Invalid update: setting positive price_amount while event remains free -> 422
    bad_free_amount = await client.put(
        f"/api/organizer/events/{event_id}",
        json={"price_amount": 150},
        headers=h_org1,
    )
    assert bad_free_amount.status_code == 422

    # 3. Valid update: switch free -> paid with positive price_amount and registration_url
    to_paid_res = await client.put(
        f"/api/organizer/events/{event_id}",
        json={
            "price_type": "paid",
            "price_amount": 599,
            "registration_url": "https://forms.gle/updatedPaidForm",
        },
        headers=h_org1,
    )
    assert to_paid_res.status_code == 200
    ev_paid = to_paid_res.json()["event"]
    assert ev_paid["price_type"] == "paid"
    assert ev_paid["price_amount"] == 599.0
    assert ev_paid["is_free"] is False
    assert ev_paid["registration_url"] == "https://forms.gle/updatedPaidForm"

    # 4. Valid update: update price_amount on already-paid event
    upd_amt_res = await client.put(
        f"/api/organizer/events/{event_id}",
        json={"price_amount": 799},
        headers=h_org1,
    )
    assert upd_amt_res.status_code == 200
    assert upd_amt_res.json()["event"]["price_amount"] == 799.0

    # 5. Non-owner Organizer 2 cannot update pricing -> 403
    forbidden_res = await client.put(
        f"/api/organizer/events/{event_id}",
        json={"price_type": "free"},
        headers=h_org2,
    )
    assert forbidden_res.status_code == 403

    # 6. Valid update: switch paid -> free (automatically resets price_amount to None)
    to_free_res = await client.put(
        f"/api/organizer/events/{event_id}",
        json={"price_type": "free"},
        headers=h_org1,
    )
    assert to_free_res.status_code == 200
    ev_free = to_free_res.json()["event"]
    assert ev_free["price_type"] == "free"
    assert ev_free["price_amount"] is None
    assert ev_free["is_free"] is True


async def test_demo_seed_script_idempotency_and_discovery_coverage(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    from scripts.seed_demo_data import seed

    # 1. Initial seed creates 7 demo users and 34 published events across all 8 UI categories
    first_stats = await seed(test_db, refresh_dates=False)
    assert first_stats["users_created"] == 7
    assert first_stats["events_created"] == 34

    # 2. Second run is idempotent and does not duplicate records
    second_stats = await seed(test_db, refresh_dates=False)
    assert second_stats["users_created"] == 0
    assert second_stats["users_existing"] == 7
    assert second_stats["events_created"] == 0
    assert second_stats["events_existing"] == 34

    # 3. Verify GET /api/events serves all 34 seeded events and every UI category has 4-5 events
    list_res = await client.get("/api/events", params={"limit": 50})
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 34

    for ui_category in [
        "Hackathon",
        "Tech Talk",
        "Workshop",
        "Startup",
        "Music",
        "Sports",
        "Art",
        "Food",
    ]:
        cat_res = await client.get("/api/events", params={"category": ui_category, "limit": 50})
        assert cat_res.status_code == 200
        assert 4 <= cat_res.json()["total"] <= 5, f"Category {ui_category} count out of range"


async def test_create_and_update_event_without_registration_url_and_in_app_booking(
    client: AsyncClient,
):
    """Verify events can be created/edited without registration_url and support in-app booking."""
    org_token, _ = await _create_organizer(client)
    part_token, _ = await _create_participant(client)
    h_org = {"Authorization": f"Bearer {org_token}"}
    h_part = {"Authorization": f"Bearer {part_token}"}

    # 1. Create a free event omitting registration_url entirely
    free_payload = _sample_event_payload(title="In-App Free Event", status="published")
    free_payload["price_type"] = "free"
    free_payload.pop("registration_url", None)

    res_free = await client.post("/api/organizer/events", json=free_payload, headers=h_org)
    assert res_free.status_code == 201
    free_ev = res_free.json()["event"]
    assert free_ev["registration_url"] is None

    # 2. Create a paid event omitting registration_url entirely
    paid_payload = _sample_event_payload(title="In-App Paid Event", status="published")
    paid_payload.pop("is_free", None)
    paid_payload["price_type"] = "paid"
    paid_payload["price_amount"] = 350.0
    paid_payload.pop("registration_url", None)

    res_paid = await client.post("/api/organizer/events", json=paid_payload, headers=h_org)
    assert res_paid.status_code == 201
    paid_ev = res_paid.json()["event"]
    assert paid_ev["registration_url"] is None

    # 3. Update the event without registration_url
    upd_res = await client.put(
        f"/api/organizer/events/{free_ev['id']}",
        json={"title": "Updated In-App Free Event"},
        headers=h_org,
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["event"]["title"] == "Updated In-App Free Event"
    assert upd_res.json()["event"]["registration_url"] is None

    # 4. Backward compatibility: update an event that had an external URL, omitting it in update
    legacy_payload = _sample_event_payload(title="Legacy External Event", status="published")
    legacy_payload["registration_url"] = "https://forms.gle/sampleLegacyForm"
    res_legacy = await client.post("/api/organizer/events", json=legacy_payload, headers=h_org)
    assert res_legacy.status_code == 201
    legacy_id = res_legacy.json()["event"]["id"]
    assert res_legacy.json()["event"]["registration_url"] == "https://forms.gle/sampleLegacyForm"

    # Edit legacy event title without supplying registration_url -> preserved
    edit_legacy = await client.put(
        f"/api/organizer/events/{legacy_id}",
        json={"title": "Updated Legacy Title"},
        headers=h_org,
    )
    assert edit_legacy.status_code == 200
    assert edit_legacy.json()["event"]["registration_url"] == "https://forms.gle/sampleLegacyForm"

    # 5. In-app registration on events without registration_url
    # Free event -> immediate confirmation
    book_free = await client.post(f"/api/registrations/{free_ev['id']}", headers=h_part)
    assert book_free.status_code == 201
    assert book_free.json()["booking_status"] == "confirmed"

    # Paid event -> reserves 15m seat and provides Razorpay checkout
    book_paid = await client.post(f"/api/registrations/{paid_ev['id']}", headers=h_part)
    assert book_paid.status_code == 201
    assert book_paid.json()["booking_status"] == "pending_payment"
    assert book_paid.json()["razorpay_checkout"] is not None
