"""FastAPI application entry point."""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from src.config import settings
from src.api.middleware.auth import AuthMiddleware
from src.api.routes import health, markets, pairs, arbitrage

# Configure structured logging
# Convert string log level to integer
log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer() if settings.log_format == "json" else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(log_level),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Create FastAPI app
app = FastAPI(
    title="Bonding Bot API",
    description="Market bonding agent for Kalshi and Polymarket cross-exchange arbitrage",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add authentication middleware
app.add_middleware(AuthMiddleware)

# Include routers
app.include_router(health.router, prefix="/v1", tags=["Health"])
app.include_router(markets.router, prefix="/v1/markets", tags=["Markets"])
app.include_router(pairs.router, prefix="/v1/pairs", tags=["Pairs"])
app.include_router(arbitrage.router, prefix="/v1", tags=["Arbitrage"])


@app.on_event("startup")
async def startup_event():
    """Run on application startup."""
    logger.info(
        "bonding_bot_startup",
        environment=settings.environment,
        database_url=settings.database_url.split("@")[1] if "@" in settings.database_url else "***",
    )


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown."""
    logger.info("bonding_bot_shutdown")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Bonding Bot API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/v1/health",
    }
