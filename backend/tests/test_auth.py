from datetime import timedelta

import pytest
from bson import ObjectId
from httpx import AsyncClient
from jose import jwt

from app.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from tests.conftest import FakeDatabase

pytestmark = pytest.mark.asyncio


async def _signup_user(
    client: AsyncClient,
    *,
    full_name: str = "Priya Sharma",
    email: str = "priya.sharma@gmail.com",
    phone: str = "9876543210",
    password: str = "SecureP@ss123",
    role: str = "participant",
):
    return await client.post(
        "/api/auth/signup",
        json={
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "password": password,
            "role": role,
        },
    )


# 1. Application and health endpoint behavior
async def test_health_endpoint_ok_and_degraded(client: AsyncClient, test_db: FakeDatabase):
    res = await client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "JWT_SECRET_KEY" not in res.text
    assert "mongodb://" not in res.text

    test_db.healthy = False
    res_deg = await client.get("/health")
    assert res_deg.status_code == 503
    assert res_deg.json()["status"] == "degraded"
    assert res_deg.json()["database"] == "unavailable"


async def test_users_indexes_created_idempotently(test_db: FakeDatabase):
    users_col = test_db["users"]
    assert "idx_email_unique" in users_col.indexes
    assert "idx_phone_unique" in users_col.indexes
    assert "idx_location_geo" in users_col.indexes


# 2. Successful signup
async def test_signup_success_and_no_password_exposed(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    res = await _signup_user(
        client,
        email="  Priya.Sharma@Gmail.com  ",
        phone="9876543210",
        role="participant",
    )
    assert res.status_code == 201
    body = res.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"

    user = body["user"]
    assert user["email"] == "priya.sharma@gmail.com"
    assert user["phone"] == "9876543210"
    assert user["role"] == "participant"
    assert user["onboarding_completed"] is False
    assert user["email_verified"] is False
    assert user["phone_verified"] is False
    assert user["is_active"] is True
    assert "password" not in user
    assert "password_hash" not in user
    assert "SecureP@ss123" not in res.text

    stored = await test_db["users"].find_one({"email": "priya.sharma@gmail.com"})
    assert stored is not None
    assert stored["password_hash"] != "SecureP@ss123"
    assert verify_password("SecureP@ss123", stored["password_hash"]) is True


async def test_signup_rejects_invalid_role_including_both(client: AsyncClient):
    res = await _signup_user(client, role="both")
    assert res.status_code == 422


# 3. Duplicate email and duplicate phone rejection
async def test_signup_duplicate_email_and_phone_rejected(client: AsyncClient):
    res1 = await _signup_user(
        client,
        email="priya@example.com",
        phone="9876543210",
    )
    assert res1.status_code == 201

    # Duplicate email (case-insensitive)
    res_dup_email = await _signup_user(
        client,
        email="PRIYA@EXAMPLE.COM",
        phone="9123456789",
    )
    assert res_dup_email.status_code == 409
    assert "email" in res_dup_email.json()["detail"].lower()

    # Duplicate phone
    res_dup_phone = await _signup_user(
        client,
        email="other@example.com",
        phone="9876543210",
    )
    assert res_dup_phone.status_code == 409
    assert "phone" in res_dup_phone.json()["detail"].lower()


# 4 & 5. Password hashing, successful login, and invalid password rejection
async def test_login_success_and_invalid_credentials(client: AsyncClient):
    hashed = hash_password("MyPass123")
    assert hashed != "MyPass123"
    assert verify_password("MyPass123", hashed) is True
    assert verify_password("WrongPass123", hashed) is False

    await _signup_user(
        client,
        email="rahul@example.com",
        phone="9988776655",
        password="CorrectPassword1",
        role="organizer",
    )

    # Successful login (case-insensitive email)
    login_ok = await client.post(
        "/api/auth/login",
        json={"email": "RAHUL@example.com", "password": "CorrectPassword1"},
    )
    assert login_ok.status_code == 200
    login_data = login_ok.json()
    assert login_data["user"]["role"] == "organizer"
    assert "password_hash" not in login_data["user"]
    assert "access_token" in login_data

    # Wrong password
    login_bad_pw = await client.post(
        "/api/auth/login",
        json={"email": "rahul@example.com", "password": "WrongPassword1"},
    )
    assert login_bad_pw.status_code == 401

    # Non-existent email
    login_no_user = await client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "CorrectPassword1"},
    )
    assert login_no_user.status_code == 401


# 6 & 7. Missing, malformed, expired, invalid JWT rejection & /api/auth/me
async def test_jwt_validation_and_get_me(client: AsyncClient):
    signup_res = await _signup_user(client)
    token = signup_res.json()["access_token"]
    user_id = signup_res.json()["user"]["id"]

    # Valid token
    me_res = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["id"] == user_id
    assert "password_hash" not in me_res.json()

    # Missing token
    no_tok = await client.get("/api/auth/me")
    assert no_tok.status_code == 401

    # Malformed token
    malformed = await client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-valid-jwt"},
    )
    assert malformed.status_code == 401

    # Expired token
    expired_token = create_access_token(
        subject=user_id,
        role="participant",
        expires_delta=timedelta(seconds=-10),
    )
    exp_res = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert exp_res.status_code == 401

    # Token signed with wrong secret
    wrong_secret_tok = jwt.encode(
        {"sub": user_id, "role": "participant"},
        "wrong-secret-key",
        algorithm=settings.JWT_ALGORITHM,
    )
    wrong_res = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {wrong_secret_tok}"},
    )
    assert wrong_res.status_code == 401

    # Token for non-existent user ID in DB
    ghost_token = create_access_token(subject=str(ObjectId()), role="participant")
    ghost_res = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {ghost_token}"},
    )
    assert ghost_res.status_code == 401


