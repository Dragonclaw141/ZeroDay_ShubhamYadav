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

### 3. Run Automated Tests
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v
```
