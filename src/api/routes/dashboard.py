"""Dashboard and status endpoints for user-friendly monitoring."""

from typing import Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
import structlog

from src.models import get_db, Bond, Market
from src.config import settings

logger = structlog.get_logger()

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request, db: Session = Depends(get_db)):
    """Interactive HTML dashboard for monitoring the Bonding Bot.

    Shows:
    - System health and status
    - Active bonds by tier
    - Recent arbitrage opportunities
    - Price update freshness
    - Performance metrics
    """
    # Get bond counts by tier
    bond_stats = db.query(
        Bond.tier,
        func.count(Bond.id).label('count'),
        func.avg(Bond.similarity_score).label('avg_similarity'),
        func.avg(Bond.p_match).label('avg_p_match')
    ).filter(
        Bond.status == 'active'
    ).group_by(Bond.tier).all()

    # Get total bonds
    total_bonds = sum(stat.count for stat in bond_stats)

    # Get recent price update info
    latest_market = db.query(Market).order_by(Market.updated_at.desc()).first()
    price_freshness_seconds = 0
    price_status = "unknown"

    if latest_market:
        price_freshness_seconds = (datetime.utcnow() - latest_market.updated_at).total_seconds()
        if price_freshness_seconds < 30:
            price_status = "excellent"
        elif price_freshness_seconds < 60:
            price_status = "good"
        elif price_freshness_seconds < 300:
            price_status = "stale"
        else:
            price_status = "critical"

    # Get total markets
    kalshi_markets = db.query(func.count(Market.id)).filter(Market.platform == 'kalshi').scalar()
    poly_markets = db.query(func.count(Market.id)).filter(Market.platform == 'polymarket').scalar()

    # Build bond stats for display
    tier_data = {stat.tier: {
        'count': stat.count,
        'avg_similarity': round(stat.avg_similarity * 100, 1) if stat.avg_similarity else 0,
        'avg_p_match': round(stat.avg_p_match * 100, 1) if stat.avg_p_match else 0
    } for stat in bond_stats}

    # Get configuration
    config_info = {
        'price_update_interval': settings.price_update_interval_sec,
        'tier1_min_similarity': settings.tier1_min_similarity_score,
        'tier2_min_similarity': settings.tier2_min_similarity_score,
        'cache_ttl': settings.bond_registry_cache_ttl_sec,
    }

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bonding Bot Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}

        h1 {{
            color: white;
            font-size: 2.5em;
            margin-bottom: 10px;
            text-align: center;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        }}

        .subtitle {{
            color: rgba(255,255,255,0.9);
            text-align: center;
            margin-bottom: 30px;
            font-size: 1.1em;
        }}

        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }}

        .card {{
            background: white;
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            transition: transform 0.2s;
        }}

        .card:hover {{
            transform: translateY(-5px);
        }}

        .card h2 {{
            color: #333;
            font-size: 1.3em;
            margin-bottom: 16px;
            border-bottom: 2px solid #667eea;
            padding-bottom: 8px;
        }}

        .metric {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #eee;
        }}

        .metric:last-child {{
            border-bottom: none;
        }}

        .metric-label {{
            color: #666;
            font-size: 0.95em;
        }}

        .metric-value {{
            font-size: 1.4em;
            font-weight: 600;
            color: #333;
        }}

        .status {{
            display: inline-block;
            padding: 6px 16px;
            border-radius: 20px;
            font-weight: 600;
            font-size: 0.9em;
        }}

        .status-excellent {{ background: #10b981; color: white; }}
        .status-good {{ background: #3b82f6; color: white; }}
        .status-stale {{ background: #f59e0b; color: white; }}
        .status-critical {{ background: #ef4444; color: white; }}

        .tier-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-weight: 600;
            font-size: 0.85em;
            margin-right: 8px;
        }}

        .tier-1 {{ background: #10b981; color: white; }}
        .tier-2 {{ background: #3b82f6; color: white; }}
        .tier-3 {{ background: #6b7280; color: white; }}

        .big-number {{
            font-size: 3em;
            font-weight: 700;
            color: #667eea;
            text-align: center;
            margin: 20px 0;
        }}

        .refresh-info {{
            text-align: center;
            color: white;
            margin-top: 20px;
            font-size: 0.9em;
        }}

        .api-link {{
            display: inline-block;
            margin-top: 12px;
            padding: 8px 16px;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 6px;
            font-size: 0.9em;
            transition: background 0.2s;
        }}

        .api-link:hover {{
            background: #5568d3;
        }}

        .alert {{
            background: #fef3c7;
            border-left: 4px solid #f59e0b;
            padding: 16px;
            margin-bottom: 20px;
            border-radius: 6px;
        }}

        .alert-title {{
            font-weight: 600;
            color: #92400e;
            margin-bottom: 4px;
        }}

        .alert-text {{
            color: #78350f;
            font-size: 0.9em;
        }}
    </style>
    <script>
        // Auto-refresh every 10 seconds
        setTimeout(function(){{
            location.reload();
        }}, 10000);
    </script>
</head>
<body>
    <div class="container">
        <h1>🤖 Bonding Bot Dashboard</h1>
        <div class="subtitle">Cross-Exchange Arbitrage Monitoring System</div>

        {"<div class='alert'><div class='alert-title'>⚠️ Price Data Stale</div><div class='alert-text'>Last update was " + str(int(price_freshness_seconds)) + " seconds ago. Check price_updater service.</div></div>" if price_status in ['stale', 'critical'] else ""}

        <div class="grid">
            <!-- System Health Card -->
            <div class="card">
                <h2>📊 System Health</h2>
                <div class="metric">
                    <span class="metric-label">Price Updates</span>
                    <span class="status status-{price_status}">{price_status.upper()}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Last Update</span>
                    <span class="metric-value">{int(price_freshness_seconds)}s ago</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Update Interval</span>
                    <span class="metric-value">{config_info['price_update_interval']}s</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Cache TTL</span>
                    <span class="metric-value">{config_info['cache_ttl']}s</span>
                </div>
            </div>

            <!-- Active Bonds Card -->
            <div class="card">
                <h2>🔗 Active Bonds</h2>
                <div class="big-number">{total_bonds}</div>
                <div class="metric">
                    <span class="metric-label"><span class="tier-badge tier-1">Tier 1</span> Auto Bond</span>
                    <span class="metric-value">{tier_data.get(1, {}).get('count', 0)}</span>
                </div>
                <div class="metric">
                    <span class="metric-label"><span class="tier-badge tier-2">Tier 2</span> Cautious</span>
                    <span class="metric-value">{tier_data.get(2, {}).get('count', 0)}</span>
                </div>
                <div class="metric">
                    <span class="metric-label"><span class="tier-badge tier-3">Tier 3</span> Rejected</span>
                    <span class="metric-value">{tier_data.get(3, {}).get('count', 0)}</span>
                </div>
            </div>

            <!-- Markets Card -->
            <div class="card">
                <h2>📈 Market Coverage</h2>
                <div class="metric">
                    <span class="metric-label">Kalshi Markets</span>
                    <span class="metric-value">{kalshi_markets}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Polymarket Markets</span>
                    <span class="metric-value">{poly_markets}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Total Markets</span>
                    <span class="metric-value">{kalshi_markets + poly_markets}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Bond Coverage</span>
                    <span class="metric-value">{round(total_bonds / max(kalshi_markets, 1) * 100, 1)}%</span>
                </div>
            </div>

            <!-- Bond Quality Card -->
            <div class="card">
                <h2>⭐ Bond Quality</h2>
                <div class="metric">
                    <span class="metric-label">Tier 1 Avg Similarity</span>
                    <span class="metric-value">{tier_data.get(1, {}).get('avg_similarity', 0)}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Tier 1 Avg P(Match)</span>
                    <span class="metric-value">{tier_data.get(1, {}).get('avg_p_match', 0)}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Tier 2 Avg Similarity</span>
                    <span class="metric-value">{tier_data.get(2, {}).get('avg_similarity', 0)}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Min Tier 1 Threshold</span>
                    <span class="metric-value">{int(config_info['tier1_min_similarity'] * 100)}%</span>
                </div>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h2>🔌 API Endpoints</h2>
                <div style="line-height: 2;">
                    <a href="/v1/docs" class="api-link">📚 API Documentation</a><br>
                    <a href="/v1/health" class="api-link">💚 Health Check</a><br>
                    <a href="/v1/status" class="api-link">📊 Detailed Status</a><br>
                    <a href="/v1/bond_registry?tier=1" class="api-link">🔗 Bond Registry</a>
                </div>
            </div>
        </div>

        <div class="refresh-info">
            Auto-refreshing every 10 seconds • Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
        </div>
    </div>
</body>
</html>
    """

    return html_content


@router.get("/status")
async def detailed_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Comprehensive status endpoint with detailed system metrics.

    Returns:
        Detailed system status including bonds, markets, health, and config
    """
    # Bond statistics
    bond_stats = db.query(
        Bond.tier,
        func.count(Bond.id).label('count'),
        func.avg(Bond.similarity_score).label('avg_similarity'),
        func.min(Bond.similarity_score).label('min_similarity'),
        func.max(Bond.similarity_score).label('max_similarity'),
        func.avg(Bond.p_match).label('avg_p_match')
    ).filter(
        Bond.status == 'active'
    ).group_by(Bond.tier).all()

    bonds_by_tier = {
        stat.tier: {
            'count': stat.count,
            'avg_similarity': round(float(stat.avg_similarity), 4) if stat.avg_similarity else 0,
            'min_similarity': round(float(stat.min_similarity), 4) if stat.min_similarity else 0,
            'max_similarity': round(float(stat.max_similarity), 4) if stat.max_similarity else 0,
            'avg_p_match': round(float(stat.avg_p_match), 4) if stat.avg_p_match else 0,
        } for stat in bond_stats
    }

    # Market statistics
    kalshi_count = db.query(func.count(Market.id)).filter(Market.platform == 'kalshi').scalar()
    poly_count = db.query(func.count(Market.id)).filter(Market.platform == 'polymarket').scalar()

    # Price update health
    latest_market = db.query(Market).order_by(Market.updated_at.desc()).first()
    price_health = {
        'status': 'unknown',
        'last_update': None,
        'age_seconds': None,
    }

    if latest_market:
        age = (datetime.utcnow() - latest_market.updated_at).total_seconds()
        price_health['last_update'] = latest_market.updated_at.isoformat()
        price_health['age_seconds'] = round(age, 1)

        if age < 30:
            price_health['status'] = 'excellent'
        elif age < 60:
            price_health['status'] = 'good'
        elif age < 300:
            price_health['status'] = 'stale'
        else:
            price_health['status'] = 'critical'

    # Configuration
    configuration = {
        'price_update_interval_sec': settings.price_update_interval_sec,
        'bond_registry_cache_ttl_sec': settings.bond_registry_cache_ttl_sec,
        'tier1_min_similarity_score': settings.tier1_min_similarity_score,
        'tier2_min_similarity_score': settings.tier2_min_similarity_score,
        'tier1_p_match_threshold': settings.tier1_p_match_threshold,
        'tier2_p_match_threshold': settings.tier2_p_match_threshold,
    }

    return {
        'status': 'healthy' if price_health['status'] in ['excellent', 'good'] else 'degraded',
        'timestamp': datetime.utcnow().isoformat(),
        'bonds': {
            'total': sum(tier['count'] for tier in bonds_by_tier.values()),
            'by_tier': bonds_by_tier,
        },
        'markets': {
            'kalshi': kalshi_count,
            'polymarket': poly_count,
            'total': kalshi_count + poly_count,
        },
        'price_updates': price_health,
        'configuration': configuration,
    }
