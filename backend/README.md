# EventAdda Backend

FastAPI + Motor (MongoDB) backend for EventAdda.

## Local Setup

1. Activate the virtual environment:
   ```powershell
   cd backend
   .\.venv\Scripts\Activate.ps1
   ```
2. Configure environment variables:
   ```powershell
   Copy-Item .env.example .env
   ```
   Update `MONGODB_URL` and `JWT_SECRET_KEY` in `.env` as needed.

3. Start the FastAPI development server:
   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   - API root: `http://localhost:8000`
   - Health check: `http://localhost:8000/health`
   - Interactive OpenAPI docs: `http://localhost:8000/docs`

4. Run automated tests:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest -v
   ```
