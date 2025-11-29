"""Redis caching utilities."""

from typing import Any, Optional, Callable
import json
import functools
import redis
import structlog

from src.config import settings

logger = structlog.get_logger()


class CacheClient:
    """Redis cache client."""

    def __init__(self, redis_url: Optional[str] = None):
        """Initialize cache client.

        Args:
            redis_url: Redis connection URL (default from settings)
        """
        self.redis_url = redis_url or settings.redis_url
        self._client = None

    @property
    def client(self) -> redis.Redis:
        """Get Redis client (lazy loaded)."""
        if self._client is None:
            self._client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            logger.info("redis_client_initialized", url=self.redis_url.split("@")[1] if "@" in self.redis_url else "***")
        return self._client

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        try:
            value = self.client.get(key)
            if value:
                logger.debug("cache_hit", key=key)
                return json.loads(value)
            logger.debug("cache_miss", key=key)
            return None
        except Exception as e:
            logger.error("cache_get_failed", key=key, error=str(e))
            return None

    def set(self, key: str, value: Any, ttl: int = 60) -> bool:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds

        Returns:
            True if successful
        """
        try:
            serialized = json.dumps(value)
            self.client.setex(key, ttl, serialized)
            logger.debug("cache_set", key=key, ttl=ttl)
            return True
        except Exception as e:
            logger.error("cache_set_failed", key=key, error=str(e))
            return False

    def delete(self, key: str) -> bool:
        """Delete key from cache.

        Args:
            key: Cache key

        Returns:
            True if successful
        """
        try:
            self.client.delete(key)
            logger.debug("cache_delete", key=key)
            return True
        except Exception as e:
            logger.error("cache_delete_failed", key=key, error=str(e))
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching pattern.

        Args:
            pattern: Key pattern (e.g., "bond_registry:*")

        Returns:
            Number of keys deleted
        """
        try:
            keys = self.client.keys(pattern)
            if keys:
                count = self.client.delete(*keys)
                logger.info("cache_invalidate_pattern", pattern=pattern, count=count)
                return count
            return 0
        except Exception as e:
            logger.error("cache_invalidate_pattern_failed", pattern=pattern, error=str(e))
            return 0

    def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment counter.

        Args:
            key: Counter key
            amount: Amount to increment

        Returns:
            New value or None on failure
        """
        try:
            value = self.client.incrby(key, amount)
            return value
        except Exception as e:
            logger.error("cache_increment_failed", key=key, error=str(e))
            return None

    def expire(self, key: str, ttl: int) -> bool:
        """Set expiration on key.

        Args:
            key: Cache key
            ttl: Time to live in seconds

        Returns:
            True if successful
        """
        try:
            self.client.expire(key, ttl)
            return True
        except Exception as e:
            logger.error("cache_expire_failed", key=key, error=str(e))
            return False

    def close(self):
        """Close Redis connection."""
        if self._client:
            self._client.close()
            self._client = None


# Global cache instance
_cache = None


def get_cache() -> CacheClient:
    """Get global cache instance."""
    global _cache
    if _cache is None:
        _cache = CacheClient()
    return _cache


def cached(ttl: int = 60, key_prefix: str = ""):
    """Decorator to cache function results.

    Args:
        ttl: Time to live in seconds
        key_prefix: Prefix for cache key

    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Build cache key
            cache_key_parts = [key_prefix or func.__name__]

            # Add args to key
            for arg in args:
                if isinstance(arg, (str, int, float, bool)):
                    cache_key_parts.append(str(arg))

            # Add kwargs to key
            for k, v in sorted(kwargs.items()):
                if isinstance(v, (str, int, float, bool)):
                    cache_key_parts.append(f"{k}={v}")

            cache_key = ":".join(cache_key_parts)

            # Try to get from cache
            cache = get_cache()
            cached_value = cache.get(cache_key)

            if cached_value is not None:
                logger.debug("cached_function_hit", function=func.__name__, key=cache_key)
                return cached_value

            # Call function
            result = func(*args, **kwargs)

            # Cache result
            cache.set(cache_key, result, ttl=ttl)
            logger.debug("cached_function_set", function=func.__name__, key=cache_key, ttl=ttl)

            return result

        return wrapper
    return decorator
