import logging
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING
from pymongo.collation import Collation
from pymongo.errors import OperationFailure

from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None


async def connect_to_mongo(app: Optional[Any] = None) -> None:
    """Initialize the shared Motor client and ensure database indexes safely."""
    global _client, _database
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            serverSelectionTimeoutMS=3000,
        )
        _database = _client[settings.DATABASE_NAME]

    if app is not None:
        app.mongodb_client = _client
        app.db = _database

    try:
        await ensure_indexes(_database)
        logger.info("Connected to MongoDB (%s)", settings.DATABASE_NAME)
    except Exception as exc:
        logger.warning(
            "Database index initialization deferred (MongoDB not yet reachable): %s",
            type(exc).__name__,
        )


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create required indexes idempotently across users, registrations, payments, and notifications."""
    users = db["users"]
    try:
        await users.create_index(
            [("email", ASCENDING)],
            name="idx_email_unique",
            unique=True,
            collation=Collation(locale="en", strength=2),
        )
    except OperationFailure:
        # Fallback if a default unique index on email (e.g. email_1) already exists
        await users.create_index("email", unique=True)

    await users.create_index(
        [("phone", ASCENDING)],
        name="idx_phone_unique",
        unique=True,
    )
    await users.create_index(
        [("location.coordinates", "2dsphere")],
        name="idx_location_geo",
        sparse=True,
    )

    registrations = db["registrations"]
    await registrations.create_index(
        [("active_slot_key", ASCENDING)],
        name="idx_reg_active_slot_unique",
        unique=True,
        sparse=True,
    )
    await registrations.create_index(
        [("participant_id", ASCENDING), ("created_at", ASCENDING)],
        name="idx_reg_participant_created",
    )
    await registrations.create_index(
        [("event_id", ASCENDING), ("status", ASCENDING), ("reservation_expires_at", ASCENDING)],
        name="idx_reg_event_status",
    )

    payments = db["payments"]
    await payments.create_index(
        [("razorpay_order_id", ASCENDING)],
        name="idx_pay_order_id_unique",
        unique=True,
        sparse=True,
    )
    await payments.create_index(
        [("razorpay_payment_id", ASCENDING)],
        name="idx_pay_payment_id_unique",
        unique=True,
        sparse=True,
    )
    await payments.create_index(
        [("registration_id", ASCENDING), ("attempt_number", ASCENDING)],
        name="idx_pay_reg_attempt_unique",
        unique=True,
    )

    notifications = db["notifications"]
    await notifications.create_index(
        [("dedupe_key", ASCENDING)],
        name="idx_notif_dedupe_unique",
        unique=True,
        sparse=True,
    )
    await notifications.create_index(
        [("status", ASCENDING), ("scheduled_at", ASCENDING), ("next_retry_at", ASCENDING)],
        name="idx_notif_due_jobs",
    )


async def close_mongo_connection(app: Optional[Any] = None) -> None:
    """Close Motor client connection cleanly."""
    global _client, _database
    if _client is not None:
        _client.close()
        _client = None
        _database = None
        logger.info("MongoDB connection closed")
    if app is not None:
        app.mongodb_client = None
        app.db = None


def get_database() -> AsyncIOMotorDatabase:
    """FastAPI dependency returning the active database handle."""
    global _client, _database
    if _database is None:
        _client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            serverSelectionTimeoutMS=3000,
        )
        _database = _client[settings.DATABASE_NAME]
    return _database


async def check_database_health(db: Optional[AsyncIOMotorDatabase] = None) -> bool:
    """Ping MongoDB to verify database connectivity without exposing credentials."""
    target_db = db if db is not None else get_database()
    try:
        result = await target_db.command("ping")
        return bool(result and result.get("ok") == 1.0)
    except Exception:
        return False
