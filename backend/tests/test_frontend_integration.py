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
        page_path = FRONTEND_DIR / page
        assert page_path.is_file(), f"Missing frontend page: {page}"
        page_html = page_path.read_text(encoding="utf-8")
        assert "brand-icon" not in page_html, f"Legacy purple E icon still present in {page}"
        assert "EventAdda" not in page_html, f"Legacy EventAdda spelling still present in {page}"
        assert '<a class="brand" href="index.html">Event<span>ADDA</span></a>' in page_html, (
            f"Missing standardized EventADDA wordmark in {page}"
        )

    index_html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="landingEventGrid"' in index_html
    assert "event-preview" in index_html
    assert "stage-card-back" in index_html

    style_css = (FRONTEND_DIR / "css" / "style.css").read_text(encoding="utf-8")
    assert "--purple:#6d4aff" in style_css
    assert "brand-icon" not in style_css

    part_signup_html = (FRONTEND_DIR / "signup-participant.html").read_text(encoding="utf-8")
    assert 'id="signupDetails"' in part_signup_html
    assert "College Name/Organization Name/Major" in part_signup_html

    org_signup_html = (FRONTEND_DIR / "signup-organizer.html").read_text(encoding="utf-8")
    assert 'id="organization"' in org_signup_html
    assert "Preferred city for Event organization" in org_signup_html
    assert "Organization / Club name / College Name" in org_signup_html

    events_html = (FRONTEND_DIR / "events.html").read_text(encoding="utf-8")
    assert 'id="priceFilter"' in events_html
    assert 'id="categoryPills"' in events_html
    assert 'id="eventCountBadge"' in events_html

    part_dash_html = (FRONTEND_DIR / "dashboard-participant.html").read_text(encoding="utf-8")
    assert 'id="priceFilter"' in part_dash_html
    assert 'id="categoryPills"' in part_dash_html
    assert 'id="toggleProfileBtn"' in part_dash_html

    org_dash_html = (FRONTEND_DIR / "dashboard-organizer.html").read_text(encoding="utf-8")
    assert 'id="evPriceType"' in org_dash_html
    assert 'id="evPriceAmount"' in org_dash_html
    assert 'id="evFormUrl"' in org_dash_html

    main_js = (FRONTEND_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "affiliation_details" in main_js
    assert "organization_name" in main_js
    assert "price_type" in main_js
    assert "price_amount" in main_js
    assert "registration_url" in main_js
    # Verify temporary development banners and stage labels are removed
    assert "Live MongoDB &amp; FastAPI Connected" not in main_js
    assert "Live MongoDB & FastAPI Connected" not in main_js
    assert "STAGE 1 LIVE API" not in main_js
    assert "ACCOUNT &amp; PROFILE" in main_js
    for endpoint in [
        "/api/auth/signup",
        "/api/auth/login",
        "/api/auth/me",
        "/api/onboarding/interests",
        "/api/onboarding/location",
        "/api/onboarding/complete",
        "/api/profile",
        "/api/events",
        "/api/organizer/events",
    ]:
        assert endpoint in main_js, f"Missing endpoint {endpoint} in frontend/js/main.js"

    # Verify Stage 3 registration boundary is explicitly reported
    assert "POST /api/registrations/{event_id}" in main_js


async def test_frontend_participant_signup_onboarding_and_login_flow(client: AsyncClient):
    """Simulate the exact sequence performed by signup-participant.html and login-participant.html."""
    selected_ui_checkboxes = ["Hackathon", "Workshop", "Tech Talk"]
    mapped_interests = [UI_TO_BACKEND_INTEREST[label] for label in selected_ui_checkboxes]

    # Step 1: POST /api/auth/signup (with affiliation_details from #signupDetails)
    signup_res = await client.post(
        "/api/auth/signup",
        json={
            "full_name": "Aarav Kulkarni",
            "email": "aarav.k@example.com",
            "phone": "+91 98765 43210",
            "password": "EventAdda123",
            "role": "participant",
            "affiliation_details": "Thakur College / Software Eng",
        },
    )
    assert signup_res.status_code == 201
    assert signup_res.json()["user"]["affiliation_details"] == "Thakur College / Software Eng"
    assert signup_res.json()["user"]["organization_name"] is None
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

    # Step 5: GET /api/auth/me verifies session, role, and affiliation_details
    me_res = await client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200
    me_user = me_res.json()
    assert me_user["role"] == "participant"
    assert me_user["affiliation_details"] == "Thakur College / Software Eng"
    assert me_user["onboarding_completed"] is True
    assert me_user["location"]["city"] == "Mumbai"


async def test_frontend_organizer_signup_profile_city_and_role_isolation(client: AsyncClient):
    """Simulate signup-organizer.html with organization_name, profile city persistence, and single-role enforcement."""
    signup_res = await client.post(
        "/api/auth/signup",
        json={
            "full_name": "Neha Deshmukh",
            "email": "neha.org@example.com",
            "phone": "+91 98111 22333",
            "password": "OrganizerPass1",
            "role": "organizer",
            "organization_name": "Tech Club, IIT",
        },
    )
    assert signup_res.status_code == 201
    assert signup_res.json()["user"]["organization_name"] == "Tech Club, IIT"
    assert signup_res.json()["user"]["affiliation_details"] is None
    token = signup_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Save preferred city via PUT /api/profile as done by signup-organizer.html
    prof_res = await client.put(
        "/api/profile",
        json={
            "location": {"city": "Pune"},
            "organization_name": "Shree LR Tiwari College Tech Club",
        },
        headers=headers,
    )
    assert prof_res.status_code == 200
    assert prof_res.json()["user"]["role"] == "organizer"
    assert prof_res.json()["user"]["location"]["city"] == "Pune"
    assert prof_res.json()["user"]["organization_name"] == "Shree LR Tiwari College Tech Club"

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
