from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from app.auth.routes import router as auth_router
from app.config import settings
from app.core.database import (
    check_database_health,
    close_mongo_connection,
    connect_to_mongo,
    get_database,
)
from app.onboarding.routes import router as onboarding_router
from app.profile.routes import router as profile_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()


app = FastAPI(
    title="EventAdda API",
    description="Hyperlocal Event Discovery & Community Engagement Platform API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PyMongoError)
async def pymongo_exception_handler(_request: Request, _exc: PyMongoError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database service is temporarily unavailable"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    safe_errors = []
    for err in exc.errors():
        clean_err = {
            "loc": err.get("loc"),
            "msg": err.get("msg"),
            "type": err.get("type"),
        }
        safe_errors.append(clean_err)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": safe_errors},
    )


@app.get(
    "/health",
    tags=["Health"],
    summary="Application and database health check",
)
async def health_check(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> JSONResponse:
    db_ok = await check_database_health(db)
    payload: dict[str, Any] = {
        "status": "ok" if db_ok else "degraded",
        "service": "EventAdda Backend",
        "database": "connected" if db_ok else "unavailable",
    }
    http_status = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=http_status, content=payload)


app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(profile_router)
