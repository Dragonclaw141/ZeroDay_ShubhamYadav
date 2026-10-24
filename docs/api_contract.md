# EventAdda â€” Shared API Contract (Stage 1)

**Base URL (Local Development):** `http://localhost:8000`
**Interactive OpenAPI Docs:** `http://localhost:8000/docs`
**Content-Type:** `application/json`
**Authentication Header:** `Authorization: Bearer <access_token>`

---

## 1. Confirmed Stage 1 Conventions

- **Single Role per Account:** Every account has an immutable `role` set at signup: either `"participant"` or `"organizer"`.
- **Supported Interests:** `"hackathons"`, `"workshops"`, `"summits_conferences"`, `"meetups"`, `"tech"`, `"design"`, `"business"`, `"health"`, `"arts"`, `"science"`, `"education"`, `"sports"`.
- **Standard Error Shape:**
  - Business/Auth errors (`400`, `401`, `403`, `404`, `409`, `503`):
    ```json
    { "detail": "Human-readable error message" }
    ```
  - Validation errors (`422`):
    ```json
    {
      "detail": [
        { "loc": ["body", "email"], "msg": "value is not a valid email address", "type": "value_error" }
      ]
    }
    ```

---

## 2. Health Check

### `GET /health`
Reports application health and MongoDB connectivity without exposing credentials.

- **Auth Required:** No
- **Success Response (`200 OK`):**
  ```json
  {
    "status": "ok",
    "service": "EventAdda Backend",
    "database": "connected"
  }
  ```
- **Degraded Response (`503 Service Unavailable`):**
  ```json
  {
    "status": "degraded",
    "service": "EventAdda Backend",
    "database": "unavailable"
  }
  ```

---

## 3. Authentication Endpoints

### `POST /api/auth/signup`
Create a new `participant` or `organizer` account and receive a signed JWT bearer token.

- **Auth Required:** No
- **Request Body:**
  ```json
  {
    "full_name": "Priya Sharma",
    "email": "priya.sharma@gmail.com",
    "phone": "9876543210",
    "password": "SecureP@ss123",
    "role": "participant"
  }
  ```
  - `full_name`: string (2â€“100 chars)
  - `email`: valid email address (normalized to lowercase)
  - `phone`: 10â€“15 digits (optional leading `+`)
  - `password`: 8â€“72 chars, must contain at least one letter and one number
  - `role`: `"participant"` or `"organizer"`
- **Success Response (`201 Created`):**
  ```json
  {
    "user": {
      "id": "6719a1b2c3d4e5f6a7b8c9d0",
      "full_name": "Priya Sharma",
      "email": "priya.sharma@gmail.com",
      "phone": "9876543210",
      "role": "participant",
      "interests": [],
      "location": null,
      "onboarding_completed": false,
      "email_verified": false,
      "phone_verified": false,
      "is_active": true,
      "created_at": "2026-10-24T06:50:00Z",
      "updated_at": "2026-10-24T06:50:00Z"
    },
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer"
  }
  ```
- **Error Statuses:**
  - `409 Conflict`: Email address or phone number is already registered
  - `422 Unprocessable Content`: Missing/invalid fields, unsupported role, or weak password

---

### `POST /api/auth/login`
Authenticate with email and password and receive a JWT bearer token.

- **Auth Required:** No
- **Request Body:**
  ```json
  {
    "email": "priya.sharma@gmail.com",
    "password": "SecureP@ss123"
  }
  ```
- **Success Response (`200 OK`):** Same shape as `POST /api/auth/signup` (`AuthResponse`: `{ "user": {...}, "access_token": "...", "token_type": "bearer" }`).
- **Error Statuses:**
  - `401 Unauthorized`: Invalid email or password
  - `422 Unprocessable Content`: Missing or malformed fields

---

### `GET /api/auth/me`
Retrieve the currently authenticated user's profile from the database.

- **Auth Required:** Yes (`Bearer <access_token>`)
- **Allowed Roles:** `participant`, `organizer`
- **Success Response (`200 OK`):** Returns `UserResponse` object (never includes `password_hash`).
- **Error Statuses:**
  - `401 Unauthorized`: Missing, malformed, expired, or invalid token

---

## 4. Participant Onboarding Endpoints

