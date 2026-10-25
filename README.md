# EventAdda

### Discover what's happening around you.

**EventAdda is a hyperlocal event discovery and community engagement platform** that brings hackathons, workshops, summits, conferences, and meetups together in one place. Discover opportunities relevant to your interests, explore events around you, register directly through the platform, and keep track of your upcoming experiences.

The goal is simple: make finding meaningful events easier, more personalized, and more accessible.

---

## About the Project

Finding relevant events can be difficult when opportunities are scattered across different websites, social media platforms, and communities. EventAdda aims to bring these opportunities together through a centralized, location-aware platform designed for both event participants and organizers.

Whether you're a student looking for your next hackathon, a developer searching for a technical workshop, or an organizer bringing a community together, EventAdda provides a common place to discover, publish, and manage events.

Rather than functioning as just another event listing website, EventAdda focuses on the entire event journey — from discovery and registration to payment, notifications, and post-registration updates.

## What You Can Do with EventAdda

### Discover Events

Explore events across different categories and find opportunities that match your interests.

- **Hackathons:** Discover collaborative coding competitions and innovation challenges.
- **Workshops:** Find hands-on learning sessions and skill-building opportunities.
- **Summits & Conferences:** Explore professional gatherings, talks, and knowledge-sharing events.
- **Meetups:** Connect with communities and discover opportunities to learn and network.
- **Location-aware discovery:** Make relevant opportunities easier to find based on location.
- **Event details:** Review event information, schedules, venues, registration requirements, and pricing before committing.
- **Personalized recommendations:** Discover relevant events based on your interests and participation history, where recommendation data is available.

### Register with Confidence

EventAdda streamlines registration and helps participants keep track of their bookings.

- In-platform event registration.
- Required email and phone number during account registration.
- Event capacity limits to help prevent overbooking.
- Registration deadlines enforced by the backend.
- Clear registration and payment status tracking.
- Booking cancellation before the applicable registration deadline.
- Support for free and paid event registrations.
- Secure payment verification through Razorpay for configured payment flows.
- Booking records retained to preserve registration history.

### A Better Experience for Organizers

Organizers can use EventAdda to publish opportunities and manage the registration process.

- Create and prepare event drafts.
- Publish events immediately when ready.
- Edit published events, with updated information reflected for participants.
- Configure event details, venue, pricing, capacity, and registration deadlines.
- View registered attendees and relevant registration information.
- Manage event information through organizer-facing workflows.

### Stay Informed

Keep track of important information after registering.

- In-app notifications for relevant updates.
- Email notifications for important events and registration updates.
- Notifications when a registered event's date, time, or venue changes, or when it is cancelled.
- Event reminders scheduled ahead of the event.
- Background reminder scheduling with recovery mechanisms for supported reminder workflows.
- Separate tracking of booking and payment states to provide clearer registration outcomes.

### Personalized Event Discovery

EventAdda is designed to make event discovery more relevant over time.

The platform's direction includes using participant interests and participation data to surface suitable opportunities on the dashboard. This helps reduce the effort involved in repeatedly searching through unrelated listings.

Personalized recommendations are intended to appear on the participant dashboard rather than adding unnecessary notification clutter.

---

## Designed Around Two User Experiences

### For Participants

Discover opportunities, compare event details, register for events, complete eligible payments, and keep track of your bookings and notifications in one place.

### For Organizers

Prepare and publish events, update event information, configure registration rules, and access attendee details through organizer-facing workflows.

Each account operates under a single selected role — participant or organizer — keeping the experience focused on the user's intended purpose.

---

## Key Platform Highlights

| Capability | What it offers |
|---|---|
| Centralized discovery | Multiple event categories in one platform |
| Location awareness | Support for discovering geographically relevant opportunities |
| Registration management | Booking records, capacity checks, and deadline enforcement |
| Payment integration | Razorpay order creation and payment verification for configured paid registrations |
| Notifications | In-app updates, important email notifications, and reminders |
| Event management | Drafts, publishing, editing, and attendee information |
| Booking reliability | Backend-controlled registration and payment state transitions |
| Responsive interface | A web experience designed to adapt to different screen sizes |

## Technology Stack

