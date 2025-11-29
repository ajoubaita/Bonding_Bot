"""Polymarket API clients for market data ingestion.

Gamma API: Market discovery and metadata
CLOB API: Simplified markets with prices
"""

from typing import List, Dict, Any, Optional
import httpx
import structlog
import json

from src.config import settings

logger = structlog.get_logger()


class PolymarketGammaClient:
    """Client for Polymarket Gamma API (market discovery)."""

    def __init__(self, api_base: Optional[str] = None, timeout: int = 10):
        """Initialize Gamma client.

        Args:
            api_base: API base URL (default from settings)
            timeout: Request timeout in seconds
        """
        self.api_base = api_base or settings.polymarket_gamma_api_base
        self.timeout = timeout
        self.session = httpx.Client(timeout=timeout)

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """Make GET request to Gamma API.

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
                "gamma_api_error",
                endpoint=endpoint,
                status_code=e.response.status_code,
                error=str(e),
            )
            raise

        except Exception as e:
            logger.error(
                "gamma_request_failed",
                endpoint=endpoint,
                error=str(e),
            )
            raise

    def get_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        closed: Optional[bool] = None,
        active: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """Get markets from Gamma API.

        Args:
            limit: Number of markets to return
            offset: Pagination offset
            closed: Filter by closed status
            active: Filter by active status

        Returns:
            List of markets
        """
        params = {
            "limit": limit,
            "offset": offset,
        }

        if closed is not None:
            params["closed"] = str(closed).lower()
        if active is not None:
            params["active"] = str(active).lower()

        logger.debug("gamma_get_markets", params=params)
        return self._get("/markets", params=params)

    def get_market(self, condition_id: str) -> Dict[str, Any]:
        """Get single market by condition ID.

        Args:
            condition_id: Ethereum condition ID

        Returns:
            Market data
        """
        logger.debug("gamma_get_market", condition_id=condition_id)
        markets = self.get_markets(limit=1000)

        # Find market by condition_id
        for market in markets:
            if market.get("conditionId") == condition_id:
                return market

        raise ValueError(f"Market not found: {condition_id}")

    def normalize_market(self, raw_market: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Gamma market to internal format.

        Args:
            raw_market: Raw market data from Gamma API

        Returns:
            Normalized market data
        """
        # Extract basic info
        condition_id = raw_market.get("conditionId")
        question = raw_market.get("question", "")
        description = raw_market.get("description", "")

        # Extract timestamps
        end_date = raw_market.get("endDate")  # ISO 8601

        # Parse CLOB token IDs (JSON string)
        clob_token_ids = []
        clob_token_ids_str = raw_market.get("clobTokenIds", "[]")
        try:
            if isinstance(clob_token_ids_str, str):
                clob_token_ids = json.loads(clob_token_ids_str)
            elif isinstance(clob_token_ids_str, list):
                clob_token_ids = clob_token_ids_str
        except json.JSONDecodeError:
            logger.warning(
                "gamma_clob_token_ids_parse_failed",
                condition_id=condition_id,
                value=clob_token_ids_str,
            )

        # Status
        active = raw_market.get("active", False)
        closed = raw_market.get("closed", False)

        if closed:
            status = "closed"
        elif active:
            status = "active"
        else:
            status = "inactive"

        # Extract category/tags
        tags = raw_market.get("tags", [])
        category = tags[0] if tags else "unknown"

        # Determine outcome type (typically yes/no for Polymarket)
        outcome_type = "yes_no"
        outcomes = [
            {"label": "Yes", "token_id": clob_token_ids[0] if len(clob_token_ids) > 0 else None, "value": True},
            {"label": "No", "token_id": clob_token_ids[1] if len(clob_token_ids) > 1 else None, "value": False},
        ]

        # Extract volumes and liquidity
        volume = raw_market.get("volume", 0)
        liquidity = raw_market.get("liquidity", 0)

        # Build normalized format
        normalized = {
            "id": condition_id,
            "title": question,
            "description": description or question,
            "category": category.lower() if category else "unknown",
            "resolution_date": end_date,
            "resolution_source": raw_market.get("resolutionSource", "Polymarket"),
            "outcome_type": outcome_type,
            "outcomes": outcomes,
            "metadata": {
                "liquidity": float(liquidity) if liquidity else 0.0,
                "volume": float(volume) if volume else 0.0,
                "clob_token_ids": clob_token_ids,
                "tags": tags,
                "market_slug": raw_market.get("marketSlug"),
            },
        }

        logger.debug(
            "gamma_market_normalized",
            condition_id=condition_id,
            category=category,
        )

        return normalized

    def fetch_all_active_markets(self) -> List[Dict[str, Any]]:
        """Fetch all active markets with pagination.

        Returns:
            List of normalized markets
        """
        logger.info("gamma_fetch_all_active_markets_start")

        all_markets = []
        offset = 0
        limit = 100

        try:
            while True:
                markets = self.get_markets(
                    limit=limit,
                    offset=offset,
                    closed=False,  # Only open markets
                )

                if not markets:
                    break

                # Normalize each market
                for market in markets:
                    try:
                        normalized = self.normalize_market(market)
                        all_markets.append(normalized)
                    except Exception as e:
                        logger.error(
                            "gamma_market_normalization_failed",
                            condition_id=market.get("conditionId"),
                            error=str(e),
                        )

                logger.info(
                    "gamma_markets_batch_fetched",
                    offset=offset,
                    count=len(markets),
                    total=len(all_markets),
                )

                # Check if we got less than limit (last page)
                if len(markets) < limit:
                    break

                offset += limit

        except Exception as e:
            logger.error(
                "gamma_fetch_all_active_markets_failed",
                error=str(e),
                markets_fetched=len(all_markets),
            )

        logger.info(
            "gamma_fetch_all_active_markets_complete",
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


class PolymarketCLOBClient:
    """Client for Polymarket CLOB API (prices and order books)."""

    def __init__(self, api_base: Optional[str] = None, timeout: int = 10):
        """Initialize CLOB client.

        Args:
            api_base: API base URL (default from settings)
            timeout: Request timeout in seconds
        """
        self.api_base = api_base or settings.polymarket_clob_api_base
        self.timeout = timeout
        self.session = httpx.Client(timeout=timeout)

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        """Make GET request to CLOB API.

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
                "clob_api_error",
                endpoint=endpoint,
                status_code=e.response.status_code,
                error=str(e),
            )
            raise

        except Exception as e:
            logger.error(
                "clob_request_failed",
                endpoint=endpoint,
                error=str(e),
            )
            raise

    def get_simplified_markets(self) -> List[Dict[str, Any]]:
        """Get simplified markets with current prices.

        This is the recommended endpoint for read-only price data.

        Returns:
            List of markets with prices
        """
        logger.debug("clob_get_simplified_markets")
        return self._get("/simplified-markets")

    def get_markets(
        self,
        limit: int = 100,
        next_cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get detailed market data with pagination.

        Args:
            limit: Number of markets to return
            next_cursor: Pagination cursor

        Returns:
            Markets data with pagination
        """
        params = {"limit": limit}
        if next_cursor:
            params["next_cursor"] = next_cursor

        logger.debug("clob_get_markets", params=params)
        return self._get("/markets", params=params)

    def enrich_market_with_prices(
        self,
        gamma_market: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Enrich Gamma market data with CLOB prices.

        Args:
            gamma_market: Normalized market from Gamma

        Returns:
            Market with price information
        """
        try:
            # Get simplified markets
            clob_markets = self.get_simplified_markets()

            # Find matching market by condition_id
            condition_id = gamma_market.get("id")

            for clob_market in clob_markets:
                if clob_market.get("condition_id") == condition_id:
                    # Extract prices from tokens
                    tokens = clob_market.get("tokens", [])

                    # Update outcomes with prices
                    if "outcomes" in gamma_market:
                        for i, outcome in enumerate(gamma_market["outcomes"]):
                            if i < len(tokens):
                                token = tokens[i]
                                # Ensure token is a dictionary before accessing fields
                                if isinstance(token, dict):
                                    outcome["price"] = float(token.get("price", 0))
                                    outcome["outcome_label"] = token.get("outcome")
                                else:
                                    logger.warning(
                                        "clob_token_not_dict",
                                        condition_id=condition_id,
                                        token_type=type(token).__name__,
                                        token_value=str(token)[:50],
                                    )

                    # Add accepting_orders flag
                    if isinstance(gamma_market.get("metadata"), dict):
                        gamma_market["metadata"]["accepting_orders"] = clob_market.get("accepting_orders", False)
                    else:
                        # Initialize metadata if it's not a dict
                        gamma_market["metadata"] = {
                            "accepting_orders": clob_market.get("accepting_orders", False)
                        }

                    logger.debug(
                        "clob_market_enriched",
                        condition_id=condition_id,
                        tokens=len(tokens),
                    )

                    break

        except Exception as e:
            logger.error(
                "clob_enrich_market_failed",
                condition_id=gamma_market.get("id"),
                error=str(e),
            )

        return gamma_market

    def close(self):
        """Close HTTP session."""
        self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


class PolymarketClient:
    """Combined Polymarket client (Gamma + CLOB)."""

    def __init__(
        self,
        gamma_api_base: Optional[str] = None,
        clob_api_base: Optional[str] = None,
        timeout: int = 10,
    ):
        """Initialize combined Polymarket client.

        Args:
            gamma_api_base: Gamma API base URL
            clob_api_base: CLOB API base URL
            timeout: Request timeout in seconds
        """
        self.gamma = PolymarketGammaClient(gamma_api_base, timeout)
        self.clob = PolymarketCLOBClient(clob_api_base, timeout)

    def fetch_all_active_markets_with_prices(self) -> List[Dict[str, Any]]:
        """Fetch all active markets with current prices.

        Returns:
            List of normalized markets with prices
        """
        logger.info("polymarket_fetch_all_active_markets_with_prices_start")

        # Fetch markets from Gamma
        markets = self.gamma.fetch_all_active_markets()

        # Enrich with CLOB prices
        enriched_markets = []
        for market in markets:
            try:
                enriched = self.clob.enrich_market_with_prices(market)
                enriched_markets.append(enriched)
            except Exception as e:
                logger.error(
                    "polymarket_enrich_failed",
                    market_id=market.get("id"),
                    error=str(e),
                )
                # Include market without prices
                enriched_markets.append(market)

        logger.info(
            "polymarket_fetch_all_active_markets_with_prices_complete",
            total_markets=len(enriched_markets),
        )

        return enriched_markets

    def close(self):
        """Close HTTP sessions."""
        self.gamma.close()
        self.clob.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