> All `/api/onboarding/*` endpoints require a valid JWT and enforce `role == "participant"`. Organizer accounts receive `403 Forbidden`.

### `PUT /api/onboarding/interests`
Set or update the participant's selected interests (at least 1 valid interest required).

- **Auth Required:** Yes (`participant` only)
- **Request Body:**
  ```json
  {
    "interests": ["hackathons", "tech", "workshops"]
  }
  ```
- **Success Response (`200 OK`):**
  ```json
  {
    "message": "Interests updated successfully",
    "interests": ["hackathons", "tech", "workshops"]
  }
  ```
- **Error Statuses:**
  - `400 Bad Request`: Empty interests array
  - `401 Unauthorized`: Not authenticated
  - `403 Forbidden`: Authenticated user is not a `participant`
  - `422 Unprocessable Content`: Contains unsupported interest string

---

### `PUT /api/onboarding/location`
Set or update the participant's preferred location (`city` required; `locality` and GeoJSON `coordinates` optional).

- **Auth Required:** Yes (`participant` only)
- **Request Body:**
  ```json
  {
    "city": "Pune",
    "locality": "Kothrud",
    "coordinates": {
      "type": "Point",
      "coordinates": [73.8567, 18.5204]
    }
  }
  ```
- **Success Response (`200 OK`):**
  ```json
  {
    "message": "Location updated successfully",
    "location": {
      "city": "Pune",
      "locality": "Kothrud",
      "coordinates": {
        "type": "Point",
        "coordinates": [73.8567, 18.5204]
      }
    }
  }
  ```
- **Error Statuses:**
  - `400 Bad Request`: Blank city string
  - `401 Unauthorized`: Not authenticated
  - `403 Forbidden`: Authenticated user is not a `participant`
  - `422 Unprocessable Content`: Missing `city` or invalid coordinates (`[longitude, latitude]`)

---

### `POST /api/onboarding/complete`
Verify that the participant has saved at least one interest and a preferred city, then set `onboarding_completed = true`.

- **Auth Required:** Yes (`participant` only)
- **Request Body:** None
- **Success Response (`200 OK`):**
  ```json
  {
    "message": "Onboarding completed",
    "onboarding_completed": true
  }
  ```
- **Error Statuses:**
  - `400 Bad Request`: Interests are empty or preferred city has not been set
  - `401 Unauthorized`: Not authenticated
  - `403 Forbidden`: Authenticated user is not a `participant`

---

## 5. Profile Endpoints

### `GET /api/profile`
Retrieve the authenticated user's own profile.

- **Auth Required:** Yes (`participant` or `organizer`)
- **Success Response (`200 OK`):** Returns `UserResponse` object.
- **Error Statuses:**
  - `401 Unauthorized`: Missing or invalid token

---

### `PUT /api/profile`
Update the authenticated user's own profile fields. Account `role` and `email` are immutable.

- **Auth Required:** Yes (`participant` or `organizer`)
- **Request Body (all fields optional):**
  ```json
  {
    "full_name": "Priya S. Sharma",
    "phone": "9876543211",
    "interests": ["hackathons", "tech", "design"],
    "location": {
      "city": "Mumbai",
      "locality": "Andheri"
    }
  }
  ```
- **Success Response (`200 OK`):**
  ```json
  {
    "message": "Profile updated successfully",
    "user": {
      "id": "6719a1b2c3d4e5f6a7b8c9d0",
      "full_name": "Priya S. Sharma",
      "email": "priya.sharma@gmail.com",
      "phone": "9876543211",
      "role": "participant",
      "interests": ["hackathons", "tech", "design"],
      "location": {
        "city": "Mumbai",
        "locality": "Andheri",
        "coordinates": null
      },
      "onboarding_completed": true,
      "email_verified": false,
      "phone_verified": false,
      "is_active": true,
      "created_at": "2026-10-24T06:50:00Z",
      "updated_at": "2026-10-24T07:05:00Z"
    }
  }
  ```
- **Error Statuses:**
  - `401 Unauthorized`: Missing or invalid token
  - `409 Conflict`: New phone number is already registered to another user
  - `422 Unprocessable Content`: Invalid field values or attempt to modify immutable fields (such as `role`)
