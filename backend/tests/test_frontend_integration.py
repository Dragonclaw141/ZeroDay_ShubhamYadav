from datetime import timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token
from tests.conftest import FakeDatabase

pytestmark = pytest.mark.asyncio

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

# Exact UI -> Backend interest mapping used by frontend/js/main.js
UI_TO_BACKEND_INTEREST = {
    "Hackathon": "hackathons",
    "Tech Talk": "summits_conferences",
    "Workshop": "workshops",
    "Startup": "business",
    "Music": "arts",
    "Sports": "sports",
    "Art": "design",
    "Food": "meetups",
}


async def test_frontend_assets_and_api_client_structure():
    """Verify frontend pages, preserved CSS, and Stage 1 API endpoints in frontend/js/main.js."""
    expected_pages = [
        "index.html",
        "login.html",
        "login-participant.html",
        "login-organizer.html",
        "signup.html",
        "signup-participant.html",
        "signup-organizer.html",
        "dashboard-participant.html",
        "dashboard-organizer.html",
        "events.html",
        "event.html",
    ]
    for page in expected_pages:
        assert (FRONTEND_DIR / page).is_file(), f"Missing frontend page: {page}"

    style_css = (FRONTEND_DIR / "css" / "style.css").read_text(encoding="utf-8")
    assert "--purple:#6d4aff" in style_css

    main_js = (FRONTEND_DIR / "js" / "main.js").read_text(encoding="utf-8")
    for endpoint in [
        "/api/auth/signup",
        "/api/auth/login",
        "/api/auth/me",
        "/api/onboarding/interests",
        "/api/onboarding/location",
        "/api/onboarding/complete",
        "/api/profile",
    ]:
        assert endpoint in main_js, f"Missing endpoint {endpoint} in frontend/js/main.js"

    # Verify later-stage controls explicitly report Stage 2 / Stage 3 unavailability
    assert "POST /api/organizer/events will be enabled in Stage 2" in main_js
    assert "POST /api/registrations/{event_id} will be enabled in Stage 3" in main_js


async def test_frontend_participant_signup_onboarding_and_login_flow(client: AsyncClient):
    """Simulate the exact sequence performed by signup-participant.html and login-participant.html."""
    selected_ui_checkboxes = ["Hackathon", "Workshop", "Tech Talk"]
    mapped_interests = [UI_TO_BACKEND_INTEREST[label] for label in selected_ui_checkboxes]

    # Step 1: POST /api/auth/signup
    signup_res = await client.post(
        "/api/auth/signup",
        json={
            "full_name": "Aarav Kulkarni",
            "email": "aarav.k@example.com",
            "phone": "+91 98765 43210",
            "password": "EventAdda123",
            "role": "participant",
        },
    )
    assert signup_res.status_code == 201
    token = signup_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Step 2: PUT /api/onboarding/interests
    int_res = await client.put(
        "/api/onboarding/interests",
        json={"interests": mapped_interests},
        headers=headers,
    )
    assert int_res.status_code == 200
    assert int_res.json()["interests"] == [
        "hackathons",
        "workshops",
        "summits_conferences",
    ]

    # Step 3: PUT /api/onboarding/location
    loc_res = await client.put(
        "/api/onboarding/location",
        json={"city": "Mumbai"},
        headers=headers,
    )
    assert loc_res.status_code == 200
    assert loc_res.json()["location"]["city"] == "Mumbai"

    # Step 4: POST /api/onboarding/complete
    comp_res = await client.post("/api/onboarding/complete", headers=headers)
    assert comp_res.status_code == 200
    assert comp_res.json()["onboarding_completed"] is True

    # Step 5: GET /api/auth/me verifies session and role for dashboard-participant.html
    me_res = await client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200
    me_user = me_res.json()
    assert me_user["role"] == "participant"
    assert me_user["onboarding_completed"] is True
    assert me_user["location"]["city"] == "Mumbai"


async def test_frontend_organizer_signup_profile_city_and_role_isolation(client: AsyncClient):
    """Simulate signup-organizer.html, profile city persistence, and single-role enforcement."""
    signup_res = await client.post(
        "/api/auth/signup",
        json={
            "full_name": "Neha Deshmukh",
            "email": "neha.org@example.com",
            "phone": "+91 98111 22333",
            "password": "OrganizerPass1",
            "role": "organizer",
        },
    )
    assert signup_res.status_code == 201
    token = signup_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Save preferred city via PUT /api/profile as done by signup-organizer.html
    prof_res = await client.put(
        "/api/profile",
        json={"location": {"city": "Pune"}},
        headers=headers,
    )
    assert prof_res.status_code == 200
    assert prof_res.json()["user"]["role"] == "organizer"
    assert prof_res.json()["user"]["location"]["city"] == "Pune"

    # Organizer cannot use participant onboarding endpoints
    forbidden_res = await client.put(
        "/api/onboarding/interests",
        json={"interests": ["hackathons"]},
        headers=headers,
    )
    assert forbidden_res.status_code == 403


async def test_frontend_cors_headers_and_session_expiration(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    """Verify CORS preflight for local static frontend server and expired token rejection."""
    preflight = await client.options(
        "/api/auth/login",
        headers={
            "Origin": "http://localhost:5500",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,Authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == "http://localhost:5500"

    expired = create_access_token(
        subject="6719a1b2c3d4e5f6a7b8c9d0",
        role="participant",
        expires_delta=timedelta(minutes=-5),
    )
    me_expired = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert me_expired.status_code == 401