EventAdda uses a lightweight web frontend backed by a Python API and a document-oriented database.

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Backend | Python, FastAPI |
| Database | MongoDB |
| Database driver | Motor, asynchronous MongoDB driver |
| Data validation | Pydantic |
| Authentication | JWT-based authentication |
| Payments | Razorpay integration |
| Testing | pytest |

### Why This Stack?

- **FastAPI** provides structured API development, request validation, and automatically generated API documentation.
- **MongoDB** provides a flexible document model for event information, user profiles, registrations, and related records.
- **Vanilla JavaScript** keeps the frontend lightweight without requiring a large client-side framework.
- **pytest** supports automated verification of backend behaviour and critical workflows.

---

## Architecture at a Glance

EventAdda follows a frontend–backend architecture.

```text
                 PARTICIPANTS / ORGANIZERS
                           |
                           v
                  HTML / CSS / JavaScript
                           |
                           v
                     FastAPI Backend
                           |
            +--------------+--------------+
            |              |              |
            v              v              v
        Accounts       Event &        Registration
      & Profiles      Discovery      & Booking Logic
                           |              |
                           v              v
                       MongoDB        Payments
                                          |
                                          v
                                       Razorpay

                  Notifications & Reminders
```

The frontend communicates with backend API endpoints, while the backend validates requests and controls important operations such as registration, capacity enforcement, payment verification, and notification workflows.

This separation helps keep business rules on the server rather than relying on frontend-only checks.

---

## Project Structure

The repository is organized into separate frontend, backend, and documentation areas.

```text
EventAdda/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   └── registrations/
│   ├── scripts/
│   │   └── seed_demo_data.py
│   ├── tests/
│   ├── .env.example
│   └── requirements.txt
│
├── frontend/
│   ├── index.html
│   ├── event.html
│   ├── events.html
│   ├── dashboard-participant.html
│   ├── js/
│   └── ...
│
├── docs/
│   ├── api_contract.md
│   └── decisions.md
│
└── README.md
```

*The tree above highlights the main areas; individual modules and files may vary as development progresses.*

---

## Getting Started

You can run EventAdda locally to explore the platform and its available workflows.

### Prerequisites

Install the following before getting started:

- Python 3.10 or a compatible version supported by the project's dependencies.
- MongoDB Community Server running locally, or another MongoDB instance you are authorized to use.
- Git.
- A modern web browser.

### 1. Clone the Repository

```bash
git clone <REPOSITORY_URL>
cd EventAdda
```

Replace `<REPOSITORY_URL>` with the repository's Git URL.

### 2. Set Up the Backend

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Alternatively, in Command Prompt:

```bat
.venv\Scripts\activate.bat
```

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create your local environment file using the provided example:

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env
```

Open `backend/.env` and configure the required values according to `backend/.env.example` and the project's configuration.

Ensure that the MongoDB connection points to the database you intend to use.

For paid registrations and email functionality, configure the relevant credentials if those services are required for your local run.

**Security note:** Keep `.env` private. Never commit API keys, payment secrets, email credentials, or other sensitive configuration to Git.

### 4. Start MongoDB

Start your local MongoDB service and confirm that the configured database connection is available.

For the default local configuration, the application uses:

```text
mongodb://127.0.0.1:27017
```

The database name is:

```text
eventadda_db
```

If you changed the connection settings in your environment file, use those settings instead.

### 5. Start the Backend

From the `backend` directory, with the virtual environment activated:

```bash
uvicorn app.main:app --reload
```

The backend will normally be available at:

```text
http://127.0.0.1:8000
```

Explore the interactive API documentation at:

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

### 6. Open the Frontend

Open the frontend using a local development server, such as the VS Code Live Server extension, or the development server configured for the project.

For example, if Live Server is configured to serve the frontend directory, open the local URL it provides.

Make sure the frontend's API configuration points to the running backend. Opening HTML files directly through `file://` may not work correctly for every API or browser operation.

---

## Exploring EventAdda with Demo Data

A fresh local installation may have no events or user accounts. To make it easier to explore the event catalogue and demonstrate available workflows, EventAdda provides an optional demo-data script.

### Populate the Local Database

