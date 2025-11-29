"""Authentication middleware for API key validation."""

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import structlog

from src.config import settings

logger = structlog.get_logger()

# Endpoints that don't require authentication
PUBLIC_ENDPOINTS = [
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/v1/health",
]


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware to validate API key for protected endpoints."""

    async def dispatch(self, request: Request, call_next):
        """Process request and validate API key."""
        # Skip auth for public endpoints
        if request.url.path in PUBLIC_ENDPOINTS:
            return await call_next(request)

        # Check for API key in header
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            logger.warning(
                "auth_missing_key",
                path=request.url.path,
                client=request.client.host if request.client else None,
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": {
                        "code": "MISSING_API_KEY",
                        "message": "API key required. Provide X-API-Key header.",
                    }
                },
            )

        # Validate API key
        if api_key != settings.bonding_api_key:
            logger.warning(
                "auth_invalid_key",
                path=request.url.path,
                client=request.client.host if request.client else None,
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "error": {
                        "code": "INVALID_API_KEY",
                        "message": "Invalid API key.",
                    }
                },
            )

        # API key valid, proceed with request
        response = await call_next(request)
        return response
