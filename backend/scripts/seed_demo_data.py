"""Idempotent demo-data seeder for EventAdda (LOCAL DEVELOPMENT / DEMO ONLY).

What it does
------------
* Creates 6 demo organizer accounts and 1 demo participant account using the
  application's own password hashing (``app.core.security.hash_password``) and
  the same user document shape produced by ``POST /api/auth/signup``.
* Creates 34 published demo events (4-5 per UI category) owned by those
  organizers. Every event payload is validated through ``EventCreateRequest``
  before insertion, so dates, pricing and registration URLs follow the exact
  same rules as the real organizer API.

Safety guarantees
-----------------
* Never deletes documents and never drops or wipes collections.
* Never modifies real (non-demo) users. If a demo e-mail or phone number is
  already used by a non-demo account, that demo record is skipped.
* Idempotent: records are keyed by ``demo_seed_key``. Re-running the script
  skips records that already exist, so manually edited demo events are left
  untouched. Use ``--refresh-dates`` to move existing demo events back into
  the future (only their date fields are updated).
* All demo records carry ``is_demo: True`` and a ``demo_seed_key``; demo
  accounts use the reserved ``@demo.eventadda.in`` e-mail domain.
* Passwords, hashes and tokens are never printed.

Usage (from the ``backend`` directory)::

    .\\.venv\\Scripts\\python.exe scripts\\seed_demo_data.py
    .\\.venv\\Scripts\\python.exe scripts\\seed_demo_data.py --refresh-dates

The demo password defaults to the documented local-only value in README.md and
can be overridden with the ``EVENTADDA_DEMO_PASSWORD`` environment variable.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pymongo.errors import DuplicateKeyError  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.events.schemas import EventCreateRequest  # noqa: E402

DEMO_EMAIL_DOMAIN = "demo.eventadda.in"
DEFAULT_DEMO_PASSWORD = "DemoPass2026"  # Local demo only - documented in README.md
IST = timezone(timedelta(hours=5, minutes=30))

# --------------------------------------------------------------------------- #
# Demo accounts
# --------------------------------------------------------------------------- #
DEMO_ORGANIZERS: list[dict[str, Any]] = [
    {"key": "org-gdg-pune", "full_name": "Arjun Kulkarni", "email": f"gdg.pune@{DEMO_EMAIL_DOMAIN}",
     "phone": "+919400000101", "organization_name": "Google Developer Group Pune", "city": "Pune"},
    {"key": "org-iitb-ecell", "full_name": "Meera Iyer", "email": f"ecell.iitb@{DEMO_EMAIL_DOMAIN}",
     "phone": "+919400000102", "organization_name": "E-Cell IIT Bombay", "city": "Mumbai"},
    {"key": "org-blr-makers", "full_name": "Rohan Shetty", "email": f"makers.blr@{DEMO_EMAIL_DOMAIN}",
     "phone": "+919400000103", "organization_name": "Bengaluru Makers Collective", "city": "Bengaluru"},
    {"key": "org-delhi-sound", "full_name": "Kabir Malhotra", "email": f"sound.delhi@{DEMO_EMAIL_DOMAIN}",
     "phone": "+919400000104", "organization_name": "Delhi Sound Society", "city": "Delhi"},
    {"key": "org-hyd-sports", "full_name": "Ananya Reddy", "email": f"sports.hyd@{DEMO_EMAIL_DOMAIN}",
     "phone": "+919400000105", "organization_name": "Hyderabad Campus Sports League", "city": "Hyderabad"},
    {"key": "org-mum-food", "full_name": "Sana Qureshi", "email": f"food.mumbai@{DEMO_EMAIL_DOMAIN}",
     "phone": "+919400000106", "organization_name": "Mumbai Food & Culture Collective", "city": "Mumbai"},
]

DEMO_PARTICIPANT: dict[str, Any] = {
    "key": "participant-demo", "full_name": "Priya Deshmukh", "email": f"participant@{DEMO_EMAIL_DOMAIN}",
    "phone": "+919400000201", "affiliation_details": "COEP Technological University / Computer Engineering",
    "city": "Pune", "interests": ["hackathons", "workshops", "summits_conferences", "design"],
}

# --------------------------------------------------------------------------- #
# Demo events: (key, category_slug, title, summary, details, organizer_key,
#               city, venue_name, address, mode, days_ahead, start_hour_ist,
#               duration_hours, price_inr_or_None, tags, capacity)
# Category slugs map to UI labels: hackathons=Hackathon, summits_conferences=
# Tech Talk, workshops=Workshop, business=Startup, arts=Music, sports=Sports,
# design=Art, meetups=Food.
# --------------------------------------------------------------------------- #
ONLINE = "Online"
DEMO_EVENTS: list[tuple] = [
    # Hackathon (5)
    ("hack-pune-36", "hackathons", "HackPune 36: Build for Bharat",
     "A 36-hour national hackathon for civic-tech and AI ideas that solve real Indian problems.",
     "Teams of 2-4. Mentors from Google, Persistent and local startups. Meals, swag and a Rs 1.5 lakh prize pool.",
     "org-gdg-pune", "Pune", "COEP Technological University", "Shivajinagar", "In-person", 9, 9, 36, None,
     ["ai", "civic-tech", "students"], 400),
    ("hack-mumbai-fintech", "hackathons", "Mumbai FinTech Sprint",
     "24 hours to prototype the next UPI-scale product with real banking sandbox APIs.",
     "Problem statements from partner banks and NBFCs. Registration fee covers food and overnight access.",
     "org-iitb-ecell", "Mumbai", "IIT Bombay - VMCC", "Powai", "In-person", 14, 10, 24, 299,
     ["fintech", "upi", "apis"], 250),
    ("hack-climate-blr", "hackathons", "Green Code Climate Hack",
     "Build tools for cleaner cities, smarter energy and climate resilience.",
     "Hybrid format: join on-site in Domlur or remotely. Datasets provided by city climate partners.",
     "org-blr-makers", "Bengaluru", "Bangalore International Centre", "Domlur", "Hybrid", 20, 9, 30, None,
     ["climate", "sustainability", "data"], 300),
    ("hack-oss-weekend", "hackathons", "Open Source Weekend: Contrib-a-thon",
     "Ship your first meaningful open-source pull request with maintainers guiding you live.",
     "Curated beginner-friendly issues across Python, JavaScript and Go projects. Runs on Discord and GitHub.",
     "org-gdg-pune", ONLINE, "Online - Discord & GitHub", "", "Online", 6, 11, 48, None,
     ["open-source", "github", "beginners"], 1000),
    ("hack-healthtech-hyd", "hackathons", "HealthTech Hack Hyderabad",
     "Design digital health solutions with doctors and public-health researchers in the room.",
     "Tracks: rural diagnostics, mental health and hospital operations. Small fee covers meals.",
     "org-hyd-sports", "Hyderabad", "T-Hub Phase 2", "Madhapur", "In-person", 27, 9, 24, 199,
     ["healthtech", "ai", "social-impact"], 200),
    # Tech Talk (4)
    ("talk-cloud-native-pune", "summits_conferences", "Cloud Native Pune Summit 2026",
     "A full day of talks on Kubernetes, platform engineering and observability at scale.",
     "12 speakers, 2 tracks, hallway-track networking and lunch included with the pass.",
     "org-gdg-pune", "Pune", "Hyatt Regency", "Viman Nagar", "In-person", 12, 10, 8, 799,
     ["cloud", "kubernetes", "devops"], 350),
    ("talk-ai-in-production", "summits_conferences", "AI in Production: Lessons from Indian Startups",
     "Engineering leaders share what actually works when shipping LLM features to millions of users.",
     "Panel plus three lightning talks, followed by open Q&A. Attend in person or via livestream.",
     "org-blr-makers", "Bengaluru", "NIMHANS Convention Centre", "Wilson Garden", "Hybrid", 8, 17, 3, None,
     ["ai", "llm", "engineering"], 500),
    ("talk-women-in-tech", "summits_conferences", "Women in Tech Leadership Talks",
     "Stories, strategies and candid conversations from women leading engineering teams.",
     "Keynote, fireside chat and mentorship speed-rounds for students and early-career engineers.",
     "org-iitb-ecell", "Mumbai", "Jio World Convention Centre", "BKC", "In-person", 18, 15, 4, None,
     ["leadership", "diversity", "careers"], 300),
    ("talk-security-night", "summits_conferences", "Security Engineering Deep-Dive Night",
     "Real-world breach post-mortems and practical web security for developers.",
     "Live demos of common API vulnerabilities and how to fix them. Online, cameras optional.",
     "org-blr-makers", ONLINE, "Online - YouTube Live", "", "Online", 5, 19, 2, None,
     ["security", "web", "apis"], 1000),
    # Workshop (5)
    ("ws-fastapi-mongo", "workshops", "FastAPI & MongoDB: Zero to Deploy",
     "Build and deploy a production-ready REST API in a single hands-on day.",
     "Bring a laptop with Python 3.11+. Covers async Motor, Pydantic validation, JWT auth and deployment.",
     "org-gdg-pune", "Pune", "Symbiosis Institute of Technology", "Lavale", "In-person", 10, 10, 6, 499,
     ["python", "fastapi", "mongodb"], 60),
    ("ws-figma-design-systems", "workshops", "Figma to Front-end: Design Systems Lab",
     "Turn a Figma component library into accessible, reusable front-end code.",
     "Hands-on session with tokens, variants and responsive layout. Laptop required.",
     "org-blr-makers", "Bengaluru", "Makers Asylum", "Indiranagar", "In-person", 7, 11, 5, 349,
     ["design-systems", "figma", "frontend"], 40),
    ("ws-arduino-robotics", "workshops", "Intro to Robotics with Arduino",
     "Wire, code and race your first line-following robot.",
     "All kits provided and yours to keep. No prior electronics experience needed.",
     "org-blr-makers", "Bengaluru", "Makers Asylum", "Indiranagar", "In-person", 22, 10, 4, 599,
     ["robotics", "arduino", "hardware"], 30),
    ("ws-git-github", "workshops", "Git & GitHub for First-Year Students",
     "Learn branching, pull requests and collaboration the way real teams do it.",
     "Beginner-friendly live session with exercises and a certificate of participation.",
     "org-gdg-pune", ONLINE, "Online - Google Meet", "", "Online", 4, 18, 2, None,
     ["git", "github", "beginners"], 500),
    ("ws-dataviz-python", "workshops", "Data Visualisation with Python",
     "Tell compelling stories with pandas, Matplotlib and Plotly.",
     "Work through real Indian open-data sets. Attend at IIT Bombay or join online.",
     "org-iitb-ecell", "Mumbai", "IIT Bombay - KReSIT", "Powai", "Hybrid", 16, 14, 4, None,
     ["python", "data", "visualisation"], 120),
    # Startup (4)
    ("su-esummit-pitch", "business", "E-Summit Pitch Night",
     "Ten student startups pitch to founders and early-stage investors.",
     "Audience voting, investor feedback and networking over dinner.",
     "org-iitb-ecell", "Mumbai", "IIT Bombay - Student Activity Centre", "Powai", "In-person", 11, 18, 4, None,
     ["pitching", "startups", "investors"], 300),
    ("su-founders-breakfast", "business", "Founders' Breakfast: Bootstrapping 101",
     "An intimate breakfast session on building a profitable startup without outside funding.",
     "Limited seats. Breakfast included. Bring your toughest questions.",
     "org-iitb-ecell", "Mumbai", "WeWork BKC", "Bandra Kurla Complex", "In-person", 6, 8, 2, 249,
     ["bootstrapping", "founders"], 40),
    ("su-student-expo-blr", "business", "Student Startup Expo Bengaluru",
     "Explore 60+ student-built products and meet the teams behind them.",
     "Expo floor, demo stage and recruiter lounge. Entry fee supports exhibitor stalls.",
     "org-blr-makers", "Bengaluru", "KTPO Convention Centre", "Whitefield", "In-person", 25, 10, 8, 99,
     ["expo", "startups", "careers"], 800),
    ("su-fundraising-clinic", "business", "Fundraising Clinic with Angel Investors",
     "Learn how angels evaluate early-stage startups and what makes a deck stand out.",
     "Live deck teardown of three volunteer startups. Online session.",
     "org-iitb-ecell", ONLINE, "Online - Zoom", "", "Online", 13, 19, 2, None,
     ["fundraising", "angels", "pitch-deck"], 600),
    # Music (4)
    ("mu-indie-nights", "arts", "Indie Nights: Campus Band Showcase",
     "Six of Delhi's best college bands, one stage, one unforgettable night.",
     "Doors open 6:30 PM. Tickets include entry and a festival wristband.",
     "org-delhi-sound", "Delhi", "Kamani Auditorium", "Mandi House", "In-person", 9, 19, 4, 399,
     ["live-music", "indie", "bands"], 600),
    ("mu-sufi-folk", "arts", "Sufi & Folk Evening",
     "An intimate evening of qawwali, folk ballads and storytelling.",
     "Seated performance with a short artist conversation at the interval.",
     "org-delhi-sound", "Delhi", "India Habitat Centre", "Lodhi Road", "In-person", 15, 18, 3, 299,
     ["sufi", "folk", "culture"], 250),
    ("mu-open-mic", "arts", "Open Mic: Songwriters' Circle",
     "Share an original song or just come to listen to new voices.",
     "Sign-ups at the door, 8 minutes per performer. Free entry.",
     "org-delhi-sound", "Delhi", "The Piano Man Jazz Club", "Safdarjung Enclave", "In-person", 5, 20, 3, None,
     ["open-mic", "songwriting"], 120),
    ("mu-beatmaking", "arts", "Beat-Making Workshop & Jam",
     "Produce your first beat with industry producers, then jam it out live.",
     "Laptops with a free DAW recommended. Headphones provided.",
     "org-delhi-sound", "Mumbai", "Bandra Base", "Bandra West", "In-person", 19, 16, 4, 499,
     ["production", "hip-hop", "jam"], 50),
    # Sports (4)
    ("sp-futsal-cup", "sports", "Inter-College Futsal Cup",
     "Five-a-side knockout tournament for college teams across Telangana.",
     "Fee is per team of up to 7 players. Referees, medals and trophies provided.",
     "org-hyd-sports", "Hyderabad", "Gachibowli Indoor Stadium", "Gachibowli", "In-person", 12, 8, 10, 999,
     ["football", "futsal", "tournament"], 32),
    ("sp-sunrise-10k", "sports", "Sunrise 10K Run Hyderabad",
     "Run 10K around Hussain Sagar as the city wakes up.",
     "Timed chip, finisher medal, hydration stations and post-run breakfast.",
     "org-hyd-sports", "Hyderabad", "Necklace Road", "Hussain Sagar", "In-person", 8, 6, 3, 349,
     ["running", "fitness"], 1500),
    ("sp-chess-rapid", "sports", "Campus Chess Rapid Open",
     "A rated rapid chess open for students of every level.",
     "Swiss format, 7 rounds, 15+10 time control. Boards and clocks provided.",
     "org-hyd-sports", "Hyderabad", "University of Hyderabad", "Gachibowli", "In-person", 17, 10, 6, None,
     ["chess", "strategy"], 150),
    ("sp-valorant-showdown", "sports", "Esports Valorant Showdown",
     "Inter-college Valorant tournament streamed live with casters.",
     "Teams of 5. Group stage online, finals streamed. Free to enter.",
     "org-hyd-sports", ONLINE, "Online - Discord & Twitch", "", "Online", 10, 17, 6, None,
     ["esports", "gaming"], 320),
    # Art (4)
    ("art-sketch-colour", "design", "Sketch & Colour Day",
     "A relaxed day of live sketching, watercolours and a pop-up exhibition.",
     "All skill levels welcome. Basic materials provided; bring your favourite pens.",
     "org-blr-makers", "Bengaluru", "Rangoli Metro Art Center", "MG Road", "In-person", 7, 11, 5, None,
     ["sketching", "watercolour"], 80),
    ("art-uiux-portfolio", "design", "UI/UX Portfolio Review Night",
     "Get your design portfolio reviewed live by senior product designers.",
     "Submit a portfolio link when registering. Reviews happen in small breakout rooms.",
     "org-blr-makers", ONLINE, "Online - Google Meet", "", "Online", 9, 18, 3, None,
     ["ux", "portfolio", "careers"], 200),
    ("art-mural-walk", "design", "Street Art & Mural Walk",
     "Discover the stories behind Bandra's most iconic murals with the artists.",
     "Guided 3-hour walk. Comfortable shoes recommended. Fee covers the guide and a zine.",
     "org-mum-food", "Mumbai", "Chapel Road", "Bandra West", "In-person", 14, 9, 3, 199,
     ["street-art", "walk"], 35),
    ("art-typography-lab", "design", "Typography & Poster Design Lab",
     "Explore type, grids and colour by designing a gig poster from scratch.",
     "Studio session with printmaking demo. Materials included.",
     "org-gdg-pune", "Pune", "MIT Institute of Design", "Loni Kalbhor", "In-person", 21, 10, 5, 449,
     ["typography", "poster", "graphic-design"], 40),
    # Food (4)
    ("food-street-fest-hyd", "meetups", "Street Food Fest Hyderabad",
     "Over 40 stalls of biryani, haleem, chaat and desserts by the lake.",
     "Free entry. Food is pay-as-you-go at individual stalls.",
     "org-mum-food", "Hyderabad", "People's Plaza", "Necklace Road", "In-person", 13, 12, 8, None,
     ["street-food", "festival"], 3000),
    ("food-monsoon-walk", "meetups", "Mumbai Monsoon Food Walk",
     "A guided evening walk through Mohammed Ali Road's legendary food lanes.",
     "Fee includes tastings at eight stops. Vegetarian options available.",
     "org-mum-food", "Mumbai", "Mohammed Ali Road", "Bhendi Bazaar", "In-person", 6, 18, 3, 599,
     ["food-walk", "heritage"], 25),
    ("food-chai-code", "meetups", "Developers' Chai & Code Meetup",
     "Casual monthly meetup for developers - chai, lightning demos and good conversation.",
     "Bring something you built (or broke) this month. Chai on us.",
     "org-gdg-pune", "Pune", "Third Wave Coffee", "Baner", "In-person", 4, 17, 3, None,
     ["community", "networking"], 60),
    ("food-cookoff", "meetups", "Regional Cuisine Cook-off",
     "Student teams compete to cook the best regional dish in 90 minutes.",
     "Fee is per team of 3. Ingredients basics provided; judges include local chefs.",
     "org-mum-food", "Mumbai", "Dadar Parsi Colony Gymkhana", "Dadar", "In-person", 20, 11, 6, 299,
     ["cooking", "competition"], 24),
]


def _event_dates(days_ahead: int, start_hour_ist: int, duration_hours: int) -> tuple[datetime, datetime, datetime]:
    """Compute future UTC start/end/deadline that satisfy backend validation."""
    today_ist = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    start = (today_ist + timedelta(days=days_ahead, hours=start_hour_ist)).astimezone(timezone.utc)
    end = start + timedelta(hours=duration_hours)
    deadline = start - timedelta(days=1)
    return start, end, deadline


def _base_user_doc(spec: dict[str, Any], role: str, password: str, now: datetime) -> dict[str, Any]:
    """Mirror the user document produced by app.auth.service.create_user_account."""
    return {
        "full_name": spec["full_name"],
        "email": spec["email"].lower(),
        "phone": spec["phone"],
        "password_hash": hash_password(password),
        "role": role,
        "affiliation_details": spec.get("affiliation_details") if role == "participant" else None,
        "organization_name": spec.get("organization_name") if role == "organizer" else None,
        "interests": list(spec.get("interests") or []),
        "location": {"city": spec["city"], "locality": None, "coordinates": None} if spec.get("city") else None,
        "onboarding_completed": role == "participant",
        "email_verified": False,
        "phone_verified": False,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "is_demo": True,
        "demo_seed_key": spec["key"],
    }


async def _ensure_user(db: Any, spec: dict[str, Any], role: str, password: str, stats: Counter) -> Optional[dict[str, Any]]:
    users = db["users"]
    existing = await users.find_one({"email": spec["email"].lower()})
    if existing:
        if not existing.get("is_demo"):
            print(f"  ! Skipping {spec['key']}: e-mail belongs to a non-demo account (left untouched).")
            stats["users_skipped_conflict"] += 1
            return None
        stats["users_existing"] += 1
        return existing
    phone_owner = await users.find_one({"phone": spec["phone"]})
    if phone_owner and not phone_owner.get("is_demo"):
        print(f"  ! Skipping {spec['key']}: phone belongs to a non-demo account (left untouched).")
        stats["users_skipped_conflict"] += 1
        return None
    doc = _base_user_doc(spec, role, password, datetime.now(timezone.utc))
    try:
        res = await users.insert_one(doc)
    except DuplicateKeyError:
        print(f"  ! Skipping {spec['key']}: unique e-mail/phone conflict.")
        stats["users_skipped_conflict"] += 1
        return None
    doc["_id"] = res.inserted_id
    stats["users_created"] += 1
    return doc


def _build_event_doc(row: tuple, organizer: dict[str, Any], now: datetime) -> dict[str, Any]:
    (key, category, title, summary, details, _org_key, city, venue_name, address, mode,
     days_ahead, start_hour, duration, price, tags, capacity) = row
    start, end, deadline = _event_dates(days_ahead, start_hour, duration)
    registration_url = f"https://example.com/eventadda-demo/register/{key}"
    payload = EventCreateRequest(
        title=title,
        description=f"{summary}\n\n{details}",
        category=category,
        tags=tags,
        venue={"name": venue_name, "address": address, "city": city},
        start_date=start,
        end_date=end,
        registration_deadline=deadline,
        max_capacity=capacity,
        status="published",
        mode=mode,
        contact_email=organizer["email"],
        price_type="paid" if price else "free",
        price_amount=float(price) if price else None,
        registration_url=registration_url,
    )
    org_name = organizer.get("organization_name") or organizer.get("full_name") or "Event Organizer"
    # Same field set as app.events.service.create_organizer_event, plus demo markers.
    return {
        "title": payload.title,
        "description": payload.description,
        "category": payload.category,
        "tags": payload.tags,
        "organizer_id": organizer["_id"],
        "organizer_name": org_name,
        "organizer_full_name": organizer.get("full_name") or org_name,
        "organizer_organization": organizer.get("organization_name"),
        "venue": payload.venue.model_dump(exclude_none=True),
        "mode": payload.mode or "In-person",
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "registration_deadline": payload.registration_deadline,
        "max_capacity": payload.max_capacity,
        "registered_count": 0,
        "status": payload.status,
        "cover_image_url": None,
        "contact_email": payload.contact_email,
        "price_type": payload.price_type,
        "price_amount": payload.price_amount,
        "registration_url": payload.registration_url,
        "is_free": bool(payload.is_free),
        "created_at": now,
        "updated_at": now,
        "is_demo": True,
        "demo_seed_key": key,
    }


async def seed(db: Any, *, password: Optional[str] = None, refresh_dates: bool = False, verbose: bool = True) -> Counter:
    """Seed demo organizers, participant and events. Safe to run repeatedly."""
    password = password or os.environ.get("EVENTADDA_DEMO_PASSWORD") or DEFAULT_DEMO_PASSWORD
    stats: Counter = Counter()

    organizers: dict[str, dict[str, Any]] = {}
    for spec in DEMO_ORGANIZERS:
        doc = await _ensure_user(db, spec, "organizer", password, stats)
        if doc:
            organizers[spec["key"]] = doc
    await _ensure_user(db, DEMO_PARTICIPANT, "participant", password, stats)

    events = db["events"]
    per_category: Counter = Counter()
    for row in DEMO_EVENTS:
        key, category, org_key = row[0], row[1], row[5]
        organizer = organizers.get(org_key)
        if organizer is None:
            stats["events_skipped_no_organizer"] += 1
            continue
        existing = await events.find_one({"demo_seed_key": key})
        if existing:
            if not existing.get("is_demo"):
                stats["events_skipped_conflict"] += 1
                continue
            stats["events_existing"] += 1
            if refresh_dates:
                start, end, deadline = _event_dates(row[10], row[11], row[12])
                await events.update_one(
                    {"_id": existing["_id"], "is_demo": True},
                    {"$set": {"start_date": start, "end_date": end, "registration_deadline": deadline,
                              "updated_at": datetime.now(timezone.utc)}},
                )
                stats["events_dates_refreshed"] += 1
        else:
            await events.insert_one(_build_event_doc(row, organizer, datetime.now(timezone.utc)))
            stats["events_created"] += 1
        per_category[category] += 1

    if verbose:
        print("Demo seed summary")
        for label in ("users_created", "users_existing", "users_skipped_conflict",
                      "events_created", "events_existing", "events_dates_refreshed",
                      "events_skipped_conflict", "events_skipped_no_organizer"):
            print(f"  {label:<28} {stats[label]}")
        print("  demo events per category:", dict(sorted(per_category.items())))
    stats["demo_events_total"] = sum(per_category.values())
    return stats


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Seed EventAdda demo data (local only).")
    parser.add_argument("--refresh-dates", action="store_true",
                        help="Move existing demo events back into the future (dates only).")
    args = parser.parse_args()

    from motor.motor_asyncio import AsyncIOMotorClient

    from app.config import settings
    from app.core.database import ensure_indexes

    client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=4000)
    try:
        db = client[settings.DATABASE_NAME]
        await db.command("ping")
        print(f"Connected to MongoDB database '{settings.DATABASE_NAME}'.")
        await ensure_indexes(db)
        await seed(db, refresh_dates=args.refresh_dates)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(_main())
