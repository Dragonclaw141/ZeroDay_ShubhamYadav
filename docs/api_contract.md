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


---

## 6. Stage 2 — Event Discovery & Organizer Event Management Endpoints

### 6.1 Public & Participant Event Discovery

#### `GET /api/events`
List published events with optional filters and pagination.

- **Auth Required:** No (Public)
- **Query Parameters:**
  - `category` (optional): Canonical slug (`hackathons`, `workshops`, `summits_conferences`, `meetups`, `tech`, `business`, `arts`, `sports`, `design`) or frontend label (`Hackathon`, `Tech Talk`, `Workshop`, `Startup`, `Music`, `Sports`, `Art`, `Food`).
  - `city` (optional): Case-insensitive venue city match.
  - `price_type` (optional): Filter by `"free"` or `"paid"`. Omitting `price_type` returns both free and paid published events.
  - `search` (optional): Case-insensitive keyword search across title, description, category, tags, venue, and organizer name.
  - `date_from` / `date_to` (optional): ISO 8601 datetime bounds on `start_date`.
  - `sort` (optional): `date_asc` (default), `date_desc`, or `popularity`.
  - `page` (default `1`), `limit` (default `20`, max `50`).
- **Success Response (`200 OK`):** `EventListResponse` (`{ "events": [EventResponse], "total": int, "page": int, "limit": int }`).

#### `GET /api/events/categories/{category}`
Category card drill-down endpoint returning published events in a specific category.

- **Auth Required:** No (Public)
- **Success Response (`200 OK`):**
  ```json
  {
    "category": "hackathons",
    "category_display": "Hackathons",
    "events": [ "...EventResponse items..." ],
    "total": 1,
    "page": 1,
    "limit": 20
  }
  ```

#### `GET /api/events/recommendations`
Return personalized upcoming event recommendations for an onboarded participant.

- **Auth Required:** Yes (`participant` only, with `onboarding_completed == true`)
- **Scoring Rules:** Interest match (50%), city/coordinate proximity (30%), upcoming freshness (20%). Excludes unpublished, cancelled, past, expired-deadline, or full-capacity events.
- **Success Response (`200 OK`):** `RecommendationListResponse` (`{ "recommendations": [RecommendedEventItem], "total": int }`).
- **Error Statuses:** `400 Bad Request` (onboarding incomplete), `401 Unauthorized`, `403 Forbidden` (not a participant).

#### `GET /api/events/{event_id}`
Get full details of an event.

- **Auth Required:** Public for `published` events; owning `organizer` may also view their own `draft` or `cancelled` events.
- **Success Response (`200 OK`):** `EventResponse`.
- **Error Statuses:** `404 Not Found` (non-existent ID, invalid ObjectId, or non-owner requesting unpublished/cancelled event).

---

### 6.2 Organizer Event Management (`role == "organizer"` required)

#### `POST /api/organizer/events`
Create a new event (`draft` or `published`).

- **Auth Required:** Yes (`organizer` only)
- **Request Body (`EventCreateRequest`):**
  ```json
  {
    "title": "HackPune 2026 — 36-Hour National Hackathon",
    "description": "Join developers for a coding marathon building AI and Web3 solutions.",
    "category": "hackathons",
    "tags": ["ai", "web3", "python"],
    "venue": {
      "name": "Symbiosis Institute of Technology",
      "address": "Gram Lavale, Mulshi",
      "city": "Pune"
    },
    "start_date": "2026-11-15T09:00:00Z",
    "end_date": "2026-11-16T21:00:00Z",
    "registration_deadline": "2026-11-10T23:59:59Z",
    "max_capacity": 200,
    "status": "draft",
    "mode": "In-person",
    "price_type": "free",
    "price_amount": null,
    "registration_url": "https://forms.gle/exampleHackPune2026"
  }
  ```
  - **Pricing & Registration URL Rules:**
    - `price_type`: `"free"` (default) or `"paid"`. Legacy `is_free` boolean remains supported and synchronized (`is_free == (price_type == "free")`).
    - `price_amount`: numeric amount in INR (`> 0`) required when `price_type == "paid"`; must be `null` or omitted when `price_type == "free"` (free events with a positive `price_amount` are rejected with `422`).
    - `registration_url` (optional): Valid `http://` or `https://` external registration link (e.g., Google Form). EventAdda does not process payments or verify external form completion.
  - **Date Rules:** `end_date` and `registration_deadline` default to `start_date` if omitted; `end_date >= start_date` and `registration_deadline <= start_date` are validated.
- **Success Response (`201 Created`):** `EventMutationResponse` (`{ "message": "Event created successfully", "event": EventResponse, "notifications_sent": 0 }`).

#### `GET /api/organizer/events`
List events owned by the authenticated organizer (optional `?status=draft|published|cancelled`, `page`, `limit`).

- **Auth Required:** Yes (`organizer` only)
- **Success Response (`200 OK`):** `EventListResponse`.

#### `GET /api/organizer/events/{event_id}`
Retrieve full details for an event owned by the authenticated organizer.

- **Auth Required:** Yes (`organizer` owner only; returns `403 Forbidden` if owned by another organizer).

#### `PUT /api/organizer/events/{event_id}`
Update fields of an owned event (`draft` or `published`). Cancelled events cannot be edited (`400 Bad Request`).

- **Auth Required:** Yes (`organizer` owner only).
- **Success Response (`200 OK`):** `EventMutationResponse`.

#### `PATCH /api/organizer/events/{event_id}/publish`
Transition an owned `draft` event to `published`.

- **Auth Required:** Yes (`organizer` owner only).
- **Error Statuses:** `400 Bad Request` (already published or cancelled), `403 Forbidden` (not owner), `404 Not Found`.

#### `PATCH /api/organizer/events/{event_id}/cancel`
Transition an owned `draft` or `published` event to `cancelled`.

- **Auth Required:** Yes (`organizer` owner only).
- **Error Statuses:** `400 Bad Request` (already cancelled), `403 Forbidden` (not owner), `404 Not Found`.
