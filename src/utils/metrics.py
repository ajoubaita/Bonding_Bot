"""Metrics collection and monitoring."""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import threading
import structlog

from src.utils.cache import get_cache

logger = structlog.get_logger()


class MetricsCollector:
    """Collect and aggregate metrics."""

    def __init__(self):
        """Initialize metrics collector."""
        self.cache = get_cache()
        self._lock = threading.Lock()

    def increment_counter(self, metric_name: str, value: int = 1, tags: Optional[Dict[str, str]] = None):
        """Increment a counter metric.

        Args:
            metric_name: Metric name
            value: Value to increment
            tags: Optional tags
        """
        key = f"metrics:counter:{metric_name}"
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"

        self.cache.increment(key, value)
        self.cache.expire(key, 86400)  # 24 hours

        logger.debug("metric_counter_incremented", metric=metric_name, value=value, tags=tags)

    def record_gauge(self, metric_name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Record a gauge metric.

        Args:
            metric_name: Metric name
            value: Gauge value
            tags: Optional tags
        """
        key = f"metrics:gauge:{metric_name}"
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"

        self.cache.set(key, value, ttl=86400)  # 24 hours

        logger.debug("metric_gauge_recorded", metric=metric_name, value=value, tags=tags)

    def record_histogram(self, metric_name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Record a histogram value.

        Args:
            metric_name: Metric name
            value: Histogram value
            tags: Optional tags
        """
        # Store in sorted set for percentile calculation
        key = f"metrics:histogram:{metric_name}"
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"

        timestamp = datetime.utcnow().timestamp()
        cache_client = self.cache.client

        # Add to sorted set (score = timestamp, value = metric value)
        cache_client.zadd(key, {str(value): timestamp})

        # Remove old entries (older than 24 hours)
        cutoff = (datetime.utcnow() - timedelta(hours=24)).timestamp()
        cache_client.zremrangebyscore(key, 0, cutoff)

        # Set expiration
        cache_client.expire(key, 86400)

        logger.debug("metric_histogram_recorded", metric=metric_name, value=value, tags=tags)

    def get_counter(self, metric_name: str, tags: Optional[Dict[str, str]] = None) -> int:
        """Get counter value.

        Args:
            metric_name: Metric name
            tags: Optional tags

        Returns:
            Counter value
        """
        key = f"metrics:counter:{metric_name}"
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"

        value = self.cache.get(key)
        return int(value) if value else 0

    def get_gauge(self, metric_name: str, tags: Optional[Dict[str, str]] = None) -> Optional[float]:
        """Get gauge value.

        Args:
            metric_name: Metric name
            tags: Optional tags

        Returns:
            Gauge value or None
        """
        key = f"metrics:gauge:{metric_name}"
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"

        value = self.cache.get(key)
        return float(value) if value is not None else None

    def get_histogram_stats(self, metric_name: str, tags: Optional[Dict[str, str]] = None) -> Dict[str, float]:
        """Get histogram statistics.

        Args:
            metric_name: Metric name
            tags: Optional tags

        Returns:
            Dictionary with p50, p95, p99, min, max
        """
        key = f"metrics:histogram:{metric_name}"
        if tags:
            tag_str = ":".join(f"{k}={v}" for k, v in sorted(tags.items()))
            key = f"{key}:{tag_str}"

        cache_client = self.cache.client

        try:
            # Get all values from sorted set
            values = cache_client.zrange(key, 0, -1)

            if not values:
                return {}

            # Convert to floats and sort
            float_values = sorted([float(v) for v in values])
            count = len(float_values)

            # Calculate percentiles
            stats = {
                "count": count,
                "min": float_values[0],
                "max": float_values[-1],
                "p50": float_values[int(count * 0.50)] if count > 0 else 0.0,
                "p95": float_values[int(count * 0.95)] if count > 0 else 0.0,
                "p99": float_values[int(count * 0.99)] if count > 0 else 0.0,
                "mean": sum(float_values) / count if count > 0 else 0.0,
            }

            return stats

        except Exception as e:
            logger.error("get_histogram_stats_failed", metric=metric_name, error=str(e))
            return {}


# Global metrics instance
_metrics = None


def get_metrics() -> MetricsCollector:
    """Get global metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


# Common metrics helpers
def record_bond_creation(tier: int):
    """Record bond creation."""
    metrics = get_metrics()
    metrics.increment_counter("bonds_created_total", tags={"tier": str(tier)})


def record_bond_validation(tier: int, success: bool):
    """Record bond validation result."""
    metrics = get_metrics()
    metrics.increment_counter(
        "bonds_validated_total",
        tags={"tier": str(tier), "success": str(success).lower()}
    )


def record_similarity_calculation(duration_ms: float):
    """Record similarity calculation duration."""
    metrics = get_metrics()
    metrics.record_histogram("similarity_calc_duration_ms", duration_ms)


def record_api_request(endpoint: str, status_code: int, duration_ms: float):
    """Record API request."""
    metrics = get_metrics()
    metrics.increment_counter(
        "api_requests_total",
        tags={"endpoint": endpoint, "status": str(status_code)}
    )
    metrics.record_histogram(
        "api_request_duration_ms",
        duration_ms,
        tags={"endpoint": endpoint}
    )


def record_market_ingestion(platform: str, success: bool):
    """Record market ingestion."""
    metrics = get_metrics()
    metrics.increment_counter(
        "markets_ingested_total",
        tags={"platform": platform, "success": str(success).lower()}
    )


def get_summary_stats() -> Dict[str, Any]:
    """Get summary statistics for all metrics.

    Returns:
        Dictionary with metric summaries
    """
    metrics = get_metrics()

    summary = {
        "bonds": {
            "tier1_created": metrics.get_counter("bonds_created_total", {"tier": "1"}),
            "tier2_created": metrics.get_counter("bonds_created_total", {"tier": "2"}),
            "tier1_validated_success": metrics.get_counter("bonds_validated_total", {"tier": "1", "success": "true"}),
            "tier1_validated_failure": metrics.get_counter("bonds_validated_total", {"tier": "1", "success": "false"}),
        },
        "similarity": {
            "calculations": metrics.get_histogram_stats("similarity_calc_duration_ms"),
        },
        "api": {
            "total_requests": sum(
                metrics.get_counter("api_requests_total", {"endpoint": e, "status": str(s)})
                for e in ["/v1/health", "/v1/bond_registry", "/v1/pairs/recompute"]
                for s in [200, 404, 500]
            ),
            "request_duration": metrics.get_histogram_stats("api_request_duration_ms"),
        },
        "ingestion": {
            "kalshi_success": metrics.get_counter("markets_ingested_total", {"platform": "kalshi", "success": "true"}),
            "kalshi_failure": metrics.get_counter("markets_ingested_total", {"platform": "kalshi", "success": "false"}),
            "polymarket_success": metrics.get_counter("markets_ingested_total", {"platform": "polymarket", "success": "true"}),
            "polymarket_failure": metrics.get_counter("markets_ingested_total", {"platform": "polymarket", "success": "false"}),
        },
    }

    return summary
