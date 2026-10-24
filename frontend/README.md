# EventADDA Frontend

Responsive HTML/CSS + vanilla JavaScript frontend integrated with the FastAPI backend.

- **`css/style.css` is untouched** — preserves the original purple-and-white visual theme, gradients, cards, and animations.
- **`css/extra.css`** — contains minimal helper styles for dashboard forms, profile panels, and status banners.
- **`js/main.js`** — centralized API client (`http://localhost:8000` by default, configurable via `window.EVENTADDA_API_BASE_URL` or `localStorage.getItem("eventaddaApiBaseUrl")`), JWT bearer session management, Stage 1 auth/onboarding/profile integration, and honest Stage 2/3 preview states.

## Pages
- `index.html` — Landing page with category cards.
- `login.html` / `signup.html` — Role entry selection (`participant` or `organizer`).
- `login-participant.html`, `signup-participant.html` — Participant login and signup (connected to `POST /api/auth/signup`, `PUT /api/onboarding/interests`, `PUT /api/onboarding/location`, `POST /api/onboarding/complete`, `POST /api/auth/login`, and `GET /api/auth/me`).
- `login-organizer.html`, `signup-organizer.html` — Organizer login and signup (connected to `POST /api/auth/signup`, `PUT /api/profile`, `POST /api/auth/login`, and `GET /api/auth/me`).
- `dashboard-participant.html` — Participant dashboard with live Account & Profile / Onboarding management panel (`GET/PUT /api/profile`, `PUT /api/onboarding/*`) and event discovery preview.
- `dashboard-organizer.html` — Organizer dashboard with live Account & Profile panel (`GET/PUT /api/profile`) and event management UI (awaiting Stage 2 `/api/organizer/events` backend endpoints).
- `events.html` & `event.html` — Event listing and detail pages (awaiting Stage 2 `/api/events` and Stage 3 `/api/registrations` backend endpoints).

## Serving the Frontend Locally

Do not open HTML files via `file://` when testing backend integration, as browsers restrict CORS on `file://` origins. Serve the `frontend/` directory over HTTP:

```powershell
cd frontend
..\backend\.venv\Scripts\python.exe -m http.server 5500
```

Then open `http://localhost:5500` in your browser while the FastAPI backend is running on `http://localhost:8000`.
