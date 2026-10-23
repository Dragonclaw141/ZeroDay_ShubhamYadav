# EventAdda

**Hyperlocal Event Discovery & Community Engagement Platform**

EventAdda centralizes discovery for hackathons, workshops, summits/conferences, and meetups with personalized location-aware recommendations and direct in-app registration.

## Tech Stack
- **Frontend:** React
- **Backend:** Python (FastAPI)
- **Database:** MongoDB (Motor async driver)

## Project Structure
- `backend/` — FastAPI application, MongoDB models/services, seed scripts, and test suite.
- `frontend/` — React frontend application.
- `docs/` — Shared API contracts, decisions register, and mock payloads.
- `Part_a Implementation Plan.pdf` — Requirements and planning reference.

## Backend Setup

1. Create and activate the virtual environment:
   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
3. Configure environment variables:
   ```powershell
   Copy-Item .env.example .env
   ```
