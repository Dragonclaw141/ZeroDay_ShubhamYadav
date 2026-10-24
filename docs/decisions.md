# EventAdda — Architecture & Product Decisions Register

1. **Account Role Model (Confirmed):** Single role per account (`participant` or `organizer`). Enforced at signup and via backend role dependencies (`require_participant`, `require_organizer`). Role is immutable on profile updates.
2. **Contact Verification (Confirmed for MVP):** Email and phone are mandatory at signup and uniqueness is enforced at the database level (`idx_email_unique` with case-insensitive collation, `idx_phone_unique`). Live OTP/email verification workflows are deferred (`email_verified: false`, `phone_verified: false`).
3. **Password Hashing & JWT (Confirmed):** Passwords hashed with `bcrypt` (12 rounds, 72-byte limit enforced). Signed HS256 JWT access tokens issued via `python-jose`; `get_current_user` loads the live user document from MongoDB on every authenticated request.
4. **Email Delivery (Stage 3):** Console fallback in development; optional SMTP via `.env`.
