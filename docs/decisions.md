# EventAdda — Architecture & Product Decisions Register

1. **Account Role Model:** Pending confirmation (Single role per account vs. Dual role support).
2. **Contact Verification:** Email & phone collected and uniqueness enforced at DB level; live OTP deferred for MVP.
3. **Email Delivery:** Console fallback in development; optional SMTP via `.env`.
