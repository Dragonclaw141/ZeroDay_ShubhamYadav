import asyncio
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Callable, Optional

from app.config import settings
from app.events.schemas import ensure_utc_datetime

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# Optional test hook allowing tests to simulate provider failures for specific notification types or emails
_email_failure_hook: Optional[Callable[[str, str], Any]] = None
_sent_emails_log: list[dict[str, Any]] = []


def set_email_failure_hook(
    hook: Optional[Callable[[str, str], Any]],
) -> None:
    """Configure or clear a test-only failure hook: hook(notification_type, to_email) -> Optional[Exception | bool]."""
    global _email_failure_hook
    _email_failure_hook = hook


def get_sent_emails_log() -> list[dict[str, Any]]:
    return list(_sent_emails_log)


def clear_sent_emails_log() -> None:
    _sent_emails_log.clear()


def format_event_time_ist(dt: datetime) -> str:
    utc_dt = ensure_utc_datetime(dt)
    ist_dt = utc_dt.astimezone(IST)
    return ist_dt.strftime("%d %b %Y, %I:%M %p IST")


def build_registration_acknowledgement_email(
    user_doc: dict[str, Any],
    event_doc: dict[str, Any],
    registration_doc: dict[str, Any],
) -> tuple[str, str]:
    """Build subject and body for a confirmed registration acknowledgement."""
    title = event_doc.get("title", "Event")
    venue = event_doc.get("venue") or {}
    venue_label = f"{venue.get('name', '')}, {venue.get('city', '')}".strip(", ")
    start_str = format_event_time_ist(event_doc["start_date"])
    price_type = registration_doc.get("price_type", "free")
    price_amount = registration_doc.get("price_amount")
    price_str = (
        f"INR {price_amount:.2f} (Paid)"
        if price_type == "paid" and price_amount
        else "Free Entry"
    )
    subject = f"[EventADDA] Booking Confirmed: {title}"
    body = (
        f"Hi {user_doc.get('full_name', 'Participant')},\n\n"
        f"Your registration for '{title}' on EventADDA is confirmed.\n\n"
        f"Booking Reference: {registration_doc['_id']}\n"
        f"Event Start: {start_str}\n"
        f"Mode & Venue: {event_doc.get('mode', 'In-person')} — {venue_label}\n"
        f"Booking Tier: {price_str}\n\n"
        f"Note: Confirmed registration reserves your spot; event check-in is managed by the organizer at the venue.\n\n"
        f"— Team EventADDA"
    )
    return subject, body


def build_event_reminder_email(
    user_doc: dict[str, Any],
    event_doc: dict[str, Any],
    registration_doc: dict[str, Any],
) -> tuple[str, str]:
    """Build subject and body for a 24-hour upcoming event reminder."""
    title = event_doc.get("title", "Event")
    venue = event_doc.get("venue") or {}
    venue_label = f"{venue.get('name', '')}, {venue.get('city', '')}".strip(", ")
    start_str = format_event_time_ist(event_doc["start_date"])
    subject = f"[EventADDA] Reminder: '{title}' starts soon ({start_str})"
    body = (
        f"Hi {user_doc.get('full_name', 'Participant')},\n\n"
        f"This is your upcoming event reminder for '{title}'.\n\n"
        f"Booking Reference: {registration_doc['_id']}\n"
        f"Event Start: {start_str}\n"
        f"Mode & Venue: {event_doc.get('mode', 'In-person')} — {venue_label}\n"
        f"Organizer: {event_doc.get('organizer_name', 'Event Organizer')}\n\n"
        f"We look forward to seeing you there!\n\n"
        f"— Team EventADDA"
    )
    return subject, body


def _send_smtp_sync(
    to_email: str,
    subject: str,
    body_text: str,
    idempotency_key: str,
) -> str:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_USER or "noreply@eventadda.in"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["X-EventADDA-Idempotency-Key"] = idempotency_key
    msg.set_content(body_text)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
        server.ehlo()
        server.starttls()
        if settings.SMTP_USER and settings.SMTP_PASS:
            server.login(settings.SMTP_USER, settings.SMTP_PASS)
        server.send_message(msg)
    return f"smtp-{idempotency_key}"


async def send_email_message(
    *,
    to_email: str,
    subject: str,
    body_text: str,
    notification_type: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Send an email via console or SMTP while sharing transport between acknowledgements and reminders."""
    if _email_failure_hook is not None:
        maybe_exc = _email_failure_hook(notification_type, to_email)
        if isinstance(maybe_exc, Exception):
            raise maybe_exc
        if maybe_exc:
            raise RuntimeError(f"Simulated email delivery failure for {notification_type}")

    _sent_emails_log.append(
        {
            "to_email": to_email,
            "subject": subject,
            "notification_type": notification_type,
            "idempotency_key": idempotency_key,
        }
    )

    mode = (settings.EMAIL_MODE or "console").strip().lower()
    if mode == "smtp" and settings.SMTP_HOST:
        provider_msg_id = await asyncio.to_thread(
            _send_smtp_sync,
            to_email,
            subject,
            body_text,
            idempotency_key,
        )
        return {
            "accepted": True,
            "provider": "smtp",
            "provider_message_id": provider_msg_id,
        }

    logger.info(
        "[EMAIL:%s] to=%s subject=%r key=%s",
        notification_type,
        to_email,
        subject,
        idempotency_key,
    )
    return {
        "accepted": True,
        "provider": "console",
        "provider_message_id": f"console-{idempotency_key}",
    }
