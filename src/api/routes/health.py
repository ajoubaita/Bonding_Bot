"""Health check endpoint."""

from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
import redis as redis_lib
import structlog

from src.models import get_db
from src.config import settings

logger = structlog.get_logger()

router = APIRouter()


@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint with dependency status.

    Returns:
        JSON response with overall health status and component details
    """
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {},
        "metrics": {},
    }

    # Check database
    try:
        db.execute(text("SELECT 1"))
        health_status["components"]["database"] = {
            "status": "healthy",
        }
    except Exception as e:
        logger.error("health_check_db_failed", error=str(e))
        health_status["components"]["database"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        health_status["status"] = "degraded"

    # Check Redis
    try:
        redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
        redis_client.ping()
        redis_client.close()
        health_status["components"]["redis"] = {
            "status": "healthy",
        }
    except Exception as e:
        logger.error("health_check_redis_failed", error=str(e))
        health_status["components"]["redis"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        health_status["status"] = "degraded"

    # Check external APIs (placeholder - implement when clients are ready)
    health_status["components"]["kalshi_api"] = {
        "status": "unknown",
        "message": "Not implemented yet",
    }
    health_status["components"]["polymarket_api"] = {
        "status": "unknown",
        "message": "Not implemented yet",
    }

    # Embedding service check (placeholder)
    health_status["components"]["embedding_service"] = {
        "status": "unknown",
        "message": "Not implemented yet",
    }

    # Get metrics from database
    try:
        from src.models import Market, Bond

        total_kalshi = db.query(Market).filter(Market.platform == "kalshi").count()
        total_poly = db.query(Market).filter(Market.platform == "polymarket").count()
        total_bonds_tier1 = db.query(Bond).filter(Bond.tier == 1, Bond.status == "active").count()
        total_bonds_tier2 = db.query(Bond).filter(Bond.tier == 2, Bond.status == "active").count()

        health_status["metrics"] = {
            "total_markets_kalshi": total_kalshi,
            "total_markets_polymarket": total_poly,
            "total_bonds_tier1": total_bonds_tier1,
            "total_bonds_tier2": total_bonds_tier2,
        }
    except Exception as e:
        logger.error("health_check_metrics_failed", error=str(e))
        health_status["metrics"] = {"error": "Failed to fetch metrics"}

    return health_status
