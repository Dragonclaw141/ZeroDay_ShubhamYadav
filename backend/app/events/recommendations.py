import math
from datetime import datetime, timezone
from typing import Any

from app.events.schemas import (
    RecommendedEventItem,
    ensure_utc_datetime,
    serialize_event,
)


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Compute great-circle distance in kilometers between two [lng, lat] points."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def score_event_for_user(
    event_doc: dict[str, Any],
    user_doc: dict[str, Any],
    now: datetime,
) -> tuple[float, list[str]]:
    """
    Compute explainable recommendation score (0.0 to 1.0) and match reasons.
    Weights:
      - Interest Match: 50% (category match = 1.0, tag overlap = 0.6)
      - Location Relevance: 30% (coordinates distance or same city = 1.0, online/other = 0.3)
      - Freshness: 20% (within 7 days = 1.0, <=30 days = 0.7, <=90 days = 0.4, else = 0.2)
    """
    reasons: list[str] = []
    user_interests = {
        str(i).strip().lower() for i in (user_doc.get("interests") or []) if i
    }
    event_category = str(event_doc.get("category") or "").strip().lower()
    event_tags = {str(t).strip().lower() for t in (event_doc.get("tags") or []) if t}

    # 1. Interest score (weight 0.50)
    interest_score = 0.0
    if event_category and event_category in user_interests:
        interest_score = 1.0
        reasons.append(f"Matches your interest in {event_category.replace('_', ' ')}")
    else:
        matched_tags = sorted(user_interests.intersection(event_tags))
        if matched_tags:
            interest_score = 0.6
            reasons.append(f"Matches your topic interest in {matched_tags[0]}")

    # 2. Location score (weight 0.30)
    location_score = 0.2
    user_loc = user_doc.get("location") or {}
    user_city = str(user_loc.get("city") or "").strip()
    user_coords = (
        (user_loc.get("coordinates") or {}).get("coordinates")
        if isinstance(user_loc.get("coordinates"), dict)
        else None
    )

    venue = event_doc.get("venue") or {}
    venue_city = str(venue.get("city") or "").strip()
    venue_coords = (
        (venue.get("coordinates") or {}).get("coordinates")
        if isinstance(venue.get("coordinates"), dict)
        else None
    )

    if (
        isinstance(user_coords, list)
        and len(user_coords) == 2
        and isinstance(venue_coords, list)
        and len(venue_coords) == 2
    ):
        dist_km = _haversine_km(
            float(user_coords[0]),
            float(user_coords[1]),
            float(venue_coords[0]),
            float(venue_coords[1]),
        )
        if dist_km <= 5.0:
            location_score = 1.0
            reasons.append(f"Within 5 km of your location in {venue_city or user_city}")
        elif dist_km <= 25.0:
            location_score = 0.85
            reasons.append(f"Near your location in {venue_city or user_city}")
        elif dist_km <= 60.0:
            location_score = 0.55
        else:
            location_score = 0.2
    elif user_city and venue_city and user_city.lower() == venue_city.lower():
        location_score = 1.0
        reasons.append(f"In your preferred city ({venue_city})")
    elif venue_city.lower() == "online" or str(event_doc.get("mode") or "").lower() == "online":
        location_score = 0.5
        reasons.append("Online event accessible from anywhere")

    # 3. Freshness score (weight 0.20)
    start_date = ensure_utc_datetime(event_doc["start_date"])
    days_until = max(0.0, (start_date - now).total_seconds() / 86400.0)
    if days_until <= 7.0:
        freshness_score = 1.0
        reasons.append("Happening within the next 7 days")
    elif days_until <= 30.0:
        freshness_score = 0.7
    elif days_until <= 90.0:
        freshness_score = 0.4
    else:
        freshness_score = 0.2

    if not reasons:
        reasons.append("Upcoming open event on EventAdda")

    total_score = round(
        (0.50 * interest_score) + (0.30 * location_score) + (0.20 * freshness_score),
        2,
    )
    return total_score, reasons


def rank_recommended_events(
    candidate_docs: list[dict[str, Any]],
    user_doc: dict[str, Any],
    *,
    limit: int = 10,
) -> list[RecommendedEventItem]:
    """Filter eligible upcoming events and return top scored recommendations."""
    now = datetime.now(timezone.utc)
    scored_items: list[ tuple[float, datetime, RecommendedEventItem] ] = []

    for doc in candidate_docs:
        if doc.get("status") != "published":
            continue
        start_date = ensure_utc_datetime(doc["start_date"])
        deadline = ensure_utc_datetime(doc.get("registration_deadline") or start_date)
        max_cap = int(doc.get("max_capacity", 100))
        reg_count = int(doc.get("registered_count", 0))

        # Exclude past events, passed deadlines, or capacity-full events
        if start_date <= now or deadline <= now or reg_count >= max_cap:
            continue

        score, reasons = score_event_for_user(doc, user_doc, now)
        base_event = serialize_event(doc, is_registered=False)
        rec_item = RecommendedEventItem(
            **base_event.model_dump(),
            relevance_score=score,
            match_reasons=reasons,
        )
        scored_items.append((score, start_date, rec_item))

    # Sort by relevance_score descending, then earlier start_date ascending
    scored_items.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored_items[:limit]]