# 8. Role enforcement for participant-only endpoints
async def test_organizer_blocked_from_participant_onboarding(client: AsyncClient):
    org_res = await _signup_user(
        client,
        email="org@example.com",
        phone="9111222333",
        role="organizer",
    )
    org_token = org_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {org_token}"}

    r1 = await client.put(
        "/api/onboarding/interests",
        json={"interests": ["hackathons"]},
        headers=headers,
    )
    assert r1.status_code == 403

    r2 = await client.put(
        "/api/onboarding/location",
        json={"city": "Pune"},
        headers=headers,
    )
    assert r2.status_code == 403

    r3 = await client.post("/api/onboarding/complete", headers=headers)
    assert r3.status_code == 403


# 9, 10, 11. Onboarding interests, location, and completion validation
async def test_participant_onboarding_flow_and_validations(client: AsyncClient):
    part_res = await _signup_user(client)
    token = part_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Cannot complete onboarding before setting interests and location
    premature = await client.post("/api/onboarding/complete", headers=headers)
    assert premature.status_code == 400

    # Empty interests rejected
    empty_int = await client.put(
        "/api/onboarding/interests",
        json={"interests": []},
        headers=headers,
    )
    assert empty_int.status_code == 400

    # Invalid interest rejected
    bad_int = await client.put(
        "/api/onboarding/interests",
        json={"interests": ["hackathons", "astrology"]},
        headers=headers,
    )
    assert bad_int.status_code == 422

    # Valid interests accepted and deduplicated
    ok_int = await client.put(
        "/api/onboarding/interests",
        json={"interests": ["hackathons", "tech", "hackathons"]},
        headers=headers,
    )
    assert ok_int.status_code == 200
    assert ok_int.json()["interests"] == ["hackathons", "tech"]

    # Still cannot complete onboarding without location
    no_loc_complete = await client.post("/api/onboarding/complete", headers=headers)
    assert no_loc_complete.status_code == 400

    # Empty city rejected
    empty_city = await client.put(
        "/api/onboarding/location",
        json={"city": "   "},
        headers=headers,
    )
    assert empty_city.status_code == 400

    # Valid city without coordinates (browser geolocation optional)
    loc_city_only = await client.put(
        "/api/onboarding/location",
        json={"city": "Pune", "locality": "Kothrud"},
        headers=headers,
    )
    assert loc_city_only.status_code == 200
    assert loc_city_only.json()["location"]["city"] == "Pune"
    assert loc_city_only.json()["location"]["locality"] == "Kothrud"
    assert loc_city_only.json()["location"]["coordinates"] is None

    # Valid location with coordinates
    loc_with_coords = await client.put(
        "/api/onboarding/location",
        json={
            "city": "Pune",
            "locality": "Kothrud",
            "coordinates": {"type": "Point", "coordinates": [73.8567, 18.5204]},
        },
        headers=headers,
    )
    assert loc_with_coords.status_code == 200
    assert loc_with_coords.json()["location"]["coordinates"]["coordinates"] == [
        73.8567,
        18.5204,
    ]

    # Complete onboarding succeeds now
    comp_ok = await client.post("/api/onboarding/complete", headers=headers)
    assert comp_ok.status_code == 200
    assert comp_ok.json()["onboarding_completed"] is True

    # Verify /api/auth/me reflects onboarding_completed = True
    me_after = await client.get("/api/auth/me", headers=headers)
    assert me_after.status_code == 200
    assert me_after.json()["onboarding_completed"] is True


# 12 & 13. Profile get/update, immutable role, and phone uniqueness
async def test_profile_get_and_update_with_phone_uniqueness(client: AsyncClient):
    u1 = await _signup_user(
        client,
        full_name="User One",
        email="u1@example.com",
        phone="9000000001",
        role="participant",
    )
    u2 = await _signup_user(
        client,
        full_name="User Two",
        email="u2@example.com",
        phone="9000000002",
        role="organizer",
    )
    headers1 = {"Authorization": f"Bearer {u1.json()['access_token']}"}

    # Get profile
    prof_get = await client.get("/api/profile", headers=headers1)
    assert prof_get.status_code == 200
    assert prof_get.json()["email"] == "u1@example.com"
    assert "password_hash" not in prof_get.json()

    # Update profile fields
    prof_put = await client.put(
        "/api/profile",
        json={
            "full_name": "User One Updated",
            "phone": "9000000099",
            "interests": ["workshops", "design"],
            "location": {"city": "Mumbai", "locality": "Andheri"},
        },
        headers=headers1,
    )
    assert prof_put.status_code == 200
    updated_user = prof_put.json()["user"]
    assert updated_user["full_name"] == "User One Updated"
    assert updated_user["phone"] == "9000000099"
    assert updated_user["interests"] == ["workshops", "design"]
    assert updated_user["location"]["city"] == "Mumbai"
    assert updated_user["role"] == "participant"

    # Attempting to change phone to User Two's phone fails with 409
    dup_phone = await client.put(
        "/api/profile",
        json={"phone": "9000000002"},
        headers=headers1,
    )
    assert dup_phone.status_code == 409

    # Attempting to pass role in profile update is rejected (immutable role)
    role_tamper = await client.put(
        "/api/profile",
        json={"full_name": "Hacker", "role": "organizer"},
        headers=headers1,
    )
    assert role_tamper.status_code == 422


# 14. Database failure handling
async def test_database_failure_returns_503(
    client: AsyncClient,
    test_db: FakeDatabase,
):
    test_db["users"].fail_operations = True
    res = await _signup_user(client)
    assert res.status_code == 503
    assert "unavailable" in res.json()["detail"].lower()