From the repository root on Windows:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\seed_demo_data.py
```

This runs the repository's demo-data seeding script against the database configured for the backend.

The script provides sample events and demo accounts for local exploration. It is a development convenience, not a requirement for every installation.

**Important:**

- Start MongoDB and configure `backend/.env` before running the script.
- Use a local development database, not a production database.
- Demo records are stored in MongoDB, not inside the Git repository.
- The script is separate from normal application startup; launching the backend does not automatically populate demo records.
- Follow the script's output and instructions for any credentials or details needed to access the sample accounts.

After seeding, restart or refresh the application as necessary to explore the available events.

---

## Payments and External Services

### Razorpay

EventAdda includes Razorpay integration for supported paid-registration flows.

The intended payment flow uses backend-created orders and server-side verification of the payment response. Payment credentials must be configured locally for the relevant payment mode.

For local development, use Razorpay Test Mode credentials and test transactions. Do not use live credentials for experimentation.

Successful setup of the payment service depends on valid credentials and connectivity to the Razorpay API.

### Email and Notifications

Email delivery requires the relevant email service configuration. In-app notification workflows and scheduled reminders depend on the backend and database being available.

Some external services may not operate until their required credentials are configured.

---

## Development and Testing

EventAdda includes a backend test suite to verify important application behaviour.

From the `backend` directory, with the virtual environment activated:

```bash
python -m pytest
```

The suite covers backend functionality, including relevant registration, payment, and notification workflows.

Run the tests after changing business logic, particularly around registration eligibility, event capacity, payment verification, and booking status transitions.

---

### Razorpay Payments

EventAdda integrates Razorpay to support secure payment processing for paid event registrations.

Participants can use Razorpay Checkout to select an available payment method. For the best experience when exploring the payment flow locally, **we recommend using Netbanking in Razorpay Test Mode**.

#### Recommended Payment Flow

1. Open a paid event and proceed with registration.
2. Continue to the Razorpay Checkout window.
3. Select **Netbanking** from the available payment options.
4. Choose any available bank displayed by Razorpay.
5. On the simulated bank page, select **Success** or **Failure** to test the corresponding payment outcome.

Razorpay Test Mode provides a simulated payment experience, so you can explore the payment workflow without making a real bank transaction.

#### Configuration

To enable payment testing:

- Configure your Razorpay Test Mode API credentials in `backend/.env`.
- Keep the Razorpay secret key exclusively on the backend.
- Ensure the backend can connect to the Razorpay API.
- Restart the backend after changing environment variables.

EventAdda uses backend-created payment orders and server-side payment verification. Payment outcomes are processed through the existing registration and payment workflows.

**Note:** Netbanking is the recommended method for the local demonstration, but the available payment methods and banks are determined by Razorpay Checkout. The exact options displayed may vary.

Use Razorpay's official documentation for further configuration details: https://razorpay.com/docs/payments/payment-gateway/test-mode/

## Project Principles

EventAdda is built around a few core principles:

- **Accessibility:** Make relevant opportunities easier to discover.
- **Simplicity:** Keep discovery and registration straightforward.
- **Reliability:** Enforce important business rules on the backend.
- **Transparency:** Keep registration and payment states distinguishable.
- **Community:** Help people discover opportunities to learn, collaborate, and connect.
- **Maintainability:** Keep the frontend, backend, database, and documentation organized into understandable components.

---

## Project Status

EventAdda is an evolving web application. Its current implementation includes event discovery, account and role workflows, event registration, booking and payment handling, notifications, and organizer-facing functionality.

Some capabilities depend on configuration of external services, and the scope of functionality may continue to evolve as the platform develops.

---

## Contributing

Contributions, suggestions, and constructive feedback are welcome.

If you would like to contribute:

1. Fork the repository.
2. Create a branch for your change.
3. Make your changes and run the relevant tests.
4. Submit a pull request describing the change and its purpose.

For larger changes, discuss the proposed behaviour and its impact on existing workflows before implementation.

Please do not include private credentials, personal data, or production database exports in contributions.

---

## License

No license has been specified here. Unless a license is added to the repository, reuse and redistribution of the code are not automatically granted.

---

**EventAdda — Discover opportunities. Find your community. Make every event count.**
