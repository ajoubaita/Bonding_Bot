"""Kalshi API client for market data ingestion.

Public API documentation: https://trading-api.readme.io/reference/getting-started
"""

from typing import List, Dict, Any, Optional
import httpx
import structlog
from datetime import datetime

from src.config import settings

logger = structlog.get_logger()


class KalshiClient:
    """Client for Kalshi public market data API."""

    def __init__(self, api_base: Optional[str] = None, timeout: int = 10):
        """Initialize Kalshi client.

        Args:
            api_base: API base URL (default from settings)
            timeout: Request timeout in seconds
        """
        self.api_base = api_base or settings.kalshi_api_base
        self.timeout = timeout
        self.session = httpx.Client(timeout=timeout)

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make GET request to Kalshi API.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            Response JSON

        Raises:
            httpx.HTTPError: On request failure
        """
        url = f"{self.api_base}{endpoint}"

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                "kalshi_api_error",
                endpoint=endpoint,
                status_code=e.response.status_code,
                error=str(e),
            )
            raise

        except Exception as e:
            logger.error(
                "kalshi_request_failed",
                endpoint=endpoint,
                error=str(e),
            )
            raise

    def get_exchange_status(self) -> Dict[str, Any]:
        """Get exchange status.

        Returns:
            Exchange status info
        """
        logger.debug("kalshi_get_exchange_status")
        return self._get("/exchange/status")

    def get_events(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
        status: Optional[str] = None,
        series_ticker: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get events (market groups).

        Args:
            limit: Number of events to return (max 1000)
            cursor: Pagination cursor
            status: Filter by status (active, settled, finalized)
            series_ticker: Filter by series ticker

        Returns:
            Events data with pagination
        """
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if status:
            params["status"] = status
        if series_ticker:
            params["series_ticker"] = series_ticker

        logger.debug("kalshi_get_events", params=params)
        return self._get("/events", params=params)

    def get_event(self, event_ticker: str) -> Dict[str, Any]:
        """Get single event details.

        Args:
            event_ticker: Event ticker symbol

        Returns:
            Event data
        """
        logger.debug("kalshi_get_event", event_ticker=event_ticker)
        return self._get(f"/events/{event_ticker}")

    def get_markets(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
        max_close_ts: Optional[int] = None,
        min_close_ts: Optional[int] = None,
        status: Optional[str] = None,
        tickers: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get markets.

        Args:
            limit: Number of markets to return (max 1000)
            cursor: Pagination cursor
            event_ticker: Filter by event ticker
            series_ticker: Filter by series ticker
            max_close_ts: Filter by max close timestamp
            min_close_ts: Filter by min close timestamp
            status: Filter by status (open, closed, settled)
            tickers: Comma-separated list of market tickers

        Returns:
            Markets data with pagination
        """
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if event_ticker:
            params["event_ticker"] = event_ticker
        if series_ticker:
            params["series_ticker"] = series_ticker
        if max_close_ts:
            params["max_close_ts"] = max_close_ts
        if min_close_ts:
            params["min_close_ts"] = min_close_ts
        if status:
            params["status"] = status
        if tickers:
            params["tickers"] = tickers

        logger.debug("kalshi_get_markets", params=params)
        return self._get("/markets", params=params)

    def get_market(self, ticker: str) -> Dict[str, Any]:
        """Get single market details.

        Args:
            ticker: Market ticker symbol

        Returns:
            Market data
        """
        logger.debug("kalshi_get_market", ticker=ticker)
        return self._get(f"/markets/{ticker}")

    def get_series(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get series (market categories).

        Args:
            limit: Number of series to return
            cursor: Pagination cursor

        Returns:
            Series data with pagination
        """
        params = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        logger.debug("kalshi_get_series", params=params)
        return self._get("/series", params=params)

    def normalize_market(self, raw_market: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Kalshi market to internal format.

        Args:
            raw_market: Raw market data from Kalshi API

        Returns:
            Normalized market data
        """
        # Extract basic info
        ticker = raw_market.get("ticker")
        title = raw_market.get("title", "")
        subtitle = raw_market.get("subtitle", "")

        # Combine title and subtitle for full description
        full_title = f"{title}"
        description = f"{title}. {subtitle}" if subtitle else title

        # Extract timestamps
        close_time = raw_market.get("close_time")
        expiration_time = raw_market.get("expiration_time")
        open_time = raw_market.get("open_time")

        # Parse resolution date (use expiration_time)
        resolution_date = expiration_time

        # Determine outcome type (Kalshi markets are typically yes/no)
        # Some markets have ranges, check subtitle
        outcome_type = "yes_no"
        outcomes = [
            {"label": "Yes", "value": True},
            {"label": "No", "value": False},
        ]

        # Extract category from series ticker or event
        category = raw_market.get("category", "unknown")

        # Market status
        status_map = {
            "open": "active",
            "closed": "closed",
            "settled": "resolved",
        }
        status = status_map.get(raw_market.get("status", "").lower(), "active")

        # Build normalized format
        normalized = {
            "id": ticker,
            "title": full_title,
            "description": description,
            "category": category.lower() if category else "unknown",
            "resolution_date": resolution_date,
            "resolution_source": "Kalshi",  # Kalshi resolves their own markets
            "outcome_type": outcome_type,
            "outcomes": outcomes,
            "metadata": {
                "liquidity": raw_market.get("liquidity", 0),
                "volume": raw_market.get("volume", 0),
                "open_time": open_time,
                "close_time": close_time,
                "event_ticker": raw_market.get("event_ticker"),
                "series_ticker": raw_market.get("series_ticker"),
            },
        }

        logger.debug(
            "kalshi_market_normalized",
            ticker=ticker,
            category=category,
        )

        return normalized

    def fetch_all_active_markets(self) -> List[Dict[str, Any]]:
        """Fetch all active markets with pagination.

        Returns:
            List of normalized markets
        """
        logger.info("kalshi_fetch_all_active_markets_start")

        all_markets = []
        cursor = None
        page = 0

        try:
            while True:
                page += 1
                response = self.get_markets(
                    limit=1000,  # Max per request
                    cursor=cursor,
                    status="open",  # Only active markets
                )

                markets = response.get("markets", [])
                if not markets:
                    break

                # Normalize each market
                for market in markets:
                    try:
                        normalized = self.normalize_market(market)
                        all_markets.append(normalized)
                    except Exception as e:
                        logger.error(
                            "kalshi_market_normalization_failed",
                            ticker=market.get("ticker"),
                            error=str(e),
                        )

                logger.info(
                    "kalshi_markets_page_fetched",
                    page=page,
                    count=len(markets),
                    total=len(all_markets),
                )

                # Check for next page
                cursor = response.get("cursor")
                if not cursor:
                    break

        except Exception as e:
            logger.error(
                "kalshi_fetch_all_active_markets_failed",
                error=str(e),
                markets_fetched=len(all_markets),
            )

        logger.info(
            "kalshi_fetch_all_active_markets_complete",
            total_markets=len(all_markets),
        )

        return all_markets

    def close(self):
        """Close HTTP session."""
        self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
