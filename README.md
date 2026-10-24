# EventAdda

**Hyperlocal Event Discovery & Community Engagement Platform**

EventAdda centralizes discovery for hackathons, workshops, summits/conferences, and meetups with personalized location-aware recommendations and direct in-app registration.

## Tech Stack
- **Frontend:** Responsive HTML5, CSS3, and Vanilla JavaScript (`frontend/`)
- **Backend:** Python with FastAPI (`backend/`)
- **Database:** MongoDB with Motor async driver

## Project Structure
- `backend/` — FastAPI application, Pydantic schemas, JWT authentication, onboarding, profile endpoints, and `pytest` suite.
- `frontend/` — Static HTML/CSS/JS frontend integrated with Stage 1 backend endpoints.
- `docs/` — Shared API contract (`docs/api_contract.md`) and decisions register (`docs/decisions.md`).
- `Part_a Implementation Plan.pdf` & `Part_b Implementation Plan.pdf` — Requirements and architecture reference documents.

## Running Locally

### 1. Start the Backend (`http://localhost:8000`)
```powershell
cd backend
Copy-Item .env.example .env
# Ensure MONGODB_URL in .env points to a running local MongoDB or MongoDB Atlas cluster
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Serve the Frontend (`http://localhost:5500`)
In a separate terminal:
```powershell
cd frontend
..\backend\.venv\Scripts\python.exe -m http.server 5500
```
Open `http://localhost:5500` in your browser.

### 3. Seed Demo Data (Optional — For Local Demo & Testing)
To populate `eventadda_db` with 6 demo organizer accounts, 1 demo participant account, and 34 realistic published events across all 8 UI categories (without wiping existing collections or modifying real user records):

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\seed_demo_data.py
```

The seed script is idempotent and safe to run multiple times. To refresh relative future event dates on existing demo events, pass `--refresh-dates`:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\seed_demo_data.py --refresh-dates
```

#### Local Demo Login Credentials
> **Note:** These are local-only development/demo credentials seeded by `scripts/seed_demo_data.py` (overridable via `EVENTADDA_DEMO_PASSWORD`). Never use them in production.

| Role | Email | Password | Organization / Affiliation |
| :--- | :--- | :--- | :--- |
| **Participant** | `participant@demo.eventadda.in` | `DemoPass2026` | COEP Technological University / Computer Engineering |
| **Organizer** | `gdg.pune@demo.eventadda.in` | `DemoPass2026` | Google Developer Group Pune |
| **Organizer** | `ecell.iitb@demo.eventadda.in` | `DemoPass2026` | E-Cell IIT Bombay |
| **Organizer** | `makers.blr@demo.eventadda.in` | `DemoPass2026` | Bengaluru Makers Collective |
| **Organizer** | `sound.delhi@demo.eventadda.in` | `DemoPass2026` | Delhi Sound Society |
| **Organizer** | `sports.hyd@demo.eventadda.in` | `DemoPass2026` | Hyderabad Campus Sports League |
| **Organizer** | `food.mumbai@demo.eventadda.in` | `DemoPass2026` | Mumbai Food & Culture Collective |

### 4. Run Automated Tests
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v
```
